"""
Agnes Video Generator — FastAPI 服务层（Batch 1 模块化后）。

路由已拆分到 ``web/routes/``（8 个 APIRouter 模块），本文件仅保留：
- app 组装（include_router 汇总）+ 静态资源挂载
- lifespan 生命周期（初始化运行时状态 + 预加载音色目录）
- 启动入口（uvicorn + 优雅退出）
- 兼容 re-export（供旧代码 / 测试从 ``server`` 导入）

任务类型路由（见 web/routes/task_creation_routes.py）：
- POST /api/tasks/simple      — 简单视频生成
- POST /api/tasks/creative    — 创意长视频生成
- POST /api/tasks/manuscript  — 稿件长视频生成
- POST /api/tasks/poetry     — 诗词视频生成
- POST /api/tasks/anchor     — 数字人口播生成
- POST /api/tasks             — 向后兼容（映射到 creative）
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.audio.voices import load_voice_catalog
from web import app_state
from web.app_state import init_runtime_state
from web.routes import (
    config_routes,
    image_routes,
    task_creation_routes,
    task_routes,
    utility_routes,
    video_routes,
    voice_routes,
    workspace_routes,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化工作目录 / uploads / 错误收集根路径，并重置上次异常退出的遗留任务
    init_runtime_state()

    # v4.0: 预加载音色目录（edge_tts.list_voices），失败不阻断启动
    try:
        await load_voice_catalog()
        logger.info("[Startup] Voice catalog loaded")
    except Exception as e:
        logger.warning(f"[Startup] Voice catalog load failed ({e}); will use fallback")

    # v5.0 (5.1): 可选启动时僵尸任务清理（AGNES_SWEEP_AGE_DAYS 设置后启用，失败不阻断）
    sweep_days = os.environ.get("AGNES_SWEEP_AGE_DAYS", "").strip()
    if sweep_days.isdigit():
        try:
            from core.artifacts import sweep_stale_tasks
            result = sweep_stale_tasks(age_days=int(sweep_days))
            logger.info(f"[Startup] Stale task sweep: "
                        f"swept={result['swept']}, protected={len(result['protected'])}")
        except Exception as e:
            logger.warning(f"[Startup] Stale task sweep failed ({e})")

    yield


app = FastAPI(title="Agnes Video Generator", lifespan=lifespan)


# ═══════════════════════════════════════════════════
# Static files
# ═══════════════════════════════════════════════════

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ═══════════════════════════════════════════════════
# 路由汇总（Batch 1 拆分）
# ═══════════════════════════════════════════════════

app.include_router(utility_routes.router)
app.include_router(config_routes.router)
app.include_router(workspace_routes.router)
app.include_router(voice_routes.router)
app.include_router(image_routes.router)
app.include_router(video_routes.router)
app.include_router(task_routes.router)
app.include_router(task_creation_routes.router)


# ═══════════════════════════════════════════════════
# 兼容 re-export（旧代码 / tests/test_core.py 从 server 导入）
# ═══════════════════════════════════════════════════

from web.helpers import (  # noqa: E402
    _build_position,
    _has_explicit_duration,
    _parse_bg_color,
    _parse_duration,
    get_upload_dir,
)
from web.app_state import (  # noqa: E402
    MAX_CONCURRENT_WEIGHT,
    TASK_TYPE_WEIGHTS,
    WeightedSemaphore,
    _AGNES_RATE_LIMIT,
    _pipeline_semaphore,
    _queued_tasks,
    active_pipelines,
    background_tasks,
    shutdown_event,
)
from web.deps import (  # noqa: E402
    _create_pipeline_for_type,
    _run_pipeline,
    _run_pipeline_with_concurrency,
)


# ═══════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    # 允许通过环境变量覆盖监听地址/端口（npm 启动器 free-short-video 会注入）
    # 默认值保持向后兼容：0.0.0.0:8765
    _HOST = os.environ.get("HOST", "0.0.0.0")
    _PORT = int(os.environ.get("PORT", "8765"))
    config = uvicorn.Config(app, host=_HOST, port=_PORT, log_level="info")
    server = uvicorn.Server(config)

    original_handle_exit = server.handle_exit

    def _handle_exit(sig, frame):
        if shutdown_event.is_set():
            logger.warning("Force exiting...")
            os._exit(1)
        logger.info("Shutting down gracefully (Ctrl+C again to force)...")
        shutdown_event.set()
        if callable(original_handle_exit):
            original_handle_exit(sig, frame)

    server.handle_exit = _handle_exit
    server.run()
