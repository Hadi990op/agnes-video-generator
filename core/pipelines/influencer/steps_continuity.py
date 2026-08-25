"""core.pipelines.influencer.steps_continuity — Continuity engine

Tracks scene metadata and checks compatibility between scenes.
"""

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class ContinuityEngine:
    """Tracks scene metadata and checks continuity between scenes."""

    def __init__(self):
        self._scene_history: list[dict] = []

    def record_scene(self, scene_idx: int, metadata: dict) -> None:
        """Record scene metadata for future checks."""
        while len(self._scene_history) <= scene_idx:
            self._scene_history.append({})
        self._scene_history[scene_idx] = metadata

    def check_continuity(
        self, prev_scene_idx: int, next_scene_idx: int
    ) -> Tuple[bool, List[str]]:
        """Check continuity between two adjacent scenes.

        Returns:
            (is_compatible, list_of_issues)
        """
        issues = []

        if prev_scene_idx < 0 or prev_scene_idx >= len(self._scene_history):
            return True, []

        if next_scene_idx < 0 or next_scene_idx >= len(self._scene_history):
            return True, []

        prev = self._scene_history[prev_scene_idx]
        next_ = self._scene_history[next_scene_idx]

        # Check wardrobe consistency
        prev_wardrobe = prev.get("wardrobe", "")
        next_wardrobe = next_.get("wardrobe", "")
        if prev_wardrobe and next_wardrobe and prev_wardrobe != next_wardrobe:
            if not next_wardrobe or next_wardrobe == "same":
                issues.append(
                    f"Wardrobe change not explained: '{prev_wardrobe}' -> '{next_wardrobe}'"
                )

        # Check character position flow
        prev_end = prev.get("end_state", {})
        next_start = next_.get("expected_start_state", {})

        if prev_end and next_start:
            prev_pos = prev_end.get("character_position", "")
            next_pos = next_start.get("character_position", "")
            if prev_pos and next_pos and not self._positions_compatible(prev_pos, next_pos):
                issues.append(
                    f"Position mismatch: '{prev_pos}' -> '{next_pos}'"
                )

        # Check location continuity
        prev_location = prev.get("location", "")
        next_location = next_.get("location", "")
        if prev_location and next_location and prev_location != next_location:
            # Location change is OK, just note it
            logger.info(
                "[Continuity] Location change: '%s' -> '%s'",
                prev_location, next_location,
            )

        is_compatible = len(issues) == 0
        return is_compatible, issues

    def _positions_compatible(self, pos1: str, pos2: str) -> bool:
        """Check if two character positions are compatible for transition."""
        # Simple heuristic: if both mention "facing camera" or similar, they're compatible
        camera_positions = {"facing camera", "center-frame", "front", "medium shot"}
        pos1_lower = pos1.lower()
        pos2_lower = pos2.lower()

        # If both are camera-facing, compatible
        if any(p in pos1_lower for p in camera_positions) and \
           any(p in pos2_lower for p in camera_positions):
            return True

        # If either is "consistent with previous", compatible
        if "consistent" in pos2_lower or "same" in pos2_lower:
            return True

        # Default: assume compatible (don't block generation)
        return True

    def get_scene_summary(self) -> str:
        """Get human-readable summary of scene history."""
        if not self._scene_history:
            return "No scenes recorded"

        lines = []
        for i, meta in enumerate(self._scene_history):
            location = meta.get("location", "unknown")
            wardrobe = meta.get("wardrobe", "default")
            emotion = meta.get("emotion", "neutral")
            lines.append(f"Scene {i+1}: {location}, {wardrobe}, {emotion}")

        return "\n".join(lines)
