"""core.pipelines.influencer.steps_character — Character identity generation

Generates or locks character identity with multi-angle references.
"""

import asyncio
import logging
import os
from typing import Optional

from models.character import CharacterProfile

logger = logging.getLogger(__name__)


class CharacterStepsMixin:
    """Character identity generation and locking steps."""

    async def _step_character_identity(self) -> None:
        """Generate or lock character identity.

        If user provided a reference image, generate multi-angle views.
        Otherwise, generate character from description.
        """
        state = self._state
        working_dir = self.working_dir

        # If character profile already exists and is complete, skip
        if self._character and self._character.front_face:
            if os.path.exists(self._character.front_face):
                logger.info("[Influencer] Character identity already locked, skipping")
                return

        # Create character directory
        char_dir = os.path.join(working_dir, "character")
        os.makedirs(char_dir, exist_ok=True)

        # Initialize character profile
        if not self._character:
            self._character = CharacterProfile(
                name=state.character_name,
                description=state.character_description,
                voice_role=state.voice_role,
                voice_speed=state.voice_speed,
                character_seed=state.character_seed,
            )

        # Generate or use provided reference image
        if state.character_image_path and os.path.exists(state.character_image_path):
            # Use provided image as front face
            self._character.front_face = state.character_image_path
            logger.info("[Influencer] Using provided character reference image")
        else:
            # Generate character from description
            await self._generate_character_from_description(char_dir)

        # Generate multi-angle references
        await self._generate_multi_angle_references(char_dir)

        # Extract appearance description for prompt injection
        await self._extract_appearance_description()

        # Save character profile
        self._state.character_profile_data = self._character.model_dump()
        self.task_manager.update_state(
            character_profile_data=self._state.character_profile_data,
        )
        logger.info("[Influencer] Character identity locked: %s", self._character.name)

    async def _generate_character_from_description(self, char_dir: str) -> None:
        """Generate character front-face image from description."""
        prompt = self._character.description or (
            "A professional young influencer, front-facing portrait, "
            "clear face, natural lighting, photorealistic"
        )
        size = f"{self._state.video_width}x{self._state.video_height}"

        await self._emit(
            "character_gen", "running",
            f"Generating character: {self._character.name}...", 0.04,
        )

        try:
            img_output = await self.image_generator.generate_single_image(
                prompt=prompt,
                size=size,
            )
            front_path = os.path.join(char_dir, "front_face.jpg")
            img_output.save(front_path)
            self._character.front_face = front_path
            logger.info("[Influencer] Generated character front face: %s", front_path)
        except Exception as e:
            logger.error("[Influencer] Character generation failed: %s", e)
            raise RuntimeError(f"Character generation failed: {e}")

    async def _generate_multi_angle_references(self, char_dir: str) -> None:
        """Generate multi-angle views from front face reference."""
        if not self._character.front_face:
            return

        angles = {
            "three_quarter_left": (
                "Three-quarter view from left, same person, same face, "
                "same clothing, slight turn to the left, natural pose"
            ),
            "three_quarter_right": (
                "Three-quarter view from right, same person, same face, "
                "same clothing, slight turn to the right, natural pose"
            ),
            "left_profile": (
                "Left profile view, same person, same face, same clothing, "
                "head turned fully to the left, clean profile"
            ),
            "right_profile": (
                "Right profile view, same person, same face, same clothing, "
                "head turned fully to the right, clean profile"
            ),
            "full_body": (
                "Full body shot, same person, same face, same clothing, "
                "standing pose, full figure visible"
            ),
        }

        size = f"{self._state.video_width}x{self._state.video_height}"

        for angle_name, angle_prompt in angles.items():
            # Skip if already generated
            existing = getattr(self._character, angle_name, "")
            if existing and os.path.exists(existing):
                continue

            try:
                img_output = await self.image_generator.generate_single_image(
                    prompt=angle_prompt,
                    reference_image_paths=[self._character.front_face],
                    size=size,
                )
                angle_path = os.path.join(char_dir, f"{angle_name}.jpg")
                img_output.save(angle_path)
                setattr(self._character, angle_name, angle_path)
                logger.info("[Influencer] Generated %s reference", angle_name)
            except Exception as e:
                logger.warning(
                    "[Influencer] Failed to generate %s: %s (will use front face)",
                    angle_name, e,
                )

    async def _extract_appearance_description(self) -> None:
        """Extract concise appearance description for prompt injection."""
        if self._character.appearance_text:
            return

        try:
            description = await asyncio.to_thread(
                self.screenwriter.get_character_appearance,
                story=self._character.description or self._character.name,
                language="en",
            )
            self._character.appearance_text = description
            logger.info("[Influencer] Extracted appearance: %s...", description[:80])
        except Exception as e:
            logger.warning("[Influencer] Failed to extract appearance: %s", e)
            # Fallback to basic description
            self._character.appearance_text = (
                f"{self._character.name} is a person with consistent facial features, "
                f"wearing the same outfit throughout."
            )
