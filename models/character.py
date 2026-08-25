"""models.character — Character identity profile for AI Influencer Studio

Stores persistent character identity across scenes:
- Multi-angle face references
- Voice identity
- Appearance metadata for prompt injection
- Locked negative prompt
"""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


# Default locked negative prompt for character consistency
DEFAULT_INFLUENCER_NEGATIVE_PROMPT = (
    "different person, altered facial identity, face morphing, face drift, "
    "different eye shape, different nose shape, different lips, altered jawline, "
    "altered facial proportions, age change, hairstyle change, hair color change, "
    "skin tone change, body proportion change, duplicate person, extra fingers, "
    "malformed hands, unnatural anatomy, plastic skin, CGI appearance, artificial face"
)


class CharacterProfile(BaseModel):
    """Persistent character identity for AI Influencer mode.

    Maintains multi-angle references and metadata to ensure
    consistent character appearance across all scenes.
    """

    character_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""

    # ── Identity references (file paths) ──────────────────────────
    front_face: str = ""                       # Front-facing portrait (primary)
    three_quarter_left: str = ""               # 3/4 view left
    three_quarter_right: str = ""              # 3/4 view right
    left_profile: str = ""                     # Left profile
    right_profile: str = ""                    # Right profile
    full_body: str = ""                        # Full body reference
    outfit_reference: str = ""                 # Clothing / accessories

    # ── Voice identity ────────────────────────────────────────────
    voice_role: str = "zh-CN-XiaoxiaoNeural"  # Locked TTS voice
    voice_speed: float = 1.0

    # ── Character metadata (for prompt injection) ─────────────────
    appearance_text: str = ""                  # Concise appearance description
    personality: str = ""                      # Personality traits

    # ── Seed identity (for reproducibility) ───────────────────────
    character_seed: Optional[int] = None       # Base seed for this character

    # ── Locked negative prompt ────────────────────────────────────
    negative_prompt: str = DEFAULT_INFLUENCER_NEGATIVE_PROMPT

    # ── Helper methods ────────────────────────────────────────────

    def get_references_for_angle(self, camera_angle: str) -> list[str]:
        """Return appropriate reference image paths for the given camera angle.

        Always includes front_face as primary identity anchor.
        """
        refs: list[str] = []
        if self.front_face:
            refs.append(self.front_face)

        angle_map = {
            "front": [self.three_quarter_left, self.three_quarter_right],
            "left_profile": [self.left_profile, self.three_quarter_left],
            "right_profile": [self.right_profile, self.three_quarter_right],
            "3/4_left": [self.three_quarter_left],
            "3/4_right": [self.three_quarter_right],
            "full_body": [self.full_body],
        }
        for path in angle_map.get(camera_angle, []):
            if path and path not in refs:
                refs.append(path)
        return refs

    def get_locked_prompt_prefix(self) -> str:
        """Return the CHARACTER LOCK section for 4-layer prompts."""
        if not self.appearance_text:
            return ""
        return (
            f"[CHARACTER LOCK — DO NOT DEVIATE]\n"
            f"{self.appearance_text}\n"
            f"Preserve identical facial identity, facial proportions, eyes, nose, "
            f"lips, jawline, skin texture, hairline and hairstyle. "
            f"This is the SAME PERSON.\n"
        )

    def get_locked_negative_prompt(self, extra: str = "") -> str:
        """Return the full negative prompt (locked + extra per-scene)."""
        parts = [self.negative_prompt]
        if extra:
            parts.append(extra)
        return ", ".join(parts)
