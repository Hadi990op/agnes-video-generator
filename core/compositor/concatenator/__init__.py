"""core.compositor.concatenator — 视频拼接器（v5.0 Batch 4 / 4.3 拆分后的包入口）

VideoConcatenator 由两个职责 mixin（ConcatMixin / AudioOverlayMixin）
组合而成；对外保留全部原符号（concatenator.py 兼容 re-export）。"""

import logging

from .audio_overlay import AudioOverlayMixin
from .concat import ConcatMixin

logger = logging.getLogger(__name__)


class VideoConcatenator(
    ConcatMixin,
    AudioOverlayMixin,
):

    """视频拼接器：纯拼接 + 带音频合成拼接。"""


from . import audio_overlay
from . import concat as concat_module

# 运行时注入：mixin 方法内显式 `VideoConcatenator.xxx` 自引用
# （原 @staticmethod 风格）在模块级延迟解析到组合类。
concat_module.VideoConcatenator = VideoConcatenator
audio_overlay.VideoConcatenator = VideoConcatenator

__all__ = [
    "VideoConcatenator",
    "ConcatMixin",
    "AudioOverlayMixin",
]

