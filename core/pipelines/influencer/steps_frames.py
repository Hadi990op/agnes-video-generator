"""core.pipelines.influencer.steps_frames — End frame generation with identity lock

Generates end frames using character references for visual continuity.
"""

import asyncio
import logging
import os
from typing import List, Optional

from core.pipelines import PipelineShutdown
from models.task import StepStatus

logger = logging.getLogger(__name__)


class InfluencerFrameStepsMixin:
    """End frame generation with character identity lock."""

    async def _step_end_frames(self) -> None:
        """Generate identity-locked end frames for each scene."""
        scenes = self._state.scenes

        for i, scene in enumerate(scenes):
            self._check_shutdown()

            # Skip if end frame already exists
            if scene.end_frame_file and os.path.exists(scene.end_frame_file):
                logger.info("[Influencer] Scene %d end frame exists, skipping", i)
                continue

            await self._emit(
                "end_frame", "running",
                f"Generating end frame {i + 1}/{len(scenes)}...",
                0.25 + 0.10 * i / max(len(scenes), 1),
            )

            end_frame_path = await self._generate_identity_locked_end_frame(i, scene)
            scene.end_frame_file = end_frame_path

        self.task_manager.update_state(
            scenes=[s.model_dump() for s in scenes],
        )

    async def _generate_identity_locked_end_frame(
        self, scene_idx: int, scene
    ) -> str:
        """Generate end frame with character identity lock.

        Uses:
        1. Character reference (identity anchor)
        2. Previous scene's end frame (continuity)
        3. End frame prompt (scene-specific)
        """
        scene_dir = os.path.join(self.working_dir, f"scene_{scene_idx}")
        os.makedirs(scene_dir, exist_ok=True)
        end_frame_path = os.path.join(scene_dir, "end_frame.jpg")

        # Build 4-layer locked prompt
        prompt = self._build_locked_end_frame_prompt(scene_idx, scene)

        # Select references
        refs = self._get_end_frame_references(scene_idx)

        try:
            img_output = await self.image_generator.generate_single_image(
                prompt=prompt,
                reference_image_paths=refs,
                size=f"{self._state.video_width}x{self._state.video_height}",
            )
            img_output.save(end_frame_path)

            # Update chain
            self._state.previous_end_frame = end_frame_path
            self._state.approved_frames.append(end_frame_path)

            logger.info("[Influencer] Generated end frame for scene %d", scene_idx)
            return end_frame_path

        except Exception as e:
            logger.error("[Influencer] End frame generation failed for scene %d: %s", scene_idx, e)
            raise

    def _build_locked_end_frame_prompt(self, scene_idx: int, scene) -> str:
        """Build 4-layer identity-locked prompt for end frame."""
        char = self._character
        if not char:
            return scene.scene_prompt or "Cinematic end frame"

        # Layer 1: Character Lock
        character_lock = char.get_locked_prompt_prefix()

        # Layer 2: Visual Lock
        visual_lock = (
            "Photorealistic, natural skin texture, realistic human anatomy, "
            "consistent wardrobe and accessories."
        )

        # Layer 3: Scene State
        scene_state = scene.scene_prompt or f"Scene {scene_idx + 1}"

        # Layer 4: End Frame Specific
        end_frame_instruction = (
            f"[END FRAME — static final pose]\n"
            f"Character ends in a natural, stable pose. "
            f"Face clearly visible, expression: {scene.emotion or 'neutral'}. "
            f"Camera angle: {scene.camera_angle or 'front'}."
        )

        return f"""{character_lock}
{visual_lock}

{scene_state}

{end_frame_instruction}
"""

    def _get_end_frame_references(self, scene_idx: int) -> List[str]:
        """Select references for end frame generation."""
        refs = []

        # Primary: character front face
        if self._character and self._character.front_face:
            refs.append(self._character.front_face)

        # Continuity: previous scene's end frame
        if scene_idx > 0 and self._state.previous_end_frame:
            if os.path.exists(self._state.previous_end_frame):
                refs.append(self._state.previous_end_frame)

        # Angle-specific reference
        if self._character:
            scene = self._state.scenes[scene_idx]
            angle_refs = self._character.get_references_for_angle(scene.camera_angle)
            for ref in angle_refs:
                if ref not in refs:
                    refs.append(ref)

        return refs[:3]  # Max 3 references
