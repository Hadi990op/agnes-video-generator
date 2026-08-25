"""core.pipelines.influencer — AI Influencer Studio pipeline (v7.0)

Character-locked multi-scene video generation with:
- Persistent character identity (multi-angle references)
- Locked voice across all scenes
- Frame chaining (prev end frame = next start frame)
- Continuity engine metadata

Extends MultiScenePipeline with identity-locking orchestration.
"""

import asyncio
import json
import logging
import os
from typing import Callable, Optional

from core.api.agnes_image import AgnesImageAPI
from core.api.agnes_video import AgnesVideoAPI
from core.compositor.concatenator import VideoConcatenator
from core.pipelines import MultiScenePipeline, PipelineShutdown
from core.pipelines.influencer.steps_character import CharacterStepsMixin
from core.pipelines.influencer.steps_script import ScriptStepsMixin
from core.pipelines.influencer.steps_frames import InfluencerFrameStepsMixin
from core.pipelines.influencer.steps_video import InfluencerVideoStepsMixin
from core.pipelines.influencer.steps_continuity import ContinuityEngine
from core.screenwriter import Screenwriter
from models.character import CharacterProfile
from models.task import (
    InfluencerSceneTask,
    InfluencerVideoTask,
    StepStatus,
)

logger = logging.getLogger(__name__)

# ── Progress constants ──────────────────────────────────────────
_PROGRESS_START = 0.02
_PROGRESS_CHARACTER_DONE = 0.10
_PROGRESS_SCRIPT_DONE = 0.18
_PROGRESS_REFERENCE_DONE = 0.25
_PROGRESS_END_FRAMES_DONE = 0.35
_PROGRESS_VIDEO_DONE = 0.70
_PROGRESS_AUDIO_DONE = 0.80
_PROGRESS_SUBTITLE_DONE = 0.88
_PROGRESS_COMPOSITE_DONE = 0.98
_PROGRESS_DONE = 1.0


