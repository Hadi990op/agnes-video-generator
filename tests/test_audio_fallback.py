"""tests.test_audio_fallback — Batch 2（S2）共享音频降级方法行为对照用例

锁定 BasePipeline._generate_audio_with_fallback 的降级行为矩阵：
    1. Edge 失败 → Silent 落盘，返回 None
    2. Edge 成功但无 cues → 返回 None（字幕回退 legacy 启发式）
    3. 音频关 + 字幕开 + harvest_cues_when_audio_off → harvest_cues + Silent 落盘
    4. Edge 成功且有 cues → 返回 sub_maker

注意：本文件位于 tests/ 顶层，不受 tests/mock_regression/conftest.py 的
autouse mock 影响，故直接使用 unittest.mock.patch 模拟引擎。
"""

import os

from unittest.mock import AsyncMock, patch

import pytest

from core.pipelines import BasePipeline
from models.task import AudioConfig, SubtitleConfig


class _FakeSubMaker:
    """最小化 SubMaker：仅含 .cues。"""

    def __init__(self, cues):
        self.cues = cues


class _TestPipeline(BasePipeline):
    """最小化具体子类（仅实现抽象 run）。"""

    async def run(self, state):
        return ""


async def _fake_silent_generate(text, output_path, voice="zh-CN-XiaoxiaoNeural",
                                rate="+0%", duration_sec=None):
    """模拟 SilentTTSEngine.generate：真实落盘小文件，返回 (path, None)。"""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(b"\x00")
    return output_path, None


@pytest.fixture
def pipeline():
    return _TestPipeline(api_key="mock_key", task_id="test_audio_fallback")


# ══════════════════════════════════════════════════════════════════════
# 用例 1：EdgeTTS 抛 RuntimeError → 降级 Silent 落盘，返回 None
# ══════════════════════════════════════════════════════════════════════

@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_edge_failure_falls_back_to_silent(mock_silent_cls, mock_edge_cls, tmp_path):
    audio_path = str(tmp_path / "narration.mp3")

    mock_edge = mock_edge_cls.return_value
    mock_edge.generate = AsyncMock(side_effect=RuntimeError("edge tts boom"))
    mock_silent = mock_silent_cls.return_value
    mock_silent.generate = AsyncMock(side_effect=_fake_silent_generate)

    result = await _TestPipeline(api_key="k", task_id="t1")._generate_audio_with_fallback(
        output_path=audio_path,
        text="你好世界",
        audio_config=AudioConfig(enabled=True),
        subtitle_config=SubtitleConfig(),
        duration_sec=5.0,
    )

    mock_edge.generate.assert_awaited_once()
    mock_silent.generate.assert_awaited_once()
    call_kwargs = mock_silent.generate.call_args.kwargs
    assert call_kwargs["output_path"] == audio_path
    assert call_kwargs["duration_sec"] == 5.0
    assert os.path.exists(audio_path), "silent fallback should write the audio file"
    assert result is None


# ══════════════════════════════════════════════════════════════════════
# 用例 2：EdgeTTS 成功但无 cues → 返回 None（字幕回退 legacy），不落 Silent
# ══════════════════════════════════════════════════════════════════════

@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_edge_success_without_cues_returns_none(mock_silent_cls, mock_edge_cls, tmp_path):
    audio_path = str(tmp_path / "narration.mp3")

    mock_edge = mock_edge_cls.return_value
    mock_edge.generate = AsyncMock(return_value=(audio_path, _FakeSubMaker(cues=[])))
    mock_silent = mock_silent_cls.return_value
    mock_silent.generate = AsyncMock(side_effect=_fake_silent_generate)

    result = await _TestPipeline(api_key="k", task_id="t2")._generate_audio_with_fallback(
        output_path=audio_path,
        text="你好世界",
        audio_config=AudioConfig(enabled=True),
        subtitle_config=SubtitleConfig(),
        duration_sec=5.0,
    )

    mock_edge.generate.assert_awaited_once()
    # 空 cues → legacy 启发式：不降级 Silent，直接返回 None
    mock_silent.generate.assert_not_called()
    assert result is None


# ══════════════════════════════════════════════════════════════════════
# 用例 3：音频关 + 字幕开 + harvest_cues_when_audio_off → harvest + Silent 落盘
# ══════════════════════════════════════════════════════════════════════

@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_audio_off_subtitle_on_harvests_cues(mock_silent_cls, mock_edge_cls, tmp_path):
    audio_path = str(tmp_path / "narration.mp3")
    fake_cues = _FakeSubMaker(cues=[{"start": 0.0, "end": 1.0, "content": "你"}])

    mock_edge = mock_edge_cls.return_value
    mock_edge.harvest_cues = AsyncMock(return_value=fake_cues)
    mock_silent = mock_silent_cls.return_value
    mock_silent.generate = AsyncMock(side_effect=_fake_silent_generate)

    result = await _TestPipeline(api_key="k", task_id="t3")._generate_audio_with_fallback(
        output_path=audio_path,
        text="你好世界",
        audio_config=AudioConfig(enabled=False),
        subtitle_config=SubtitleConfig(enabled=True, harvest_cues_when_audio_off=True),
        duration_sec=5.0,
    )

    mock_edge.harvest_cues.assert_awaited_once()
    mock_edge.generate.assert_not_called()
    mock_silent.generate.assert_awaited_once()
    assert os.path.exists(audio_path), "silent placeholder should be written for compositing"
    assert result is fake_cues


# ══════════════════════════════════════════════════════════════════════
# 用例 4（补充）：音频开 + EdgeTTS 成功且有 cues → 返回 sub_maker，不落 Silent
# ══════════════════════════════════════════════════════════════════════

@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_edge_success_with_cues_returns_sub_maker(mock_silent_cls, mock_edge_cls, tmp_path):
    audio_path = str(tmp_path / "narration.mp3")
    fake_cues = _FakeSubMaker(cues=[{"start": 0.0, "end": 1.0, "content": "你"}])

    mock_edge = mock_edge_cls.return_value
    mock_edge.generate = AsyncMock(return_value=(audio_path, fake_cues))
    mock_silent = mock_silent_cls.return_value
    mock_silent.generate = AsyncMock(side_effect=_fake_silent_generate)

    result = await _TestPipeline(api_key="k", task_id="t4")._generate_audio_with_fallback(
        output_path=audio_path,
        text="你好世界",
        audio_config=AudioConfig(enabled=True),
        subtitle_config=SubtitleConfig(),
        duration_sec=5.0,
    )

    mock_edge.generate.assert_awaited_once()
    mock_silent.generate.assert_not_called()
    assert result is fake_cues
