"""core.pipelines.poetry_video -- 诗词视频流水线（类型 6 / v4.0）

用户输入古诗 → LLM 拆分为若干场景（narration=原诗句, scene_prompt=视频描述）
→ 逐场景 t2v 生成 → 逐场景 TTS 朗诵配音 + 该句字幕（定时对齐）→ 逐场景合成后拼接。

与创意视频的区别：创意从 idea 经 story/script 生成 narration+prompt；
诗歌直接由 LLM 从原诗拆分出 narration(原诗句) + scene_prompt(视频描述)。
字幕/配音定制：逐场景生成，每句间隔由场景视频时长补足（拉长间隔，诗句↔画面一一对应）。
"""

import asyncio
import logging
import os
import re
import shutil
from typing import List, Optional

from core.api.agnes_video import AgnesVideoAPI
from core.audio.subtitle import SubtitleGenerator
from core.audio.tts import EdgeTTSEngine, SilentTTSEngine
from core.compositor.concatenator import VideoConcatenator
from core.pipelines import MultiScenePipeline
from core.screenwriter import Screenwriter
from models.task import (
    PoetryVideoTask,
    SceneTask,
    StepStatus,
    SubtitleStyle,
)

logger = logging.getLogger(__name__)

# 诗歌固定字幕样式：居中偏下、白字黑描边、半透明底（用户只开关，不选样式）
POETRY_SUBTITLE_STYLE = SubtitleStyle(
    font="STHeitiMedium.ttc",
    color="white",
    position=("center", "bottom-80"),
    fontsize=48,
    stroke_color="black",
    stroke_width=2,
    bg_color=(0, 0, 0, 140),
)

_CHARS_PER_SEC = 4.0

_SCENE_LABEL_RE = re.compile(r"^(场景|Scene)\s*\d+|[（(]\s*\d+\s*:\s*\d+")


def _is_scene_label(line: str) -> bool:
    """判断一行是否为纯场景标签（如「场景 1（00:00 - 00:10）」），而非分镜描述。

    用户或外部 LLM 常在每行前加「场景 N」或时间范围，这类行不含有效描述，
    需过滤掉以免干扰「全部含 |」的直接构建检测。
    """
    s = line.strip()
    if re.match(r"^(场景|Scene)\s*\d+", s, re.IGNORECASE):
        return True
    if re.search(r"[（(]\s*\d+\s*:\s*\d+", s):
        return True
    return False


