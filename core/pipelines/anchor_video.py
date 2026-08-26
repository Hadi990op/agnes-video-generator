"""core.pipelines.anchor_video -- 数字人口播流水线（类型 4）

支持两种音频模式：
  - post_stitch: 生成一段短 i2v 视频循环 + TTS 后拼接音频（音频可控，嘴型较难匹配）
  - model:      交由视频模型自身生成音频（音频由模型控制，效果不可控）

v4.0 重构：继承 MultiScenePipeline，复用模板方法 run() 与步骤编排。
锚点形象图生成放入 _build_reference_images，clip prompt 生成放入 _build_scenes，
视频/音频/字幕/合成按模式覆写。

v7.0 重写（model 模式）：将长脚本按句切分为多个 ~20s 片段（chunk），
每个 chunk 复用【同一张主播图（face 一致性）】+【同一段角色/外貌描述】生成 i2v 视频，
视频模型自带口播音频；最后按 chunk 顺序拼接为一条完整长视频。
"""

import asyncio
import logging
import math
import os
import re
import shutil
import subprocess
from typing import Callable, List, Optional

from core.api.agnes_image import AgnesImageAPI
from core.api.agnes_video import AgnesVideoAPI
from core.compositor.concatenator import VideoConcatenator
from core.pipelines import MultiScenePipeline, PipelineShutdown
from core.screenwriter import Screenwriter
from models.task import (
    AnchorVideoTask,
    ManuscriptParagraph,
    SceneTask,
    StepStatus,
    AudioConfig,
    SubtitleConfig,
)

logger = logging.getLogger(__name__)

# 单片段重试间隔基数（秒）：delay = 基数 * (attempt + 1)
_CLIP_RETRY_INTERVAL_BASE_SECONDS = 15

# 主播形象生成阶段起始进度
_PROGRESS_ANCHOR_IMAGE = 0.02

# 数字人流水线进度映射（阶段内固定值；保持原有行为不变）
_PROGRESS_ANCHOR_IMAGE_DONE = 0.08
_PROGRESS_CLIP_PROMPTS_START = 0.12
_PROGRESS_CLIP_PROMPTS_DONE = 0.18
_PROGRESS_CLIP_GEN_START = 0.28
_PROGRESS_CLIP_GEN_DONE = 0.55
_PROGRESS_AUDIO_START = 0.55
# 注意：post_stitch 音频完成态回退 0.28（历史行为，保持不变）
_PROGRESS_AUDIO_DONE = 0.28
_PROGRESS_SUBTITLE_START = 0.65
_PROGRESS_SUBTITLE_DONE = 0.75
_PROGRESS_CONCAT_START = 0.80

_DEFAULT_ANCHOR_PROMPT_ZH = (
    "一位专业的新闻主播，穿着正式西装，坐在现代化的新闻演播室中，"
    "面带微笑，正面半身照，高清画质，专业灯光"
)

_DEFAULT_ANCHOR_PROMPT_EN = (
    "A professional news anchor in formal business attire, seated in a modern "
    "news studio, smiling warmly, front-facing half-body shot, high definition, "
    "professional studio lighting"
)

_SENTENCE_END_RE = re.compile(r"(?<=[。！？])")
_CHARS_PER_SEC = 4.0

# 每个 chunk 的最大字符数（~20s @ 4 字/秒，受视频模型时长上限约束）
_CHUNK_MAX_CHARS = 80
# chunk 视频时长上限（秒），与 DURATION_PRESETS 的 20s 上限对齐
_CHUNK_MAX_DURATION = 20


def _split_script_into_chunks(text: str, max_chars: int = _CHUNK_MAX_CHARS) -> List[str]:
    """将口播稿件按句子边界切分为多个 chunk，每段不超过 max_chars。

    保持句末标点；不足 max_chars 的短句向前合并，过长句（>max_chars）单独成段。
    """
    text = (text or "").strip()
    if not text:
        return []
    # 按句子（保留句末标点）切分
    parts = re.findall(r'[^。！？!?]+[。！？!?]?', text)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        parts = [text]
    chunks: List[str] = []
    cur = ""
    for p in parts:
        if cur and len(cur) + len(p) > max_chars:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + p) if cur else p
    if cur:
        chunks.append(cur)
    return chunks


