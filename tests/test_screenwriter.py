"""
Batch 6（S10）编剧/拆段纯函数单测 — tests/test_screenwriter.py

覆盖（6.1 验收项：screenwriter 拆分后各模块纯函数 + mock LLM 方法 + 稿件拆段）：
- scenes.py 纯函数：_parse_poetry_scene_lines（行格式解析/编号前缀/标签行跳过/围栏剥离）、
  _poetry_scene_prompts（count/duration/style hint 构造）、generate_poetry_scenes（mock _chat 全链路）
- style.py 纯函数：_validate_styles（index 校验/去重/clamp/缺失填充）、_fallback_styles（循环位置）
- story.py mock LLM：extract_scene_info_from_idea（成功/clamp/RuntimeError）、
  develop_story（_xml_escape 防注入）、generate_narration_for_video（clean_narration_text 清洗）
- __init__.py 模块级：build_poetry_scene_prompt（复用内部提示词构造）
- manuscript_video.py 拆段算法：_split_text（贪心合并/长句不拆/短段回并/换行切块/resume）
- BasePipeline.fix_double_utf8（双重 UTF-8 修复）

用法:
    .venv/bin/python -m pytest tests/test_screenwriter.py -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.pipelines import BasePipeline
from core.pipelines.manuscript_video import ManuscriptVideoPipeline
from core.screenwriter import Screenwriter, build_poetry_scene_prompt
from core.screenwriter.style import ScreenwriterStyleMixin
from models.task import ManuscriptParagraph, ManuscriptVideoTask


# ═══════════════════════════════════════════════
# 1. scenes.py 纯函数：_parse_poetry_scene_lines
# ═══════════════════════════════════════════════

class TestParsePoetrySceneLines:
    """诗词场景行格式解析（`原诗句 | 画面描述`）。"""

    @pytest.fixture()
    def parser(self):
        return Screenwriter(api_key="", language="zh")._parse_poetry_scene_lines

    def test_parses_standard_lines(self, parser):
        raw = "床前明月光 | 月光洒落窗前\n疑是地上霜 | 地面泛起白霜"
        scenes = parser(raw)
        assert len(scenes) == 2
        assert scenes[0] == {"narration": "床前明月光", "scene_prompt": "月光洒落窗前"}
        assert scenes[1] == {"narration": "疑是地上霜", "scene_prompt": "地面泛起白霜"}

    def test_strips_numbering_prefix(self, parser):
        raw = "1. 春眠不觉晓 | 春日清晨薄雾\n2、夜来风雨声 | 夜雨敲窗"
        scenes = parser(raw)
        assert scenes[0]["narration"] == "春眠不觉晓"
        assert scenes[1]["narration"] == "夜来风雨声"

    def test_scene_label_lines_skipped_entirely(self, parser):
        """带「场景N」/「Scene N」前缀的行整体跳过（历史行为：无论是否含 `|`）。"""
        raw = "场景1：白日依山尽 | 夕阳西下\nScene 2: 黄河入海流 | 大河奔涌\n床前明月光 | 月光洒落窗前"
        scenes = parser(raw)
        assert len(scenes) == 1
        assert scenes[0]["narration"] == "床前明月光"

    def test_skips_pure_scene_label_lines(self, parser):
        """纯场景标签行（如「场景 1（00:00 - 00:10）」）不应被误判为分镜。"""
        raw = "场景 1（00:00 - 00:10）\n床前明月光 | 月光洒落窗前"
        scenes = parser(raw)
        assert len(scenes) == 1
        assert scenes[0]["narration"] == "床前明月光"

    def test_line_without_separator_becomes_empty_narration(self, parser):
        """无 `|` 的行视为纯画面描述，诗句留空由调用方处理。"""
        raw = "只有画面描述没有诗句"
        scenes = parser(raw)
        assert scenes == [{"narration": "", "scene_prompt": "只有画面描述没有诗句"}]

    def test_skips_lines_with_empty_prompt(self, parser):
        raw = "床前明月光 |\n疑是地上霜 | 地面泛起白霜"
        scenes = parser(raw)
        assert len(scenes) == 1
        assert scenes[0]["narration"] == "疑是地上霜"

    def test_strips_code_fence(self, parser):
        raw = "```\n床前明月光 | 月光洒落窗前\n```"
        scenes = parser(raw)
        assert len(scenes) == 1
        assert scenes[0]["narration"] == "床前明月光"

    def test_empty_input(self, parser):
        assert parser("") == []
        assert parser(None) == []


# ═══════════════════════════════════════════════
# 2. scenes.py 纯函数：_poetry_scene_prompts / build_poetry_scene_prompt
# ═══════════════════════════════════════════════

class TestPoetryScenePrompts:
    """诗词场景提示词构造（内部 LLM 与外部复制提示词共用）。"""

    def test_count_hint_numeric_when_specified(self):
        sw = Screenwriter(api_key="", language="zh")
        _, user = sw._poetry_scene_prompts("床前明月光", scene_count=3, scene_durations=[], total_duration=30, style="")
        assert "3 个" in user
        assert "目标总时长：30 秒" in user

    def test_count_hint_auto_when_zero(self):
        sw = Screenwriter(api_key="", language="zh")
        _, user = sw._poetry_scene_prompts("床前明月光", scene_count=0, scene_durations=[], total_duration=30, style="")
        assert "自行决定" in user

    def test_durations_hint_includes_total(self):
        sw = Screenwriter(api_key="", language="zh")
        _, user = sw._poetry_scene_prompts("床前明月光", scene_count=2, scene_durations=[5, 8], total_duration=30, style="")
        assert "5秒" in user and "8秒" in user
        assert "合计 13 秒" in user

    def test_style_hint_fallback_default(self):
        sw = Screenwriter(api_key="", language="zh")
        _, user = sw._poetry_scene_prompts("床前明月光", scene_count=0, scene_durations=[], total_duration=30, style="")
        assert "通用电影质感写实风格" in user

    def test_style_hint_uses_provided_style(self):
        sw = Screenwriter(api_key="", language="zh")
        _, user = sw._poetry_scene_prompts("床前明月光", scene_count=0, scene_durations=[], total_duration=30, style="水墨国风")
        assert "水墨国风" in user

    def test_poem_and_format_embedded(self):
        sw = Screenwriter(api_key="", language="zh")
        sys_p, user = sw._poetry_scene_prompts("床前明月光", scene_count=2, scene_durations=[5, 5], total_duration=10, style="")
        assert "<poem>" in user and "床前明月光" in user
        assert "|" in sys_p  # 行格式示例含分隔符

    def test_build_poetry_scene_prompt_matches_internal(self):
        """模块级 build_poetry_scene_prompt 与内部 _poetry_scene_prompts 逐字一致。"""
        sw = Screenwriter(api_key="", language="zh")
        result = build_poetry_scene_prompt(
            "床前明月光", scene_count=2, scene_durations=[5, 8], total_duration=13, style="水墨")
        internal = sw._poetry_scene_prompts(
            "床前明月光", 2, [5, 8], 13, "水墨")
        assert (result["system_prompt"], result["user_prompt"]) == internal


# ═══════════════════════════════════════════════
# 3. style.py 纯函数：_validate_styles / _fallback_styles
# ═══════════════════════════════════════════════

class TestValidateStyles:
    """LLM 字幕样式输出校验与修复。"""

    def test_valid_styles_kept_and_sorted(self):
        styles = [
            {"index": 2, "position": ["center", "top+60"], "color": "gold", "fontsize": 56},
            {"index": 1, "position": ["center", "bottom-80"], "color": "white", "fontsize": 40},
        ]
        result = Screenwriter(api_key="", language="zh")._validate_styles(styles, 3)
        assert [s["index"] for s in result] == [1, 2, 3]  # 3 为缺失条目填充
        assert result[0]["position"] == ["center", "bottom-80"]

    def test_duplicate_and_out_of_range_indices_dropped(self):
        styles = [
            {"index": 1, "position": ["center", "top+80"], "color": "white", "fontsize": 48},
            {"index": 1, "position": ["left", "center"], "color": "red", "fontsize": 40},   # 重复
            {"index": 99, "position": ["right", "center"], "color": "blue", "fontsize": 40},  # 越界
        ]
        result = Screenwriter(api_key="", language="zh")._validate_styles(styles, 2)
        assert [s["index"] for s in result] == [1, 2]
        assert result[0]["color"] == "white"

    def test_fontsize_clamped_to_default(self):
        styles = [
            {"index": 1, "position": ["center", "top+80"], "color": "white", "fontsize": 12},   # < 18
            {"index": 2, "position": ["center", "top+80"], "color": "white", "fontsize": 200},  # > 80
            {"index": 3, "position": ["center", "top+80"], "color": "white", "fontsize": "big"},  # 非 int
        ]
        result = Screenwriter(api_key="", language="zh")._validate_styles(styles, 3)
        assert all(s["fontsize"] == 48 for s in result)

    def test_invalid_position_replaced_with_default(self):
        styles = [
            {"index": 1, "position": "center", "color": "white", "fontsize": 48},
            {"index": 2, "position": ["center"], "color": "white", "fontsize": 48},
        ]
        result = Screenwriter(api_key="", language="zh")._validate_styles(styles, 2)
        assert all(s["position"] == ["center", "bottom-80"] for s in result)

    def test_missing_entries_filled_from_position_pool(self):
        """缺失条目按循环位置池填充，保证不同条目分布在不同区域。"""
        result = Screenwriter(api_key="", language="zh")._validate_styles([], 4)
        assert [s["index"] for s in result] == [1, 2, 3, 4]
        positions = [s["position"] for s in result]
        # 池内前 4 个位置互不相同 → 无单调重复
        assert len({tuple(p) for p in positions}) == 4
        assert all(s["color"] == "white" and s["fontsize"] == 48 for s in result)

    def test_llm_style_method_falls_back_on_chat_failure(self, monkeypatch, tmp_path):
        """_chat_json 抛异常 → 使用 _fallback_styles（数量与字幕一致）。"""
        srt_file = tmp_path / "subs.srt"
        srt_file.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\n第一句字幕\n\n"
            "2\n00:00:03,500 --> 00:00:06,000\n第二句字幕\n",
            encoding="utf-8",
        )
        sw = Screenwriter(api_key="", language="zh")

        def boom(system_prompt, user_prompt):
            raise ValueError("LLM down")

        monkeypatch.setattr(sw, "_chat_json", boom)
        styles = sw.generate_subtitle_styles(str(srt_file), 768, 1152)
        assert len(styles) == 2
        assert all(s["color"] == "white" and s["fontsize"] == 48 for s in styles)
        # 两条字幕位置不同（循环 6 位置池）
        assert styles[0]["position"] != styles[1]["position"]

    def test_llm_style_accepts_wrapped_and_plain_list(self, monkeypatch, tmp_path):
        srt_file = tmp_path / "subs.srt"
        srt_file.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\n第一句字幕\n",
            encoding="utf-8",
        )
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(
            sw, "_chat_json",
            lambda s, u: {"styles": [{"index": 1, "position": ["center", "top+60"], "color": "gold", "fontsize": 56}]},
        )
        wrapped = sw.generate_subtitle_styles(str(srt_file), 768, 1152)
        assert wrapped[0]["fontsize"] == 56 and wrapped[0]["position"] == ["center", "top+60"]

        monkeypatch.setattr(
            sw, "_chat_json",
            lambda s, u: [{"index": 1, "position": ["right", "bottom-120"], "color": "white", "fontsize": 40}],
        )
        plain = sw.generate_subtitle_styles(str(srt_file), 768, 1152)
        assert plain[0]["position"] == ["right", "bottom-120"]

    def test_empty_srt_returns_empty(self, tmp_path):
        srt_file = tmp_path / "empty.srt"
        srt_file.write_text("", encoding="utf-8")
        sw = Screenwriter(api_key="", language="zh")
        assert sw.generate_subtitle_styles(str(srt_file), 768, 1152) == []


# ═══════════════════════════════════════════════
# 4. story.py mock LLM 方法
# ═══════════════════════════════════════════════

class TestSceneInfoExtraction:
    """extract_scene_info_from_idea（mock _chat_json）。"""

    def _make_sw(self):
        return Screenwriter(api_key="", language="zh")

    def test_success(self, monkeypatch):
        sw = self._make_sw()
        monkeypatch.setattr(
            sw, "_chat_json",
            lambda s, u: {"scene_count": 3, "durations": [5, 8, 12], "reasoning": "按情节拆分"},
        )
        result = sw.extract_scene_info_from_idea("测试创意", "写实")
        assert result == {"scene_count": 3, "durations": [5, 8, 12]}

    def test_durations_clamped_to_2_30(self, monkeypatch):
        sw = self._make_sw()
        monkeypatch.setattr(
            sw, "_chat_json",
            lambda s, u: {"scene_count": 3, "durations": [1, 25, 99], "reasoning": ""},
        )
        result = sw.extract_scene_info_from_idea("测试创意", "写实")
        assert result["durations"] == [2, 25, 30]

    def test_missing_durations_raises(self, monkeypatch):
        sw = self._make_sw()
        monkeypatch.setattr(sw, "_chat_json", lambda s, u: {"scene_count": 2, "reasoning": ""})
        with pytest.raises(RuntimeError, match="无法从创意描述中提取"):
            sw.extract_scene_info_from_idea("测试创意", "写实")

    def test_length_mismatch_raises(self, monkeypatch):
        sw = self._make_sw()
        monkeypatch.setattr(
            sw, "_chat_json",
            lambda s, u: {"scene_count": 3, "durations": [5, 8], "reasoning": ""},
        )
        with pytest.raises(RuntimeError, match="无法从创意描述中提取"):
            sw.extract_scene_info_from_idea("测试创意", "写实")


class TestDevelopStory:
    """develop_story：_xml_escape 防 prompt 注入。"""

    def test_idea_xml_escaped_in_user_prompt(self, monkeypatch):
        captured = {}

        def fake_chat(system_prompt, user_prompt):
            captured["user_prompt"] = user_prompt
            return "测试故事"

        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat", fake_chat)
        story = sw.develop_story('</idea><script>alert(1)</script>', style="写实")
        assert story == "测试故事"
        # 注入原文必须被 XML 转义（`</idea>` 为 prompt 模板自带闭合标签，属正常结构）
        assert "<script>" not in captured["user_prompt"]
        assert "&lt;/idea&gt;" in captured["user_prompt"]
        assert "&lt;script&gt;" in captured["user_prompt"]


class TestNarrationGeneration:
    """generate_narration_for_video：clean_narration_text 清洗 raw 输出。"""

    def test_raw_markdown_structure_cleaned(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(
            sw, "_chat",
            lambda s, u: "# 故事标题\n**受众**：16-35岁\n小河边\n\n第二句",
        )
        narration = sw.generate_narration_for_video(
            story="测试故事", scenes=["场景一", "场景二"], total_duration=10
        )
        assert narration == "小河边第二句"
        assert "#" not in narration and "**" not in narration

    def test_empty_raw_falls_back_to_empty(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat", lambda s, u: "")
        assert sw.generate_narration_for_video("测试故事", ["场景一"], 10) == ""


class TestPoetryScenesEndToEnd:
    """generate_poetry_scenes：mock _chat 返回行格式 → 解析为场景列表。"""

    def test_full_flow_parses_lines(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(
            sw, "_chat",
            lambda s, u: "床前明月光 | 月光洒落窗前\n疑是地上霜 | 地面泛起白霜",
        )
        scenes = sw.generate_poetry_scenes("床前明月光，疑是地上霜。", scene_count=2, total_duration=10)
        assert len(scenes) == 2
        assert scenes[0]["narration"] == "床前明月光"
        assert scenes[1]["scene_prompt"] == "地面泛起白霜"

    def test_prompt_language_follows_zh(self):
        """zh 语言下提示词为中文（含行格式示例）。"""
        sw = Screenwriter(api_key="", language="zh")
        sys_p, user = sw._poetry_scene_prompts("春眠不觉晓", 0, [], 10, "")
        assert "场景" in sys_p
        assert "春眠不觉晓" in user


# ═══════════════════════════════════════════════
# 5. manuscript_video.py 拆段算法（_split_text）
# ═══════════════════════════════════════════════

def _make_manuscript_pipeline(text: str) -> ManuscriptVideoPipeline:
    """构造最小可测实例：__new__ 绕过 __init__，注入纯内存 state + stub task_manager。"""
    pipeline = ManuscriptVideoPipeline.__new__(ManuscriptVideoPipeline)
    pipeline._state = ManuscriptVideoTask(manuscript_text=text)
    pipeline.task_manager = _StubTaskManager()
    return pipeline


class _StubTaskManager:
    def update_state(self, **kwargs):
        pass


class TestManuscriptSplitText:
    """稿件拆段：4 字/秒、5-12s 贪心合并、长句不拆、短段回并。"""

    def test_short_text_single_paragraph(self):
        pipeline = _make_manuscript_pipeline("你好。")
        paras = pipeline._split_text("你好。")
        assert len(paras) == 1
        assert paras[0].text == "你好。"

    def test_sentences_greedily_merged_within_12s(self):
        pipeline = _make_manuscript_pipeline("")
        # 每句 20 字 = 5s，两句 10s ≤ 12s → 合并为一段；三句 15s > 12s → 拆开
        text = "甲" * 19 + "。" + "乙" * 19 + "。" + "丙" * 19 + "。"
        paras = pipeline._split_text(text)
        assert len(paras) == 2
        assert paras[0].text == "甲" * 19 + "。" + "乙" * 19 + "。"
        assert paras[1].text == "丙" * 19 + "。"

    def test_long_sentence_kept_as_is(self):
        pipeline = _make_manuscript_pipeline("")
        long_sentence = "长" * 60 + "。"  # 61 字 = 15.25s > 12s
        paras = pipeline._split_text(long_sentence)
        assert len(paras) == 1
        assert paras[0].text == long_sentence

    def test_short_trailing_segment_merged_into_previous(self):
        pipeline = _make_manuscript_pipeline("")
        # 长句 15.25s 独立成段；尾句 2 字 0.5s < 5s → 回并到前一段
        text = "长" * 60 + "。" + "短。"
        paras = pipeline._split_text(text)
        assert len(paras) == 1
        assert paras[0].text == "长" * 60 + "。" + "短。"

    def test_newlines_split_blocks_but_sentences_merge_across(self):
        pipeline = _make_manuscript_pipeline("")
        text = "第一句。\n第二句。"  # 换行切块，但句子仍按时长合并
        paras = pipeline._split_text(text)
        assert len(paras) == 1
        assert paras[0].text == "第一句。第二句。"

    def test_empty_text_returns_empty_list(self):
        pipeline = _make_manuscript_pipeline("")
        assert pipeline._split_text("") == []

    def test_resume_reuses_existing_paragraphs(self):
        pipeline = _make_manuscript_pipeline("原文")
        pipeline._state.paragraphs = [ManuscriptParagraph(index=0, text="已存在段落")]
        paras = pipeline._split_text("原文")
        assert len(paras) == 1
        assert paras[0].text == "已存在段落"

    def test_paragraph_indices_sequential(self):
        pipeline = _make_manuscript_pipeline("")
        text = "甲" * 19 + "。" + "乙" * 19 + "。" + "丙" * 19 + "。"
        paras = pipeline._split_text(text)
        assert [p.index for p in paras] == [0, 1]


class TestFixDoubleUtf8:
    """BasePipeline.fix_double_utf8：双重 UTF-8 编码修复。"""

    def test_fixes_double_encoded_chinese(self):
        mojibake = "你好".encode("utf-8").decode("latin-1")
        assert BasePipeline.fix_double_utf8(mojibake) == "你好"

    def test_passthrough_normal_text(self):
        assert BasePipeline.fix_double_utf8("正常文本") == "正常文本"
        assert BasePipeline.fix_double_utf8("") == ""