class PoetryVideoPipeline(MultiScenePipeline):
    """诗词视频生成流水线。

    古诗原文 → LLM 拆分场景(narration+scene_prompt) → 逐场景视频生成 →
    逐场景朗诵配音 + 该句字幕 → 逐场景合成后拼接。
    """

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: Optional[str] = None,
        chat_model: str = "agnes-2.0-flash",
        video_model: str = "agnes-video-v2.0",
        progress_callback: Optional[callable] = None,
        shutdown_event: Optional = None,
    ):
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)
        self.video_api = AgnesVideoAPI(api_key=api_key, model=video_model)
        self.screenwriter = Screenwriter(api_key=api_key, model=chat_model)
        self.video_api.set_refresh_key_callback(self._make_refresh_key_callback())
        self._state: Optional[PoetryVideoTask] = None

    @property
    def state(self) -> Optional[PoetryVideoTask]:
        return self._state

    # ------------------------------------------------------------------
    # 水印语言
    # ------------------------------------------------------------------

    def _get_watermark_language_text(self) -> str:
        return self._state.poem_text

    # ------------------------------------------------------------------
    # Phase 1: 分镜（LLM 拆分原诗 → scenes）
    # ------------------------------------------------------------------

    def _resolve_durations_for_count(
        self, count: int, duration_source: str, scene_durations: List[int]
    ) -> List[int]:
        """规整时长列表至 count 个（与创意视频一致：不足补末值、超出截断）。"""
        if duration_source == "prompt":
            total = max(int(self._state.video_duration), count * 3)
            per = max(int(total / count), 3)
            return [per] * count
        if not scene_durations:
            return [5] * count
        d = list(scene_durations)
        if len(d) < count:
            while len(d) < count:
                d.append(d[-1])
        elif len(d) > count:
            d = d[:count]
        return d

    def _build_scenes_from_user(
        self, user_scenes: List[tuple], duration_source: str, scene_durations: List[int]
    ) -> List[SceneTask]:
        """用户用「诗句 | 描述」完整定义分镜 → 直接构建，跳过 LLM 拆分。"""
        count = len(user_scenes)
        durations = self._resolve_durations_for_count(count, duration_source, scene_durations)
        return [
            SceneTask(index=i, scene_prompt=p, narration_text=v, duration=durations[i])
            for i, (v, p) in enumerate(user_scenes)
        ]

    def _finalize_scenes(self, scenes: List[SceneTask], poem: str, source: str) -> None:
        n = len(scenes)
        self._state.scenes = scenes
        self._state.scene_count = n
        self._state.scene_durations = [s.duration for s in scenes]
        self.task_manager.update_state(
            scenes=[s.model_dump() for s in scenes],
            scene_count=n,
            scene_durations=[s.duration for s in scenes],
        )
        self.save_prompts({
            "poem_text": poem,
            "scene_prompts": [s.scene_prompt for s in scenes],
            "narrations": [s.narration_text for s in scenes],
            "durations": [s.duration for s in scenes],
            "source": source,
        })

    async def _build_scenes(self) -> None:
        """拆分整首诗词为若干场景，保留原诗句作为 narration。

        分镜描述支持「原诗句 | 画面描述」格式：左侧诗句成为该场景的字幕+配音
        文本，右侧为视频画面描述。用户用该格式完整定义每个分镜时，直接构建
        场景（跳过 LLM 拆分），使每景与诗句精确对应。

        场景配置解析与创意视频完全一致：
        - ``duration_source == "prompt"``：时长由 video_duration 均分。
        - ``duration_source == "manual"``：使用用户指定的 scene_count 与
          scene_durations（统一/独立）。
        """
        poem = self._state.poem_text.strip()
        if not poem:
            self._state.scenes = []
            return

        duration_source = self._state.duration_source
        scene_count = self._state.scene_count
        scene_durations = list(self._state.scene_durations) if self._state.scene_durations else []

        # 解析用户分镜描述：每行支持「原诗句 | 画面描述」。
        # 过滤纯场景标签行（如「场景 1（00:00 - 00:10）」），避免干扰格式检测。
        user_lines = [
            l.strip() for l in (self._state.user_scene_prompts or [])
            if l.strip() and not _is_scene_label(l)
        ]
        user_scenes: List[tuple] = []
        for line in user_lines:
            if "|" in line:
                verse, _, prompt = line.partition("|")
                user_scenes.append((verse.strip() or None, prompt.strip()))
            else:
                user_scenes.append((None, line))

        # 用户用「诗句 | 描述」完整定义每个分镜 → 直接构建，跳过 LLM 拆分。
        if user_scenes and all(v is not None for v, _ in user_scenes):
            scenes = self._build_scenes_from_user(user_scenes, duration_source, scene_durations)
            self._finalize_scenes(scenes, poem, source="user_formatted")
            return

        # 否则：LLM 拆分原诗（用户未提供完整格式时仍由 AI 决定场景与诗句对应）。
        resolved_count = 0 if duration_source == "prompt" else scene_count
        if duration_source == "prompt":
            # prompt 来源：时长由 video_duration 均分，场景数交由 LLM 决定
            llm_durations: List[int] = []
            llm_total = int(self._state.video_duration)
        else:
            # 手动模式：把表单里的每场景时长原样交给 LLM，使提示词与可复制提示词、
            # 实际视频生成时长三者一致（合计 = 各场景时长之和）。
            llm_durations = self._resolve_durations_for_count(
                resolved_count, duration_source, scene_durations)
            llm_total = sum(llm_durations) if llm_durations else int(self._state.video_duration)

        raw_scenes = await asyncio.to_thread(
            self.screenwriter.generate_poetry_scenes,
            poem,
            resolved_count,
            llm_durations,
            llm_total,
            self._state.style,
        )
        if not raw_scenes:
            raise RuntimeError("[Poetry] LLM 未返回有效场景，请重试")

        n = len(raw_scenes)
        durations = self._resolve_durations_for_count(n, duration_source, scene_durations)

        scenes: List[SceneTask] = []
        for idx, sc in enumerate(raw_scenes):
            narration = (sc.get("narration") or "").strip()
            prompt = (sc.get("scene_prompt") or "").strip()
            # 用户在该索引提供了分镜（可能含诗句）→ 覆盖对应字段
            if idx < len(user_scenes):
                uv, up = user_scenes[idx]
                if up:
                    prompt = up
                if uv:
                    narration = uv  # 用户显式绑定诗句到该分镜
            scenes.append(SceneTask(
                index=idx,
                scene_prompt=prompt,
                narration_text=narration,
                duration=durations[idx] if idx < len(durations) else 5,
            ))

        self._finalize_scenes(scenes, poem, source="llm")

    async def _build_reference_images(self) -> None:
        """诗词视频不需参考图，跳过。"""
        pass

    # ------------------------------------------------------------------
    # Phase 4: 配音（逐场景 TTS narration_text）
    # ------------------------------------------------------------------
    _AUDIO_MIN_CHARS_PER_SEC = 3.0  # 中文 TTS 最低语速 ~3 字/秒
    _SCENE_TTS_DELAY = 2.0           # 场景间间隔，避免 edge_tts 流截断

    async def _generate_audio(self) -> Optional[object]:
        """逐场景生成朗诵配音，每段存 scene_{idx}/narration.mp3。

        返回 None（字幕由各场景独立生成，不使用全局 sub_maker）。

        注意：逐场景 TTS 在快速连续调用时，edge_tts Communicate.stream()
        可能提前截断（仅前半段有声音、后半段丢失且不抛异常）。
        因此每个场景间加入延迟，并在生成后校验音频时长。
        """
        import subprocess as _sp

        scenes = self._state.scenes
        audio_config = self._state.audio_config
        has_audio = audio_config.enabled

        for idx, scene in enumerate(scenes):
            scene_dir = os.path.join(self.working_dir, f"scene_{idx}")
            os.makedirs(scene_dir, exist_ok=True)
            audio_path = os.path.join(scene_dir, "narration.mp3")

            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                scene.narration_audio = audio_path
                continue

            text = (scene.narration_text or "").strip()
            if not text:
                silent = SilentTTSEngine()
                await silent.generate(
                    text=" ", output_path=audio_path,
                    duration_sec=max(int(scene.duration), 2),
                )
                scene.narration_audio = audio_path
                continue

            await self._emit(
                "audio", "running",
                f"生成朗诵配音 {idx+1}/{len(scenes)}...", 0.75,
            )

            # 场景间延迟（除第一个）：避免 edge_tts 流截断
            if idx > 0:
                await asyncio.sleep(self._SCENE_TTS_DELAY)

            silent = SilentTTSEngine()
            min_dur = max(len(text) / self._AUDIO_MIN_CHARS_PER_SEC, 2.0)

            if has_audio:
                try:
                    edge_tts = EdgeTTSEngine()
                    await edge_tts.generate(
                        text=text, output_path=audio_path,
                        voice=audio_config.voice, rate=audio_config.rate,
                    )
                    # 校验：音频文件存在且时长不低于预期的 60%
                    actual_dur = self._probe_duration(audio_path, _sp)
                    if actual_dur is not None and actual_dur < min_dur * 0.6:
                        logger.warning(
                            f"[Poetry] scene {idx} audio incomplete "
                            f"(actual={actual_dur:.1f}s < expected={min_dur:.1f}s*0.6), "
                            f"falling back to silent"
                        )
                        os.remove(audio_path)
                        await silent.generate(
                            text=text, output_path=audio_path,
                            duration_sec=max(int(scene.duration), int(min_dur)),
                        )
                except RuntimeError as e:
                    logger.warning(f"[Poetry] scene {idx} TTS failed: {e}, silent")
                    await silent.generate(
                        text=text, output_path=audio_path,
                        duration_sec=max(int(scene.duration), int(min_dur)),
                    )
            else:
                await silent.generate(
                    text=text, output_path=audio_path,
                    duration_sec=max(int(scene.duration), int(min_dur)),
                )
            scene.narration_audio = audio_path

        self.task_manager.update_state(
            scenes=[s.model_dump() for s in scenes],
        )
        return None

    @staticmethod
    def _probe_duration(filepath: str, _sp=None) -> Optional[float]:
        """ffprobe 获取音频时长（秒），失败返回 None。"""
        try:
            if _sp is None:
                import subprocess as _sp2
                _sp = _sp2
            proc = _sp.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                 filepath],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return float(proc.stdout.strip())
        except Exception:
            pass
        return None

    @staticmethod
    def _has_audio_stream(filepath: str) -> bool:
        """ffprobe 检测视频文件是否包含音频流（防止复用不完整合成产物）。"""
        try:
            import subprocess as _sp
            proc = _sp.run(
                ["ffprobe", "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                 filepath],
                capture_output=True, text=True, timeout=10,
            )
            return "audio" in proc.stdout
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Phase 5: 字幕（逐场景 SRT，定时对齐朗诵）
    # ------------------------------------------------------------------

    async def _generate_subtitles(self, sub_maker: Optional[object] = None) -> None:
        """逐场景生成字幕，每段存 scene_{idx}/subtitle.srt。

        字幕只在朗诵时段显示，其余为静默画面（句间间隔拉长）。
        """
        scenes = self._state.scenes
        sub_config = self._state.subtitle_config
        if not sub_config.enabled:
            return

        for idx, scene in enumerate(scenes):
            scene_dir = os.path.join(self.working_dir, f"scene_{idx}")
            os.makedirs(scene_dir, exist_ok=True)
            srt_path = os.path.join(scene_dir, "subtitle.srt")

            if os.path.exists(srt_path) and os.path.getsize(srt_path) > 0:
                scene.subtitle_srt = srt_path
                continue

            text = (scene.narration_text or "").strip()
            if not text:
                continue

            # 字幕时长 = 朗诵音频时长（首段显示，余下静默）
            audio_dur = self.get_audio_duration(scene.narration_audio or "")
            dur = max(audio_dur, 1.0)
            await self._emit(
                "subtitle", "running",
                f"生成字幕 {idx+1}/{len(scenes)}...", 0.87,
            )
            SubtitleGenerator.text_to_srt(
                text, srt_path, duration_sec=dur, chars_per_sec=_CHARS_PER_SEC,
            )
            scene.subtitle_srt = srt_path

        self.task_manager.update_state(
            scenes=[s.model_dump() for s in scenes],
        )

    # ------------------------------------------------------------------
    # Phase 6: 合成（逐场景 composite 后拼接）
    # ------------------------------------------------------------------

    async def _composite_final(self) -> str:
        """逐场景合成 video+audio+subtitle → final_clip，再拼接为成片。

        合成器自动将每场景音频补静音至视频时长，即"每句间隔拉长"的实现。
        """
        scenes = self._state.scenes
        has_subtitle = self._state.subtitle_config.enabled

        final_clips = []
        for idx, scene in enumerate(scenes):
            scene_dir = os.path.join(self.working_dir, f"scene_{idx}")
            video_path = scene.video_file
            if not video_path or not os.path.exists(video_path):
                raise RuntimeError(f"[Poetry] scene {idx} video missing")

            audio_path = scene.narration_audio or ""
            srt_path = scene.subtitle_srt or ""
            clip_out = os.path.join(scene_dir, "final_clip.mp4")

            if os.path.exists(clip_out) and os.path.getsize(clip_out) > 0:
                if self._has_audio_stream(clip_out):
                    final_clips.append(clip_out)
                    continue
                logger.warning(f"[Poetry] scene {idx} clip has no audio, redoing compositing")

            # 兜底：音频缺失则生成静音占位，保证合成不中断
            audio_exists = os.path.exists(audio_path) and os.path.getsize(audio_path) > 0
            if not audio_exists:
                audio_path = os.path.join(scene_dir, "narration.mp3")
                await SilentTTSEngine().generate(
                    text=" ", output_path=audio_path,
                    duration_sec=max(int(scene.duration), 2),
                )
                scene.narration_audio = audio_path
                audio_exists = True

            srt_exists = os.path.exists(srt_path) and os.path.getsize(srt_path) > 0

            await self._emit(
                "concatenate", "running",
                f"合成场景 {idx+1}/{len(scenes)}...", 0.90,
            )
            await asyncio.to_thread(
                VideoConcatenator.concat_videos_with_audio_overlay,
                [video_path],
                audio_path,
                srt_path if (has_subtitle and srt_exists) else None,
                clip_out,
                POETRY_SUBTITLE_STYLE,
                None,
            )
            final_clips.append(clip_out)

        output_path = os.path.join(self.working_dir, "final_video.mp4")
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path

        if len(final_clips) == 1:
            shutil.copy2(final_clips[0], output_path)
        else:
            await asyncio.to_thread(
                VideoConcatenator.concat_videos, final_clips, output_path,
            )
        return output_path
