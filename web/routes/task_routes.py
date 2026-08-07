"""任务路由：列表 / 详情 / 恢复 / 停止 / 并发状态。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from core.config import API_KEY_MISSING_MSG, get_api_key
from core.task_manager import TaskManager
from models.task import (
    AnchorVideoTask,
    CreativeVideoTask,
    ManuscriptVideoTask,
    PoetryVideoTask,
    SimpleImageTask,
    SimpleVideoTask,
    StepStatus,
)

from web import app_state, deps, helpers

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


@router.get("/api/tasks")
async def list_tasks():
    tm = TaskManager("_")
    tasks = tm.list_tasks()
    for t in tasks:
        task_tm = TaskManager(t["task_id"], dir_name=t.get("dir_name"))
        state = task_tm.load()
        if state:
            t["final_video_file"] = state.final_video_file
            t["task_type"] = state.task_type
            # 创意视频特有字段
            if isinstance(state, CreativeVideoTask):
                t["scene_count"] = state.scene_count
                t["idea"] = state.idea[:100] if state.idea else ""
            # 稿件视频特有字段
            elif isinstance(state, ManuscriptVideoTask):
                t["paragraph_count"] = len(state.paragraphs)
                t["manuscript_text"] = state.manuscript_text[:100] if state.manuscript_text else ""
            # 数字人口播
            elif isinstance(state, AnchorVideoTask):
                t["script_text"] = state.script_text[:100] if state.script_text else ""
                t["anchor_prompt"] = state.anchor_prompt[:100] if state.anchor_prompt else ""
                t["paragraph_count"] = len(state.paragraphs)
            # 简单视频
            elif isinstance(state, SimpleVideoTask):
                t["prompt"] = state.prompt[:100] if state.prompt else ""
                t["mode"] = state.mode
            # 诗歌视频
            elif isinstance(state, PoetryVideoTask):
                t["poem_text"] = state.poem_text[:100] if state.poem_text else ""
            # 简单图片
            elif isinstance(state, SimpleImageTask):
                t["prompt"] = state.prompt[:100] if state.prompt else ""
                t["size"] = state.size
    return {"tasks": tasks}


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
    data = state.model_dump()
    data["dir_name"] = dir_name
    return data


@router.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=API_KEY_MISSING_MSG)

    # 关键段串行化：check 与 insert 之间存在多个 await 让出点，快速重复 resume
    # 会让两次请求都通过 "task not in active_pipelines" 检查并各自启动 pipeline，
    # 导致同任务双重运行、状态文件交叉写入。
    async with app_state.get_pipeline_lock(task_id):
        if task_id in app_state.active_pipelines:
            existing = app_state.active_pipelines[task_id]
            if existing._stop_event.is_set():
                logger.info(f"[Resume] Replacing stopped pipeline for task {task_id}")
                del app_state.active_pipelines[task_id]
            else:
                raise HTTPException(status_code=400, detail="Task is already running")

        dir_name = helpers.find_dir_name(task_id)
        tm = TaskManager(task_id, dir_name=dir_name)
        state = tm.load()
        if not state:
            raise HTTPException(status_code=404, detail="Task not found")

        if state.status == StepStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="Task is already completed")

        logger.info(f"[Resume] Starting resume for task {task_id}, type={state.task_type}, status={state.status}")

        # v2.0：根据 task_type 选择对应的 Pipeline
        pipeline = deps.create_pipeline_for_type(state.task_type, api_key, task_id, dir_name)
        app_state.active_pipelines[task_id] = pipeline

        app_state.launch_background_task(deps.run_pipeline_with_concurrency(pipeline, state, tm))
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@router.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    if task_id not in app_state.active_pipelines and task_id not in app_state._queued_tasks:
        raise HTTPException(status_code=400, detail="Task is not running")

    # 停止运行中的 pipeline
    if task_id in app_state.active_pipelines:
        pipeline = app_state.active_pipelines[task_id]
        pipeline.stop()

    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if state and state.status in (StepStatus.RUNNING, StepStatus.QUEUED):
        tm.update_state(status=StepStatus.PENDING)
        logger.info(f"[Stop] Task {task_id} status -> pending")

    logger.info(f"[Stop] Task {task_id} stop requested")
    return {"ok": True, "task_id": task_id}


@router.post("/api/tasks/sweep")
async def sweep_stale_tasks_endpoint(age_days: int = 7):
    """手动触发僵尸任务清理（v5.0 Batch 5 / 5.1）。

    清理工作区中状态文件超龄且非活跃的任务目录；运行中/排队中/断点续传
    （PENDING）任务默认保护不清理。活跃 pipeline 中的任务一律跳过。

    Args:
        age_days: 任务状态文件超龄阈值（天），默认 7
    """
    from core.artifacts import sweep_stale_tasks

    # 活跃 pipeline 保护：即使状态文件超龄也不允许清理
    active_ids = set(app_state.active_pipelines.keys()) | set(app_state._queued_tasks)
    result = sweep_stale_tasks(age_days=age_days)
    result["swept"] = [d for d in result["swept"] if d not in active_ids]
    result["protected"] = result["protected"] + sorted(active_ids)
    logger.info(f"[Cleanup] Sweep finished: swept={result['swept']}, "
                f"protected={len(result['protected'])}, errors={len(result['errors'])}")
    return {"ok": True, **result}


@router.get("/api/concurrency")
async def get_concurrency_status():
    """返回当前并发控制状态：已用权重、上限、排队任务列表。"""
    running_tasks = []
    for tid, pl in app_state.active_pipelines.items():
        if tid not in app_state._queued_tasks:
            # 真正在运行的（已获取信号量）
            running_tasks.append({
                "task_id": tid,
                "type": getattr(pl, '_task_type', 'unknown'),
            })

    queued = [
        {"task_id": tid, "weight": w}
        for tid, w in app_state._queued_tasks.items()
    ]

    semaphore = app_state.get_semaphore()
    return {
        "ok": True,
        "max_weight": semaphore.max_weight,
        "current_weight": semaphore.current,
        "utilization": round(semaphore.utilization, 2),
        "running_count": len(running_tasks),
        "queued_count": len(queued),
        "queued_tasks": queued,
        "rate_limit_per_min": app_state.get_rate_limit(),
        "task_weights": {k.value: v for k, v in app_state.TASK_TYPE_WEIGHTS.items()},
    }
