"""core.audio.subtitle — SRT 字幕生成 + moviepy 叠加（兼容 re-export 模块）

v5.0 Batch 4（4.3）：实现迁移至 core/audio/subtitle/ 包，本模块保留
全部原符号供外部调用点（pipelines/tests）零修改。"""

from core.audio.subtitle import (
    SubtitleGenerator,
    SubtitleRenderMixin,
    SubtitleSrtMixin,
)

__all__ = [
    "SubtitleGenerator",
    "SubtitleSrtMixin",
    "SubtitleRenderMixin",
]
