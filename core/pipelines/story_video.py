"""core.pipelines.story_video -- Master Story Creator pipeline (Type STORY)

用户创建完整故事 (角色 + 场景 + 风格 + 自定义指令)
→ LLM 生成视频 prompt
→ 角色参考 (character reference)
→ 逐场景生成视频
→ TTS 旁白 + 字幕
→ 拼接合成最终视频

Pipeline steps:
    validate_input -> build_scenes (generate video prompts) ->
    reference_images (character consistency) ->
    video_generation -> audio_subtitle -> concatenate
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
from core.pipelines import MultiScenePipeline, PipelineShutdown
from core.screenwriter import Screenwriter
from models.task import (
    StoryTaskState,
    SceneTask,
    StepStatus,
    SubtitleConfig,
    AudioConfig,
)

logger = logging.getLogger(__name__)

_CHARS_PER_SEC = 4.0
_SUBMIT_RETRIES = 3


class StoryVideoPipeline(MultiScenePipeline):
    """Master Story Creator pipeline."""

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: str = None,
        progress_callback=None,
        shutdown_event=None,
    ):
        super().__init__(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            progress_callback=progress_callback,
            shutdown_event=shutdown_event,
        )
        self._state: Optional[StoryTaskState] = None  # type: ignore[assignment]

    # ═══════════════════════════════════════════════════
    # 模板方法覆写
    # ═══════════════════════════════════════════════════

    def _get_all_scenes(self) -> List[SceneTask]:
        return self._state.scenes_output

    def _get_scenes_completed(self) -> int:
        return sum(1 for s in self._state.scenes_output if s.video_status == StepStatus.COMPLETED)

    def _get_pending_scenes(self) -> List[SceneTask]:
        return [s for s in self._state.scenes_output if s.video_status != StepStatus.COMPLETED]

    async def _run_pipeline(self) -> None:
        """Run the full story pipeline."""
        self._check_shutdown()

        # Step 1: Build scenes — generate video prompts from story data
        self._state.step_build_scenes = StepStatus.RUNNING
        self._state.current_step = "build_scenes"
        self._state.current_status = "running"
        self._state.current_message = "Generating video prompts from story..."
        self.task_manager.update_state(**self._get_update_dict())

        await self._build_scenes()
        self._state.step_build_scenes = StepStatus.COMPLETED
        self.task_manager.update_state(**self._get_update_dict())

        self._check_shutdown()

        # Step 2: Reference images (character consistency)
        self._state.step_reference_images = StepStatus.RUNNING
        self._state.current_step = "reference_images"
        self._state.current_status = "running"
        self._state.current_message = "Preparing character reference images..."
        self.task_manager.update_state(**self._get_update_dict())

        await self._collect_reference_images()
        self._state.step_reference_images = StepStatus.COMPLETED
        self.task_manager.update_state(**self._get_update_dict())

        self._check_shutdown()

        # Step 3: Video generation
        self._state.step_video_generation = StepStatus.RUNNING
        self._state.current_step = "video_generation"
        self._state.current_status = "running"
        self._state.current_message = "Generating videos for all scenes..."
        self.task_manager.update_state(**self._get_update_dict())

        await self._generate_videos()
        self._state.step_video_generation = StepStatus.COMPLETED
        self.task_manager.update_state(**self._get_update_dict())

        self._check_shutdown()

        # Step 4: Audio + Subtitle
        self._state.step_audio_subtitle = StepStatus.RUNNING
        self._state.current_step = "audio_subtitle"
        self._state.current_status = "running"
        self._state.current_message = "Generating narration and subtitles..."
        self.task_manager.update_state(**self._get_update_dict())

        await self._generate_audio()
        await self._generate_subtitles()
        self._state.step_audio_subtitle = StepStatus.COMPLETED
        self.task_manager.update_state(**self._get_update_dict())

        self._check_shutdown()

        # Step 5: Concatenate
        self._state.step_concatenation = StepStatus.RUNNING
        self._state.current_step = "concatenation"
        self._state.current_status = "running"
        self._state.current_message = "Concatenating final video..."
        self.task_manager.update_state(**self._get_update_dict())

        await self._concatenate_scenes()
        self._state.step_concatenation = StepStatus.COMPLETED
        self._state.status = StepStatus.COMPLETED
        self.task_manager.update_state(**self._get_update_dict())

    async def _build_scenes(self) -> None:
        """Generate video prompts for each story scene using style + instructions."""
        logger.info("[Story] Building scenes from %d story scenes", len(self._state.scenes))
        self._state.scenes_output = []

        # Build style context string
        style_ctx = self._build_style_context()

        for i, scene in enumerate(self._state.scenes):
            self._check_shutdown()

            # Combine location + characters + action + mood + dialogue into narration
            narration_parts = []
            if scene.location:
                narration_parts.append(f"At {scene.location}")
            if scene.characters:
                narration_parts.append(f"with {', '.join(scene.characters)}")
            if scene.action:
                narration_parts.append(scene.action)
            if scene.mood:
                narration_parts.append(f"the mood is {scene.mood}")
            narration = " ".join(narration_parts) if narration_parts else scene.action or ""

            # Combine dialogue for TTS
            dialogue_text = scene.dialogue or ""

            # Generate video prompt using LLM (screenwriter) or simple combination
            scene_prompt = await self._generate_scene_prompt(scene, style_ctx)

            # Create SceneTask
            st = SceneTask(
                index=i,
                status=StepStatus.PENDING,
                scene_prompt=scene_prompt,
                narration_text=dialogue_text or narration,
                duration=max(scene.duration, 3),
                ref_images=[],  # Will be filled by _collect_reference_images
            )
            self._state.scenes_output.append(st)

            yield_progress = i / max(len(self._state.scenes), 1)
            await self._emit("scene_build", "running", f"Scene {i+1}/{len(self._state.scenes)} prompt generated", yield_progress)

        # Calculate total duration
        self._state.total_duration = sum(s.duration for s in self._state.scenes_output)
        logger.info("[Story] Built %d scenes, total duration: %ds", len(self._state.scenes_output), self._state.total_duration)

    def _build_style_context(self) -> str:
        """Build a style context string from story style settings."""
        parts = []
        s = self._state.style
        if s.art_style:
            parts.append(f"Art style: {s.art_style}")
        if s.camera_style:
            parts.append(f"Camera: {s.camera_style}")
        if s.color_tone:
            parts.append(f"Color tone: {s.color_tone}")
        if s.lighting:
            parts.append(f"Lighting: {s.lighting}")
        if s.music_mood:
            parts.append(f"Music mood: {s.music_mood}")
        return " | ".join(parts) if parts else "cinematic realistic"

    async def _generate_scene_prompt(self, scene, style_ctx: str) -> str:
        """Generate a detailed video prompt for a scene using screenwriter LLM."""
        if not self._state.story_synopsis and not self._state.story_summary:
            # Fallback: combine scene data
            prompt_parts = []
            if scene.location:
                prompt_parts.append(f"Scene set at {scene.location}")
            if scene.characters:
                prompt_parts.append(f"featuring {', '.join(scene.characters)}")
            if scene.action:
                prompt_parts.append(scene.action)
            if scene.mood:
                prompt_parts.append(f"{scene.mood} atmosphere")
            base_prompt = " ".join(prompt_parts)

            return f"{base_prompt}. {style_ctx}"

        # Use screenwriter to generate detailed prompt from story context
        try:
            enhanced = await asyncio.to_thread(
                self._screenwriter.enhance_scene_prompt,
                scene_description=f"{scene.location}: {scene.action}",
                narration=scene.action or scene.dialogue or "",
            )
            return f"{enhanced}. {style_ctx}"
        except Exception as e:
            logger.warning("[Story] Screenwriter failed, using fallback: %s", e)
            prompt_parts = []
            if scene.location:
                prompt_parts.append(f"at {scene.location}")
            if scene.action:
                prompt_parts.append(scene.action)
            return f"{' '.join(prompt_parts)}. {style_ctx}"

    async def _collect_reference_images(self) -> None:
        """Collect character reference images from story characters."""
        logger.info("[Story] Collecting reference images for %d characters", len(self._state.characters))
        char_refs = []

        for char in self._state.characters:
            if char.image_base64:
                ref = char.image_base64
                if not ref.startswith(("http://", "https://", "data:")):
                    ref = "data:image/png;base64," + ref
                char_refs.append(ref)
                logger.info("[Story] Character '%s': reference image loaded", char.name)
            elif char.image_url:
                char_refs.append(char.image_url)

        # Store as character reference for the pipeline
        if char_refs:
            object.__setattr__(self._state, "reference_image", char_refs[0] if len(char_refs) == 1 else ",".join(char_refs[:5]))
        else:
            object.__setattr__(self._state, "reference_image", "")

        logger.info("[Story] Total character references: %d", len(char_refs))

    async def _wait_for_videos(
        self, pending: list, total: int, timeout: int = 900
    ) -> None:
        """Wait for batch video submissions with retry.

        Polls all pending videos in parallel with per-video timeout.
        """
        import time
        deadline = time.time() + timeout

        # Keep track of which videos have timed out
        timed_out = set()

        while pending:
            self._check_shutdown()
            if time.time() > deadline:
                logger.warning("[Story] Video generation timeout, cancelling remaining")
                break

            still_pending = []
            # Gather all video polls in parallel
            async def _check_one(scene_idx, video_id, video_path):
                """Check a single video, returns result or None."""
                if not video_id:
                    return None
                try:
                    result = await asyncio.wait_for(
                        self.video_api.wait_for_video(video_id),
                        timeout=60,  # Per-video timeout
                    )
                    if result:
                        if hasattr(result, 'save'):
                            result.save(video_path)
                        elif hasattr(result, 'url') and result.url:
                            import urllib.request
                            urllib.request.urlretrieve(result.url, video_path)
                        logger.info("[Story] Video %d ready: %s", scene_idx, video_path)
                        return (scene_idx, video_id, video_path, True)
                except asyncio.TimeoutError:
                    logger.warning("[Story] Video %d timeout (60s), will retry", scene_idx)
                    timed_out.add(scene_idx)
                except Exception as e:
                    logger.error("[Story] Failed to get video %d: %s", scene_idx, e)

                return (scene_idx, video_id, video_path, False)

            tasks = [
                _check_one(idx, vid, path)
                for idx, vid, path in pending
            ]
            results = await asyncio.gather(*tasks)

            # Separate completed from pending
            for scene_idx, video_id, video_path, ok in results:
                if ok and (scene_idx, video_id, video_path) in pending:
                    pending.remove((scene_idx, video_id, video_path))
                else:
                    still_pending.append((scene_idx, video_id, video_path))

            pending = still_pending
            if pending:
                # Respect rate limiter between polls
                await asyncio.sleep(15)

        completed = total - len(pending)
        await self._emit(
            "video_gen", "running",
            f"Videos ready: {completed}/{total}",
            0.40 + 0.30 * completed / max(total, 1),
        )

    async def _generate_videos(self) -> None:
        """Generate videos for each scene."""
        scenes = self._state.scenes_output
        total = len(scenes)
        if total == 0:
            logger.warning("[Story] No scenes to generate videos for")
            return

        logger.info("[Story] Generating %d scene videos...", total)

        # Collect character refs
        char_refs = []
        if self._state.reference_image:
            for ref in self._state.reference_image.split(","):
                ref = ref.strip()
                if ref:
                    char_refs.append(ref)

        # Batch submit all scenes
        pending: list[tuple[int, str, str]] = []

        for i, scene in enumerate(scenes):
            self._check_shutdown()

            scene_dir = os.path.join(self.working_dir, f"scene_{scene.index}")
            video_path = os.path.join(scene_dir, "video.mp4")

            if os.path.exists(video_path):
                scene.video_file = video_path
                scene.video_status = StepStatus.COMPLETED
                continue

            if not scene.scene_prompt:
                logger.warning("[Story] Scene %d has no prompt, skipping", scene.index)
                continue

            os.makedirs(scene_dir, exist_ok=True)

            # Load saved video_id if exists
            saved_video_id = self._load_task_json(scene_dir)
            if saved_video_id:
                logger.info("[Story] video: reusing saved video_id %s for scene %d", saved_video_id, scene.index)
                saved_path = os.path.join(scene_dir, "video.mp4")
                if os.path.exists(saved_path):
                    scene.video_id = saved_video_id
                    scene.video_file = saved_path
                    scene.video_status = StepStatus.COMPLETED
                    pending.append((scene.index, saved_video_id, video_path))
                    continue

            await self._emit(
                "video_gen", "running",
                f"Generating video {i + 1}/{total}",
                0.3 + 0.4 * (i / max(total, 1)),
            )

            for retry in range(_SUBMIT_RETRIES):
                try:
                    video_id = await self.video_api.submit_video(
                        prompt=scene.scene_prompt,
                        reference_image_paths=char_refs + scene.ref_images,
                        duration=scene.duration,
                        width=self._state.video_width,
                        height=self._state.video_height,
                    )
                    scene.video_id = video_id
                    self._save_task_json(scene_dir, {"video_id": video_id})
                    pending.append((scene.index, video_id, video_path))
                    break
                except Exception as e:
                    if retry < _SUBMIT_RETRIES - 1:
                        delay = 15 * (retry + 1)
                        logger.warning(
                            "[Story] Scene %d video submit failed (%s), retry %d/%d in %ds...",
                            scene.index, e, retry + 1, _SUBMIT_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error("[Story] Scene %d video submission failed after retries: %s", scene.index, e)
                        scene.video_status = StepStatus.FAILED
                        self._save_task_json(scene_dir, {"error": str(e)})

        # Wait for all videos
        if pending:
            await self._emit(
                "video_gen", "running",
                f"Waiting for {len(pending)} videos...",
                0.7,
            )
            await self._wait_for_videos(pending, total, 900)  # 15 min timeout

        # Update file paths after videos are done
        for idx, video_id, video_path in pending:
            if idx < len(self._state.scenes_output):
                st = self._state.scenes_output[idx]
                if os.path.exists(video_path):
                    st.video_file = video_path
                    st.video_status = StepStatus.COMPLETED
                elif st.video_id == video_id and st.video_id:
                    # Downloaded elsewhere
                    st.video_status = StepStatus.COMPLETED

    async def _generate_audio(self) -> None:
        """Generate TTS narration for all scenes."""
        if self._state.audio_config and not self._state.audio_config.enabled:
            logger.info("[Story] Audio disabled, skipping")
            return

        narrations = []
        for scene in self._state.scenes_output:
            if scene.narration_text:
                narrations.append(scene.narration_text)

        if not narrations:
            logger.info("[Story] No narration text found, using silent audio")
            # Create empty audio files for each scene
            for scene in self._state.scenes_output:
                scene_dir = os.path.join(self.working_dir, f"scene_{scene.index}")
                audio_path = os.path.join(scene_dir, "audio.wav")
                os.makedirs(scene_dir, exist_ok=True)
                # Create silent audio
                await asyncio.get_event_loop().run_in_executor(
                    None, self._create_silent_audio, audio_path, scene.duration
                )
                scene.narration_audio = audio_path
            return

        # Generate TTS for each scene's narration
        tts_engine = EdgeTTSEngine()

        for scene in self._state.scenes_output:
            self._check_shutdown()
            if not scene.narration_text:
                continue

            scene_dir = os.path.join(self.working_dir, f"scene_{scene.index}")
            audio_path = os.path.join(scene_dir, "audio.wav")
            os.makedirs(scene_dir, exist_ok=True)

            try:
                voice = self._state.audio_config.voice if self._state.audio_config else "zh-CN-XiaoxiaoNeural"
                await tts_engine.generate(
                    text=scene.narration_text,
                    output_path=audio_path,
                    voice=voice,
                    rate=self._state.audio_config.rate if self._state.audio_config else "+0%",
                )
                scene.narration_audio = audio_path
                logger.info("[Story] Audio generated for scene %d", scene.index)
            except Exception as e:
                logger.warning("[Story] Audio generation failed for scene %d: %s", scene.index, e)

    @staticmethod
    def _create_silent_audio(path: str, duration: int) -> None:
        """Create a silent audio WAV file."""
        import subprocess
        try:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i",
                f"anullsrc=r=44100:cl=mono",
                "-t", str(duration), path
            ], check=True, capture_output=True, timeout=10)
        except Exception:
            # Fallback: create empty file
            with open(path, "wb") as f:
                f.write(b"")

    async def _generate_subtitles(self, sub_maker=None) -> None:
        """Generate SRT subtitles for all scenes."""
        if self._state.subtitle_config and not self._state.subtitle_config.enabled:
            logger.info("[Story] Subtitles disabled, skipping")
            return

        for scene in self._state.scenes_output:
            self._check_shutdown()
            if not scene.narration_text:
                continue

            scene_dir = os.path.join(self.working_dir, f"scene_{scene.index}")
            os.makedirs(scene_dir, exist_ok=True)
            srt_path = os.path.join(scene_dir, "subtitle.srt")

            try:
                # Generate simple SRT from text and duration
                srt_content = "1\n00:00:00,000 --> 00:00:{:02d},000\n{}".format(
                    scene.duration, scene.narration_text
                )
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
                scene.subtitle_srt = srt_path
            except Exception as e:
                logger.warning("[Story] Subtitle generation failed for scene %d: %s", scene.index, e)

    async def _concatenate_scenes(self) -> None:
        """Concatenate all scene videos + audio + subtitles into final video."""
        scenes = self._state.scenes_output
        completed = [s for s in scenes if s.video_status == StepStatus.COMPLETED and s.video_file]

        if not completed:
            logger.error("[Story] No completed scenes to concatenate")
            self._state.status = StepStatus.FAILED
            return

        logger.info("[Story] Concatenating %d scenes...", len(completed))

        try:
            # Sort by index
            completed.sort(key=lambda s: s.index)
            scene_paths = [s.video_file for s in completed if s.video_file and os.path.exists(s.video_file)]

            output_path = os.path.join(self.working_dir, "final_video.mp4")

            # Step 1: Concatenate videos using the static method
            final_path = VideoConcatenator.concat_videos(scene_paths, output_path)

            # Step 2: If we have combined audio, overlay it and save as final
            if self._state.combined_audio and os.path.exists(self._state.combined_audio):
                logger.info("[Story] Overlaying audio into final video")
                audio_path = os.path.join(self.working_dir, "final_with_audio.mp4")
                final_path = VideoConcatenator.concat_videos_with_audio_overlay(
                    video_paths=scene_paths,
                    audio_path=self._state.combined_audio,
                    srt_path=self._state.subtitle_file,
                    output_path=audio_path,
                )
                # Move to final name
                if audio_path != final_path:
                    os.replace(audio_path, output_path)
                    final_path = output_path

            self._state.final_video_path = final_path
            self._state.final_video_file = final_path
            logger.info("[Story] Final video saved to %s", final_path)

        except Exception as e:
            logger.error("[Story] Concatenation failed: %s", e, exc_info=True)
            self._state.status = StepStatus.FAILED

    async def _build_reference_images(self) -> None:
        """Build reference images from character descriptions and images."""
        logger.info("[Story] Building reference images from %d characters", len(self._state.characters))
        object.__setattr__(self._state, "reference_image", "")

        ref_paths = []
        for char in self._state.characters:
            self._check_shutdown()
            if char.image_base64:
                # Save reference image
                img_dir = os.path.join(self.working_dir, "characters")
                os.makedirs(img_dir, exist_ok=True)
                import base64
                img_data = base64.b64decode(char.image_base64.split(",")[1]) if "," in char.image_base64 else base64.b64decode(char.image_base64)
                img_path = os.path.join(img_dir, f"{char.name or 'char'}_{len(ref_paths)}.png")
                with open(img_path, "wb") as f:
                    f.write(img_data)
                ref_paths.append(img_path)
                logger.info("[Story] Added character reference: %s → %s", char.name, img_path)
            elif char.appearance:
                # Generate character reference image from description
                # Note: API may not support image generation yet
                try:
                    # Try submit_image_gen if available
                    if hasattr(self.video_api, 'submit_image_gen'):
                        result = await self.video_api.submit_image_gen(prompt=prompt, style="", ratio="1:1")
                        vid_id = result.get("video_id") or result.get("id")
                        if vid_id:
                            url = await self.video_api.get_result(vid_id)
                            if url:
                                img_path = os.path.join(self.working_dir, f"char_ref_{len(ref_paths)}.png")
                                import urllib.request
                                urllib.request.urlretrieve(url, img_path)
                                ref_paths.append(img_path)
                                logger.info("[Story] Generated character reference for %s", char.name)
                    else:
                        logger.warning("[Story] submit_image_gen not available for character %s, skipping reference generation", char.name)
                except Exception as e:
                    logger.warning("[Story] Failed to generate reference for %s: %s", char.name, e)

        # Join paths with commas
        if ref_paths:
            object.__setattr__(self._state, "reference_image", ",".join(ref_paths))
        logger.info("[Story] Total reference images: %d", len(ref_paths))

    async def _composite_final(self) -> str:
        """Concatenate all scene videos into the final video."""
        logger.info("[Story] Concatenating final video")
        await self._concatenate_scenes()
        return self._state.final_video_file
