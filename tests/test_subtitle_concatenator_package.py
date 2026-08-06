"""
Subtitle / Concatenator 包拆分（v5.0 Batch 4 / 4.3）组合与 re-export 契约测试。

core/audio/subtitle.py → core/audio/subtitle/ 包（generator SRT 生成 + renderer
moviepy 叠加）；core/compositor/concatenator.py → core/compositor/concatenator/
包（concat 纯拼接 + audio_overlay 音频叠加）。本文件守护拆分契约：
- SubtitleGenerator / VideoConcatenator 经 mixin 组合后对外方法完整
  （17 个 / 7 个，与拆分前一致）；
- 各方法定义在正确的职责模块中（method ownership）；
- 模块级常量（6 个 / 4 个）原样保留，audio_overlay 经 .concat 复用常量；
- 旧模块路径 re-export 生效，外部调用点零改动；
- 关键行为（多行拆分、SRT 时间格式化、拼接方法存在性）不因拆分而改变。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.audio import subtitle as subtitle_legacy
from core.audio.subtitle import (
    SubtitleGenerator,
    SubtitleSrtMixin,
    SubtitleRenderMixin,
)
from core.audio.subtitle import generator as srt_generator
from core.audio.subtitle import renderer as subtitle_renderer
from core.compositor import concatenator as concatenator_legacy
from core.compositor.concatenator import (
    AudioOverlayMixin,
    ConcatMixin,
    VideoConcatenator,
)
from core.compositor.concatenator import audio_overlay as concat_audio_overlay
from core.compositor.concatenator import concat as concat_module


# ═══════════════════════════════════════════════
# 1. mixin 组合：全部原方法经 MRO 可用
# ═══════════════════════════════════════════════

_SUBTITLE_METHODS = [
    # generator.py（15）
    "_split_long_text", "_chunk_text", "enforce_max_lines", "cue_to_srt_time",
    "_cue_total_seconds", "_generate_fine_srt_from_word_cues", "_group_items_to_srt",
    "_detect_prominence", "_generate_scene_aware_srt", "_scene_char_ranges",
    "generate_cue_aware_srt", "cues_to_srt", "text_to_srt", "_parse_vtt_to_srt",
    "_parse_time",
    # renderer.py（2）
    "resolve_position", "overlay_subtitles_to_video",
]

_CONCATENATOR_METHODS = [
    # concat.py（5）
    "concat_videos", "_resolve_subtitle_position", "_parse_srt_to_clips",
    "_get_duration", "_run_ffmpeg",
    # audio_overlay.py（2）
    "concat_videos_with_audio_overlay", "composite_anchor_video",
]


def test_subtitle_composes_all_original_methods():
    """拆分后 SubtitleGenerator 仍具备拆分前全部 17 个方法。"""
    missing = [m for m in _SUBTITLE_METHODS if not hasattr(SubtitleGenerator, m)]
    assert not missing, f"missing methods after split: {missing}"


def test_concatenator_composes_all_original_methods():
    """拆分后 VideoConcatenator 仍具备拆分前全部 7 个方法。"""
    missing = [m for m in _CONCATENATOR_METHODS if not hasattr(VideoConcatenator, m)]
    assert not missing, f"missing methods after split: {missing}"


def test_mixin_classes_are_used_by_composed_classes():
    """两个主类的 MRO 都包含各自的全部职责 mixin。"""
    sub_mro = [c.__name__ for c in SubtitleGenerator.__mro__]
    for mixin in ("SubtitleSrtMixin", "SubtitleRenderMixin"):
        assert mixin in sub_mro, f"{mixin} not in SubtitleGenerator MRO"
    con_mro = [c.__name__ for c in VideoConcatenator.__mro__]
    for mixin in ("ConcatMixin", "AudioOverlayMixin"):
        assert mixin in con_mro, f"{mixin} not in VideoConcatenator MRO"


# ═══════════════════════════════════════════════
# 2. method ownership：方法定义在对应职责模块
# ═══════════════════════════════════════════════

def test_subtitle_method_ownership():
    """SRT 生成方法在 generator.py，moviepy 叠加方法在 renderer.py。"""
    for m in _SUBTITLE_METHODS[:15]:
        assert getattr(SubtitleGenerator, m).__module__ == "core.audio.subtitle.generator", m
    for m in _SUBTITLE_METHODS[15:]:
        assert getattr(SubtitleGenerator, m).__module__ == "core.audio.subtitle.renderer", m


def test_concatenator_method_ownership():
    """纯拼接方法在 concat.py，音频叠加方法在 audio_overlay.py。"""
    for m in _CONCATENATOR_METHODS[:5]:
        assert getattr(VideoConcatenator, m).__module__ == "core.compositor.concatenator.concat", m
    for m in _CONCATENATOR_METHODS[5:]:
        assert getattr(VideoConcatenator, m).__module__ == "core.compositor.concatenator.audio_overlay", m


# ═══════════════════════════════════════════════
# 3. 模块级常量保留 + audio_overlay 复用
# ═══════════════════════════════════════════════

def test_subtitle_constants_preserved():
    """6 个 SRT 生成常量原样保留在 generator 模块。"""
    assert srt_generator._MAX_SUB_DURATION == 1.8
    assert srt_generator._MAX_SUB_CHARS == 14
    assert srt_generator._MIN_WORD_CUES_FOR_FINE == 6
    assert srt_generator._PROMINENT_DURATION_MULTIPLIER == 1.4
    assert srt_generator._PROMINENT_MAX_CHARS == 12
    assert srt_generator._FINE_OVERLAP_SEC == 0.12


def test_concatenator_constants_preserved_and_shared():
    """4 个输出常量保留在 concat 模块，audio_overlay 经 .concat import 复用。"""
    assert concat_module._AUDIO_CODEC == "aac"
    assert concat_module._AUDIO_BITRATE == "192k"
    assert concat_module._AUDIO_FPS == 44100
    assert concat_module._VIDEO_FPS == 30
    assert concat_audio_overlay._AUDIO_BITRATE is concat_module._AUDIO_BITRATE
    assert concat_audio_overlay._VIDEO_FPS is concat_module._VIDEO_FPS


# ═══════════════════════════════════════════════
# 4. 旧模块路径 re-export（外部调用点零修改）
# ═══════════════════════════════════════════════

def test_legacy_module_reexports():
    """旧 module 路径 re-export 出同一 class 对象。"""
    assert subtitle_legacy.SubtitleGenerator is SubtitleGenerator
    assert concatenator_legacy.VideoConcatenator is VideoConcatenator


def test_pipeline_imports_still_resolve():
    """下游 pipelines 经旧路径 import 的组合类即新类。"""
    from core.pipelines.poetry_video import SubtitleGenerator as pg_sub
    from core.pipelines.creative.steps_audio import VideoConcatenator as sa_con
    from core.pipelines.anchor_video import VideoConcatenator as an_con
    assert pg_sub is SubtitleGenerator
    assert sa_con is VideoConcatenator
    assert an_con is VideoConcatenator


# ═══════════════════════════════════════════════
# 5. 关键行为不因拆分而改变
# ═══════════════════════════════════════════════

def test_split_long_text_behavior_unchanged():
    """多行拆分行为与拆分前一致。"""
    assert SubtitleGenerator._split_long_text("短视频", 14) == "短视频"
    assert SubtitleGenerator._split_long_text("", 14) == ""
    assert SubtitleGenerator._split_long_text("已有\n换行", 14) == "已有\n换行"
    assert SubtitleGenerator._split_long_text(
        "今天天气真好，我们一起去公园散步吧", 14
    ) == "今天天气真好，\n我们一起去公园散步吧"


def test_cue_to_srt_time_behavior_unchanged():
    """SRT 时间格式化行为不变。"""
    assert SubtitleGenerator.cue_to_srt_time(0.0) == "00:00:00,000"
    assert SubtitleGenerator.cue_to_srt_time(2.5) == "00:00:02,500"
    assert SubtitleGenerator.cue_to_srt_time(65.123) == "00:01:05,123"


def test_text_to_srt_structure(tmp_path):
    """text_to_srt 生成标准 SRT（序号 + 时间轴 + 正文）。"""
    out = tmp_path / "demo.srt"
    result = SubtitleGenerator.text_to_srt(
        "春天来了。", str(out), duration_sec=4.0
    )
    content = out.read_text(encoding="utf-8")
    assert result == str(out)
    assert content.startswith("1\n00:00:00,000 --> 00:00:03,")  # 原计算含毫秒舍入
    assert "春天来了。" in content


def test_cross_mixin_mro_resolution():
    """跨组方法调用经 MRO 解析（audio_overlay 方法使用 concat 组 helper）。"""
    # _run_ffmpeg（concat 组）可经组合类访问
    assert callable(VideoConcatenator._run_ffmpeg)
    assert callable(VideoConcatenator._parse_srt_to_clips)
    # renderer 组方法可用（即便调用方是 generator 组方法）
    assert callable(SubtitleGenerator.resolve_position)
    assert callable(SubtitleGenerator.overlay_subtitles_to_video)
