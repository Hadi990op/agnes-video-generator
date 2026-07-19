"""core.pipelines.manuscript_video -- 稿件长视频生成流水线（类型 3）

用户粘贴长文本稿件 -> 按朗读时长拆段 -> 每段生成视频 prompt -> 视频生成 -> TTS+字幕 -> 拼接。

v4.0 重构：继承 MultiScenePipeline，复用模板方法 run() 与步骤编排，
仅保留稿件特有的数据准备与视频生成逻辑（覆写 _build_scenes / _generate_videos /
_generate_audio / _generate_subtitles / _composite_final）。
"""

import asyncio
import json
import logging
import math
import os
import re
from typing import Callable, List, Optional

from core.api.agnes_video import AgnesVideoAPI
from core.audio.tts import EdgeTTSEngine, SilentTTSEngine
from core.compositor.concatenator import VideoConcatenator
from core.screenwriter import Screenwriter
from core.pipelines import MultiScenePipeline, PipelineShutdown
from models.task import (
    ManuscriptVideoTask,
    ManuscriptParagraph,
    SceneTask,
    StepStatus,
    AudioConfig,
    SubtitleConfig,
)

logger = logging.getLogger(__name__)

# Chinese sentence-ending punctuation pattern.
_SENTENCE_END_RE = re.compile(r"(?<=[。！？])")

# Estimated Chinese speech rate: ~4 characters per second.
_CHARS_PER_SEC = 4.0

# Greedy-merge duration thresholds (seconds).
_MAX_SEGMENT_DURATION = 12.0
_MIN_SEGMENT_DURATION = 5.0

# Scene marker pattern: [SCENE: <video prompt>] or [场景: <video prompt>]
# Lines starting with this marker define a new scene with its video prompt.
# Everything after the marker (until next marker) is narration text.
_SCENE_MARKER_RE = re.compile(r"^\s*\[(?:SCENE|场景|_scene|sc)\s*[:：]\s*(.+?)\]\s*$", re.IGNORECASE | re.MULTILINE)


