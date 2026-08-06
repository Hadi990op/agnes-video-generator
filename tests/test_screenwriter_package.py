"""
Screenwriter 包拆分（v5.0 Batch 4 / 4.1）组合与 re-export 契约测试。

core/screenwriter.py → core/screenwriter/ 包（story/scenes/characters/style mixin
+ __init__ 组合）。本文件守护拆分契约：
- Screenwriter 经 mixin 组合后对外方法完整（26 个，与拆分前一致）；
- 模块级符号（clean_narration_text / build_poetry_scene_prompt / _xml_escape /
  PROMPT_LANGUAGE / AgnesChatAPI）re-export 可用，外部调用点零改动；
- 关键行为（旁白清洗、诗词提示词构建）不因拆分而改变。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import core.api.agnes_chat as agnes_chat
from core.screenwriter import (
    Screenwriter,
    ScreenwriterStoryMixin,
    ScreenwriterScenesMixin,
    ScreenwriterCharactersMixin,
    ScreenwriterStyleMixin,
    AgnesChatAPI,
    PROMPT_LANGUAGE,
    _xml_escape,
    build_poetry_scene_prompt,
    clean_narration_text,
)


# ═══════════════════════════════════════════════
# 1. mixin 组合：全部原方法经 MRO 可用
# ═══════════════════════════════════════════════

_SCREENWRITER_METHODS = [
    # __init__.py 基础设施（8）
    "__init__", "_prompt", "_chat", "_chat_json", "_image_to_b64_uri",
    "_chat_multimodal", "describe_images", "_describe_with_retry",
    # story.py（4）
    "extract_scene_info_from_idea", "develop_story", "write_script",
    "generate_narration_for_video",
    # characters.py（6）
    "extract_character_description", "get_character_appearance",
    "generate_end_frame_prompts", "generate_anchor_clip_prompt",
    "generate_anchor_smooth_loop_prompt", "generate_anchor_model_audio_prompt",
    # scenes.py（5）
    "design_shots_for_scene", "generate_scene_prompt_for_paragraph",
    "generate_poetry_scenes", "_poetry_scene_prompts", "_parse_poetry_scene_lines",
    # style.py（3）
    "generate_subtitle_styles", "_validate_styles", "_fallback_styles",
]


def test_screenwriter_composes_all_original_methods():
    """拆分后 Screenwriter 仍具备拆分前全部 26 个方法（mixin MRO 组合）。"""
    missing = [m for m in _SCREENWRITER_METHODS if not hasattr(Screenwriter, m)]
    assert not missing, f"missing methods after split: {missing}"


def test_mixin_classes_are_used_by_screenwriter():
    """Screenwriter 的 MRO 包含全部四个职责 mixin。"""
    mro_names = [c.__name__ for c in Screenwriter.__mro__]
    for mixin in (
        "ScreenwriterStoryMixin",
        "ScreenwriterScenesMixin",
        "ScreenwriterCharactersMixin",
        "ScreenwriterStyleMixin",
    ):
        assert mixin in mro_names, f"{mixin} not in Screenwriter MRO"


def test_mixin_methods_defined_in_respective_modules():
    """各 mixin 的方法定义在对应的拆分模块中（职责归属正确）。"""
    assert ScreenwriterStoryMixin.develop_story.__module__ == "core.screenwriter.story"
    assert ScreenwriterCharactersMixin.get_character_appearance.__module__ == "core.screenwriter.characters"
    assert ScreenwriterScenesMixin.design_shots_for_scene.__module__ == "core.screenwriter.scenes"
    assert ScreenwriterStyleMixin.generate_subtitle_styles.__module__ == "core.screenwriter.style"


def test_fallback_styles_kept_staticmethod():
    """_fallback_styles 是 staticmethod（拆分前后调用语义一致）。

    _fallback_styles 定义在 style mixin 中，经 MRO 组合进 Screenwriter；
    直接查 mixin 的 __dict__ 确认 staticmethod 装饰器存在。
    """
    assert isinstance(ScreenwriterStyleMixin.__dict__["_fallback_styles"], staticmethod)


# ═══════════════════════════════════════════════
# 2. 模块级 re-export（外部调用点零修改）
# ═══════════════════════════════════════════════

def test_module_level_reexports():
    """core.screenwriter 包入口保留全部原模块级符号。"""
    assert callable(clean_narration_text)
    assert callable(build_poetry_scene_prompt)
    assert callable(_xml_escape)
    assert isinstance(PROMPT_LANGUAGE, str)
    assert AgnesChatAPI is agnes_chat.AgnesChatAPI


def test_clean_narration_text_behavior_unchanged():
    """旁白清洗行为与拆分前一致（元数据行/标题/列表符号去除）。"""
    assert clean_narration_text("") == ""
    assert clean_narration_text("**受众**：16-35岁\n# 故事标题\n小河边\n\n第二句") == "小河边第二句"
    assert clean_narration_text("## 目标受众\nstory title: demo\n\n纯叙事正文") == "纯叙事正文"
    assert clean_narration_text("- 列表项\n- 另一项") == "列表项另一项"


def test_xml_escape_behavior_unchanged():
    """XML 转义行为不变（防 prompt 注入）。"""
    assert _xml_escape("<idea>x</idea>") == "&lt;idea&gt;x&lt;/idea&gt;"
    assert _xml_escape("a & b \"c\"") == "a &amp; b &quot;c&quot;"
    assert _xml_escape("") == ""


def test_build_poetry_scene_prompt_offline():
    """诗词场景提示词构建为纯字符串拼接，不触网。"""
    result = build_poetry_scene_prompt(
        "床前明月光", scene_count=2, scene_durations=[5, 5], total_duration=10
    )
    assert set(result) == {"system_prompt", "user_prompt"}
    assert "<poem>" in result["user_prompt"]
    assert "床前明月光" in result["user_prompt"]
    assert "2" in result["user_prompt"]
