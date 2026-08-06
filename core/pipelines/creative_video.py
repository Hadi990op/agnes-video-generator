"""core.pipelines.creative_video — Creative 长视频流水线（兼容 re-export 模块）

v5.0 Batch 4（4.2）：实现迁移至 core.pipelines.creative/ 包，本模块保留
全部原符号供外部调用点（web/deps.py、core/pipelines/__init__.py、测试）零修改。

注意：mock 回归的 patch 目标已迁移到 core.pipelines.creative.pipeline 下的
AgnesVideoAPI/AgnesImageAPI（实例化发生在 pipeline.py 的 __init__）。"""

from core.pipelines.creative import (
    AudioStepsMixin,
    CreativeVideoPipeline,
    FramesStepsMixin,
    ScriptStepsMixin,
    VideoStepsMixin,
)

__all__ = [
    "CreativeVideoPipeline",
    "ScriptStepsMixin",
    "FramesStepsMixin",
    "VideoStepsMixin",
    "AudioStepsMixin",
]
