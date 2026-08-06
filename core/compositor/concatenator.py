"""core.compositor.concatenator — 视频拼接器（兼容 re-export 模块）

v5.0 Batch 4（4.3）：实现迁移至 core/compositor/concatenator/ 包，本模块保留
全部原符号供外部调用点（pipelines/tests）零修改。"""

from core.compositor.concatenator import (
    AudioOverlayMixin,
    ConcatMixin,
    VideoConcatenator,
)

__all__ = [
    "VideoConcatenator",
    "ConcatMixin",
    "AudioOverlayMixin",
]
