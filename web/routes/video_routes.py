"""视频下载 + 中间产物管理路由。"""
from __future__ import annotations

import json
import logging
import os
import shutil

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.artifacts import (
    apply_cascade_plan,
    get_cascade_plan,
    list_artifacts,
    resolve_artifact,
)
from core.config import get_working_dir
from core.path_security import UnsafePathError, safe_join
from core.task_manager import TaskManager

from web import app_state, helpers

logger = logging.getLogger(__name__)

router = APIRouter(tags=["video", "artifacts"])

# 产物类别 → MIME 类型映射
_ARTIFACT_MEDIA_TYPES = {
    "image": "image/png",
    "video": "video/mp4",
    "audio": "audio/mpeg",
    "text": "text/plain; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "subtitle": "text/plain; charset=utf-8",
}


@router.get("/api/video/{task_id}")
async def serve_video(task_id: str):
    dir_name = helpers.find_dir_name(task_id)
    try:
        task_dir = safe_join(get_working_dir(), dir_name)
    except UnsafePathError:
        raise HTTPException(status_code=404, detail="Video not found")
    video_path = os.path.join(task_dir, "final_video.mp4")
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(video_path, media_type="video/mp4")


@router.get("/api/tasks/{task_id}/artifacts")
async def list_task_artifacts(task_id: str):
    """列举任务的所有中间产物（含存在性检测）。"""
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    artifacts = list_artifacts(state, tm.task_dir)
    return {
        "ok": True,
        "task_type": state.task_type.value,
        "task_status": state.status.value if state.status else "pending",
        "dir_name": dir_name,
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "step_key": a.step_key,
                "label_key": a.label_key,
                "category": a.category,
                "scope": a.scope,
                "scope_index": a.scope_index,
                "exists": a.exists,
                "size": a.size,
                "deletable": a.deletable,
                # v5.x 产物规范前置：暴露相对路径 / 字段说明 / 预览 URL
                "file_relpath": a.file_relpath,
                "schema_hint": a.schema_hint,
                "preview_url": (
                    f"/api/tasks/{task_id}/artifacts/{a.artifact_id}/file"
                    if a.file_relpath else ""
                ),
            }
            for a in artifacts
        ],
    }


@router.get("/api/tasks/{task_id}/artifacts/{artifact_id}/file")
async def serve_artifact_file(task_id: str, artifact_id: str):
    """安全地服务中间产物文件。"""
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    artifact = resolve_artifact(artifact_id, state, tm.task_dir)
    if not artifact or not artifact.file_relpath:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not artifact.exists:
        raise HTTPException(status_code=404, detail="Artifact file not found")

    abs_path = os.path.join(tm.task_dir, artifact.file_relpath)
    # 路径穿越防护
    real_task_dir = os.path.realpath(tm.task_dir)
    real_abs_path = os.path.realpath(abs_path)
    if not real_abs_path.startswith(real_task_dir + os.sep):
        raise HTTPException(status_code=403, detail="Access denied")

    media_type = _ARTIFACT_MEDIA_TYPES.get(artifact.category, "application/octet-stream")
    return FileResponse(real_abs_path, media_type=media_type)


