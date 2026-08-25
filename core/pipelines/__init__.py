"""core.pipelines — 业务流水线层

BasePipeline 抽象基类 + 四种流水线导出。
"""

import asyncio
import json
import logging
import os
import subprocess
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

from core.compositor.watermark import add_watermark, detect_language
from core.config import get_watermark_config
from core.task_manager import TaskManager
from models.task import AudioConfig, BaseTaskState, StepStatus, SubtitleConfig, SubtitleStyle

logger = logging.getLogger(__name__)


class PipelineShutdown(Exception):
    """流水线中断异常。"""
    pass


class CheckpointPause(Exception):
    """手动模式检查点暂停（v6.0）。

    非失败、非中断：流水线在某个检查点正常暂停，等待用户确认产物后
    通过 resume 恢复执行。携带暂停的检查点名，供 run() 捕获后返回。
    """

    def __init__(self, checkpoint: str, message: str = ""):
        self.checkpoint = checkpoint
        self.message = message or f"等待用户在检查点 '{checkpoint}' 确认产物"
        super().__init__(self.message)


# 检查点定义（v6.0，PRD §4.3）：步骤名 → 检查点名
CHECKPOINT_SCENES = "scenes"
CHECKPOINT_REFERENCES = "references"
CHECKPOINT_VIDEOS = "videos"
CHECKPOINT_AUDIO = "audio"
CHECKPOINT_SUBTITLE = "subtitle"
CHECKPOINT_FINAL = "final"

# 细粒度检查点（v6.1：所有有产物的环节均可暂停）
CHECKPOINT_IMAGE_ANALYSIS = "image_analysis"
CHECKPOINT_STORY = "story"
CHECKPOINT_SCRIPT = "script"
CHECKPOINT_CHARACTER_REF = "character_ref"
CHECKPOINT_END_FRAME_PROMPTS = "end_frame_prompts"
CHECKPOINT_END_FRAME_GEN = "end_frame_gen"

# 手动模式下全部可选暂停点（creative 用细粒度集合，其余任务类型用粗粒度）
ALL_CHECKPOINTS = [
    CHECKPOINT_IMAGE_ANALYSIS,
    CHECKPOINT_STORY,
    CHECKPOINT_SCRIPT,
    CHECKPOINT_CHARACTER_REF,
    CHECKPOINT_END_FRAME_PROMPTS,
    CHECKPOINT_END_FRAME_GEN,
    CHECKPOINT_SCENES,
    CHECKPOINT_REFERENCES,
    CHECKPOINT_VIDEOS,
    CHECKPOINT_AUDIO,
    CHECKPOINT_SUBTITLE,
    CHECKPOINT_FINAL,
]

# 步骤字段名 → 检查点名（_execute_step 完成后调用 _maybe_pause 时映射）
_STEP_TO_CHECKPOINT = {
    "step_build_scenes": CHECKPOINT_SCENES,
    "step_image_analysis": CHECKPOINT_IMAGE_ANALYSIS,
    "step_story": CHECKPOINT_STORY,
    "step_character_ref": CHECKPOINT_CHARACTER_REF,
    "step_script": CHECKPOINT_SCRIPT,
    "step_end_frame_prompts": CHECKPOINT_END_FRAME_PROMPTS,
    "step_end_frame_generation": CHECKPOINT_END_FRAME_GEN,
    "step_reference_images": CHECKPOINT_REFERENCES,
    "step_video_generation": CHECKPOINT_VIDEOS,
    "step_audio": CHECKPOINT_AUDIO,
    "step_subtitle": CHECKPOINT_SUBTITLE,
    "step_concatenation": CHECKPOINT_FINAL,
}

# 步骤 → 暂停点应展示的进度（步骤完成时的真实进度，而非 100%）。
# 与 multi_scene.StepProgressLimits 对齐；creative 细粒度步骤映射到所属大阶段。
_PAUSE_PROGRESS_BY_STEP = {
    "step_build_scenes": 0.08,
    "step_resolve_scene_config": 0.05,
    "step_image_analysis": 0.06,
    "step_story": 0.07,
    "step_script": 0.08,
    "step_reference_images": 0.12,
    "step_character_ref": 0.12,
    "step_end_frame_prompts": 0.12,
    "step_end_frame_generation": 0.15,
    "step_video_generation": 0.80,
    "step_audio": 0.86,
    "step_subtitle": 0.90,
    "step_concatenation": 0.98,
}


