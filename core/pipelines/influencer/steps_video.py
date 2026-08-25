"""core.pipelines.influencer.steps_video — Video generation with frame chaining

Generates videos using keyframes mode with character identity lock.
"""

import asyncio
import logging
import os
from typing import List

from core.pipelines import PipelineShutdown
from models.task import StepStatus

logger = logging.getLogger(__name__)


class InfluencerVideoStepsMixin:
    """Video generation with frame chaining and identity lock."""

    async def _step_video_generation(self) -> None:
        """Generate videos with frame chaining.

        Each scene uses:
        - First frame: previous scene's end frame (or character image for scene 0)
        - End frame: identity-locked end frame from step_end_frames
        """
        scenes = self._state.scenes

        # Phase 1: Submit all videos in parallel
        async def _submit_scene(idx: int, scene) -> tuple:
            """Submit single scene video, return (idx, video_id, video_path) or None."""
            self._check_shutdown()

            scene_dir = os.path.join(self.working_dir, f"scene_{idx}")
            os.makedirs(scene_dir, exist_ok=True)
            video_path = os.path.join(scene_dir, "video.mp4")

            # Skip if video exists
            if os.path.exists(video_path):
                scene.video_file = video_path
                return None

            # Skip if video_id already exists (resume)
            saved = self._load_task_json(scene_dir)
            if saved:
                scene.video_id = saved
                return (idx, saved, video_path)

            # Get first frame (previous end frame or character image)
            first_frame = self._get_first_frame(idx)

            # Get end frame
            end_frame = scene.end_frame_file

            # Build references list
            refs = []
            if first_frame and os.path.exists(first_frame):
                refs.append(first_frame)
            if end_frame and os.path.exists(end_frame):
                refs.append(end_frame)

            # Build prompt with identity lock
            prompt = self._build_locked_video_prompt(scene)

            # Submit video
            video_id = await self.video_generator.submit_video(
                prompt=prompt,
                reference_image_paths=refs,
                duration=scene.duration,
                width=self._state.video_width,
                height=self._state.video_height,
                seed=self._state.character_seed,
                negative_prompt=self._get_locked_negative_prompt(),
            )

            scene.video_id = video_id
            self._save_task_json(scene_dir, {"video_id": video_id})
            return (idx, video_id, video_path)

        # Submit all in parallel
        submit_tasks = [_submit_scene(i, s) for i, s in enumerate(scenes)]
        results = await asyncio.gather(*submit_tasks, return_exceptions=True)

        # Collect pending
        pending = []
        for r in results:
            if isinstance(r, Exception):
                raise r
            if r is not None:
                pending.append(r)

        self.task_manager.update_state(
            scenes=[s.model_dump() for s in scenes],
        )

        if not pending:
            logger.info("[Influencer] All videos already generated")
            return

        # Phase 2: Wait for all in parallel
        await self._emit(
            "video_gen", "running",
            f"Waiting for {len(pending)} videos...",
            0.35,
        )

        async def _wait_scene(idx: int, video_id: str, video_path: str):
            self._check_shutdown()
            video_output = await self._wait_for_video_with_retry(video_id, idx)
            video_output.save(video_path)
            self._state.scenes[idx].video_file = video_path

        wait_tasks = [_wait_scene(i, vid, path) for i, vid, path in pending]
        await asyncio.gather(*wait_tasks, return_exceptions=True)

        self.task_manager.update_state(
            scenes=[s.model_dump() for s in self._state.scenes],
        )

    def _get_first_frame(self, scene_idx: int) -> str:
        """Get first frame for scene (previous end frame or character image)."""
        if scene_idx > 0 and self._state.previous_end_frame:
            prev = self._state.previous_end_frame
            if os.path.exists(prev):
                return prev

        # Fallback: character front face
        if self._character and self._character.front_face:
            return self._character.front_face

        return ""

    def _build_locked_video_prompt(self, scene) -> str:
        """Build 4-layer identity-locked video prompt."""
        char = self._character
        if not char:
            return scene.scene_prompt or "Cinematic video scene"

        # Layer 1: Character Lock
        character_lock = char.get_locked_prompt_prefix()

        # Layer 2: Visual Lock
        visual_lock = (
            "Photorealistic, natural skin texture, realistic human anatomy, "
            "consistent wardrobe and accessories. Smooth natural movement."
        )

        # Layer 3: Scene State
        scene_state = scene.scene_prompt or "Character in scene"

        # Layer 4: Action / Camera
        action_camera = (
            f"Camera angle: {scene.camera_angle or 'front'}. "
            f"Emotion: {scene.emotion or 'neutral'}. "
            f"Natural, subtle movement. Maintain character identity throughout."
        )

        return f"""{character_lock}
{visual_lock}

{scene_state}

{action_camera}
"""

    def _get_locked_negative_prompt(self) -> str:
        """Get the locked negative prompt from character profile."""
        if self._character:
            return self._character.get_locked_negative_prompt()
        return (
            "different person, altered facial identity, face morphing, "
            "face drift, different eye shape, different nose shape, "
            "different lips, altered jawline, altered facial proportions, "
            "age change, hairstyle change, hair color change, "
            "skin tone change, body proportion change, duplicate person, "
            "extra fingers, malformed hands, unnatural anatomy, "
            "plastic skin, CGI appearance, artificial face"
        )

    async def _wait_for_video_with_retry(
        self, video_id: str, scene_idx: int, max_retries: int = 3
    ):
        """Wait for video with retry logic."""
        for retry in range(max_retries):
            try:
                return await self.video_generator.wait_for_video(video_id)
            except Exception as e:
                if retry < max_retries - 1:
                    delay = 20 * (retry + 1)
                    logger.warning(
                        "[Influencer] Video %s retry %d/%d: %s",
                        video_id[:16], retry + 1, max_retries, e,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