@router.get("/api/tasks/{task_id}/manifest")
async def get_task_manifest(task_id: str):
    """返回任务产物清单（manifest.json）。

    清单由流水线运行开始/结束时自动落盘；若不存在（如排队中或旧任务）
    则现场构建并写盘。包含结构化产物（path/schema_hint/preview_url）
    与通用文件树两部分，是 v6.0 手动模式 checkpoint 的数据基础。
    """
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    from core.artifacts import build_manifest, write_manifest

    manifest_path = os.path.join(tm.task_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        write_manifest(state, tm.task_dir)
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        # 清单损坏/不可读 → 现场重建
        manifest = build_manifest(state, tm.task_dir)
    return {"ok": True, **manifest}


@router.get("/api/tasks/{task_id}/manifest.md")
async def get_task_manifest_md(task_id: str):
    """返回任务目录说明文件 MANIFEST.md（供用户与外部 Agent 阅读）。"""
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    from core.artifacts import write_manifest_md

    md_path = os.path.join(tm.task_dir, "MANIFEST.md")
    if not os.path.exists(md_path):
        write_manifest_md(state, tm.task_dir)
    if not os.path.exists(md_path):
        raise HTTPException(status_code=404, detail="Manifest not available")
    return FileResponse(md_path, media_type="text/markdown; charset=utf-8")


@router.get("/api/tasks/{task_id}/artifacts/{artifact_id}/cascade-preview")
async def preview_artifact_cascade(task_id: str, artifact_id: str):
    """预览删除产物的级联计划（不执行删除）。"""
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    artifact = resolve_artifact(artifact_id, state, tm.task_dir)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    plan = get_cascade_plan(artifact_id, state, tm.task_dir)
    if not plan:
        raise HTTPException(status_code=400, detail="Cannot compute cascade plan")

    # 只返回存在的文件
    existing_files = []
    for f in plan.files_to_delete:
        abs_path = os.path.join(tm.task_dir, f)
        if os.path.exists(abs_path):
            existing_files.append(f)

    return {
        "ok": True,
        "artifact_id": artifact_id,
        "files_to_delete": existing_files,
        "steps_to_reset": plan.steps_to_reset,
    }


@router.delete("/api/tasks/{task_id}/artifacts/{artifact_id}")
async def delete_task_artifact(task_id: str, artifact_id: str):
    """删除指定中间产物（含级联删除后续产物 + 状态回退）。"""
    # 运行中任务保护（已停止的 pipeline 允许删除产物）
    if task_id in app_state.active_pipelines:
        pipeline = app_state.active_pipelines[task_id]
        if not pipeline._stop_event.is_set():
            raise HTTPException(status_code=409, detail="Task is running, please stop it first")

    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    artifact = resolve_artifact(artifact_id, state, tm.task_dir)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    plan = get_cascade_plan(artifact_id, state, tm.task_dir)
    if not plan:
        raise HTTPException(status_code=400, detail="Cannot compute cascade plan")

    # 1. 删除文件
    deleted_files = []
    real_task_dir = os.path.realpath(tm.task_dir)
    for f in plan.files_to_delete:
        abs_path = os.path.join(tm.task_dir, f)
        real_abs_path = os.path.realpath(abs_path)
        # 路径穿越防护
        if not real_abs_path.startswith(real_task_dir + os.sep):
            continue
        if os.path.exists(abs_path) and os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
                deleted_files.append(f)
            except OSError as e:
                logger.warning(f"[Artifacts] Failed to delete {f}: {e}")

    # 2. 应用级联计划到 state
    update_kwargs = apply_cascade_plan(state, plan)

    # 3. 持久化
    tm.update_state(**update_kwargs)

    logger.info(
        f"[Artifacts] Deleted {len(deleted_files)} files for task {task_id}, "
        f"artifact={artifact_id}, reset_steps={plan.steps_to_reset}"
    )

    return {
        "ok": True,
        "deleted_files": deleted_files,
        "reset_steps": plan.steps_to_reset,
        "task_status": state.status.value if state.status else "pending",
    }


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务及其磁盘上全部生成文件（优化 3）。

    运行中/排队中任务拒绝删除。删除范围：任务工作目录（含状态文件、全部产物、
    上传文件）。删除后任务从任务列表消失，不可恢复。
    """
    # 1. 运行中保护（含排队中）
    if task_id in app_state.active_pipelines:
        pipeline = app_state.active_pipelines.get(task_id)
        if pipeline is not None and not getattr(pipeline, "_stop_event", None).is_set():
            raise HTTPException(
                status_code=400,
                detail="Cannot delete a running task. Stop it first.",
            )
    if task_id in app_state._queued_tasks:
        raise HTTPException(
            status_code=400,
            detail="Task is queued. Stop it before deleting.",
        )

    # 2. 定位任务工作目录
    dir_name = helpers.find_dir_name(task_id)
    removed_dir = False
    if dir_name:
        task_dir = os.path.join(get_working_dir(), dir_name)
        # 路径穿越防护：task_dir 必须位于工作目录内
        real_task_dir = os.path.realpath(task_dir)
        real_root = os.path.realpath(get_working_dir())
        if real_task_dir != real_root and real_task_dir.startswith(real_root + os.sep):
            if os.path.exists(task_dir):
                shutil.rmtree(task_dir, ignore_errors=True)
                removed_dir = True
                logger.info(f"[Delete] Task {task_id} directory removed: {task_dir}")
        else:
            logger.warning(f"[Delete] Unsafe task dir for {task_id}, skipped: {task_dir}")

    # 3. 从活动注册表 / 排队列表摘除
    app_state.active_pipelines.pop(task_id, None)
    app_state._queued_tasks.pop(task_id, None)
    app_state.release_pipeline_lock(task_id)

    if not removed_dir and not _task_exists(task_id):
        # 任务目录不存在且任务已不在列表中：视为不存在
        raise HTTPException(status_code=404, detail="Task not found")

    return {"ok": True, "task_id": task_id, "message": "Task deleted", "removed_dir": removed_dir}


def _task_exists(task_id: str) -> bool:
    """检查任务是否仍存在于任务列表（状态文件存在）。"""
    from core.task_manager import TaskManager

    tm = TaskManager("_")
    for t in tm.list_tasks():
        if t["task_id"] == task_id:
            return True
    return False