def compute_current_checkpoint(state) -> str:
    """推断任务当前所处检查点（最近一个已完成的步骤对应的检查点，v6.0）。

    自动变手动时用于确定展示边界（PRD §4.1）：中断可能发生在步骤中间
    （如生成到 scene_3/5），取最后一个步骤字段为 COMPLETED 的检查点作为
    current_checkpoint；无任何已完成步骤时返回空串。

    Args:
        state: 任务状态对象（含 step_* 字段）。

    Returns:
        检查点名（scenes/references/videos/audio/subtitle/final）或空串。
    """
    if not state:
        return ""
    for cp in reversed(ALL_CHECKPOINTS):
        step_field = None
        for name, c in _STEP_TO_CHECKPOINT.items():
            if c == cp:
                step_field = name
                break
        if step_field and getattr(state, step_field, None) == StepStatus.COMPLETED:
            return cp
    return ""


class BasePipeline(ABC):
    """所有流水线的抽象基类。

    提供共享的进度回调、断点续传、shutdown 控制等基础设施。
    """

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: str = None,
        progress_callback: Optional[Callable] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        self.api_key = api_key
        self.task_id = task_id
        self.dir_name = dir_name or task_id
        self.task_manager = TaskManager(task_id, dir_name=self.dir_name)
        self.progress_callback = progress_callback
        self.shutdown_event = shutdown_event
        self._stop_event = asyncio.Event()
        self._state: Optional[BaseTaskState] = None
        # Batch 3（S4）：screenwriter 统一初始化，子类（creative/manuscript/anchor/poetry）
        # 在自身 __init__ 中赋真实实例；仅 LLM 样式生成使用，None 表示不可用。
        self.screenwriter = None

    async def _emit(
        self,
        step: str,
        status: str,
        message: str,
        progress: float = 0.0,
        data: dict = None,
    ):
        """更新进度并持久化到 state（轮询模式）。

        将 step/status/message/progress 写入 state 的 current_* 字段，
        前端通过 GET /api/tasks/{id} 轮询读取。
        """
        if self._state:
            self._state.current_step = step
            self._state.current_status = status
            self._state.current_progress = progress
            self._state.current_message = message
            # 持久化（写盘开销 < 1ms，pipeline 步骤间隔通常 > 1s）
            try:
                self.task_manager.update_state(
                    current_step=step,
                    current_status=status,
                    current_progress=progress,
                    current_message=message,
                )
            except Exception as e:
                logger.debug(f"[Pipeline] Failed to persist progress: {e}")

        # 保留 callback 兼容性（移除 WS 后通常为 None）
        if self.progress_callback:
            await self.progress_callback(step, status, message, progress, data or {})

    def _is_shutdown(self) -> bool:
        """检查是否收到停止信号。"""
        if self._stop_event.is_set():
            return True
        return self.shutdown_event is not None and self.shutdown_event.is_set()

    def stop(self):
        """请求流水线在下一个检查点停止。"""
        self._stop_event.set()

    def _get_pausable_steps(self) -> set[str]:
        """当前任务实际可暂停的步骤（v6.0 P3）。

        子类按实际产物覆写：空实现步骤（如 manuscript/poetry 的 references、
        anchor 的 model 模式 audio/subtitle）不在集合中，手动模式不会在
        无实际产物的步骤上暂停。默认返回全部标准步骤。

        Returns:
            步骤字段名集合（如 {"step_build_scenes", "step_video_generation", ...}）。
        """
        return set(_STEP_TO_CHECKPOINT.keys())

    async def _maybe_pause(self, step_name: str, progress: Optional[float] = None) -> bool:
        """手动模式检查点暂停判定（v6.0）。

        在步骤完成后调用。命中手动暂停点时落盘暂停态（PENDING + current_checkpoint），
        抛 ``CheckpointPause`` 使流水线正常返回（非失败）；未命中返回 False 继续执行。

        命中条件（PRD §4.1）：
            manual_config.enabled 且 pause_points 非空
            且 step 对应检查点在 pause_points 中
            且尚未在 approved_checkpoints 中
            且该步骤在本流水线实际可暂停（P3：空实现步骤自动跳过）

        Args:
            step_name: 步骤字段名（如 ``step_build_scenes``），经 _STEP_TO_CHECKPOINT 映射。
            progress: 暂停点应展示的进度。缺省按 _PAUSE_PROGRESS_BY_STEP 映射取
                该步骤完成时的真实进度（而非 100%）；未映射的步骤兜底 1.0。

        Returns:
            False（未暂停）；命中时抛出 CheckpointPause。
        """
        state = self._state
        mc = getattr(state, "manual_config", None)
        if not mc or not mc.enabled or not mc.pause_points:
            return False

        # P3：步骤实际不可暂停（空实现/无产物）→ 跳过
        if step_name not in self._get_pausable_steps():
            logger.info("[Pipeline] Task %s step %s is not pausable, skipping pause", self.task_id, step_name)
            return False

        checkpoint = _STEP_TO_CHECKPOINT.get(step_name)
        if not checkpoint:
            return False
        if checkpoint not in mc.pause_points:
            return False
        if checkpoint in mc.approved_checkpoints:
            return False

        # 落盘暂停态：复用 PENDING + current_checkpoint 表达"等待用户"（PRD §4.2）
        # 进度展示该步骤完成时的真实进度（progress 参数 > 映射表 > 兜底 1.0），避免暂停显示 100%
        if progress is None:
            progress = _PAUSE_PROGRESS_BY_STEP.get(step_name, 1.0)
        mc.current_checkpoint = checkpoint
        state.status = StepStatus.PENDING
        self.task_manager.update_state(
            status=StepStatus.PENDING,
            manual_config=mc,
            current_step=checkpoint,
            current_status="awaiting_user",
            current_message=f"等待你在检查点 '{checkpoint}' 确认或修改产物",
            current_progress=progress,
        )
        logger.info(
            "[Pipeline] Task %s paused at checkpoint '%s' (manual mode)",
            self.task_id, checkpoint,
        )
        raise CheckpointPause(checkpoint)

    @property
    def state(self) -> Optional[BaseTaskState]:
        return self._state

    @property
    def working_dir(self) -> str:
        return self.task_manager.task_dir

    @abstractmethod
    async def run(self, state: BaseTaskState) -> str:
        """执行流水线，返回最终视频路径。"""
        ...

    # ==================================================================
    # 通用工具方法
    # ==================================================================

    @staticmethod
    def fix_double_utf8(text: str) -> str:
        """检测并修复双重 UTF-8 编码的文本。

        当 UTF-8 字节被误解读为 Latin-1 后再编码为 UTF-8 时，
        会产生乱码。此方法尝试还原原始文本。

        Args:
            text: 可能双重编码的文本。

        Returns:
            修复后的文本，如果不需要修复则返回原文。
        """
        if not text:
            return text
        # 检测典型乱码特征：包含 Latin-1 扩展字符且可被还原
        try:
            # 尝试将文本当作 Latin-1 编码的 UTF-8 字节来解码
            fixed = text.encode('latin-1').decode('utf-8')
            # 验证修复后的文本是有效的中文/ASCII
            if all(ord(c) < 0x80 or '\u4e00' <= c <= '\u9fff'
                   or '\u3000' <= c <= '\u303f'
                   or '\uff00' <= c <= '\uffef'
                   or '\u2000' <= c <= '\u206f'
                   for c in fixed[:20]):
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        return text

    def save_prompts(self, prompts_data: dict) -> str:
        """将自动生成的 prompt 记录保存到 working_dir/prompts.json。

        Args:
            prompts_data: 包含各类 prompt 的字典，如
                {"anchor_prompt": ..., "clip_prompts": [...], "subtitle_styles": ...}

        Returns:
            保存的文件路径。
        """
        path = os.path.join(self.working_dir, "prompts.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(prompts_data, f, ensure_ascii=False, indent=2)
            logger.info("[Pipeline] prompts saved → %s", path)
        except Exception as e:
            logger.warning("[Pipeline] Failed to save prompts: %s", e)
        return path

    def _save_narration_txt(self, text: str, audio_path: str = "") -> str:
        """将旁白/读稿纯文本导出为 .txt（v5.x 产物规范前置工作）。

        文件名与音频同名推导（``xxx.mp3`` → ``xxx.txt``）；未给 ``audio_path``
        时使用 ``narration.txt``。导出文件供用户 / 外部 Agent 直接投喂给 LLM
        润色或修正，属于 v6.0 手动模式「产物可外部处理」的前置。

        Args:
            text: 旁白纯文本（无则跳过）。
            audio_path: 对应音频文件路径（可为空）。

        Returns:
            落盘的 txt 路径；失败或空文本时返回空串。
        """
        if not text:
            return ""
        if audio_path:
            txt_path = os.path.splitext(audio_path)[0] + ".txt"
        else:
            txt_path = os.path.join(self.working_dir, "narration.txt")
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
            logger.info("[Artifacts] narration txt saved → %s", txt_path)
        except Exception as e:
            logger.warning("[Artifacts] failed to save narration txt: %s", e)
            return ""
        return txt_path

    @staticmethod
    def get_audio_duration(audio_path: str) -> float:
        """通过 ffprobe 获取音频文件时长（秒），失败返回 0.0。"""
        if not audio_path or not os.path.exists(audio_path):
            return 0.0
        if os.path.getsize(audio_path) == 0:
            return 0.0
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", audio_path],
                stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=15,
            )
            return float(r.stdout.strip())
        except Exception:
            return 0.0

    async def generate_subtitles_common(
        self,
        segment_texts: List[str],
        segment_durations: List[float],
        subtitle_config: SubtitleConfig,
        sub_maker: object = None,
        audio_path: str = "",
        srt_filename: str = "full_subtitle.srt",
        styles_filename: str = "subtitle_styles.json",
        screenwriter=None,
        video_width: int = 768,
        video_height: int = 1152,
        role: str = "",
    ) -> tuple:
        """通用字幕生成逻辑，供所有 pipeline 复用。

        统一处理：
            1. 获取实际音频时长并按比例缩放段落时长
            2. 场景感知 SRT 生成（多段落）/ cues_to_srt（单段+词级）/ text_to_srt（纯文本）
            3. LLM 智能样式生成（style_mode=llm 时）

        Args:
            segment_texts: 各段文本列表。
            segment_durations: 各段估算时长列表（秒）。
            subtitle_config: 字幕配置。
            sub_maker: TTS SubMaker cues（可选）。
            audio_path: 音频文件路径（用于获取实际时长）。
            srt_filename: SRT 文件名。
            styles_filename: LLM 样式 JSON 文件名。
            screenwriter: Screenwriter 实例（LLM 样式生成用）。
            video_width: 视频宽度。
            video_height: 视频高度。
            role: 角色描述（传给 LLM 样式生成）。

        Returns:
            (srt_path, styles_path) 元组，styles_path 为空串表示未生成。
        """
        from core.audio.subtitle import SubtitleGenerator

        srt_path = os.path.join(self.working_dir, srt_filename)
        styles_path = ""

        # ── 已存在则跳过 ──
        if os.path.exists(srt_path) and os.path.getsize(srt_path) > 0:
            logger.info("[Subtitle] SRT already exists, skipping: %s", srt_path)
            if subtitle_config.enabled and subtitle_config.style.style_mode == "llm":
                sp = os.path.join(self.working_dir, styles_filename)
                if os.path.exists(sp) and os.path.getsize(sp) > 0:
                    styles_path = sp
            return srt_path, styles_path

        full_text = "\n\n".join(t for t in segment_texts if t)
        if not full_text:
            logger.warning("[Subtitle] empty text, skipping")
            return "", ""

        # ── 1. 获取实际音频时长 ──
        actual_audio_dur = self.get_audio_duration(audio_path)

        # ── 2. 生成 SRT ──
        num_segments = len(segment_texts)
        use_cue_timeline = getattr(subtitle_config, "use_cue_timeline", True)

        if subtitle_config.enabled and num_segments > 1:
            # 按音频时长等比缩放段落时长（场景时间轴/策略B 用；cues 路径计时本身不依赖缩放）
            total_est = sum(segment_durations)
            scaled_durations = list(segment_durations)
            if actual_audio_dur > 0 and total_est > 0:
                scale = actual_audio_dur / total_est
                scaled_durations = [d * scale for d in scaled_durations]
                logger.info(
                    "[Subtitle] durations scaled by %.3f (audio=%.2fs, est=%.2fs)",
                    scale, actual_audio_dur, total_est,
                )

            # cues 精确对齐（有 sub_maker 且开关开启）；否则回退 legacy 启发式
            if sub_maker is not None and use_cue_timeline:
                scene_start_times = []
                acc = 0.0
                for d in scaled_durations:
                    scene_start_times.append(acc)
                    acc += d
                srt_content = SubtitleGenerator.generate_cue_aware_srt(
                    sub_maker,
                    segment_texts=segment_texts,
                    scene_start_times=scene_start_times,
                    scene_durations=scaled_durations,
                    audio_duration=actual_audio_dur if actual_audio_dur > 0 else None,
                )
                if not srt_content.strip():
                    # cues 不足（如 raw_cues 粒度过低）→ 回退 legacy
                    logger.warning(
                        "[Subtitle] cue-aware produced empty SRT, "
                        "falling back to scene-aware"
                    )
                    srt_content = SubtitleGenerator._generate_scene_aware_srt(
                        segment_texts, scaled_durations, word_cues=None,
                    )
            else:
                srt_content = SubtitleGenerator._generate_scene_aware_srt(
                    segment_texts, scaled_durations, word_cues=None,
                )

            if srt_content.strip():
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
                entry_count = srt_content.count("\n\n") + 1 if "\n\n" in srt_content else 0
                logger.info(
                    "[Subtitle] Scene-aware SRT: %d entries across %d segments",
                    entry_count, num_segments,
                )
            else:
                subtitle_config.enabled = False
        elif subtitle_config.enabled and sub_maker is not None:
            SubtitleGenerator.cues_to_srt(sub_maker, srt_path)
        elif subtitle_config.enabled:
            total_dur = actual_audio_dur if actual_audio_dur > 0 else sum(segment_durations)
            SubtitleGenerator.text_to_srt(full_text, srt_path, total_dur)
        else:
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("")

        # ── 2.5 统一后处理：确保每条字幕不超过 2 行（参考中文短字幕规范，适配所有语言）──
        try:
            raw_srt = open(srt_path, "r", encoding="utf-8").read()
            fixed_srt = SubtitleGenerator.enforce_max_lines(
                raw_srt, max_lines=2,
                video_width=video_width, fontsize=subtitle_config.style.fontsize,
            )
            if fixed_srt and fixed_srt != raw_srt:
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(fixed_srt)
                entry_count = fixed_srt.count("\n\n") + 1 if "\n\n" in fixed_srt else 1
                logger.info(
                    "[Subtitle] enforce_max_lines applied: ≤2 lines/entry (%d entries)",
                    entry_count,
                )
        except Exception as e:
            logger.warning("[Subtitle] enforce_max_lines failed: %s", e)

        # ── 3. LLM 智能样式 ──
        if (subtitle_config.enabled
                and subtitle_config.style.style_mode == "llm"
                and screenwriter is not None):
            sp = os.path.join(self.working_dir, styles_filename)
            if not os.path.exists(sp) or os.path.getsize(sp) == 0:
                try:
                    styles = await asyncio.to_thread(
                        screenwriter.generate_subtitle_styles,
                        srt_path=srt_path,
                        video_width=video_width,
                        video_height=video_height,
                        style_hints=subtitle_config.style.style_hints,
                        **({"role": role} if role else {}),
                    )
                    with open(sp, "w", encoding="utf-8") as f:
                        json.dump(styles, f, ensure_ascii=False, indent=2)
                    styles_path = sp
                    logger.info(
                        "[Subtitle] LLM styles saved: %s (%d entries)",
                        sp, len(styles),
                    )
                except Exception as e:
                    logger.warning(
                        "[Subtitle] LLM styles failed: %s, falling back to fixed", e
                    )

        return srt_path, styles_path


    # ==================================================================
    # 共享工具：上提自各 pipeline 子类（v4.0 重构消重）
    # ==================================================================

    def _check_shutdown(self) -> None:
        """检查是否需要停止流水线，收到停止信号则抛出 PipelineShutdown。"""
        if self._is_shutdown():
            raise PipelineShutdown("Pipeline shutdown requested")

    async def _recover_sub_maker(
        self, narration_text: str, audio_config, subtitle_config
    ) -> object:
        """音频文件已存在、TTS 步骤被跳过时，若字幕需要 cues 则仅重新采集 cues。

        续传场景下 ``_step_audio`` 常因音频文件已存在而跳过，导致 ``sub_maker``
        丢失，进而字幕退回 legacy 启发式（v2.0 cue 精确对齐失效）。此方法在不重新
        生成音频字节的前提下，仅消费 TTS 流采集 WordBoundary cues，恢复精确时间线。

        Returns:
            SubMaker cues 对象；不需要或失败时返回 None。
        """
        if not narration_text:
            return None
        use_cue = getattr(subtitle_config, "use_cue_timeline", True)
        if not (getattr(subtitle_config, "enabled", False) and use_cue):
            return None
        try:
            from core.audio.tts import EdgeTTSEngine
            return await EdgeTTSEngine().harvest_cues(
                text=narration_text,
                voice=getattr(audio_config, "voice", ""),
                rate=getattr(audio_config, "rate", "+0%"),
            )
        except RuntimeError as e:
            logger.warning("[Subtitle] recover sub_maker via harvest_cues failed: %s", e)
            return None

    async def _generate_audio_with_fallback(
        self,
        output_path: str,
        text: str,
        audio_config: AudioConfig,
        subtitle_config: Optional[SubtitleConfig] = None,
        duration_sec: float = 0.0,
        empty_placeholder: str = "",
    ) -> Optional[object]:
        """统一 TTS 音频生成（EdgeTTS → Silent 降级 + cues 采集）。

        S2 收敛目标：替代 multi_scene / creative / poetry / manuscript / anchor
        五处复制的"EdgeTTS → Silent 降级 + harvest_cues"逻辑（v5.0 Batch 2）。

        行为矩阵：
            1. text 为空：empty_placeholder="" → 跳过返回 None（不落盘）；
               非空 → 以占位文本直接走 Silent 落盘（不调用 EdgeTTS）。
            2. audio_config.enabled → EdgeTTSEngine.generate：
               成功 → 校验 cues（无逐词时间戳 → warning 并返回 None，
               字幕回退 legacy 启发式）；
               RuntimeError → Silent(duration_sec) 落盘。
            3. 音频关 + 字幕开 + harvest_cues_when_audio_off（路径 B）：
               harvest_cues 采集（RuntimeError 仅警告）→ 随后 Silent 落盘，返回 cues。
            4. 其他（音频关 / 不采集 cues）→ Silent 落盘，返回 None。

        Args:
            output_path: 输出音频文件路径。
            text: 配音文本。
            audio_config: 音频配置（AudioConfig 或含 enabled/voice/rate 的鸭子类型）。
            subtitle_config: 字幕配置（音频关闭时决定是否采集 cues）。
            duration_sec: Silent 降级音频时长（秒）；0 表示由引擎按文本估算。
            empty_placeholder: 文本为空时的占位文本；"" 表示空文本直接跳过。

        Returns:
            SubMaker cues 对象（有 cues 可用时）；否则 None。
        """
        from core.audio.tts import EdgeTTSEngine, SilentTTSEngine

        audio_enabled = bool(getattr(audio_config, "enabled", True))
        subtitle_enabled = bool(getattr(subtitle_config, "enabled", False))
        harvest_cues = bool(getattr(subtitle_config, "harvest_cues_when_audio_off", True))
        voice = getattr(audio_config, "voice", "zh-CN-XiaoxiaoNeural")
        rate = getattr(audio_config, "rate", "+0%")

        # 空文本：无占位 → 跳过；有占位 → 直接 Silent 落盘（不调用 EdgeTTS）
        if not text:
            if not empty_placeholder:
                logger.info("[Audio] empty text, skipping TTS: %s", output_path)
                return None
            text = empty_placeholder
            await SilentTTSEngine().generate(
                text=text, output_path=output_path,
                **({"duration_sec": duration_sec} if duration_sec else {}),
            )
            return None

        silent_tts = SilentTTSEngine()

        # 路径 A：音频开 → EdgeTTS 生成
        if audio_enabled:
            try:
                edge_tts = EdgeTTSEngine()
                _, sub_maker = await edge_tts.generate(
                    text=text, output_path=output_path, voice=voice, rate=rate,
                )
                # cues 不足 → 字幕回退 legacy 启发式（不删音频，仅返回 None）
                if sub_maker is not None and not getattr(sub_maker, "cues", None):
                    logger.warning(
                        "[Audio] EdgeTTS produced no cues, "
                        "subtitles fall back to legacy: %s",
                        output_path,
                    )
                    return None
                return sub_maker
            except RuntimeError as e:
                logger.warning("[Audio] EdgeTTS failed, falling back to silent: %s", e)
                await silent_tts.generate(
                    text=text, output_path=output_path,
                    **({"duration_sec": duration_sec} if duration_sec else {}),
                )
                return None

        # 路径 B：音频关 + 字幕开 + harvest_cues_when_audio_off → 仅采集 cues
        if subtitle_enabled and harvest_cues:
            sub_maker = None
            try:
                edge_tts = EdgeTTSEngine()
                sub_maker = await edge_tts.harvest_cues(
                    text=text, voice=voice, rate=rate,
                )
            except RuntimeError as e:
                logger.warning("[Audio] harvest_cues failed, silent fallback: %s", e)
            await silent_tts.generate(
                text=text, output_path=output_path,
                **({"duration_sec": duration_sec} if duration_sec else {}),
            )
            return sub_maker

        # 其他（音频关 / 不采集 cues）→ Silent 落盘
        await silent_tts.generate(
            text=text, output_path=output_path,
            **({"duration_sec": duration_sec} if duration_sec else {}),
        )
        return None

    @staticmethod
    def _make_curl(video_id: str) -> str:
        """生成用于查询视频状态的 curl 命令（供调试/续传）。"""
        return (
            f'curl -s -H "Authorization: Bearer $AGNES_API_KEY" '
            f'"https://apihub.agnes-ai.com/agnesapi?video_id={video_id}"'
        )

    def _save_task_json(self, sub_dir: str, data: dict) -> None:
        """持久化任务元数据（video_id 等）到 sub_dir/task.json + curl.sh。"""
        os.makedirs(sub_dir, exist_ok=True)
        task_file = os.path.join(sub_dir, "task.json")
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        curl_file = os.path.join(sub_dir, "curl.sh")
        with open(curl_file, "w", encoding="utf-8") as f:
            f.write(self._make_curl(data.get("video_id", "")) + "\n")

    def _load_task_json(self, sub_dir: str) -> Optional[str]:
        """从 sub_dir/task.json 读取已保存的 video_id（断点续传用）。"""
        task_file = os.path.join(sub_dir, "task.json")
        if os.path.exists(task_file):
            try:
                with open(task_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("video_id") or data.get("task_id")
            except Exception as e:
                logger.debug(f"[Pipeline] Failed to load cached task.json: {e}")
        return None

    def _get_watermark_language_text(self) -> str:
        """水印语言检测用文本。子类可覆盖以返回合适的来源文本。"""
        return ""

    def _apply_watermark(self, video_path: str) -> str:
        """通用水印后处理：根据配置叠加水印（不修改原文件则原样返回）。"""
        wm_config = get_watermark_config()
        if wm_config.get("enabled") and os.path.exists(video_path):
            lang = wm_config.get("language", "auto")
            if lang == "auto":
                lang = detect_language(self._get_watermark_language_text())
            wm_output = video_path + ".wm_tmp.mp4"
            if add_watermark(video_path, wm_output, language=lang):
                os.replace(wm_output, video_path)
        return video_path

    @staticmethod
    async def run_ffmpeg_async(cmd: List[str], timeout: float = 30.0) -> None:
        """异步执行 ffmpeg 命令（不阻塞事件循环）。等价于 subprocess.run(check=True)。"""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        if proc.returncode != 0:
            err = stderr.decode(errors="replace")[:500] if stderr else ""
            raise RuntimeError(f"ffmpeg exited with code {proc.returncode}: {err}")


# 导出
from core.pipelines.multi_scene import MultiScenePipeline
from core.pipelines.simple_video import SimpleVideoPipeline
from core.pipelines.creative_video import CreativeVideoPipeline
from core.pipelines.manuscript_video import ManuscriptVideoPipeline
from core.pipelines.anchor_video import AnchorPipeline
from core.pipelines.poetry_video import PoetryVideoPipeline
from core.pipelines.influencer import InfluencerPipeline

__all__ = [
    "BasePipeline",
    "PipelineShutdown",
    "MultiScenePipeline",
    "SimpleVideoPipeline",
    "CreativeVideoPipeline",
    "ManuscriptVideoPipeline",
    "AnchorPipeline",
    "PoetryVideoPipeline",
    "InfluencerPipeline",
]
