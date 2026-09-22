"""tests/test_cinematography.py — Cinematography knowledge base tests."""

import pytest

from core.production.bible_builder import (
    ProductionBibleBuilder,
    _SYSTEM_ANALYZE,
    _SYSTEM_SHOTS,
)
from core.production.cinematography import (
    CAMERA_ANGLES,
    CAMERA_MOVEMENTS,
    DIRECTOR_PLANNING_SYSTEM,
    LENSES,
    SHOT_SIZES,
    VISUAL_STYLES,
    lookup_visual_style,
    all_style_names,
)


class TestCinematographyKnowledgeBase:
    def test_all_vocab_categories_present(self):
        assert len(SHOT_SIZES) >= 8
        assert len(CAMERA_ANGLES) >= 8
        assert len(CAMERA_MOVEMENTS) >= 10
        assert len(LENSES) >= 8

    def test_style_lookup_exact(self):
        for name in VISUAL_STYLES:
            assert lookup_visual_style(name) == VISUAL_STYLES[name]

    def test_style_lookup_case_insensitive(self):
        assert "chiaroscuro" in lookup_visual_style("FILM NOIR").lower()

    def test_style_lookup_substring(self):
        assert "chiaroscuro" in lookup_visual_style("noir").lower()

    def test_style_lookup_unknown_passthrough(self):
        assert lookup_visual_style("my weird custom style") == "my weird custom style"

    def test_all_style_names(self):
        names = all_style_names()
        assert "cinematic photorealistic" in names
        assert len(names) == len(VISUAL_STYLES)


class TestSystemPrompts:
    def test_analyze_prompt_has_cinematography(self):
        assert "CINEMATOGRAPHY GRAMMAR" in _SYSTEM_ANALYZE or "SHOT SIZES" in _SYSTEM_ANALYZE
        assert "low angle" in _SYSTEM_ANALYZE.lower()
        assert "three-point" in _SYSTEM_ANALYZE or "chiaroscuro" in _SYSTEM_ANALYZE

    def test_shots_prompt_has_director_planning(self):
        assert "180-degree" in _SYSTEM_SHOTS
        assert "STORYBOARD" in _SYSTEM_SHOTS
        assert "dolly" in _SYSTEM_SHOTS
        assert "shot size + angle + movement" in _SYSTEM_SHOTS

    def test_director_planning_system_importable(self):
        assert "180-degree" in DIRECTOR_PLANNING_SYSTEM


class TestShotVariationEnforcer:
    def test_no_change_on_varied(self):
        shots = [
            {"camera": "wide, eye-level, static"},
            {"camera": "medium close-up, low angle, dolly in"},
        ]
        out = ProductionBibleBuilder._enforce_shot_variation(shots)
        assert out == shots

    def test_consecutive_duplicate_camera_modified(self):
        original = "medium shot, eye-level, static"
        cam = original
        shots = [
            {"camera": cam},
            {"camera": cam},
        ]
        ProductionBibleBuilder._enforce_shot_variation(shots)
        assert shots[1]["camera"] != original
        # new camera still contains original
        assert original in shots[1]["camera"]
        # angle added
        assert "over-the-shoulder" in shots[1]["camera"] or "high angle" in shots[1]["camera"]

    def test_empty_shots(self):
        assert ProductionBibleBuilder._enforce_shot_variation([]) == []

    def test_blank_cameras_untouched(self):
        shots = [{"camera": ""}, {"camera": ""}]
        out = ProductionBibleBuilder._enforce_shot_variation(shots)
        assert out == shots


class TestComposeShotPrompt:
    def test_prompt_has_all_sections(self):
        from core.production.bible_builder import compose_shot_prompt

        shot = {
            "camera": "medium close-up, eye-level, slow dolly in",
            "action": "hero walks",
            "emotion": "determined",
            "characters": ["A"],
            "location": "forest",
            "continuity_in": "x",
            "continuity_out": "y",
            "lighting": "low-key",
        }
        bible = {
            "visual_style": "cinematic photorealistic",
            "cinematography": "anamorphic, teal-orange",
            "lighting": "",
        }
        p = compose_shot_prompt(shot, bible, "cinematic photorealistic")
        assert "[MASTER VISUAL STYLE]" in p
        assert "[CAMERA]" in p
        assert "slow dolly in" in p
        assert "[CINEMATOGRAPHY]" in p
        assert "[LIGHTING]" in p
        assert "[CONTINUITY]" in p
        assert "[NEGATIVE CONSTRAINTS]" in p
        assert "low-key" in p  # shot lighting wins

    def test_shot_prompt_falls_back_to_bible_lighting(self):
        from core.production.bible_builder import compose_shot_prompt

        shot = {
            "camera": "wide",
            "action": "a",
            "emotion": "",
            "characters": [],
            "location": "x",
            "continuity_in": "",
            "continuity_out": "",
            "lighting": "",
        }
        bible = {"visual_style": "vs", "cinematography": "", "lighting": "neon"}
        p = compose_shot_prompt(shot, bible, "vs")
        assert "neon" in p
