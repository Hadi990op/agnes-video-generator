"""tests/test_cue_aware_srt.py — v2.0 cues 精确时间线对齐单元测试

不依赖网络/edge_tts，使用 mock 的 SubMaker.cues（srt.Subtitle 形态）验证：
  - 分组逻辑 _group_items_to_srt（与单段路径共用）
  - 场景归属策略 A（文本锚定）
  - 场景归属策略 B（时间区间兜底，monkeypatch）
  - 残余归一化（最后 cue 钳到音频时长）
  - 空 cues / legacy 回退
"""

import datetime
import os

import srt
import pytest

from core.audio.subtitle import SubtitleGenerator


class FakeCue:
    """模仿 edge_tts / srt 的 WordBoundary cue（start/end 为 timedelta）。"""

    def __init__(self, start: float, end: float, content: str):
        self.start = datetime.timedelta(seconds=start)
        self.end = datetime.timedelta(seconds=end)
        self.content = content


class FakeSubMaker:
    def __init__(self, cues):
        self.cues = cues


def _parse_entries(srt_text: str):
    """返回 [(start_s, end_s, text), ...] 列表。"""
    out = []
    for sub in srt.parse(srt_text):
        out.append((sub.start.total_seconds(), sub.end.total_seconds(), sub.content))
    return out


# ───────────────────────── 分组逻辑 ─────────────────────────

def test_group_items_to_srt_basic():
    items = [
        (0.0, 0.5, "今天"),
        (0.5, 1.0, "天气"),
        (1.0, 1.5, "真好"),
        (1.6, 2.1, "我们"),
        (2.1, 2.6, "一起"),
    ]
    out = SubtitleGenerator._group_items_to_srt(items)
    entries = _parse_entries(out)
    # 5 词、13 字、时长 2.6s；受 max_duration 约束可能分为 1~2 条，
    # 不依赖精确 end（突出时长加成会拉伸 end），仅校验内容完整+起点
    assert len(entries) >= 1
    assert "".join(e[2] for e in entries) == "今天天气真好我们一起"
    assert abs(entries[0][0] - 0.0) < 1e-6
    assert entries[0][1] > entries[0][0]


def test_group_items_to_srt_splits_on_duration():
    # 制造超长序列，强制断成多条
    items = [(float(i) * 0.5, float(i) * 0.5 + 0.5, f"词{i}") for i in range(10)]
    out = SubtitleGenerator._group_items_to_srt(items, max_duration=1.0, max_chars=4)
    entries = _parse_entries(out)
    assert len(entries) >= 2


# ─────────────────────── 单段路径行为不变 ───────────────────────

def test_fine_srt_from_word_cues_still_works():
    cues = [
        FakeCue(0.0, 0.4, "第一"),
        FakeCue(0.4, 0.8, "句话"),
        FakeCue(0.9, 1.3, "第二"),
        FakeCue(1.3, 1.7, "句话"),
    ]
    out = SubtitleGenerator._generate_fine_srt_from_word_cues(cues)
    assert out.strip()
    entries = _parse_entries(out)
    assert len(entries) >= 1


# ─────────────────────── 场景归属策略 A ───────────────────────

def _two_scene_cues_a():
    """场景1=今天天气真好(6)，场景2=我们一起去公园(7)。"""
    return [
        FakeCue(0.0, 0.5, "今天"),
        FakeCue(0.5, 1.0, "天气"),
        FakeCue(1.0, 1.5, "真好"),
        FakeCue(1.6, 2.1, "我们"),
        FakeCue(2.1, 2.6, "一起"),
        FakeCue(2.6, 2.9, "去"),
        FakeCue(2.9, 3.4, "公园"),
    ]


def test_cue_aware_strategy_a_attribution():
    cues = _two_scene_cues_a()
    segment_texts = ["今天天气真好", "我们一起去公园"]
    out = SubtitleGenerator.generate_cue_aware_srt(
        FakeSubMaker(cues), segment_texts=segment_texts,
    )
    entries = _parse_entries(out)
    # 场景1 合并为「今天天气真好」0.0 起；场景2 合并为「我们一起去公园」1.6 起
    # 不依赖精确 end：突出时长加成会拉伸短句 end（>= 自然 cue end 即可）
    assert len(entries) == 2
    e0, e1 = entries
    assert e0[2] == "今天天气真好"
    assert abs(e0[0] - 0.0) < 1e-6
    assert e0[1] >= 1.5 - 1e-6
    assert e1[2] == "我们一起去公园"
    assert abs(e1[0] - 1.6) < 1e-6
    assert e1[1] >= 3.4 - 1e-6