class ManuscriptVideoPipeline(MultiScenePipeline):
    """稿件长视频生成流水线。

    将用户提交的长文本稿件拆分为若干段落，每个段落独立生成视频片段，
    再叠加 TTS 旁白和字幕后拼接为最终长视频。

    Pipeline steps（由 MultiScenePipeline 模板编排）:
        build_scenes -> reference_images -> video_generation
        -> audio -> subtitle -> concatenation -> watermark
    """

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: str = None,
        progress_callback: Optional[Callable] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)
        self.video_api = AgnesVideoAPI(api_key=api_key)
        self.video_api.shutdown_event = shutdown_event
        self.video_api.set_refresh_key_callback(self._make_refresh_key_callback())
        self.screenwriter = Screenwriter(api_key=api_key)
        # v5.0: image generator for character reference images
        from core.api.agnes_image import AgnesImageAPI
        self.image_api = AgnesImageAPI(api_key=api_key)

    # ------------------------------------------------------------------
    # 模板钩子：数据来源
    # ------------------------------------------------------------------

    def _get_watermark_language_text(self) -> str:
        return self._state.manuscript_text

    async def _build_scenes(self) -> None:
        """构建场景列表：拆段 → 生成场景 prompt → 填充 self._state.scenes。

        支持 resume：若 paragraphs 已存在则复用，仅补全缺失的 scene_prompt。
        """
        # resume：若 paragraphs 已存在（如中途续传），直接复用
        if not self._state.paragraphs:
            paragraphs = self._split_text(self._state.manuscript_text)
            self._state.paragraphs = paragraphs
            self.task_manager.update_state(paragraphs=paragraphs)
        else:
            logger.info(
                "[Manuscript] _build_scenes: reuse %d existing paragraphs",
                len(self._state.paragraphs),
            )

        # 为缺失 scene_prompt 的段落生成视频描述
        await self._generate_scene_prompts(self._state.paragraphs)

        # 填充通用 scenes 列表（供模板与下游步骤引用）
        self._state.scenes = [
            SceneTask(
                index=p.index,
                scene_prompt=p.scene_prompt,
                narration_text=p.text,
                duration=max(int(math.ceil(len(p.text) / _CHARS_PER_SEC)), 3),
            )
            for p in self._state.paragraphs
        ]
        self.task_manager.update_state(scenes=[s.model_dump() for s in self._state.scenes])

    async def _build_reference_images(self) -> None:
        """v5.0: Generate character reference image for consistency across scenes.

        - If user provided a reference image → use it directly.
        - Otherwise, extract character description from manuscript text and
          generate a reference image via t2i.
        - Store path in self._state.character_ref_file.
        """
        # Skip if already done (resume)
        if self._state.step_character_ref == StepStatus.COMPLETED:
            ref = self._state.character_ref_file
            if ref and (ref.startswith(("http://", "https://")) or os.path.exists(ref)):
                logger.info("[Manuscript] character_ref: SKIP (already completed)")
                return
            logger.warning("[Manuscript] character_ref: marked done but file missing, re-running")

        ref_img_path = os.path.join(self.working_dir, "character_reference.png")
        ref_prompt_path = os.path.join(self.working_dir, "character_ref_prompt.txt")

        # Case 1: user provided reference image
        if self._state.reference_image:
            ref = self._state.reference_image
            if ref.startswith(("http://", "https://")) or os.path.exists(ref):
                logger.info("[Manuscript] character_ref: using user-provided reference image")
                self._state.character_ref_file = ref
                self._state.step_character_ref = StepStatus.COMPLETED
                self.task_manager.update_state(
                    character_ref_file=ref,
                    step_character_ref=StepStatus.COMPLETED,
                )
                await self._emit("reference_images", "completed", "使用用户提供的角色参考图", 0.25)
                return

        # Case 2: cached on disk (resume after restart)
        if os.path.exists(ref_img_path) and os.path.exists(ref_prompt_path):
            logger.info("[Manuscript] character_ref: found cached reference image")
            self._state.character_ref_file = ref_img_path
            self._state.step_character_ref = StepStatus.COMPLETED
            with open(ref_prompt_path, "r") as f:
                self._state.character_ref_prompt = f.read()
            self.task_manager.update_state(
                character_ref_file=ref_img_path,
                character_ref_prompt=self._state.character_ref_prompt,
                step_character_ref=StepStatus.COMPLETED,
            )
            await self._emit("reference_images", "completed", "角色参考图已缓存", 0.25)
            return

        # Case 3: generate new reference image
        await self._emit("reference_images", "running", "正在提取角色描述...", 0.18)

        # Build a condensed story context for character extraction
        # Use first ~2000 chars of manuscript for character description
        story_context = self._state.manuscript_text[:2000]
        style_hint = getattr(self._state, 'style', '') or ""

        char_prompt = await asyncio.to_thread(
            self.screenwriter.extract_character_description,
            story_context, style_hint,
        )
        with open(ref_prompt_path, "w") as f:
            f.write(char_prompt)
        self._state.character_ref_prompt = char_prompt

        await self._emit("reference_images", "running", "正在生成角色参考图...", 0.22)

        try:
            img_output = await self.image_api.generate_single_image(
                prompt=char_prompt,
                size=f"{self._state.video_width}x{self._state.video_height}",
            )
            img_output.save(ref_img_path)
        except Exception as e:
            logger.error(f"[Manuscript] character_ref: failed to generate: {e}")
            # Non-fatal: continue without reference image
            await self._emit("reference_images", "completed", "角色参考图生成失败，跳过", 0.25)
            self._state.step_character_ref = StepStatus.COMPLETED
            self.task_manager.update_state(step_character_ref=StepStatus.COMPLETED)
            return

        self._state.character_ref_file = ref_img_path
        self._state.step_character_ref = StepStatus.COMPLETED
        self.task_manager.update_state(
            character_ref_file=ref_img_path,
            character_ref_prompt=char_prompt,
            step_character_ref=StepStatus.COMPLETED,
        )
        logger.info("[Manuscript] character_ref: generated → %s", ref_img_path)
        await self._emit("reference_images", "completed", "角色参考图生成完成", 0.25)

    # ------------------------------------------------------------------
    # 步骤实现（覆写通用实现以保留稿件特有逻辑）
    # ------------------------------------------------------------------

    def _split_text(self, text: str) -> List[ManuscriptParagraph]:
        """将长文本按朗读时长拆分为段落列表。

        攋分策略:
            0. 如果文本含 [SCENE: ...] 标记，则按场景拆分（用户自定义视频 prompt）。
            1. 先按换行符 (``\\n``) 切分为粗段落。
            2. 每个粗段落再按中文句末标点 (``。！？``) 切分为候选句。
            3. 对候选句进行贪心合并：累积时长 <= 12s，最短 >= 5s。
            4. 短句 (< 5s) 合并到前一个段落；长句 (> 12s) 保持原样不拆分。
        """
        # 防御性修复：检测并修复双重 UTF-8 编码
        text = self.fix_double_utf8(text)
        if text != self._state.manuscript_text:
            logger.info("[Manuscript] split_text: fixed double-encoded UTF-8 text")
            self._state.manuscript_text = text
            self.task_manager.update_state(manuscript_text=text)

        # Resume: if paragraphs already populated, return them directly.
        if self._state.paragraphs:
            logger.info(
                "[Manuscript] split_text: %d paragraphs already exist, resuming",
                len(self._state.paragraphs),
            )
            return self._state.paragraphs

        logger.info("[Manuscript] split_text: splitting %d chars...", len(text))

        # ── Mode 0: Scene-marker mode ──
        # If text contains [SCENE: ...] markers, split by scenes.
        # The marker line becomes scene_prompt; text after it (until next
        # marker) becomes narration. Long narration is further split into
        # sub-segments so each video clip stays 5-12s.
        paragraphs = self._split_by_scene_markers(text)
        if paragraphs is not None:
            logger.info(
                "[Manuscript] split_text: scene-marker mode, %d scenes created",
                len(paragraphs),
            )
            return paragraphs

        # ── Mode 1: Original auto-split mode ──
        # Step 1: split by newline.
        raw_blocks = [b.strip() for b in text.split("\n") if b.strip()]

        # Step 2: further split each block by Chinese sentence-ending punctuation.
        candidate_sentences: List[str] = []
        for block in raw_blocks:
            parts = _SENTENCE_END_RE.split(block)
            for part in parts:
                part = part.strip()
                if part:
                    candidate_sentences.append(part)

        if not candidate_sentences:
            logger.warning("[Manuscript] split_text: no sentences found in text")
            return []

        # Step 3: greedy merge.
        merged: List[str] = []
        current_text = ""
        current_duration = 0.0

        for sentence in candidate_sentences:
            sentence_duration = len(sentence) / _CHARS_PER_SEC

            if not current_text:
                current_text = sentence
                current_duration = sentence_duration
                continue

            prospective_duration = current_duration + sentence_duration

            if prospective_duration <= _MAX_SEGMENT_DURATION:
                current_text += sentence
                current_duration = prospective_duration
            else:
                merged.append(current_text)
                current_text = sentence
                current_duration = sentence_duration

        if current_text:
            merged.append(current_text)

        # Step 4: post-process -- merge short trailing segments into previous.
        final_texts: List[str] = []
        for segment in merged:
            seg_duration = len(segment) / _CHARS_PER_SEC
            if seg_duration < _MIN_SEGMENT_DURATION and final_texts:
                final_texts[-1] += segment
            else:
                final_texts.append(segment)

        # Build ManuscriptParagraph list.
        paragraphs: List[ManuscriptParagraph] = []
        for idx, para_text in enumerate(final_texts):
            paragraphs.append(ManuscriptParagraph(index=idx, text=para_text))
            logger.info(
                "[Manuscript] Paragraph %d: %d chars, ~%.1fs",
                idx, len(para_text), len(para_text) / _CHARS_PER_SEC,
            )

        logger.info(
            "[Manuscript] split_text: %d paragraphs created", len(paragraphs),
        )
        return paragraphs

    def _split_by_scene_markers(
        self, text: str,
    ) -> Optional[List[ManuscriptParagraph]]:
        """Parse script with [SCENE: ...] markers into paragraphs.

        Format:
            [SCENE: A rainy night in the city, neon lights on wet streets]
            The narration text for this scene. The narrator speaks this...
            More narration...

            [SCENE: Close-up of an old man's face in a café]
            Another narration text here...

        Returns None if no scene markers found (falls back to auto-split).
        Long narration blocks are sub-split into 5-12s segments, each
        reusing the same scene_prompt, so very long scenes still generate
        multiple video clips that get merged.
        """
        markers = list(_SCENE_MARKER_RE.finditer(text))
        if not markers:
            return None

        scenes_raw: List[tuple] = []  # (scene_prompt, narration_text)
        for i, m in enumerate(markers):
            scene_prompt = m.group(1).strip()
            start = m.end()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
            narration = text[start:end].strip()
            scenes_raw.append((scene_prompt, narration))

        paragraphs: List[ManuscriptParagraph] = []
        idx = 0
        for scene_prompt, narration in scenes_raw:
            if not narration:
                # Scene with no narration — still create a 3s clip
                paragraphs.append(ManuscriptParagraph(
                    index=idx, text=scene_prompt, scene_prompt=scene_prompt,
                ))
                logger.info(
                    "[Manuscript] Scene %d (no narration): %s...",
                    idx, scene_prompt[:60],
                )
                idx += 1
                continue

            # Sub-split long narration into 5-12s segments
            sub_texts = self._greedy_split_narration(narration)
            for sub_text in sub_texts:
                paragraphs.append(ManuscriptParagraph(
                    index=idx,
                    text=sub_text,
                    scene_prompt=scene_prompt,
                ))
                logger.info(
                    "[Manuscript] Scene %d: %d chars ~%.1fs | prompt: %s...",
                    idx, len(sub_text),
                    len(sub_text) / _CHARS_PER_SEC,
                    scene_prompt[:60],
                )
                idx += 1

        return paragraphs if paragraphs else None

    def _greedy_split_narration(self, text: str) -> List[str]:
        """Split narration text into segments of 5-12 seconds.

        Uses both sentence-ending punctuation (。！？ and .!?) and newlines.
        Short segments merge into previous; long segments stay as-is.
        """
        # Split by newlines first, then by sentence-ending punctuation.
        sent_re = re.compile(r"(?<=[。！？\.!\?])\s*")
        candidate_sentences: List[str] = []
        for block in text.split("\n"):
            block = block.strip()
            if not block:
                continue
            for part in sent_re.split(block):
                part = part.strip()
                if part:
                    candidate_sentences.append(part)

        if not candidate_sentences:
            return [text.strip()] if text.strip() else []

        merged: List[str] = []
        current_text = ""
        current_duration = 0.0
        for sentence in candidate_sentences:
            sentence_duration = len(sentence) / _CHARS_PER_SEC
            if not current_text:
                current_text = sentence
                current_duration = sentence_duration
                continue
            prospective = current_duration + sentence_duration
            if prospective <= _MAX_SEGMENT_DURATION:
                current_text += sentence
                current_duration = prospective
            else:
                merged.append(current_text)
                current_text = sentence
                current_duration = sentence_duration
        if current_text:
            merged.append(current_text)

        # Merge short trailing segments into previous.
        final: List[str] = []
        for seg in merged:
            seg_dur = len(seg) / _CHARS_PER_SEC
            if seg_dur < _MIN_SEGMENT_DURATION and final:
                final[-1] += seg
            else:
                final.append(seg)
        return final or [text.strip()]

    async def _generate_scene_prompts(
        self, paragraphs: List[ManuscriptParagraph],
    ) -> None:
        """为每个段落生成视频场景描述 prompt（语言跟随输入段落）。

        v5.0: Inject character appearance description for cross-scene consistency,
        and extract dialogue from the paragraph text.
        """
        total = len(paragraphs)

        # v5.0: Get character appearance for consistency
        char_appearance = self._state.character_ref_prompt or ""
        style_hint = getattr(self._state, 'style', '') or ""

        for i, para in enumerate(paragraphs):
            self._check_shutdown()

            if para.scene_prompt:
                logger.info(
                    "[Manuscript] scene_prompt: paragraph %d already has prompt, skipping",
                    para.index,
                )
                continue

            logger.info(
                "[Manuscript] scene_prompt: generating for paragraph %d/%d...",
                i + 1, total,
            )
            await self._emit(
                "scene_prompts", "running",
                f"生成场景描述 {i + 1}/{total}",
                0.05 + 0.10 * (i / max(total, 1)),
            )

            # v5.0: Extract dialogue from the paragraph text
            dialogue = ""
            try:
                dialogue = await asyncio.to_thread(
                    self.screenwriter.extract_dialogue, para.text,
                )
                para.dialogue = dialogue
            except Exception as e:
                logger.debug(f"[Manuscript] dialogue extract failed for para {i}: {e}")

            prompt = await asyncio.to_thread(
                self.screenwriter.generate_scene_prompt_enhanced,
                para.text,
                style_hint,
                char_appearance,
                dialogue,
            )
            para.scene_prompt = prompt.strip()

            self.task_manager.update_state(paragraphs=paragraphs)
            logger.info(
                "[Manuscript] scene_prompt %d: %s...",
                para.index, para.scene_prompt[:80],
            )

        self.save_prompts({
            "scene_prompts": [
                {"index": p.index, "text": p.text, "scene_prompt": p.scene_prompt,
                 "dialogue": p.dialogue}
                for p in paragraphs
            ],
        })

    async def _generate_videos(self) -> None:
        """为每个段落调用 Agnes Video API 生成视频（两阶段并行）。

        v5.0: Pass character reference image for cross-scene consistency.
        每段视频保存到 ``{working_dir}/para_{index}/video.mp4``，
        同时记录 video_id 和 curl 命令到 ``task.json`` / ``curl.sh``。
        """
        _SUBMIT_RETRIES = 3
        _WAIT_RETRIES = 3
        paragraphs = self._state.paragraphs
        total = len(paragraphs)

        # v5.0: Collect character reference image
        char_ref = self._state.character_ref_file or ""
        char_ref_valid = bool(
            char_ref and (
                char_ref.startswith(("http://", "https://"))
                or os.path.exists(char_ref)
            )
        )
        if char_ref_valid:
            logger.info("[Manuscript] video: using character ref: %s", char_ref[:60])

        # ── Phase 1: 批量提交 ────────────────────────────────────────────
        pending: list[tuple[int, str, str]] = []  # (para_index, video_id, video_path)

        for i, para in enumerate(paragraphs):
            self._check_shutdown()

            para_dir = os.path.join(self.working_dir, f"para_{para.index}")
            video_path = os.path.join(para_dir, "video.mp4")

            if os.path.exists(video_path):
                para.video_file = video_path
                continue

            if not para.scene_prompt:
                logger.warning(
                    "[Manuscript] video: paragraph %d has no scene_prompt, skipping",
                    para.index,
                )
                continue

            os.makedirs(para_dir, exist_ok=True)

            saved_video_id = self._load_task_json(para_dir)
            if saved_video_id:
                para.video_id = saved_video_id
                pending.append((para.index, saved_video_id, video_path))
                continue

            logger.info(
                "[Manuscript] video: submitting paragraph %d/%d...",
                i + 1, total,
            )
            await self._emit(
                "video_gen", "running",
                f"提交视频 {i + 1}/{total}",
                0.15 + 0.20 * (i / max(total, 1)),
            )

            para_duration = max(int(math.ceil(len(para.text) / _CHARS_PER_SEC)), 3)

            # v5.0: Build reference images list
            ref_images = []
            if char_ref_valid:
                ref_images = [char_ref]

            for retry in range(_SUBMIT_RETRIES):
                try:
                    video_id = await self.video_api.submit_video(
                        prompt=para.scene_prompt,
                        reference_image_paths=ref_images,
                        duration=para_duration,
                        width=self._state.video_width,
                        height=self._state.video_height,
                    )
                    para.video_id = video_id
                    self._save_task_json(para_dir, {"video_id": video_id})
                    pending.append((para.index, video_id, video_path))
                    break
                except Exception as e:
                    if retry < _SUBMIT_RETRIES - 1:
                        delay = 15 * (retry + 1)
                        logger.warning(
                            "[Manuscript] video: paragraph %d submit failed "
                            "(%s), retry %d/%d in %ds...",
                            para.index, e, retry + 1, _SUBMIT_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise

        self.task_manager.update_state(paragraphs=paragraphs)

        # ── Phase 2: 逐个等待完成 ────────────────────────────────────────
        for j, (para_idx, video_id, video_path) in enumerate(pending):
            self._check_shutdown()

            para = paragraphs[para_idx]
            await self._emit(
                "video_gen", "running",
                f"等待视频 {j + 1}/{len(pending)} ({video_id[:16]}...)",
                0.35 + 0.25 * (j / max(len(pending), 1)),
            )

            for retry in range(_WAIT_RETRIES):
                try:
                    video_output = await self.video_api.wait_for_video(video_id)
                    video_output.save(video_path)
                    break
                except Exception as e:
                    if retry < _WAIT_RETRIES - 1:
                        delay = 20 * (retry + 1)
                        logger.warning(
                            "[Manuscript] video: paragraph %d wait failed "
                            "(%s), retry %d/%d in %ds...",
                            para_idx, e, retry + 1, _WAIT_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise

            para.video_file = video_path
            self.task_manager.update_state(paragraphs=paragraphs)
            logger.info(
                "[Manuscript] video: paragraph %d saved → %s (video_id=%s)",
                para_idx, video_path, video_id[:16],
            )

    async def _generate_audio(self) -> object:
        """生成整段连续 TTS 音频，返回 sub_maker 供字幕步骤。"""
        paragraphs = self._state.paragraphs
        audio_config = self._state.audio_config
        full_text = "\n\n".join(p.text for p in paragraphs if p.text)
        if not full_text:
            logger.warning("[Manuscript] audio: empty full text, skipping")
            return None

        audio_path = os.path.join(self.working_dir, "full_narration.mp3")

        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            self._state.combined_audio = audio_path
            logger.info("[Manuscript] audio: file already exists, skipping")
            return None

        edge_tts = EdgeTTSEngine()
        silent_tts = SilentTTSEngine()

        await self._emit(
            "audio", "running",
            f"生成整段旁白 ({len(full_text)} 字)...",
            0.60,
        )

        sub_maker = None
        if audio_config.enabled:
            try:
                audio_result, sub_maker = await edge_tts.generate(
                    text=full_text,
                    output_path=audio_path,
                    voice=audio_config.voice,
                    rate=audio_config.rate,
                )
            except RuntimeError as e:
                logger.warning(f"[Manuscript] EdgeTTS failed, falling back to silent: {e}")
                audio_result, sub_maker = await silent_tts.generate(
                    text=full_text,
                    output_path=audio_path,
                )
        else:
            audio_result, sub_maker = await silent_tts.generate(
                text=full_text,
                output_path=audio_path,
            )

        self._state.combined_audio = audio_result
        self.task_manager.update_state(combined_audio=audio_result)
        logger.info("[Manuscript] audio: combined → %s", audio_path)
        return sub_maker

    async def _generate_subtitles(self, sub_maker: object = None) -> None:
        """生成整段 SRT 字幕（复用通用字幕生成逻辑）。"""
        paragraphs = self._state.paragraphs
        subtitle_config = self._state.subtitle_config
        segment_texts = [p.text for p in paragraphs if p.text]
        if not segment_texts:
            logger.warning("[Manuscript] subtitle: empty text, skipping")
            return

        segment_durations = []
        for p in paragraphs:
            dur = max(len(p.text) / _CHARS_PER_SEC, 2.0) if p.text else 5.0
            segment_durations.append(dur)

        await self._emit(
            "subtitle", "running",
            f"生成整段字幕 ({sum(len(t) for t in segment_texts)} 字, {len(paragraphs)} 段)...",
            0.75,
        )

        srt_path, styles_path = await self.generate_subtitles_common(
            segment_texts=segment_texts,
            segment_durations=segment_durations,
            subtitle_config=subtitle_config,
            sub_maker=sub_maker,
            audio_path=self._state.combined_audio or "",
            screenwriter=self.screenwriter,
            video_width=self._state.video_width,
            video_height=self._state.video_height,
        )

        if styles_path:
            self._state.subtitle_styles_path = styles_path
            self.task_manager.update_state(subtitle_styles_path=styles_path)

            try:
                prompts_path = os.path.join(self.working_dir, "prompts.json")
                existing = {}
                if os.path.exists(prompts_path):
                    with open(prompts_path, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                with open(styles_path, "r", encoding="utf-8") as f:
                    existing["subtitle_styles"] = json.load(f)
                self.save_prompts(existing)
            except Exception:
                pass

        self._state.combined_subtitle = srt_path
        self.task_manager.update_state(combined_subtitle=srt_path)
        logger.info("[Manuscript] subtitle: combined → %s", srt_path)

    async def _composite_final(self) -> str:
        """先拼接所有段落视频，再统一叠加整段音频 + 整段字幕。"""
        paragraphs = self._state.paragraphs
        subtitle_config = self._state.subtitle_config
        output_path = os.path.join(self.working_dir, "final_video.mp4")

        if os.path.exists(output_path):
            logger.info("[Manuscript] concatenate: final video already exists, skipping")
            return output_path

        video_paths = [
            p.video_file for p in paragraphs
            if p.video_file and os.path.exists(p.video_file)
        ]
        if not video_paths:
            raise RuntimeError("[Manuscript] concatenate: no valid videos to concatenate")

        has_audio = self._state.audio_config.enabled and bool(self._state.combined_audio)
        has_subtitle = subtitle_config.enabled and bool(self._state.combined_subtitle)

        styles_path = self._state.subtitle_styles_path or ""
        if styles_path and not os.path.exists(styles_path):
            styles_path = ""

        logger.info(
            "[Manuscript] concatenate: %d videos + audio=%s + subtitle=%s → %s",
            len(video_paths), has_audio, has_subtitle, output_path,
        )

        if has_audio or has_subtitle:
            await self._emit(
                "concatenate", "running",
                f"拼接 {len(video_paths)} 段视频+音频+字幕...", 0.80,
            )
            await asyncio.to_thread(
                VideoConcatenator.concat_videos_with_audio_overlay,
                video_paths=video_paths,
                audio_path=self._state.combined_audio or "",
                srt_path=self._state.combined_subtitle if has_subtitle else None,
                output_path=output_path,
                subtitle_style=subtitle_config.style if has_subtitle else None,
                subtitle_styles_path=styles_path if styles_path else None,
            )
        else:
            await self._emit(
                "concatenate", "running",
                f"拼接 {len(video_paths)} 段视频（无音频字幕）...", 0.80,
            )
            await asyncio.to_thread(
                VideoConcatenator.concat_videos, video_paths, output_path
            )

        logger.info("[Manuscript] concatenate: final video → %s", output_path)
        return output_path
