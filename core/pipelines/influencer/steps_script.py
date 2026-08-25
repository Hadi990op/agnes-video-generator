"""core.pipelines.influencer.steps_script — Script planning with continuity

Splits script into scenes with continuity metadata.
"""

import asyncio
import logging
import os
from typing import List

from models.task import InfluencerSceneTask

logger = logging.getLogger(__name__)


class ScriptStepsMixin:
    """Script planning and scene generation with continuity metadata."""

    async def _step_script_planning(self) -> None:
        """Plan scenes from script with continuity metadata."""
        state = self._state

        # If scenes already exist, skip
        if state.scenes and state.scenes[0].scene_prompt:
            logger.info("[Influencer] Script planning already done, skipping")
            return

        script = state.script_text
        if not script:
            raise RuntimeError("Script text is required")

        await self._emit(
            "script_plan", "running",
            f"Planning {state.scene_count} scenes...", 0.10,
        )

        # Split script into scenes
        scenes = await self._split_script_to_scenes(script, state.scene_count)

        # Generate scene prompts with continuity metadata
        for i, scene in enumerate(scenes):
            scene.continuity_metadata = await self._build_continuity_metadata(i, scene)

        state.scenes = scenes
        self.task_manager.update_state(
            scenes=[s.model_dump() for s in state.scenes],
        )
        logger.info("[Influencer] Script planned: %d scenes", len(scenes))

    async def _split_script_to_scenes(
        self, script: str, target_count: int
    ) -> List[InfluencerSceneTask]:
        """Split script into scenes using LLM."""
        try:
            result = await asyncio.to_thread(
                self.screenwriter._chat,
                system_prompt=self._split_system_prompt(),
                user_prompt=self._split_user_prompt(script, target_count),
            )
            scenes_data = self._parse_scenes_from_llm(result)
            return [
                InfluencerSceneTask(
                    index=i,
                    narration_text=s.get("narration", ""),
                    scene_prompt=s.get("scene_prompt", ""),
                    camera_angle=s.get("camera_angle", "front"),
                    location=s.get("location", ""),
                    wardrobe_notes=s.get("wardrobe", ""),
                    emotion=s.get("emotion", "neutral"),
                    duration=s.get("duration", 5),
                )
                for i, s in enumerate(scenes_data)
            ]
        except Exception as e:
            logger.warning("[Influencer] LLM scene split failed: %s, using fallback", e)
            return self._fallback_split(script, target_count)

    def _split_system_prompt(self) -> str:
        return """You are a video script planner. Split the given script into scenes.

For each scene, provide:
- narration: The text to be spoken (keep original language)
- scene_prompt: Visual description for video generation (80-150 words, cinematic)
- camera_angle: One of "front", "left_profile", "right_profile", "3/4_left", "3/4_right", "full_body"
- location: Where the scene takes place
- wardrobe: Any clothing notes (empty if same as previous)
- emotion: Character emotion (neutral, happy, serious, etc.)
- duration: Estimated duration in seconds (5-10)

Output as JSON array. Keep character identity consistent across scenes.
Use the SAME LANGUAGE as the input script for all fields."""

    def _split_user_prompt(self, script: str, count: int) -> str:
        return f"""Split this script into exactly {count} scenes for an AI influencer video.

<script>
{script}
</script>

Output a JSON array with {count} objects. Each object must have:
narration, scene_prompt, camera_angle, location, wardrobe, emotion, duration

Important: Keep the SAME CHARACTER identity across all scenes.
The character should be recognizable as the same person throughout."""

    def _parse_scenes_from_llm(self, text: str) -> list:
        """Parse JSON scenes from LLM response."""
        import json
        import re

        # Try to extract JSON array
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Fallback: try to parse line by line
        logger.warning("[Influencer] Could not parse LLM response as JSON")
        return []

    def _fallback_split(self, script: str, count: int) -> List[InfluencerSceneTask]:
        """Fallback: split script by sentences."""
        import re

        # Split by sentence-ending punctuation
        sentences = re.split(r'(?<=[。！？.!?])\s*', script.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        # Group into target count
        scenes = []
        per_scene = max(1, len(sentences) // count)

        for i in range(count):
            start = i * per_scene
            end = start + per_scene if i < count - 1 else len(sentences)
            narration = " ".join(sentences[start:end])

            scenes.append(InfluencerSceneTask(
                index=i,
                narration_text=narration,
                scene_prompt=f"Cinematic scene: {narration[:100]}",
                camera_angle="front",
                duration=5,
            ))

        return scenes

    async def _build_continuity_metadata(
        self, scene_idx: int, scene: InfluencerSceneTask
    ) -> dict:
        """Build continuity metadata for a scene."""
        # Get previous scene end state
        prev_end_state = None
        if scene_idx > 0 and self._state.scenes:
            prev_scene = self._state.scenes[scene_idx - 1]
            prev_end_state = prev_scene.continuity_metadata.get("end_state")

        return {
            "scene_index": scene_idx,
            "character_position": "center-frame" if scene.camera_angle == "front" else "varies",
            "character_wardrobe": scene.wardrobe_notes or "default",
            "location": scene.location,
            "emotion": scene.emotion,
            "camera_angle": scene.camera_angle,
            "previous_end_state": prev_end_state,
            "expected_start_state": {
                "character_position": "consistent with previous",
                "wardrobe": scene.wardrobe_notes or "same as previous",
            },
            "end_state": {
                "character_position": "consistent with scene",
                "facial_expression": scene.emotion,
            },
        }
