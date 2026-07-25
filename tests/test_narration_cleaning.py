"""单元测试：旁白文本清洗（防止把 Markdown 结构/元数据当旁白念出）。

对应 v5.0-dev 修复：创意视频旁白原为单段纯文本，但 LLM 偶发回显
``# 故事标题`` / ``## 目标受众`` 等结构化文档，被 TTS 念出。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.screenwriter import clean_narration_text


def test_strips_metadata_headers_and_bold():
    """真实污染串：仅含标题/受众等元数据，清洗后应丢弃这些行。"""
    raw = (
        "# 故事标题：《鞋择其主》\n\n"
        "## 目标受众与类型\n"
        "- **受众**：16-35岁，偏好暗黑童话、悬疑惊悚与视觉反差内容的短视频用户。"
    )
    out = clean_narration_text(raw)
    # 元数据行全部被剥离
    assert "故事标题" not in out
    assert "目标受众" not in out
    assert "受众" not in out
    assert "**" not in out
    assert "#" not in out


def test_preserves_pure_narration():
    """纯旁白正文应原样保留（仅合并换行、去多余空白）。"""
    raw = "在古老的教堂里，新娘缓缓抬起头。\n镜面如水波荡漾，十二道身影从雾中凝结。"
    out = clean_narration_text(raw)
    assert "在古老的教堂里" in out
    assert "十二道身影从雾中凝结" in out
    # 合并为一段连续文本（无换行）
    assert "\n" not in out


def test_keeps_narrative_body_inside_structured_doc():
    """结构化文档中若含叙事正文段落，应保留正文、丢弃元数据行。"""
    raw = (
        "# 故事标题：《测试》\n\n"
        "## 正文\n"
        "月光洒在石阶上，她迈出第一步。风穿过长廊，带来远处的钟声。"
    )
    out = clean_narration_text(raw)
    assert "故事标题" not in out
    assert "月光洒在石阶上" in out
    assert "远处的钟声" in out


def test_english_metadata_also_stripped():
    """英文元数据前缀同样被剥离。"""
    raw = "## Story Title\nThe hero walked into the silent hall."
    out = clean_narration_text(raw)
    assert "Story Title" not in out
    assert "The hero walked into the silent hall." in out


def test_empty_and_none():
    assert clean_narration_text("") == ""
    assert clean_narration_text(None) == ""
    assert clean_narration_text("   \n\n  ") == ""


def test_only_metadata_yields_empty():
    """全为元数据且无正文时返回空串（交由调用方回退）。"""
    raw = "# 故事标题：《X》\n## 目标受众\n**受众**：年轻人"
    assert clean_narration_text(raw) == ""
