"""tests.mock_regression.conftest — pytest 全局 fixtures

自动注入 mock API 替换，确保所有测试无外部网络调用。

Mock 策略：替换类定义（不是实例），使所有地方的 `ClassName()` 都创建 mock 对象。
"""

import os
import sys
import pytest
import logging

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from .mock_apis import (
    MockAgnesVideoAPI,
    MockAgnesImageAPI,
    MockAgnesChatAPI,
    MockEdgeTTSEngine,
    MockRateLimiter,
)

logging.basicConfig(level=logging.WARNING)


# ══════════════════════════════════════════════════════════════════════
# Core API 类的 mock 替换
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def mock_video_api(monkeypatch):
    """替换 AgnesVideoAPI 为 mock 版本（覆盖所有导入位置）。"""
    paths = [
        "core.api.agnes_video.AgnesVideoAPI",
        "core.pipelines.simple_video.AgnesVideoAPI",
        "core.pipelines.creative_video.AgnesVideoAPI",
        "core.pipelines.manuscript_video.AgnesVideoAPI",
        "core.pipelines.anchor_video.AgnesVideoAPI",
        "core.pipelines.poetry_video.AgnesVideoAPI",
    ]
    for p in paths:
        monkeypatch.setattr(p, MockAgnesVideoAPI)


@pytest.fixture(autouse=True)
def mock_image_api(monkeypatch):
    """替换 AgnesImageAPI 为 mock 版本。"""
    paths = [
        "core.api.agnes_image.AgnesImageAPI",
        "core.pipelines.creative_video.AgnesImageAPI",
        "core.pipelines.anchor_video.AgnesImageAPI",
    ]
    for p in paths:
        monkeypatch.setattr(p, MockAgnesImageAPI)


@pytest.fixture(autouse=True)
def mock_chat_api(monkeypatch):
    """替换 AgnesChatAPI 为 mock 版本。"""
    paths = [
        "core.api.agnes_chat.AgnesChatAPI",
        "core.screenwriter.AgnesChatAPI",
    ]
    for p in paths:
        monkeypatch.setattr(p, MockAgnesChatAPI)


@pytest.fixture(autouse=True)
def mock_edge_tts(monkeypatch):
    """替换 EdgeTTSEngine 为 mock 版本（内部用 SilentTTSEngine）。

    需要 patch 所有 pipeline 中直接 import EdgeTTSEngine 的位置。
    """
    paths = [
        "core.audio.tts.EdgeTTSEngine",
        "core.pipelines.manuscript_video.EdgeTTSEngine",
        "core.pipelines.creative_video.EdgeTTSEngine",
        "core.pipelines.anchor_video.EdgeTTSEngine",
        "core.pipelines.poetry_video.EdgeTTSEngine",
    ]
    for p in paths:
        monkeypatch.setattr(p, MockEdgeTTSEngine)


@pytest.fixture(autouse=True)
def mock_rate_limiter(monkeypatch):
    """禁用全局限速器。"""
    paths = [
        "core.api.rate_limiter.get_rate_limiter",
        "core.api.agnes_video.get_rate_limiter",
        "core.api.agnes_chat.get_rate_limiter",
        "core.api.agnes_image.get_rate_limiter",
    ]
    for p in paths:
        monkeypatch.setattr(p, lambda: MockRateLimiter())


# ══════════════════════════════════════════════════════════════════════
# 测试 fixtures
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def temp_workdir(tmp_path):
    """临时工作目录，测试结束后自动清理。"""
    workdir = tmp_path / "agnes_test"
    workdir.mkdir()
    return str(workdir)


@pytest.fixture
def mock_api_key():
    """Mock API Key。"""
    return "mock_api_key_12345"
