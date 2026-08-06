"""core.audio.subtitle — SRT 字幕生成 + moviepy 叠加（v5.0 Batch 4 / 4.3 拆分后的包入口）

SubtitleGenerator 由两个职责 mixin（SubtitleSrtMixin / SubtitleRenderMixin）
组合而成；对外保留全部原符号（subtitle.py 兼容 re-export）。"""

import logging

from .generator import SubtitleSrtMixin
from .renderer import SubtitleRenderMixin

logger = logging.getLogger(__name__)


class SubtitleGenerator(
    SubtitleSrtMixin,
    SubtitleRenderMixin,
):

    """字幕生成器：cues → SRT + moviepy 叠加。"""


from . import generator as srt_generator
from . import renderer as subtitle_renderer

# 运行时注入：mixin 方法内显式 `SubtitleGenerator.xxx` 自引用
# （原 @staticmethod 风格）在模块级延迟解析到组合类。
srt_generator.SubtitleGenerator = SubtitleGenerator
subtitle_renderer.SubtitleGenerator = SubtitleGenerator

__all__ = [
    "SubtitleGenerator",
    "SubtitleSrtMixin",
    "SubtitleRenderMixin",
]