class InfluencerPipeline(
    CharacterStepsMixin,
    ScriptStepsMixin,
    InfluencerFrameStepsMixin,
    InfluencerVideoStepsMixin,
    MultiScenePipeline,
):
    """AI Influencer Studio pipeline.

    8-phase flow:
        1. Character Identity Lock
        2. Script + Scene Planning
        3. Reference Images (multi-angle)
        4. End Frame Generation (identity-locked)
        5. Video Generation (frame chaining)
        6. Audio (locked voice)
        7. Subtitles
        8. Composite
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
        self._state: Optional[InfluencerVideoTask] = None
        self._character: Optional[CharacterProfile] = None
        self._continuity = ContinuityEngine()

    @property
    def state(self) -> Optional[InfluencerVideoTask]:
        return self._state

    # ── Template hooks ────────────────────────────────────────────

    def _get_watermark_language_text(self) -> str:
        return self._state.script_text

    # ── Main pipeline ─────────────────────────────────────────────

    async def run(self, state: InfluencerVideoTask) -> str:
        """Run the 8-phase AI Influencer pipeline."""
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        # Load character profile if exists
        if self._state.character_profile_data:
            self._character = CharacterProfile(**self._state.character_profile_data)

        await self._emit("init", "running", "Starting AI Influencer Studio...", _PROGRESS_START)

        try:
            # Phase 1: Character Identity Lock
            await self._execute_step(
                "step_character", self._step_character_identity,
                _PROGRESS_START, _PROGRESS_CHARACTER_DONE,
                "Locking character identity...", "Character identity locked",
            )

            # Phase 2: Script + Scene Planning
            await self._execute_step(
                "step_script", self._step_script_planning,
                _PROGRESS_CHARACTER_DONE, _PROGRESS_SCRIPT_DONE,
                "Planning scenes with continuity...", "Script planning complete",
            )

            # Phase 3: Reference Images (multi-angle)
            await self._execute_step(
                "step_reference_images", self._step_reference_images,
                _PROGRESS_SCRIPT_DONE, _PROGRESS_REFERENCE_DONE,
                "Generating character references...", "Character references ready",
            )

            # Phase 4: End Frame Generation (identity-locked)
            await self._execute_step(
                "step_end_frames", self._step_end_frames,
                _PROGRESS_REFERENCE_DONE, _PROGRESS_END_FRAMES_DONE,
                "Generating identity-locked end frames...", "End frames generated",
                coarse_skip=False,  # Always re-check for frame chaining
            )

            # Phase 5: Video Generation (frame chaining)
            await self._execute_step(
                "step_video_generation", self._step_video_generation,
                _PROGRESS_END_FRAMES_DONE, _PROGRESS_VIDEO_DONE,
                "Generating videos with frame chaining...", "Videos generated",
                coarse_skip=False,
            )

            # Phase 6: Audio (locked voice)
            sub_maker = await self._execute_step(
                "step_audio", self._step_audio,
                _PROGRESS_VIDEO_DONE, _PROGRESS_AUDIO_DONE,
                "Generating audio with locked voice...", "Audio generated",
            )

            # Phase 7: Subtitles
            await self._execute_step(
                "step_subtitle",
                lambda: self._step_subtitles(sub_maker),
                _PROGRESS_AUDIO_DONE, _PROGRESS_SUBTITLE_DONE,
                "Generating subtitles...", "Subtitles generated",
            )

            # Phase 8: Composite
            final_video = await self._execute_step(
                "step_concatenation", self._step_composite,
                _PROGRESS_SUBTITLE_DONE, _PROGRESS_COMPOSITE_DONE,
                "Compositing final video...", "Composite complete",
            )

            # Watermark
            final_video = self._apply_watermark(final_video)

            # Complete
            self._state.status = StepStatus.COMPLETED
            self._state.final_video_file = final_video
            self.task_manager.update_state(
                status=StepStatus.COMPLETED,
                final_video_file=final_video,
            )
            await self._emit(
                "done", "completed", "Influencer video complete!",
                _PROGRESS_DONE, {"final_video": final_video},
            )
            return final_video

        except PipelineShutdown:
            await self._emit("error", "failed", "Task interrupted", 0.0)
            raise
        except Exception as e:
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(status=StepStatus.FAILED)
            await self._emit("error", "failed", str(e), 0.0)
            raise

    # ── Default implementations (overridden by mixins) ────────────

    async def _build_scenes(self) -> None:
        """Delegate to script planning mixin."""
        await self._step_script_planning()

    async def _build_reference_images(self) -> None:
        """Delegate to character identity mixin."""
        await self._step_character_identity()

    async def _composite_final(self) -> str:
        """Delegate to composite step."""
        return await self._step_composite()

    # ── Reference images step ─────────────────────────────────────

    async def _step_reference_images(self) -> None:
        """Generate multi-angle character references."""
        await self._step_character_identity()

    # ── Audio step (locked voice) ─────────────────────────────────

    async def _step_audio(self):
        """Generate audio with locked voice for all scenes."""
        state = self._state

        # Use locked voice from character profile
        if self._character:
            state.audio_config.voice = self._character.voice_role
            state.audio_config.speed = self._character.voice_speed

        # Build full narration text
        full_text = "\n\n".join(
            s.narration_text for s in state.scenes if s.narration_text
        )
        if not full_text:
            logger.info("[Influencer] No narration text, skipping audio")
            return None

        audio_path = os.path.join(self.working_dir, "full_narration.mp3")

        # Skip if exists
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            state.combined_audio = audio_path
            logger.info("[Influencer] Audio already exists, skipping")
            return await self._recover_sub_maker(
                full_text, state.audio_config, state.subtitle_config,
            )

        await self._emit(
            "audio", "running",
            f"Generating audio ({len(full_text)} chars)...",
            _PROGRESS_AUDIO_DONE,
        )

        sub_maker = await self._generate_audio_with_fallback(
            output_path=audio_path,
            text=full_text,
            audio_config=state.audio_config,
            subtitle_config=state.subtitle_config,
            duration_sec=sum(s.duration for s in state.scenes),
            empty_placeholder="",
        )

        state.combined_audio = audio_path
        self.task_manager.update_state(combined_audio=audio_path)
        return sub_maker

    # ── Subtitle step ─────────────────────────────────────────────

    async def _step_subtitles(self, sub_maker=None):
        """Generate subtitles for all scenes."""
        state = self._state

        if not state.subtitle_config.enabled:
            return

        full_text = "\n\n".join(
            s.narration_text for s in state.scenes if s.narration_text
        )
        if not full_text:
            return

        segment_texts = [full_text]
        segment_durations = [sum(s.duration for s in state.scenes)]

        srt_path, styles_path = await self.generate_subtitles_common(
            segment_texts=segment_texts,
            segment_durations=segment_durations,
            subtitle_config=state.subtitle_config,
            sub_maker=sub_maker,
            audio_path=state.combined_audio or "",
            screenwriter=self.screenwriter,
            video_width=state.video_width,
            video_height=state.video_height,
        )

        if styles_path:
            state.subtitle_styles_path = styles_path

        state.combined_subtitle = srt_path
        self.task_manager.update_state(
            combined_subtitle=srt_path,
            subtitle_styles_path=styles_path or "",
        )

    # ── Composite step ────────────────────────────────────────────

    async def _step_composite(self) -> str:
        """Composite all scene videos with audio and subtitles."""
        state = self._state

        output_path = os.path.join(self.working_dir, "final_video.mp4")
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info("[Influencer] Final video exists, skipping")
            return output_path

        # Collect video paths
        video_paths = [
            s.video_file for s in state.scenes
            if s.video_file and os.path.exists(s.video_file)
        ]
        if not video_paths:
            raise RuntimeError("No scene videos to composite")

        await self._emit(
            "concatenate", "running",
            "Compositing final video...",
            _PROGRESS_COMPOSITE_DONE,
        )

        # Use shared compositor
        await asyncio.to_thread(
            VideoConcatenator.concat_videos_with_audio_overlay,
            video_paths=video_paths,
            audio_path=state.combined_audio or "",
            srt_path=state.combined_subtitle if state.combined_subtitle else None,
            output_path=output_path,
            subtitle_style=state.subtitle_config.style if state.subtitle_config.enabled else None,
            subtitle_styles_path=state.subtitle_styles_path or None,
            video_width=state.video_width,
            video_height=state.video_height,
        )

        logger.info("[Influencer] Final video: %s", output_path)
        return output_path