class AnchorPipeline(MultiScenePipeline):
    """数字人口播视频生成流水线。

    根据 audio_source 分两种模式：
      - post_stitch: 生成一段短 i2v 视频 → 循环播放 → TTS + 字幕叠加
      - model:      长脚本切分为多个 ~20s chunk，逐段 i2v（同图同角色描述，模型自带音频）
                     → 按顺序拼接为一条完整长视频
    """

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: Optional[str] = None,
        chat_model: str = "agnes-2.0-flash",
        image_model: str = "agnes-image-2.1-flash",
        video_model: str = "agnes-video-v2.0",
        progress_callback: Optional[Callable] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)
        self.image_generator = AgnesImageAPI(api_key=api_key, model=image_model)
        self.video_generator = AgnesVideoAPI(api_key=api_key, model=video_model)
        self.video_generator.shutdown_event = shutdown_event
        self.screenwriter = Screenwriter(api_key=api_key, model=chat_model)
        self._state: Optional[AnchorVideoTask] = None

    @property
    def state(self) -> Optional[AnchorVideoTask]:
        return self._state

    # ------------------------------------------------------------------
    # 模板钩子
    # ------------------------------------------------------------------

    def _get_watermark_language_text(self) -> str:
        return self._state.script_text

    def _get_default_anchor_prompt(self) -> str:
        """根据 script_text 语言返回合适的主播默认描述。"""
        text = (self._state.script_text or "").strip()
        if re.search(r'[\u4e00-\u9fff]', text):
            return _DEFAULT_ANCHOR_PROMPT_ZH
        return _DEFAULT_ANCHOR_PROMPT_EN

    # ------------------------------------------------------------------
    # 数据来源：参考图（主播形象）
    # ------------------------------------------------------------------

    async def _build_reference_images(self) -> None:
        """Step: 生成主播形象图（t2i / i2i）。"""
        prompt = self._state.anchor_prompt or self._get_default_anchor_prompt()
        output_path = os.path.join(self.working_dir, "anchor.png")

        if os.path.exists(output_path):
            self._state.anchor_image_path = output_path
            logger.info("[Anchor] anchor image already exists, skipping")
            return

        ref_image = self._state.anchor_reference_image
        size = f"{self._state.video_width}x{self._state.video_height}"

        await self._emit(
            "generate_anchor", "running",
            "生成主播形象图..." if not ref_image else "基于参考图生成主播形象...",
            _PROGRESS_ANCHOR_IMAGE,
        )

        try:
            if ref_image and os.path.exists(ref_image):
                img_output = await self.image_generator.generate_single_image(
                    prompt=prompt,
                    reference_image_paths=[ref_image],
                    size=size,
                )
            else:
                img_output = await self.image_generator.generate_single_image(
                    prompt=prompt,
                    size=size,
                )
            img_output.save(output_path)
        except Exception as e:
            logger.error(f"[Anchor] Anchor image generation failed: {e}")
            raise RuntimeError(f"主播形象生成失败: {e}")

        self._state.anchor_image_path = output_path
        self.task_manager.update_state(anchor_image_path=output_path)
        await self._emit("generate_anchor", "completed", "主播形象生成完成", _PROGRESS_ANCHOR_IMAGE_DONE)

    # ------------------------------------------------------------------
    # 数据来源：分镜（单段 / 多 chunk clip 的 prompt）
    # ------------------------------------------------------------------

    async def _build_scenes(self) -> None:
        """构建场景：

        - post_stitch: 生成单段「循环优化」动态描述（1 个 scene）。
        - model:       长脚本切分为多个 chunk，逐 chunk 生成「含口播」视频 prompt
                        （每个 chunk 都包含【同一角色外貌描述】以保证一致性）。
        """
        if self._state.scenes and self._state.scenes[0].scene_prompt:
            logger.info("[Anchor] _build_scenes: SKIP (scene prompt already exists)")
            return
        audio_source = self._state.audio_source or "post_stitch"
        anchor_prompt = self._state.anchor_prompt or self._get_default_anchor_prompt()

        await self._emit(
            "clip_prompts", "running",
            "生成循环优化动态描述..." if audio_source == "post_stitch"
            else "切分脚本并生成各分段口播描述...", _PROGRESS_CLIP_PROMPTS_START,
        )

        if audio_source == "post_stitch":
            try:
                prompt = await asyncio.to_thread(
                    self.screenwriter.generate_anchor_smooth_loop_prompt,
                    anchor_prompt=anchor_prompt,
                )
                prompt = prompt.strip()
            except Exception as e:
                logger.warning("[Anchor] clip prompt generation failed: %s, using fallback", e)
                prompt = (
                    "A digital human anchor, subtle breathing motion, "
                    "slight head micro-nod, nearly still posture, "
                    "seamless loop, professional studio lighting"
                )
            self.save_prompts({
                "anchor_prompt": anchor_prompt,
                "smooth_loop_prompt": prompt,
            })
            self._state.scenes = [SceneTask(index=0, scene_prompt=prompt, duration=5)]
        else:
            # model 模式：长脚本 → 多 chunk
            full_text = self._state.script_text or ""
            chunks = _split_script_into_chunks(full_text, _CHUNK_MAX_CHARS)
            if not chunks:
                chunks = [full_text]
            scenes: List[SceneTask] = []
            prompts_info: dict = {"anchor_prompt": anchor_prompt, "chunks": []}
            for i, chunk in enumerate(chunks):
                try:
                    chunk_prompt = await asyncio.to_thread(
                        self.screenwriter.generate_anchor_model_audio_prompt,
                        anchor_prompt=anchor_prompt,
                        script_text=chunk,
                    )
                    chunk_prompt = chunk_prompt.strip()
                except Exception as e:
                    logger.warning("[Anchor] chunk %d prompt failed: %s, fallback", i, e)
                    chunk_prompt = f"{anchor_prompt}. Speak the following naturally: {chunk}"
                dur = max(5, min(_CHUNK_MAX_DURATION, math.ceil(len(chunk) / _CHARS_PER_SEC)))
                scenes.append(SceneTask(index=i, scene_prompt=chunk_prompt, duration=dur))
                prompts_info["chunks"].append({"index": i, "text": chunk, "prompt": chunk_prompt})
            self.save_prompts(prompts_info)
            self._state.scenes = scenes

        self.task_manager.update_state(scenes=[s.model_dump() for s in self._state.scenes])
        await self._emit(
            "clip_prompts", "completed",
            f"动态描述生成完成（{len(self._state.scenes)} 段）", _PROGRESS_CLIP_PROMPTS_DONE,
        )

    # ------------------------------------------------------------------
    # 视频生成（逐 chunk i2v，复用同一张主播图保证 face 一致性）
    # ------------------------------------------------------------------

    async def _generate_videos(self) -> None:
        """逐段生成 i2v 视频（model 模式多 chunk；post_stitch 模式单段）。

        每个 chunk 均使用同一张 anchor_image_path（face 一致性）与各自包含
        相同角色描述的 prompt。
        """
        anchor_image_path = self._state.anchor_image_path
        vw = self._state.video_width
        vh = self._state.video_height

        clip_dir = os.path.join(self.working_dir, "clip")
        os.makedirs(clip_dir, exist_ok=True)

        self.task_manager.update_step("step_clip_generation", StepStatus.RUNNING)
        await self._emit("clip_gen", "running", "生成分段视频...", _PROGRESS_CLIP_GEN_START)

        total = len(self._state.scenes)
        for idx, scene in enumerate(self._state.scenes):
            clip_path = os.path.join(clip_dir, f"clip_{scene.index}.mp4")
            if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                scene.video_file = clip_path
                logger.info("[Anchor] chunk %d clip already exists, skipping", idx)
                continue

            prompt = scene.scene_prompt
            dur = scene.duration or 5

            # 断点续传：每个 chunk 单独保存 video_id
            id_path = os.path.join(clip_dir, f"clip_{scene.index}_id.txt")
            video_id = None
            if os.path.exists(id_path):
                try:
                    with open(id_path, "r", encoding="utf-8") as f:
                        video_id = f.read().strip()
                except Exception:
                    video_id = None
            if not video_id:
                video_id = await self.video_generator.submit_video(
                    prompt=prompt,
                    reference_image_paths=[anchor_image_path],
                    duration=dur,
                    width=vw,
                    height=vh,
                )
                try:
                    with open(id_path, "w", encoding="utf-8") as f:
                        f.write(video_id)
                except Exception:
                    pass

            for attempt in range(3):
                try:
                    video_output = await self.video_generator.wait_for_video(video_id)
                    video_output.save(clip_path)
                    # Guard against 0KB/empty download
                    if not os.path.exists(clip_path) or os.path.getsize(clip_path) == 0:
                        raise RuntimeError(f"[Anchor] chunk {idx} clip download empty")
                    # Guard against 0-duration clip (valid file, no frames)
                    clip_dur = VideoConcatenator._get_duration(clip_path)
                    if clip_dur <= 0.1:
                        raise RuntimeError(f"[Anchor] chunk {idx} clip has ~0 duration")
                    break
                except Exception as e:
                    if attempt < 2:
                        logger.warning(
                            "[Anchor] chunk %d attempt %d failed: %s, retrying...",
                            idx, attempt + 1, e,
                        )
                        await asyncio.sleep(_CLIP_RETRY_INTERVAL_BASE_SECONDS * (attempt + 1))
                    else:
                        raise

            scene.video_file = clip_path
            prog = _PROGRESS_CLIP_GEN_START + (_PROGRESS_CLIP_GEN_DONE - _PROGRESS_CLIP_GEN_START) * ((idx + 1) / total)
            await self._emit("clip_gen", "running", f"分段 {idx + 1}/{total} 完成", prog)

        self.task_manager.update_step("step_clip_generation", StepStatus.COMPLETED)
        await self._emit("clip_gen", "completed", "分段视频生成完成", _PROGRESS_CLIP_GEN_DONE)

    # ------------------------------------------------------------------
    # 音频生成（覆写通用实现）
    # ------------------------------------------------------------------

    # v6.0 P3：model 音频模式下 audio/subtitle 步骤无实际产物（直接 return），
    # 手动模式不应在无产物的检查点上暂停；post_stitch 模式全部可暂停。
    def _get_pausable_steps(self) -> set:
        from core.pipelines import _STEP_TO_CHECKPOINT

        steps = set(_STEP_TO_CHECKPOINT.keys())
        if (self._state.audio_source or "post_stitch") == "model":
            steps.discard("step_audio")
            steps.discard("step_subtitle")
        return steps

    async def _generate_audio(self) -> object:
        """生成整段 TTS 音频（post_stitch 模式）；model 模式返回 None。"""
        audio_source = self._state.audio_source or "post_stitch"
        if audio_source == "model":
            logger.info("[Anchor] model audio mode: skip TTS (model provides audio per chunk)")
            return None

        full_text = self._state.script_text
        if not full_text:
            logger.warning("[Anchor] audio: empty text, skipping")
            return None

        audio_path = os.path.join(self.working_dir, "full_narration.mp3")
        self._save_narration_txt(full_text, audio_path)

        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            self._state.combined_audio = audio_path
            logger.info("[Anchor] audio: file already exists, skipping")
            return await self._recover_sub_maker(
                full_text, self._state.audio_config, self._state.subtitle_config,
            )

        audio_config = self._state.audio_config
        await self._emit("audio", "running", f"生成整段读稿 ({len(full_text)} 字)...", _PROGRESS_AUDIO_START)

        sub_maker = await self._generate_audio_with_fallback(
            output_path=audio_path,
            text=full_text,
            audio_config=audio_config,
            subtitle_config=self._state.subtitle_config,
            duration_sec=len(full_text) / _CHARS_PER_SEC,
            empty_placeholder="",
        )

        self._state.combined_audio = audio_path
        self.task_manager.update_state(combined_audio=audio_path)
        await self._emit("audio", "completed", "读稿音频生成完成", _PROGRESS_AUDIO_DONE)
        return sub_maker

    # ------------------------------------------------------------------
    # 字幕生成（覆写通用实现）
    # ------------------------------------------------------------------

    async def _generate_subtitles(self, sub_maker: object = None) -> None:
        """生成整段 SRT 字幕（post_stitch 模式）；model 模式跳过。"""
        audio_source = self._state.audio_source or "post_stitch"
        if audio_source == "model":
            logger.info("[Anchor] model audio mode: skip subtitle")
            return

        full_text = self._state.script_text
        if not full_text:
            logger.warning("[Anchor] subtitle: empty text, skipping")
            return

        subtitle_config = self._state.subtitle_config
        audio_duration = max(len(full_text) / _CHARS_PER_SEC, 2.0)
        segment_texts = [full_text]
        segment_durations = [audio_duration]

        await self._emit("subtitle", "running", f"生成整段字幕 ({len(full_text)} 字)...", _PROGRESS_SUBTITLE_START)

        srt_path, styles_path = await self.generate_subtitles_common(
            segment_texts=segment_texts,
            segment_durations=segment_durations,
            subtitle_config=subtitle_config,
            sub_maker=sub_maker,
            audio_path=self._state.combined_audio or "",
            screenwriter=self.screenwriter,
            video_width=self._state.video_width,
            video_height=self._state.video_height,
            role="anchorperson digital human",
        )

        if styles_path:
            self._state.subtitle_styles_path = styles_path
            self.task_manager.update_state(subtitle_styles_path=styles_path)

        self._state.combined_subtitle = srt_path
        self.task_manager.update_state(combined_subtitle=srt_path)
        await self._emit("subtitle", "completed", "字幕生成完成", _PROGRESS_SUBTITLE_DONE)

    # ------------------------------------------------------------------
    # 合成（覆写通用实现）
    # ------------------------------------------------------------------

    async def _composite_final(self) -> str:
        """合成最终视频。

        - model 模式：将各 chunk 视频（含模型自带音频）按序拼接为完整长视频。
        - post_stitch 模式：循环单段视频 + 叠加 TTS 音频 + 字幕。
        """
        audio_source = self._state.audio_source or "post_stitch"
        output_path = os.path.join(self.working_dir, "final_video.mp4")
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info("[Anchor] composite: final video already exists, skipping")
            return output_path

        if audio_source == "model":
            return await self._composite_model_chunks(output_path)

        # post_stitch：循环单段 + TTS
        clip_path = self._state.scenes[0].video_file
        audio_path = self._state.combined_audio or ""
        audio_duration = 0.0
        if audio_path and os.path.exists(audio_path):
            audio_duration = VideoConcatenator._get_duration(audio_path)

        has_subtitle = (
            self._state.subtitle_config.enabled
            and bool(self._state.combined_subtitle)
        )

        await self._emit("concatenate", "running", "循环拼接视频+音频+字幕...", _PROGRESS_CONCAT_START)

        await asyncio.to_thread(
            VideoConcatenator.composite_anchor_video,
            clip_path=clip_path,
            audio_path=audio_path,
            srt_path=self._state.combined_subtitle if has_subtitle else None,
            output_path=output_path,
            audio_duration=audio_duration,
            subtitle_style=self._state.subtitle_config.style if has_subtitle else None,
            subtitle_styles_path=self._state.subtitle_styles_path or None,
            video_width=self._state.video_width,
            video_height=self._state.video_height,
        )

        logger.info("[Anchor] composite: final video → %s", output_path)
        return output_path

    async def _composite_model_chunks(self, output_path: str) -> str:
        """model 模式：将各 chunk 视频（含模型自带音频）按序拼接。"""
        scenes = self._state.scenes
        clip_paths = [
            s.video_file for s in scenes
            if s.video_file and os.path.exists(s.video_file)
        ]
        if not clip_paths:
            raise RuntimeError("[Anchor] 没有可拼接的 chunk 视频")

        await self._emit("concatenate", "running", f"拼接 {len(clip_paths)} 段视频...", _PROGRESS_CONCAT_START)

        if len(clip_paths) == 1:
            # 单 chunk：直接复用（保留模型音频）
            shutil.copy(clip_paths[0], output_path)
            logger.info("[Anchor] composite(model): single chunk → %s", output_path)
            return output_path

        loop_dir = self.working_dir
        concat_file = os.path.join(loop_dir, "_anchor_chunks_concat.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for p in clip_paths:
                f.write(f"file '{p}'\n")

        # 优先流拷贝（chunk 同源同参数，码流兼容）；失败回退重编码
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_file, "-c", "copy", output_path],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=600, check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.warning("[Anchor] concat copy failed: %s, re-encoding", str(e)[:200])
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_file,
                 "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "192k", output_path],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=600, check=True,
            )

        # 校验：避免 0:00 产物
        out_dur = VideoConcatenator._get_duration(output_path)
        if out_dur <= 0.1:
            raise RuntimeError(f"[Anchor] concatenated video is 0:00: {output_path}")

        logger.info("[Anchor] composite(model): %d chunks → %s (%.1fs)", len(clip_paths), output_path, out_dur)
        return output_path
