"""Web 层路由包（Batch 1：从 server.py 单体拆分）。

模块划分：
- app_state.py          应用级全局状态（并发控制、活动任务、生命周期事件）
- helpers.py            纯工具函数（字幕解析、音色校验、时长提取等）
- deps.py               共享依赖（Pipeline 工厂、执行器）
- routes/*.py           按域拆分的 APIRouter 模块

server.py 仅保留：app 组装（include_router）+ lifespan + 启动入口 + 兼容 re-export。
"""
