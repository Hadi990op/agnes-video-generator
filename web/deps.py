"""Web 层共享依赖（Batch 1 从 server.py 拆出）。

Pipeline 工厂与执行器：任务创建 / resume 端点共同依赖的
「按 task_type 构建 Pipeline」与「并发受控的后台执行」逻辑。
"""
from __future__ import annotations

import asyncio
import logging

from core.config import get_selected_models
from core.pipelines import (
    AnchorPipeline,
    BasePipeline,
    CreativeVideoPipeline,
    ManuscriptVideoPipeline,
    PipelineShutdown,
    PoetryVideoPipeline,
    SimpleVideoPipeline,
)
from core.task_manager import TaskManager
from models.task import BaseTaskState, StepStatus, TaskType

from web import app_state

logger = logging.getLogger(__name__)


def create_pipeline_for_type(
    task_type: TaskType,
    api_key: str,
    task_id: str,
    dir_name: str,
) -> BasePipeline:
    """根据任务类型创建对应的 Pipeline 实例。

    从配置读取选中的模型（文本/图像/视频），注入各 Pipeline，
    使界面选择的模型生效。
    """
    models = get_selected_models()
    text_model = models["text"]
    image_model = models["image"]
    video_model = models["video"]
    shutdown_event = app_state.shutdown_event

    if task_type == TaskType.SIMPLE:
        return SimpleVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            chat_model=text_model,
            image_model=image_model,
            video_model=video_model,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.MANUSCRIPT:
        return ManuscriptVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            chat_model=text_model,
            image_model=image_model,
            video_model=video_model,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.ANCHOR:
        return AnchorPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            chat_model=text_model,
            image_model=image_model,
            video_model=video_model,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.POETRY:
        return PoetryVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            chat_model=text_model,
            video_model=video_model,
            shutdown_event=shutdown_event,
        )
    else:
        # CREATIVE（默认）
        return CreativeVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            chat_model=text_model,
            image_model=image_model,
            video_model=video_model,
            shutdown_event=shutdown_event,
        )


async def run_pipeline(pipeline: BasePipeline, state: BaseTaskState):
    """通用 Pipeline 执行包装器。"""
    try:
        logger.info(f"[Pipeline] Starting run for task {pipeline.task_id}, type={state.task_type}")
        await pipeline.run(state)
        logger.info(f"[Pipeline] Completed run for task {pipeline.task_id}")
    except PipelineShutdown:
        logger.info(f"[Pipeline] Task {pipeline.task_id} stopped by user")
    except Exception as e:
        logger.error(f"[Pipeline] Task {pipeline.task_id} failed: {e}", exc_info=True)
    finally:
        # 身份比对：仅当字典里仍是当前 pipeline 时才删除。
        # 否则快速 resume→stop 会让旧 pipeline 的 finally 误删新 pipeline。
        if app_state.active_pipelines.get(pipeline.task_id) is pipeline:
            del app_state.active_pipelines[pipeline.task_id]


async def run_pipeline_with_concurrency(
    pipeline: BasePipeline,
    state: BaseTaskState,
    task_manager: TaskManager,
):
    """带并发控制的 Pipeline 执行包装器。

    复用回归流程的加权信号量逻辑：
    1. 先将任务标记为 queued（排队中）
    2. 等待加权信号量（总并发权重 ≤ MAX_CONCURRENT_WEIGHT）
    3. 获取到信号量后启动 pipeline
    4. pipeline 结束后释放信号量
    """
    weight = app_state.TASK_TYPE_WEIGHTS.get(state.task_type, 1)
    task_id = pipeline.task_id
    semaphore = app_state.get_semaphore()
    app_state._queued_tasks[task_id] = weight

    logger.info(
        f"[Concurrency] Task {task_id} queued (weight={weight}, "
        f"current={semaphore.current}/{semaphore.max_weight})"
    )

    # 标记排队状态
    task_manager.update_state(status=StepStatus.QUEUED)

    # 排队时持久化进度消息（前端轮询可读取）
    task_manager.update_state(
        current_step="init", current_status="running",
        current_message="任务排队中...", current_progress=0.0,
    )

    try:
        # 等待并发槽位
        await semaphore.acquire(weight)
        # 已获取槽位，从排队列表移除
        app_state._queued_tasks.pop(task_id, None)

        logger.info(
            f"[Concurrency] Task {task_id} acquired slot (weight={weight}, "
            f"current={semaphore.current}/{semaphore.max_weight})"
        )

        # 检查是否在排队期间被 stop
        if getattr(pipeline, '_stop_event', None) and pipeline._stop_event.is_set():
            logger.info(f"[Concurrency] Task {task_id} was stopped while queued, skipping")
            return

        # 启动 pipeline
        await run_pipeline(pipeline, state)
    except asyncio.CancelledError:
        # 任务被取消（如 stop 操作）
        app_state._queued_tasks.pop(task_id, None)
        logger.info(f"[Concurrency] Task {task_id} cancelled while queued")
    finally:
        # 释放信号量
        try:
            await semaphore.release(weight)
            logger.info(
                f"[Concurrency] Task {task_id} released slot (weight={weight}, "
                f"current={semaphore.current}/{semaphore.max_weight})"
            )
        except Exception:
            pass
        app_state._queued_tasks.pop(task_id, None)


# 下划线别名：兼容旧代码 ``from server import _create_pipeline_for_type`` 等导入
_create_pipeline_for_type = create_pipeline_for_type
_run_pipeline = run_pipeline
_run_pipeline_with_concurrency = run_pipeline_with_concurrency
