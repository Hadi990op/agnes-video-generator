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


# ══════════════════════════════════════════════════════════════════════
# Batch 6（S11）补充：空文本 / 路径 B 失败与开关 / 异常传播 / 参数透传
# ══════════════════════════════════════════════════════════════════════

@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_empty_text_without_placeholder_skips_tts(mock_silent_cls, mock_edge_cls, tmp_path):
    """空文本 + 无占位 → 直接返回 None，不落盘、不调用任何引擎。"""
    audio_path = str(tmp_path / "skip.mp3")

    result = await _TestPipeline(api_key="k", task_id="t5")._generate_audio_with_fallback(
        output_path=audio_path,
        text="",
        audio_config=AudioConfig(enabled=True),
        subtitle_config=SubtitleConfig(enabled=True, harvest_cues_when_audio_off=True),
        duration_sec=5.0,
    )

    mock_edge_cls.assert_not_called()
    mock_silent_cls.assert_not_called()
    assert result is None
    assert not os.path.exists(audio_path), "no file should be written for empty text"


@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_empty_text_with_placeholder_writes_silent(mock_silent_cls, mock_edge_cls, tmp_path):
    """空文本 + 有占位 → 占位文本直接 Silent 落盘，不调用 EdgeTTS。"""
    audio_path = str(tmp_path / "placeholder.mp3")
    mock_silent = mock_silent_cls.return_value
    mock_silent.generate = AsyncMock(side_effect=_fake_silent_generate)

    result = await _TestPipeline(api_key="k", task_id="t6")._generate_audio_with_fallback(
        output_path=audio_path,
        text="",
        audio_config=AudioConfig(enabled=True),
        subtitle_config=SubtitleConfig(),
        duration_sec=5.0,
        empty_placeholder="（静音）",
    )

    mock_edge_cls.assert_not_called()
    mock_silent.generate.assert_awaited_once()
    assert mock_silent.generate.call_args.kwargs["text"] == "（静音）"
    assert os.path.exists(audio_path)
    assert result is None


@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_audio_off_no_harvest_writes_silent_only(mock_silent_cls, mock_edge_cls, tmp_path):
    """音频关 + harvest_cues_when_audio_off=False → 仅 Silent 落盘，不 harvest。"""
    audio_path = str(tmp_path / "silent_only.mp3")
    mock_silent = mock_silent_cls.return_value
    mock_silent.generate = AsyncMock(side_effect=_fake_silent_generate)

    result = await _TestPipeline(api_key="k", task_id="t7")._generate_audio_with_fallback(
        output_path=audio_path,
        text="你好世界",
        audio_config=AudioConfig(enabled=False),
        subtitle_config=SubtitleConfig(enabled=True, harvest_cues_when_audio_off=False),
        duration_sec=5.0,
    )

    mock_edge_cls.assert_not_called()
    mock_silent.generate.assert_awaited_once()
    assert result is None


@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_harvest_cues_failure_falls_back_to_silent(mock_silent_cls, mock_edge_cls, tmp_path):
    """路径 B：harvest_cues 抛 RuntimeError → 仅警告，仍 Silent 落盘，返回 None。"""
    audio_path = str(tmp_path / "harvest_fail.mp3")
    mock_edge = mock_edge_cls.return_value
    mock_edge.harvest_cues = AsyncMock(side_effect=RuntimeError("harvest boom"))
    mock_silent = mock_silent_cls.return_value
    mock_silent.generate = AsyncMock(side_effect=_fake_silent_generate)

    result = await _TestPipeline(api_key="k", task_id="t8")._generate_audio_with_fallback(
        output_path=audio_path,
        text="你好世界",
        audio_config=AudioConfig(enabled=False),
        subtitle_config=SubtitleConfig(enabled=True, harvest_cues_when_audio_off=True),
        duration_sec=5.0,
    )

    mock_edge.harvest_cues.assert_awaited_once()
    mock_silent.generate.assert_awaited_once()
    assert os.path.exists(audio_path)
    assert result is None