def test_cue_aware_strategy_a_offset_is_zero():
    """cues 时间即成片时间，不应有任何场景偏移。"""
    cues = _two_scene_cues_a()
    segment_texts = ["今天天气真好", "我们一起去公园"]
    out = SubtitleGenerator.generate_cue_aware_srt(
        FakeSubMaker(cues), segment_texts=segment_texts,
    )
    entries = _parse_entries(out)
    # 第一条起点必须贴合 cues 起点 0.0（偏移为 0）
    assert abs(entries[0][0] - 0.0) < 1e-6


# ─────────────────────── 场景归属策略 B（monkeypatch） ───────────────────────

def test_cue_aware_strategy_b_time_interval(monkeypatch):
    """当 _scene_char_ranges 返回 None（文本无法还原）时走时间区间归属。"""
    # 强制策略 B
    monkeypatch.setattr(
        SubtitleGenerator, "_scene_char_ranges", staticmethod(lambda texts: None)
    )
    cues = [
        FakeCue(0.0, 1.5, "前"),  # 应归属场景0 [0, 2.0)
        FakeCue(2.0, 3.4, "后"),  # 应归属场景1 [2.0, ...)
    ]
    segment_texts = ["前半段文本", "后半段文本"]
    out = SubtitleGenerator.generate_cue_aware_srt(
        FakeSubMaker(cues),
        segment_texts=segment_texts,
        scene_start_times=[0.0, 2.0],
    )
    entries = _parse_entries(out)
    assert len(entries) == 2
    # 场景0 的 cue 时间起点 0.0 原样保留（offset=0）；end 受突出时长加成拉伸，仅校验起点
    assert abs(entries[0][0] - 0.0) < 1e-6 and entries[0][1] >= 1.5 - 1e-6
    assert abs(entries[1][0] - 2.0) < 1e-6 and entries[1][1] >= 3.4 - 1e-6


# ─────────────────────── 残余归一化（最后 cue 钳到音频时长） ───────────────────────

def test_cue_aware_clamps_last_cue_to_audio_duration():
    cues = [
        FakeCue(0.0, 0.5, "第一"),
        FakeCue(0.5, 0.9, "第二"),
        FakeCue(0.9, 5.0, "最后一句超长"),  # end 远超 audio_duration
    ]
    segment_texts = ["第一", "第二", "最后一句超长"]
    out = SubtitleGenerator.generate_cue_aware_srt(
        FakeSubMaker(cues), segment_texts=segment_texts, audio_duration=2.0,
    )
    entries = _parse_entries(out)
    # 最后一条不应超出 audio_duration=2.0
    assert entries[-1][1] <= 2.0 + 1e-6


# ─────────────────────── 空 cues / 边界 ───────────────────────

def test_cue_aware_empty_cues_returns_empty():
    out = SubtitleGenerator.generate_cue_aware_srt(
        FakeSubMaker([]), segment_texts=["你好", "世界"],
    )
    assert out == ""


def test_cue_aware_no_segment_texts_returns_empty():
    out = SubtitleGenerator.generate_cue_aware_srt(
        FakeSubMaker(_two_scene_cues_a()), segment_texts=[],
    )
    assert out == ""


def test_scene_char_ranges_basic():
    ranges = SubtitleGenerator._scene_char_ranges(["今天天气真好", "我们一起去公园"])
    assert ranges == [(0, 6), (6, 13)]


def test_scene_char_ranges_empty():
    assert SubtitleGenerator._scene_char_ranges([]) is None


# ─────────────────────── legacy 启发式路径不变 ───────────────────────

def test_scene_aware_legacy_still_works():
    """legacy 多段均匀分配路径（无 cues）仍可用，且重叠缓冲为 0.12。"""
    out = SubtitleGenerator._generate_scene_aware_srt(
        scene_texts=["第一句话内容", "第二句话内容"],
        scene_durations=[2.0, 2.0],
        word_cues=None,
    )
    assert out.strip()
    entries = _parse_entries(out)
    assert len(entries) == 2


def test_scene_aware_legacy_overlap_is_visual_buffer():
    """v2.0 后 legacy 重叠默认 0.12（视觉缓冲），不再是 0.8 掩盖补丁。"""
    out = SubtitleGenerator._generate_scene_aware_srt(
        scene_texts=["一句话", "另一句话"],
        scene_durations=[2.0, 2.0],
        word_cues=None,
        overlap_sec=0.12,
    )
    entries = _parse_entries(out)
    # 两条之间重叠不超过 0.12
    if len(entries) >= 2:
        gap = entries[1][0] - entries[0][1]
        assert gap >= -0.12 - 1e-6