@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_edge_success_with_none_submaker_returns_none(mock_silent_cls, mock_edge_cls, tmp_path):
    """Edge 成功但 sub_maker 为 None → 直接返回 None，不降级 Silent。"""
    audio_path = str(tmp_path / "no_submaker.mp3")
    mock_edge = mock_edge_cls.return_value
    mock_edge.generate = AsyncMock(return_value=(audio_path, None))
    mock_silent = mock_silent_cls.return_value
    mock_silent.generate = AsyncMock(side_effect=_fake_silent_generate)

    result = await _TestPipeline(api_key="k", task_id="t9")._generate_audio_with_fallback(
        output_path=audio_path,
        text="你好世界",
        audio_config=AudioConfig(enabled=True),
        subtitle_config=SubtitleConfig(),
        duration_sec=5.0,
    )

    mock_edge.generate.assert_awaited_once()
    mock_silent.generate.assert_not_called()
    assert result is None


@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_non_runtime_error_propagates(mock_silent_cls, mock_edge_cls, tmp_path):
    """EdgeTTS 抛非 RuntimeError（如 ValueError）→ 不降级，异常向上传播。"""
    audio_path = str(tmp_path / "boom.mp3")
    mock_edge = mock_edge_cls.return_value
    mock_edge.generate = AsyncMock(side_effect=ValueError("unexpected"))
    mock_silent = mock_silent_cls.return_value
    mock_silent.generate = AsyncMock(side_effect=_fake_silent_generate)

    with pytest.raises(ValueError, match="unexpected"):
        await _TestPipeline(api_key="k", task_id="t10")._generate_audio_with_fallback(
            output_path=audio_path,
            text="你好世界",
            audio_config=AudioConfig(enabled=True),
            subtitle_config=SubtitleConfig(),
            duration_sec=5.0,
        )

    mock_silent.generate.assert_not_called()
    assert not os.path.exists(audio_path)


@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_edge_failure_without_duration_omits_kwarg(mock_silent_cls, mock_edge_cls, tmp_path):
    """Edge 失败 + duration_sec=0 → Silent 调用不带 duration_sec 参数。"""
    audio_path = str(tmp_path / "no_dur.mp3")
    mock_edge = mock_edge_cls.return_value
    mock_edge.generate = AsyncMock(side_effect=RuntimeError("edge boom"))
    mock_silent = mock_silent_cls.return_value
    mock_silent.generate = AsyncMock(side_effect=_fake_silent_generate)

    await _TestPipeline(api_key="k", task_id="t11")._generate_audio_with_fallback(
        output_path=audio_path,
        text="你好世界",
        audio_config=AudioConfig(enabled=True),
        subtitle_config=SubtitleConfig(),
        duration_sec=0.0,
    )

    assert "duration_sec" not in mock_silent.generate.call_args.kwargs


@patch("core.audio.tts.EdgeTTSEngine")
@patch("core.audio.tts.SilentTTSEngine")
async def test_voice_and_rate_passed_to_edge(mock_silent_cls, mock_edge_cls, tmp_path):
    """EdgeTTS 调用透传 audio_config 的 voice/rate。"""
    audio_path = str(tmp_path / "voice.mp3")
    fake_cues = _FakeSubMaker(cues=[{"start": 0.0, "end": 1.0, "content": "你"}])
    mock_edge = mock_edge_cls.return_value
    mock_edge.generate = AsyncMock(return_value=(audio_path, fake_cues))
    mock_silent = mock_silent_cls.return_value
    mock_silent.generate = AsyncMock(side_effect=_fake_silent_generate)

    await _TestPipeline(api_key="k", task_id="t12")._generate_audio_with_fallback(
        output_path=audio_path,
        text="Hello world",
        audio_config=AudioConfig(enabled=True, voice="en-US-JennyNeural", rate="+10%"),
        subtitle_config=SubtitleConfig(),
        duration_sec=5.0,
    )

    call_kwargs = mock_edge.generate.call_args.kwargs
    assert call_kwargs["voice"] == "en-US-JennyNeural"
    assert call_kwargs["rate"] == "+10%"
