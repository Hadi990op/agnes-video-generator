"""
Agnes Video Generator v2.0 — FastAPI 服务层

三种任务类型的路由集成：
- POST /api/tasks/simple      — 简单视频生成
- POST /api/tasks/creative    — 创意长视频生成
- POST /api/tasks/manuscript  — 稿件长视频生成
- POST /api/tasks/poetry     — 诗词视频生成
- POST /api/tasks             — 向后兼容（映射到 creative）

所有类型共享任务进度轮询、任务列表、任务详情、视频下载等端点。
resume 端点根据 task_type 自动选择对应的 Pipeline。
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional, Union

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from core.config import get_api_key, set_api_key, set_api_keys, delete_api_key, get_api_key_source, get_api_keys, get_key_rotation_status, get_working_dir, DURATION_FRAME_MAP, get_workspaces, add_workspace, remove_workspace, set_active_workspace, get_active_workspace, REGRESSION_WORKING_DIR_ENV, get_watermark_config, set_watermark_config, WATERMARK_PROMO_TEXT_ZH, WATERMARK_PROMO_TEXT_EN
from core.audio.voices import (
    get_voice_catalog,
    get_voice_lang,
    is_voice_compatible,
    is_voice_compatible_with_text,
    load_voice_catalog,
    VOICE_PREVIEW_TEXTS,
    LANG_COMPAT,
    PROJECT_LANGUAGES,
)
import edge_tts
from core.pipelines import (
    AnchorPipeline,
    BasePipeline,
    PipelineShutdown,
    SimpleVideoPipeline,
    CreativeVideoPipeline,
    ManuscriptVideoPipeline,
    PoetryVideoPipeline,
    StoryVideoPipeline,
)
from core.pipelines.poetry_video import POETRY_SUBTITLE_STYLE
from core.api.agnes_image import AgnesImageAPI
from core.api.error_collector import set_workspace_root
from core.artifacts import list_artifacts, resolve_artifact, get_cascade_plan, apply_cascade_plan
from core.task_manager import TaskManager
from models.task import (
    AnchorVideoTask,
    AudioConfig,
    BaseTaskState,
    CreativeVideoTask,
    ManuscriptVideoTask,
    PoetryVideoTask,
    SimpleImageTask,
    SimpleVideoTask,
    StepStatus,
    SubtitleConfig,
    SubtitleStyle,
    TaskType,
    VideoMode,
)


# ═══════════════════════════════════════════════════
# 并发控制（复用回归流程的加权信号量逻辑）
# ═══════════════════════════════════════════════════

# Agnes API 每分钟调用上限（与 rate_limiter.py / regression_runner.py 一致）
_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "20"))
# 各任务类型权重 = 该类型预估的每分钟 Agnes API 调用数
# 留 50% 余量 => 总权重上限 = _AGNES_RATE_LIMIT / 2
TASK_TYPE_WEIGHTS = {
    TaskType.SIMPLE: 1,       # 1 submit + 轻量轮询
    TaskType.CREATIVE: 3,     # Chat + N*Image + N*Video + 轮询
    TaskType.MANUSCRIPT: 4,   # 段落*Chat + 段落*Image + 轮询
    TaskType.ANCHOR: 2,       # 1 i2v submit + 轻量轮询
    TaskType.POETRY: 3,       # 1 Chat(拆分) + N*Video + N*合成
    TaskType.IMAGE: 1,        # 1 image submit
}
MAX_CONCURRENT_WEIGHT = _AGNES_RATE_LIMIT // 2  # 默认 10


class WeightedSemaphore:
    """加权信号量：控制并发任务的总权重不超过上限。

    每个任务类型的权重 = 该类型预估的每分钟 Agnes API 调用数。
    控制并发任务数，确保总 API 调用 ≤ AGNES_RATE_LIMIT/分钟。
    逻辑与 regression_runner.py 的 WeightedSemaphore 完全一致。
    """
    def __init__(self, max_weight: int):
        self.max_weight = max_weight
        self.current = 0
        self._lock = asyncio.Lock()
        self._cond = asyncio.Condition(self._lock)

    async def acquire(self, weight: int):
        if weight > self.max_weight:
            raise ValueError(f"task weight {weight} > max {self.max_weight}")
        async with self._lock:
            while self.current + weight > self.max_weight:
                await self._cond.wait()
            self.current += weight

    async def release(self, weight: int):
        async with self._lock:
            self.current -= weight
            self._cond.notify_all()

    @property
    def utilization(self) -> float:
        return self.current / self.max_weight if self.max_weight else 0


# 全局加权信号量（服务端所有任务共享）
_pipeline_semaphore = WeightedSemaphore(MAX_CONCURRENT_WEIGHT)
# 排队中的任务: task_id -> weight
_queued_tasks: Dict[str, int] = {}


def _parse_bg_color(raw: str) -> tuple:
    """将 bg_color 字符串解析为 moviepy 2.x 兼容的 RGBA 元组。"""
    if isinstance(raw, tuple):
        return raw
    if isinstance(raw, str):
        if raw.startswith("(") and raw.endswith(")"):
            return tuple(int(x.strip()) for x in raw[1:-1].split(","))
        if "@" in raw:
            parts = raw.split("@", 1)
            color_name = parts[0].strip().lower()
            alpha_pct = float(parts[1])
            rgb = {"black": (0, 0, 0), "white": (255, 255, 255),
                   "red": (255, 0, 0), "blue": (0, 0, 255),
                   "yellow": (255, 255, 0)}.get(color_name, (0, 0, 0))
            return (*rgb, int(alpha_pct * 255))
        if raw.lower() in ("none", "transparent", ""):
            return None
    return (0, 0, 0, 128)


def _build_position(subtitle_position: str) -> tuple:
    """将 'bottom'/'top' 转为 moviepy 兼容的位置元组。"""
    if subtitle_position == "top":
        return ("center", "top")
    return ("center", "bottom")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

active_pipelines: Dict[str, BasePipeline] = {}
# task_id -> asyncio.Lock, 串行化 create/resume/stop，避免并发操作同一任务导致
# 旧 pipeline 的 finally 误删新 pipeline、或同任务双重运行。
_pipeline_locks: Dict[str, asyncio.Lock] = {}
background_tasks: set = set()
shutdown_event = asyncio.Event()


def _get_pipeline_lock(task_id: str) -> asyncio.Lock:
    """获取（必要时创建）task_id 级别的并发锁。

    create/resume/stop 端点对 ``active_pipelines`` 的检查与插入之间存在
    ``await`` 让出点，快速重复操作（如 resume→stop）会让旧 pipeline 的
    ``finally`` 误删新 pipeline，甚至产生同任务双重运行。用 per-task 锁将
    这三类操作的「检查+插入/删除」关键段串行化。
    """
    lock = _pipeline_locks.get(task_id)
    if lock is None:
        lock = asyncio.Lock()
        _pipeline_locks[task_id] = lock
    return lock


def _find_dir_name(task_id: str) -> str:
    """Find the directory name for a task_id. Falls back to task_id for legacy tasks."""
    tm = TaskManager("_")
    for t in tm.list_tasks():
        if t["task_id"] == task_id:
            return t.get("dir_name", task_id)
    return task_id


# ═══════════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(get_working_dir(), exist_ok=True)
    upload_dir = os.path.join(get_working_dir(), "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    working_dir = get_working_dir()
    set_workspace_root(working_dir)  # 错误收集模块使用激活的工作空间
    if os.path.exists(working_dir):
        for name in os.listdir(working_dir):
            task_file = os.path.join(working_dir, name, "task_state.json")
            if os.path.exists(task_file):
                try:
                    with open(task_file, "r") as f:
                        data = json.load(f)
                    if data.get("status") in ("running", "queued"):
                        old_status = data["status"]
                        data["status"] = "pending"
                        # H5: 原子写（临时文件 + os.replace），避免写入中途崩溃损坏 JSON
                        tmp_fd, tmp_path = tempfile.mkstemp(
                            dir=os.path.join(working_dir, name), suffix=".tmp"
                        )
                        try:
                            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                                json.dump(data, f, ensure_ascii=False, indent=2)
                            os.replace(tmp_path, task_file)
                        except Exception:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                            raise
                        logger.info(f"[Startup] Reset stale {old_status} task {name} -> pending")
                except Exception as e:
                    logger.debug(f"[Startup] Failed to reset stale task {name}: {e}")

    # v4.0: 预加载音色目录（edge_tts.list_voices），失败不阻断启动
    try:
        await load_voice_catalog()
        logger.info("[Startup] Voice catalog loaded")
    except Exception as e:
        logger.warning(f"[Startup] Voice catalog load failed ({e}); will use fallback")

    yield


app = FastAPI(title="Agnes Video Generator", lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Return JSON error response for all unhandled exceptions."""
    import traceback
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "detail": f"Internal Server Error: {str(exc)}"},
    )


# ═══════════════════════════════════════════════════
# v4.0: 音色试听缓存
# ═══════════════════════════════════════════════════

# 试听音频缓存目录（系统临时目录，重启后自动清理）
VOICE_PREVIEW_CACHE_DIR = os.path.join(tempfile.gettempdir(), "agnes-voice-previews")
os.makedirs(VOICE_PREVIEW_CACHE_DIR, exist_ok=True)


def _preview_cache_key(voice_id: str, text: str) -> str:
    """生成试听缓存文件名：{voice_id}__{md5(text)}.mp3"""
    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    return f"{voice_id}__{text_hash}"


async def _get_or_generate_preview(voice_id: str, text: str) -> str:
    """获取试听音频：缓存命中直接返回路径，否则调用 edge_tts 生成后缓存。

    写入使用 .tmp + os.replace 原子替换，避免并发读到半成品。
    """
    cache_key = _preview_cache_key(voice_id, text)
    cache_path = os.path.join(VOICE_PREVIEW_CACHE_DIR, cache_key + ".mp3")
    if os.path.exists(cache_path):
        return cache_path  # 缓存命中

    tmp_path = cache_path + ".tmp"
    communicate = edge_tts.Communicate(text, voice=voice_id)
    await communicate.save(tmp_path)
    os.replace(tmp_path, cache_path)  # 原子替换
    return cache_path


def _resolve_preview_text(voice_id: str, text: str) -> str:
    """解析试听文本：显式传入优先，否则用该音色语言的预设试听句。"""
    if text:
        return text
    vlang = get_voice_lang(voice_id) or "zh"
    name = voice_id.split("-")[-1].replace("Neural", "")
    return VOICE_PREVIEW_TEXTS.get(vlang, VOICE_PREVIEW_TEXTS["zh"]).format(name=name)


def _validate_voice_compat(audio_voice: str, target_lang: str, text: str = None):
    """校验 voice 与目标任务语言的兼容性，不兼容时抛出 422。

    - target_lang: 页面语言（创意/诗歌/主播等由 LLM 按页面语言生成文本）
    - text: 稿件正文（manuscript），已知文本时做更精确的脚本级检测
    """
    if not audio_voice:
        return
    if text is not None and text.strip():
        if not is_voice_compatible_with_text(audio_voice, text):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"所选音色 {audio_voice} 不支持当前稿件语言的朗读"
                    f"（跨文字体系无法朗读，任务将失败）。请更换为匹配语言的音色。"
                ),
            )
        return
    if target_lang and not is_voice_compatible(audio_voice, target_lang):
        lang_label = PROJECT_LANGUAGES.get(target_lang, {}).get("label", target_lang)
        supported = LANG_COMPAT.get(get_voice_lang(audio_voice) or "", [])
        supported_labels = [PROJECT_LANGUAGES.get(c, {}).get("label", c) for c in supported]
        raise HTTPException(
            status_code=422,
            detail=(
                f"所选音色 {audio_voice} 不支持「{lang_label}」语言的视频生成"
                f"（仅支持：{', '.join(supported_labels)}）。请更换音色或语言。"
            ),
        )

def get_upload_dir() -> str:
    """返回当前激活工作目录下的 uploads 子目录。"""
    return os.path.join(get_working_dir(), "uploads")


# ═══════════════════════════════════════════════════
# Static files + Root
# ═══════════════════════════════════════════════════


static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Serve workspace uploads via a simple route (outside app dir)
workspace_uploads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))
if os.path.exists(workspace_uploads_dir):
    @app.get("/uploads/")
    async def list_uploads():
        """List uploaded files."""
        files = []
        for f in sorted(os.listdir(workspace_uploads_dir)):
            fp = os.path.join(workspace_uploads_dir, f)
            if os.path.isfile(fp):
                size = os.path.getsize(fp)
                files.append({"name": f, "size": size})
        return {"files": files, "dir": "/uploads/"}

    @app.get("/uploads/{filename:path}")
    async def serve_upload(filename: str):
        """Serve an uploaded file."""
        filepath = os.path.join(workspace_uploads_dir, filename)
        # Security: prevent path traversal
        real_path = os.path.realpath(filepath)
        if not real_path.startswith(os.path.realpath(workspace_uploads_dir)):
            return {"error": "Access denied"}
        if os.path.isfile(real_path):
            return FileResponse(real_path)
        return {"error": "File not found"}


@app.get("/")
async def root():
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Agnes Video Generator API"}


# ═══════════════════════════════════════════════════
# API Key 配置
# ═══════════════════════════════════════════════════


@app.get("/api/config")
async def get_config():
    keys = get_api_keys()
    source = get_api_key_source()
    active_ws = get_active_workspace()
    wm = get_watermark_config()
    data = {
        "api_key": keys[0][:8] + "..." if keys else "",
        "api_keys_count": len(keys),
        "api_keys_masked": [k[:8] + "..." for k in keys],
        "source": source,
        "can_clear": source == "config",
        "workspaces": get_workspaces(),
        "active_workspace": active_ws,
        "working_dir_source": "regression" if os.environ.get(REGRESSION_WORKING_DIR_ENV) else "config",
        "watermark": wm,
        "watermark_promo_zh": WATERMARK_PROMO_TEXT_ZH,
        "watermark_promo_en": WATERMARK_PROMO_TEXT_EN,
    }
    return data


@app.post("/api/config")
async def save_config(api_key: str = Form(...)):
    """保存 API Key（支持逗号分隔的多个 key）。"""
    # 按逗号/换行分割，支持多 key 输入
    keys = [k.strip() for k in api_key.replace("\n", ",").split(",") if k.strip()]
    if not keys:
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    set_api_keys(keys)
    return {"ok": True, "keys_count": len(keys)}


@app.get("/api/config/keys")
async def get_keys_status():
    """返回各 API key 的轮转状态（冷却信息）。"""
    return get_key_rotation_status()


@app.delete("/api/config")
async def clear_config():
    """Delete the API key from the config file."""
    source = get_api_key_source()
    if source == "env":
        raise HTTPException(
            status_code=400,
            detail="API Key 来自环境变量，无法从界面清除",
        )
    delete_api_key()
    return {"ok": True}


# ═══════════════════════════════════════════════════
# 水印配置
# ═══════════════════════════════════════════════════


@app.post("/api/config/watermark")
async def save_watermark_config(enabled: bool = Form(False)):
    """Save watermark toggle."""
    set_watermark_config(enabled=enabled)
    return {"ok": True, "enabled": enabled}


# ═══════════════════════════════════════════════════
# 工作目录管理（多工作目录，同时仅一个 active）
# ═══════════════════════════════════════════════════


@app.get("/api/workspaces")
async def list_workspaces():
    """列出所有已配置的工作目录及当前激活项。"""
    return {
        "workspaces": get_workspaces(),
        "active_workspace": get_active_workspace(),
    }


@app.post("/api/workspaces")
async def create_workspace(path: str = Form(...), name: str = Form("")):
    """添加一个工作目录。"""
    if not path.strip():
        raise HTTPException(status_code=422, detail="path 不能为空")
    entry = add_workspace(path.strip(), name.strip())
    os.makedirs(entry["path"], exist_ok=True)
    os.makedirs(os.path.join(entry["path"], "uploads"), exist_ok=True)
    return {"ok": True, "workspace": entry, "active_workspace": get_active_workspace()}


@app.delete("/api/workspaces")
async def delete_workspace(path: str = Form(...)):
    """移除一个工作目录（仅从配置中移除，不删除磁盘文件）。"""
    if not path.strip():
        raise HTTPException(status_code=422, detail="path 不能为空")
    removed = remove_workspace(path.strip())
    if not removed:
        raise HTTPException(status_code=404, detail="工作目录不存在")
    return {"ok": True, "active_workspace": get_active_workspace()}


@app.post("/api/workspaces/active")
async def activate_workspace(path: str = Form(...)):
    """设置当前激活的工作目录。"""
    if not path.strip():
        raise HTTPException(status_code=422, detail="path 不能为空")
    try:
        active = set_active_workspace(path.strip())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    os.makedirs(active, exist_ok=True)
    os.makedirs(os.path.join(active, "uploads"), exist_ok=True)
    return {"ok": True, "active_workspace": active}


@app.get("/api/workspaces/pick-directory")
async def pick_directory():
    """弹出操作系统原生目录选择框，返回所选目录路径。

    跨平台实现：
    - macOS: osascript
    - Linux: zenity（若不可用回退 kdialog）
    - Windows: PowerShell Forms.FolderBrowserDialog
    """
    path = await asyncio.to_thread(_pick_directory_native)
    if not path:
        return {"ok": False, "path": ""}
    return {"ok": True, "path": path}


def _pick_directory_native() -> str:
    """同步调用系统原生目录选择器，返回路径或空字符串。"""
    system = platform.system()
    try:
        if system == "Darwin":
            script = (
                'set chosenFolder to choose folder with prompt "选择工作目录"'
                "\nreturn POSIX path of chosenFolder"
            )
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                return r.stdout.strip()
        elif system == "Windows":
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
                "if ($f.ShowDialog() -eq 'OK') { Write-Output $f.SelectedPath }"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        else:
            for cmd in (["zenity", "--file-selection", "--directory"],
                        ["kdialog", "--getexistingdirectory", os.path.expanduser("~")]):
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if r.returncode == 0 and r.stdout.strip():
                        return r.stdout.strip()
                    break
                except FileNotFoundError:
                    continue
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.warning(f"[Workspace] Directory picker failed: {e}")
    return ""


@app.get("/api/voices")
async def get_voices():
    """返回按语言分组的可选 TTS 语音角色列表（含兼容性提示）。

    响应结构：
    {
      "languages": [
        {"code": "zh", "label": "中文", "count": N, "voices": [ {id,name,region,gender,style_tags,preview_text,lang}, ... ]},
        ...
      ],
      "compat_hint": { "zh": ["zh","en"], ... }
    }
    """
    return get_voice_catalog()


@app.get("/api/voices/preview")
async def preview_voice(voice: str, text: str = ""):
    """返回音色试听音频（audio/mpeg），带服务端缓存。

    - voice: 必填，音色 id
    - text: 选填，试听文本；缺省时使用该音色语言的预设试听句
    - 跨语言不兼容时 edge_tts 抛异常，返回 400 + 明确错误信息
    """
    if not voice:
        raise HTTPException(status_code=400, detail="缺少 voice 参数")
    preview_text = _resolve_preview_text(voice, text)
    try:
        cache_path = await _get_or_generate_preview(voice, preview_text)
    except Exception as e:
        logger.warning(f"[Preview] voice={voice} failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"该音色不支持此语言的试听文本（跨文字体系无法朗读）：{e}",
        )
    return FileResponse(
        cache_path,
        media_type="audio/mpeg",
        filename=f"{voice}.mp3",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/voices/compat")
async def voice_compat(voice: str, target_lang: str):
    """查询 voice 与目标语言 target_lang 的兼容性。

    响应：{"compatible": bool, "voice_lang": str, "target_lang": str, "supported_langs": [...]}
    """
    vlang = get_voice_lang(voice)
    compatible = is_voice_compatible(voice, target_lang)
    supported = LANG_COMPAT.get(vlang, [vlang]) if vlang else []
    return {
        "compatible": compatible,
        "voice_lang": vlang,
        "target_lang": target_lang,
        "supported_langs": supported,
    }


# ═══════════════════════════════════════════════════
# 简单图片生成（任务 + working_dir 持久化）
# ═══════════════════════════════════════════════════


@app.post("/api/image/generate")
async def generate_image(
    prompt: str = Form(...),
    size: str = Form("1024x1024"),
    negative_prompt: Optional[str] = Form(None),
    system_prompt: str = Form(""),
    reference_image: UploadFile = File(None),
    # v5.1: Storyboard
    use_storyboard: bool = Form(False),
    storyboard_scenes: str = Form("[]"),
):
    """简单图片生成：创建任务 → 直调 Agnes Image API → 保存到任务目录。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    if len(prompt) > 5000:
        raise HTTPException(status_code=422, detail="prompt 最多 5000 字符")
    if not prompt.strip():
        raise HTTPException(status_code=422, detail="prompt 不能为空")

    _VALID_SIZES = {"1024x1024", "768x1152", "1152x768", "768x1344", "1344x768", "1792x1024", "1024x1792"}
    if size not in _VALID_SIZES:
        raise HTTPException(status_code=422, detail=f"size 必须为 {_VALID_SIZES} 之一")

    task_id = uuid.uuid4().hex[:12]
    name = f"image_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    state = SimpleImageTask(
        task_id=task_id,
        creative_name=name,
        prompt=prompt.strip(),
        size=size,
        negative_prompt=negative_prompt or "",
        system_prompt=system_prompt,
    )

    # 先用 PENDING 创建任务目录和状态文件
    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)

    image_api = AgnesImageAPI(api_key=api_key)

    ref_paths = []
    if reference_image and reference_image.filename:
        ext = os.path.splitext(reference_image.filename)[1] or ".png"
        upload_dir = get_upload_dir()
        os.makedirs(upload_dir, exist_ok=True)
        ref_path = os.path.join(upload_dir, f"img_ref_{uuid.uuid4().hex[:8]}{ext}")
        with open(ref_path, "wb") as f:
            f.write(await reference_image.read())
        ref_paths.append(ref_path)

    try:
        state.status = StepStatus.RUNNING
        tm.update_state(status=StepStatus.RUNNING)

        full_prompt = _build_encrypted_image_prompt(system_prompt, prompt) if system_prompt.strip() else prompt
        output = await image_api.generate_single_image(
            prompt=full_prompt,
            reference_image_paths=ref_paths,
            size=size,
            negative_prompt=negative_prompt,
        )
    except Exception as e:
        state.status = StepStatus.FAILED
        tm.update_state(status=StepStatus.FAILED)
        logger.error(f"[Image] Task {task_id} failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    img_filename = "final_image.png"
    img_path = os.path.join(tm.task_dir, img_filename)
    try:
        output.save(img_path)
    except Exception as e:
        state.status = StepStatus.FAILED
        tm.update_state(status=StepStatus.FAILED)
        logger.error(f"[Image] Task {task_id} save failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"图片保存失败: {e}")

    state.status = StepStatus.COMPLETED
    state.final_video_file = img_path
    tm.update_state(status=StepStatus.COMPLETED, final_video_file=img_path)

    logger.info(f"[Image] Task {task_id} completed: {img_path}, prompt={prompt[:60]}...")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.get("/api/image/{task_id}")
async def serve_image(task_id: str):
    """返回已生成的图片文件。"""
    dir_name = _find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state or not state.final_video_file:
        raise HTTPException(status_code=404, detail="Image not found")
    if not os.path.exists(state.final_video_file):
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(state.final_video_file)


# ═══════════════════════════════════════════════════
# 任务列表 + 详情 + 视频下载
# ═══════════════════════════════════════════════════


@app.get("/api/tasks")
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
            # 简单图片
            elif isinstance(state, SimpleImageTask):
                t["prompt"] = state.prompt[:100] if state.prompt else ""
                t["size"] = state.size
    return {"tasks": tasks}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    dir_name = _find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
    data = state.model_dump()
    data["dir_name"] = dir_name
    return data


@app.get("/api/video/{task_id}")
async def serve_video(task_id: str):
    dir_name = _find_dir_name(task_id)
    task_dir = os.path.join(get_working_dir(), dir_name)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    
    # Try the task state's final_video_file first (handles various naming conventions)
    candidate_files = []
    if state and state.final_video_file:
        candidate_files.append(state.final_video_file)
    
    # Also try common filenames in the task directory
    common_names = ["final_video.mp4", "final.mp4", "final_with_audio.mp4"]
    for name in common_names:
        path = os.path.join(task_dir, name)
        if os.path.exists(path) and path not in candidate_files:
            candidate_files.append(path)
    
    # Try all candidates
    for video_path in candidate_files:
        if os.path.exists(video_path):
            return FileResponse(video_path, media_type="video/mp4")
    
    raise HTTPException(status_code=404, detail="Video not found")


# ═══════════════════════════════════════════════════
# 中间产物 API
# ═══════════════════════════════════════════════════


# 产物类别 → MIME 类型映射
_ARTIFACT_MEDIA_TYPES = {
    "image": "image/png",
    "video": "video/mp4",
    "audio": "audio/mpeg",
    "text": "text/plain; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "subtitle": "text/plain; charset=utf-8",
}


@app.get("/api/tasks/{task_id}/artifacts")
async def list_task_artifacts(task_id: str):
    """列举任务的所有中间产物（含存在性检测）。"""
    dir_name = _find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    artifacts = list_artifacts(state, tm.task_dir)
    return {
        "ok": True,
        "task_type": state.task_type.value,
        "task_status": state.status.value if state.status else "pending",
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
            }
            for a in artifacts
        ],
    }


@app.get("/api/tasks/{task_id}/artifacts/{artifact_id}/file")
async def serve_artifact_file(task_id: str, artifact_id: str):
    """安全地服务中间产物文件。"""
    dir_name = _find_dir_name(task_id)
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
    return FileResponse(abs_path, media_type=media_type)


@app.get("/api/tasks/{task_id}/artifacts/{artifact_id}/cascade-preview")
async def preview_artifact_cascade(task_id: str, artifact_id: str):
    """预览删除产物的级联计划（不执行删除）。"""
    dir_name = _find_dir_name(task_id)
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


@app.delete("/api/tasks/{task_id}/artifacts/{artifact_id}")
async def delete_task_artifact(task_id: str, artifact_id: str):
    """删除指定中间产物（含级联删除后续产物 + 状态回退）。"""
    # 运行中任务保护（已停止的 pipeline 允许删除产物）
    if task_id in active_pipelines:
        pipeline = active_pipelines[task_id]
        if not pipeline._stop_event.is_set():
            raise HTTPException(status_code=409, detail="Task is running, please stop it first")

    dir_name = _find_dir_name(task_id)
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


# ═══════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════


# 时长提取 regex 模式（支持 7 种语言）
_DURATION_PATTERNS = [
    # 中文
    r'(?:每个场景|每段|每节|每个|每)(?:约)?(\d+)\s*(?:秒|s)',
    r'(\d+)\s*(?:秒|s)\s*(?:每|/)',
    # 日文
    r'各\s*(\d+)\s*秒',
    # 英文
    r'(\d+)\s*(?:seconds?|secs?|s)\s*(?:each|per)',
    r'(?:each|per)\s*(?:scene)?\s*(\d+)\s*(?:seconds?|secs?|s)',
    # 韩文
    r'각\s*(\d+)\s*초',
    # 俄文
    r'по\s*(\d+)\s*секунд',
    # 马来/印尼
    r'(\d+)\s*(?:saat|detik)\s*(?:setiap|masing)',
    r'(?:setiap|masing)\s*(?:satu\s+)?(\d+)\s*(?:saat|detik)',
    # 通用回退
    r'(\d+)\s*(?:秒|seconds?|secs?|초|секунд|saat|detik|s)\b',
]


def _parse_duration(user_requirement: str) -> int:
    """从 user_requirement 中提取时长。支持 7 种语言。"""
    for pattern in _DURATION_PATTERNS:
        match = re.search(pattern, user_requirement, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 5


def _has_explicit_duration(user_requirement: str) -> bool:
    """检查 user_requirement 中是否显式提到了时长。支持 7 种语言。"""
    for pattern in _DURATION_PATTERNS:
        if re.search(pattern, user_requirement, re.IGNORECASE):
            return True
    return False


def _build_encrypted_image_prompt(system_prompt: str, user_prompt: str) -> str:
    """Base64 加密图片描述，在系统提示词末尾写明解密方法。"""
    encoded = base64.b64encode(user_prompt.encode("utf-8")).decode("ascii")
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', system_prompt))
    if has_chinese:
        decryption = (
            "解密方法：以下图片描述为 base64 编码。"
            "请先进行 base64 解码以获取实际描述，"
            "然后根据解码后的描述生成图片。"
            "不要直接根据编码文本生成图片。\n\n"
            f"加密描述：\n{encoded}"
        )
    else:
        decryption = (
            "Decryption method: The image description below is base64-encoded. "
            "Base64-decode it to get the actual description, "
            "then generate the image based on the decoded description. "
            "Do NOT generate based on the encoded text itself.\n\n"
            f"Encrypted description:\n{encoded}"
        )
    return f"{system_prompt}\n\n{decryption}"


def _create_pipeline_for_type(
    task_type: TaskType,
    api_key: str,
    task_id: str,
    dir_name: str,
) -> BasePipeline:
    """根据任务类型创建对应的 Pipeline 实例。"""
    if task_type == TaskType.SIMPLE:
        return SimpleVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.STORY:
        return StoryVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.MANUSCRIPT:
        return ManuscriptVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.ANCHOR:
        return AnchorPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.POETRY:
        return PoetryVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )
    else:
        # CREATIVE（默认）
        return CreativeVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )


async def _run_pipeline(pipeline: BasePipeline, state: BaseTaskState):
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
        if active_pipelines.get(pipeline.task_id) is pipeline:
            del active_pipelines[pipeline.task_id]


async def _run_pipeline_with_concurrency(
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
    weight = TASK_TYPE_WEIGHTS.get(state.task_type, 1)
    task_id = pipeline.task_id
    _queued_tasks[task_id] = weight

    logger.info(
        f"[Concurrency] Task {task_id} queued (weight={weight}, "
        f"current={_pipeline_semaphore.current}/{_pipeline_semaphore.max_weight})"
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
        await _pipeline_semaphore.acquire(weight)
        # 已获取槽位，从排队列表移除
        _queued_tasks.pop(task_id, None)

        logger.info(
            f"[Concurrency] Task {task_id} acquired slot (weight={weight}, "
            f"current={_pipeline_semaphore.current}/{_pipeline_semaphore.max_weight})"
        )

        # 检查是否在排队期间被 stop
        if getattr(pipeline, '_stop_event', None) and pipeline._stop_event.is_set():
            logger.info(f"[Concurrency] Task {task_id} was stopped while queued, skipping")
            return

        # 启动 pipeline
        await _run_pipeline(pipeline, state)
    except asyncio.CancelledError:
        # 任务被取消（如 stop 操作）
        _queued_tasks.pop(task_id, None)
        logger.info(f"[Concurrency] Task {task_id} cancelled while queued")
    finally:
        # 释放信号量
        try:
            await _pipeline_semaphore.release(weight)
            logger.info(
                f"[Concurrency] Task {task_id} released slot (weight={weight}, "
                f"current={_pipeline_semaphore.current}/{_pipeline_semaphore.max_weight})"
            )
        except Exception:
            pass
        _queued_tasks.pop(task_id, None)


def _launch_background_task(coro):
    """Launch a background task with a strong reference to prevent GC."""
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task


# ═══════════════════════════════════════════════════
# 任务创建端点 — 三种类型
# ═══════════════════════════════════════════════════


@app.post("/api/tasks/simple")
async def create_simple_task(
    prompt: str = Form(...),
    mode: str = Form("t2v"),
    duration: int = Form(5),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    seed: Optional[int] = Form(None),
    negative_prompt: Optional[str] = Form(None),
    system_prompt: str = Form(""),
    reference_image: UploadFile = File(None),
    end_frame_image: UploadFile = File(None),
):
    """创建简单视频任务（类型 1）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    # P7: 参数校验
    _VALID_MODES = {"t2v", "i2v", "ti2vid", "keyframes"}
    if mode not in _VALID_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"mode 必须为 {_VALID_MODES} 之一，当前: {mode}",
        )
    if duration not in DURATION_FRAME_MAP:
        raise HTTPException(
            status_code=422,
            detail=f"duration 必须为 {sorted(DURATION_FRAME_MAP.keys())} 之一，当前: {duration}",
        )
    if len(prompt) > 5000:
        raise HTTPException(status_code=422, detail="prompt 最多 5000 字符")

    task_id = uuid.uuid4().hex[:12]
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 映射模式
    video_mode = VideoMode.T2V
    if mode in ("i2v", "ti2vid"):
        video_mode = VideoMode.I2V if mode == "i2v" else VideoMode.TI2VID
    elif mode == "keyframes":
        video_mode = VideoMode.KEYFRAMES

    state = SimpleVideoTask(
        task_id=task_id,
        creative_name=f"simple_{task_id}",
        prompt=prompt,
        mode=video_mode,
        duration=duration,
        video_width=video_width,
        video_height=video_height,
        seed=seed,
        negative_prompt=negative_prompt,
        system_prompt=system_prompt,
    )

    # 处理参考图上传（L4: 用 UUID 替代客户端文件名，避免路径穿越）
    if reference_image and reference_image.filename:
        ext = os.path.splitext(reference_image.filename)[1] or ".png"
        os.makedirs(get_upload_dir(), exist_ok=True)
        upload_path = os.path.join(get_upload_dir(), f"{task_id}_ref{ext}")
        with open(upload_path, "wb") as f:
            f.write(await reference_image.read())
        state.reference_image = upload_path

    # 处理尾帧图上传（keyframes 模式）
    if end_frame_image and end_frame_image.filename:
        ext = os.path.splitext(end_frame_image.filename)[1] or ".png"
        upload_path = os.path.join(get_upload_dir(), f"{task_id}_end{ext}")
        with open(upload_path, "wb") as f:
            f.write(await end_frame_image.read())
        state.end_frame_image = upload_path

    pipeline = _create_pipeline_for_type(TaskType.SIMPLE, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Simple] Task created: {task_id}, mode={mode}, duration={duration}s (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/creative")
async def create_creative_task(
    idea: str = Form(...),
    creative_name: str = Form(""),
    style: str = Form("电影质感写实风格"),
    chaining_mode: str = Form("keyframes"),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    # ── v3.x 场景配置 ──
    duration_source: str = Form("manual"),
    scene_count: int = Form(3),
    uniform_duration: bool = Form(True),
    scene_durations_json: str = Form("[5,5,5]"),
    reference_image: UploadFile = File(None),
    end_frame_images: List[UploadFile] = File(None),
    use_custom_end_frames: bool = Form(False),
    generate_end_frames_from_ref: bool = Form(True),
    # v2.0 音频配置
    audio_enabled: bool = Form(False),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("+0%"),
    audio_lang: str = Form(""),  # 页面语言，用于音色兼容性校验
    # v3.0 字幕独立配置
    subtitle_enabled: bool = Form(True),
    subtitle_style_mode: str = Form("fixed"),
    subtitle_style_hints: str = Form(""),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(48),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
):
    """创建创意长视频任务（类型 2）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    # v4.0: 音色与目标语言兼容性校验
    if audio_enabled:
        _validate_voice_compat(audio_voice, audio_lang or "zh")

    # P7: 参数校验
    if len(idea) > 10000:
        raise HTTPException(status_code=422, detail="idea 最多 10000 字符")
    if duration_source not in ("manual", "prompt"):
        raise HTTPException(status_code=422, detail="duration_source 必须为 manual 或 prompt")
    if duration_source == "manual":
        if scene_count < 1 or scene_count > 30:
            raise HTTPException(status_code=422, detail="scene_count 范围 1-30")
        # 解析场景时长 JSON
        try:
            scene_durations = json.loads(scene_durations_json)
            if not isinstance(scene_durations, list):
                raise ValueError("not a list")
        except Exception:
            raise HTTPException(status_code=422, detail="scene_durations_json 必须为 JSON 数组")
        # 校验每个时长
        for i, d in enumerate(scene_durations):
            if not isinstance(d, (int, float)) or d < 2 or d > 30:
                raise HTTPException(status_code=422, detail=f"场景 {i+1} 时长范围 2-30 秒")
    else:
        scene_durations = []

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"video_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 构建音频配置
    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    # 构建独立字幕配置（v3.0）
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=_build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=_parse_bg_color(subtitle_bg_color),
        style_mode=subtitle_style_mode,
        style_hints=subtitle_style_hints,
    )
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=subtitle_style,
    )

    state = CreativeVideoTask(
        task_id=task_id,
        creative_name=name,
        idea=idea,
        style=style,
        chaining_mode=chaining_mode,
        video_width=video_width,
        video_height=video_height,
        video_duration=5,
        duration_source=duration_source,
        scene_count=scene_count,
        uniform_duration=uniform_duration,
        scene_durations=scene_durations,
        use_custom_end_frames=use_custom_end_frames,
        generate_end_frames_from_ref=generate_end_frames_from_ref,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
    )

    logger.info(
        f"[Pipeline] Scene config: source={duration_source}, "
        f"scenes={scene_count}, durations={scene_durations}, uniform={uniform_duration}"
    )

    # 处理参考图上传（L4: 用 UUID 替代客户端文件名，避免路径穿越）
    if reference_image and reference_image.filename:
        ext = os.path.splitext(reference_image.filename)[1] or ".png"
        os.makedirs(get_upload_dir(), exist_ok=True)
        upload_path = os.path.join(get_upload_dir(), f"{task_id}_ref{ext}")
        with open(upload_path, "wb") as f:
            f.write(await reference_image.read())
        state.reference_image = upload_path

    # P3: 处理自定义尾帧图片上传
    if use_custom_end_frames and end_frame_images:
        saved_paths = []
        for idx, ef_file in enumerate(end_frame_images):
            if ef_file and ef_file.filename:
                ext = os.path.splitext(ef_file.filename)[1] or ".png"
                upload_path = os.path.join(get_upload_dir(), f"{task_id}_end_{idx}{ext}")
                with open(upload_path, "wb") as f:
                    f.write(await ef_file.read())
                saved_paths.append(upload_path)
        if saved_paths:
            state.end_frame_images = saved_paths
            logger.info(f"[Pipeline] Saved {len(saved_paths)} custom end frame images for task {task_id}")

    pipeline = _create_pipeline_for_type(TaskType.CREATIVE, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Creative] Task created: {task_id}, idea={idea[:40]}... (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/manuscript")
async def create_manuscript_task(
    manuscript_text: str = Form(...),
    creative_name: str = Form(""),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    video_duration: int = Form(10),
    # v2.0 音频配置
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("+0%"),
    audio_lang: str = Form(""),  # 页面语言，用于音色兼容性校验
    # v3.0 字幕独立配置
    subtitle_enabled: bool = Form(True),
    subtitle_style_mode: str = Form("fixed"),
    subtitle_style_hints: str = Form(""),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(48),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
    # v5.0: Character consistency + style
    style: str = Form(""),
    reference_image: UploadFile = File(None),
    # v5.1: Storyboard
    use_storyboard: bool = Form(False),
    storyboard_scenes: str = Form("[]"),
    # v5.2: Dialogue-only mode (narration off → only dialogue lines)
    dialogue_only: bool = Form(False),
):
    """创建稿件长视频任务（类型 3）。

    v5.0: 支持角色参考图上传和艺术风格，用于跨场景角色一致性。
    """
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    if not manuscript_text.strip():
        raise HTTPException(status_code=400, detail="稿件内容不能为空")
    # P7: 文本长度上限（扩展至 200000 支持长视频/1小时电影脚本）
    if len(manuscript_text) > 200000:
        raise HTTPException(status_code=422, detail="稿件文本最多 200000 字符")

    # v4.0: 稿件正文已知，做脚本级音色兼容性校验（最准确）
    if audio_enabled:
        _validate_voice_compat(audio_voice, audio_lang or "zh", text=manuscript_text)

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"manuscript_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 构建音频配置
    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    # 构建独立字幕配置（v3.0）
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=_build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=_parse_bg_color(subtitle_bg_color),
        style_mode=subtitle_style_mode,
        style_hints=subtitle_style_hints,
    )
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=subtitle_style,
    )

    state = ManuscriptVideoTask(
        task_id=task_id,
        creative_name=name,
        manuscript_text=manuscript_text.strip(),
        video_width=video_width,
        video_height=video_height,
        video_duration=video_duration,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
        style=style,
        use_storyboard=use_storyboard,
        storyboard_scenes=json.loads(storyboard_scenes) if storyboard_scenes else [],
        dialogue_only=dialogue_only,
    )

    # v5.0: Handle user-provided character reference image
    if reference_image and reference_image.filename:
        ext = os.path.splitext(reference_image.filename)[1] or ".png"
        upload_dir = os.path.join(get_working_dir(), dir_name)
        os.makedirs(upload_dir, exist_ok=True)
        upload_path = os.path.join(upload_dir, f"character_ref_input{ext}")
        with open(upload_path, "wb") as f:
            f.write(await reference_image.read())
        state.reference_image = upload_path

    pipeline = _create_pipeline_for_type(TaskType.MANUSCRIPT, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Manuscript] Task created: {task_id}, text_len={len(manuscript_text)} (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}




class StoryboardRequest(BaseModel):
    manuscript_text: str


def _sse_event(data: dict) -> str:
    """Format a dict as a Server-Sent Event."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/tasks/preview/storyboard")
async def preview_storyboard(
    req: StoryboardRequest,
):
    """Generate a storyboard preview with SSE streaming progress.

    Returns scene descriptions for user review. Streams progress events:
      {"type": "step", "message": "...", "progress": 0.0}
      {"type": "scene", "index": N, "total": N, "message": "..."}
      {"type": "image_progress", "index": N, "total": N, "message": "..."}
      {"type": "done", "scenes": [...], "total_scenes": N}
      {"type": "error", "message": "..."}
    """
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")
    manuscript_text = req.manuscript_text
    if not manuscript_text.strip():
        raise HTTPException(status_code=400, detail="稿件内容不能为空")

    async def event_generator():
        try:
            from core.screenwriter import Screenwriter
            sw = Screenwriter(api_key=api_key)

            # Step 1: Parse scene markers if present
            from core.pipelines.manuscript_video import _SCENE_MARKER_RE, _split_text

            has_markers = bool(_SCENE_MARKER_RE.search(manuscript_text))

            if has_markers:
                # Has scene markers — parse them
                yield _sse_event({"type": "step", "message": "分析场景标记...", "progress": 0.0})
                parts = _SCENE_MARKER_RE.split(manuscript_text)
                markers = _SCENE_MARKER_RE.findall(manuscript_text)
                scene_list = []
                total = len(markers)
                for i, (marker_text, narration_text) in enumerate(zip(markers, parts[1:])):
                    narration_text = narration_text.strip()
                    video_prompt = marker_text.strip()
                    scene_prompt = await asyncio.to_thread(
                        sw.enhance_scene_prompt,
                        scene_description=video_prompt,
                        narration=narration_text,
                    )
                    scene_list.append({
                        "index": i,
                        "video_prompt": scene_prompt,
                        "narration_text": narration_text[:200],
                        "duration": 5,
                        "description": video_prompt,
                    })
                    yield _sse_event({
                        "type": "scene", "index": i, "total": total,
                        "message": f"场景 {i+1}/{total} 描述完成",
                    })
                scenes = scene_list
            else:
                # No markers — split text into segments
                yield _sse_event({"type": "step", "message": "智能拆分文本段落...", "progress": 0.0})
                from core.pipelines.manuscript_video import _split_text
                paragraphs = _split_text(manuscript_text.strip())
                total = len(paragraphs)
                yield _sse_event({"type": "step", "message": f"已拆分为 {total} 个段落", "progress": 0.05})
                scene_list = []
                for i, p in enumerate(paragraphs):
                    scene_prompt = await asyncio.to_thread(
                        sw.enhance_scene_prompt,
                        scene_description=p.text[:300],
                        narration=p.text,
                    )
                    scene_list.append({
                        "index": i,
                        "video_prompt": scene_prompt,
                        "narration_text": p.text[:200],
                        "duration": max(int(len(p.text) / 4), 3),
                        "description": p.text[:200],
                    })
                    yield _sse_event({
                        "type": "scene", "index": i, "total": total,
                        "message": f"场景 {i+1}/{total} 描述完成",
                    })
                scenes = scene_list

            # Step 2: Generate storyboard images concurrently with key rotation
            if scenes:
                import base64
                import requests as sync_requests
                from core.config import get_api_keys

                image_count = min(len(scenes), 5)
                all_keys = get_api_keys()

                yield _sse_event({
                    "type": "image_progress",
                    "message": f"正在生成 {image_count} 张故事板图片...",
                    "progress": 0.6,
                })

                async def generate_one_image(idx, prompt, key):
                    """Generate a single storyboard image via direct HTTP call.
                    Hard 30s timeout total — storyboards are previews."""
                    headers = {
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    }
                    payload = {
                        "model": "agnes-image-2.1-flash",
                        "prompt": prompt,
                        "size": "768x1152",
                        "n": 1,
                    }
                    url = "https://apihub.agnes-ai.com/v1/images/generations"

                    try:
                        # 3s connect + 25s read = 28s, plus 2s buffer
                        resp = await asyncio.wait_for(
                            asyncio.to_thread(
                                sync_requests.post, url, headers=headers,
                                json=payload, timeout=(3, 25),
                            ),
                            timeout=30,
                        )

                        if resp.status_code != 200:
                            err_msg = resp.text[:100] if resp.text else f"HTTP {resp.status_code}"
                            logger.warning(f"[Storyboard] Image {idx}: {err_msg}")
                            return idx, None, f"HTTP {resp.status_code}"

                        result = resp.json()
                        if "error" in result:
                            return idx, None, result["error"].get("message", "API error")

                        data_list = result.get("data", [])
                        if not data_list:
                            return idx, None, "No data"

                        item = data_list[0]
                        b64_data = item.get("b64_json", "")
                        if b64_data:
                            return idx, f"data:image/png;base64,{b64_data}", None

                        img_url = item.get("url", "")
                        if not img_url:
                            return idx, None, "No URL/b64"

                        resp_img = await asyncio.wait_for(
                            asyncio.to_thread(sync_requests.get, img_url, timeout=15),
                            timeout=18,
                        )
                        b64_data = base64.b64encode(resp_img.content).decode()
                        return idx, f"data:image/png;base64,{b64_data}", None

                    except asyncio.TimeoutError:
                        return idx, None, "Timeout"
                    except Exception as e:
                        return idx, None, str(e)

                tasks = [
                    generate_one_image(i, scenes[i]["video_prompt"], all_keys[i % len(all_keys)])
                    for i in range(image_count)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                completed = 0
                for result in results:
                    if isinstance(result, Exception):
                        continue
                    idx, img_url, err = result
                    if img_url:
                        scenes[idx]["image_url"] = img_url
                        yield _sse_event({
                            "type": "image_progress",
                            "index": idx,
                            "total": image_count,
                            "message": f"图片 {idx+1}/{image_count} 完成 ✅",
                            "progress": 0.6 + 0.35 * ((idx + 1) / max(image_count, 1)),
                        })
                    else:
                        scenes[idx]["image_url"] = None
                        yield _sse_event({
                            "type": "image_progress",
                            "index": idx,
                            "total": image_count,
                            "message": f"图片 {idx+1}/{image_count} 失败",
                            "progress": 0.6 + 0.35 * ((idx + 1) / max(image_count, 1)),
                        })
                    completed += 1

                yield _sse_event({
                    "type": "image_progress",
                    "message": f"共 {completed}/{image_count} 张图片生成完成",
                    "progress": 0.95,
                })

            # Done
            yield _sse_event({
                "type": "done",
                "scenes": scenes,
                "total_scenes": len(scenes),
            })
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[Storyboard] Preview failed: {e}")
            yield _sse_event({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/tasks/poetry")
async def create_poetry_task(
    poem_text: str = Form(...),
    creative_name: str = Form(""),
    user_scene_prompts_json: str = Form("[]"),
    style: str = Form("电影质感写实风格"),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    video_duration: int = Form(30),
    # ── 场景配置（与创意视频完全一致）──
    duration_source: str = Form("manual"),
    scene_count: int = Form(3),
    uniform_duration: bool = Form(True),
    scene_durations_json: str = Form("[5,5,5]"),
    # 音频配置（默认开启朗诵配音）
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("-15%"),
    audio_lang: str = Form(""),  # 页面语言，用于音色兼容性校验
    # 字幕配置（默认开启，固定诗歌样式，用户仅开关）
    subtitle_enabled: bool = Form(True),
):
    """创建诗词视频任务（类型 6）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    # v4.0: 音色与目标语言兼容性校验
    if audio_enabled:
        _validate_voice_compat(audio_voice, audio_lang or "zh")

    if not poem_text.strip():
        raise HTTPException(status_code=400, detail="古诗原文不能为空")
    if len(poem_text) > 2000:
        raise HTTPException(status_code=422, detail="古诗原文最多 2000 字符")
    if video_duration < 5 or video_duration > 300:
        raise HTTPException(status_code=422, detail="video_duration 范围 5-300 秒")
    if duration_source not in ("manual", "prompt"):
        raise HTTPException(status_code=422, detail="duration_source 必须为 manual 或 prompt")
    if duration_source == "manual":
        if scene_count < 1 or scene_count > 30:
            raise HTTPException(status_code=422, detail="scene_count 范围 1-30")
        # 解析场景时长 JSON
        try:
            scene_durations = json.loads(scene_durations_json)
            if not isinstance(scene_durations, list):
                raise ValueError("not a list")
        except Exception:
            raise HTTPException(status_code=422, detail="scene_durations_json 必须为 JSON 数组")
        for i, d in enumerate(scene_durations):
            if not isinstance(d, (int, float)) or d < 2 or d > 30:
                raise HTTPException(status_code=422, detail=f"场景 {i+1} 时长范围 2-30 秒")
    else:
        scene_durations = []

    # 解析可选分镜 prompt 列表（JSON 数组）
    try:
        user_scene_prompts = json.loads(user_scene_prompts_json)
        if not isinstance(user_scene_prompts, list):
            raise ValueError("not a list")
        user_scene_prompts = [str(p) for p in user_scene_prompts]
    except Exception:
        raise HTTPException(status_code=422, detail="user_scene_prompts_json 必须为 JSON 数组")

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"poetry_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    # 字幕使用固定诗歌样式，用户仅控制开关
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=POETRY_SUBTITLE_STYLE,
    )

    state = PoetryVideoTask(
        task_id=task_id,
        creative_name=name,
        poem_text=poem_text.strip(),
        user_scene_prompts=user_scene_prompts,
        style=style.strip() or "电影质感写实风格",
        video_width=video_width,
        video_height=video_height,
        video_duration=video_duration,
        duration_source=duration_source,
        scene_count=scene_count,
        uniform_duration=uniform_duration,
        scene_durations=scene_durations,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
    )

    pipeline = _create_pipeline_for_type(TaskType.POETRY, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Poetry] Task created: {task_id}, poem={poem_text[:20]!r} (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/anchor")
async def create_anchor_task(
    anchor_prompt: str = Form(""),
    anchor_reference_image: UploadFile = File(None),
    script_text: str = Form(...),
    audio_source: str = Form("post_stitch"),
    video_width: int = Form(768),
    video_height: int = Form(1344),
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("+0%"),
    audio_lang: str = Form(""),  # 页面语言，用于音色兼容性校验
    subtitle_enabled: bool = Form(True),
    subtitle_style_mode: str = Form("fixed"),
    subtitle_style_hints: str = Form(""),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(42),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
):
    """创建数字人口播任务（类型 4 / Phase 3）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    # v4.0: 音色与目标语言兼容性校验
    if audio_enabled:
        _validate_voice_compat(audio_voice, audio_lang or "zh")

    if not script_text.strip():
        raise HTTPException(status_code=400, detail="口播稿件不能为空")
    if len(script_text) > 50000:
        raise HTTPException(status_code=422, detail="口播稿件最多 50000 字符")

    task_id = uuid.uuid4().hex[:12]
    name = f"anchor_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=_build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=_parse_bg_color(subtitle_bg_color),
        style_mode=subtitle_style_mode,
        style_hints=subtitle_style_hints,
    )
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=subtitle_style,
    )

    # Handle uploaded reference image: save to upload dir and pass file path
    ref_image_path = ""
    if anchor_reference_image and anchor_reference_image.filename:
        ext = os.path.splitext(anchor_reference_image.filename)[1] or ".png"
        upload_dir = get_upload_dir()
        os.makedirs(upload_dir, exist_ok=True)
        ref_image_path = os.path.join(upload_dir, f"anchor_ref_{task_id}{ext}")
        with open(ref_image_path, "wb") as f:
            f.write(await anchor_reference_image.read())
        logger.info(f"[Anchor] Task {task_id} uploaded reference image saved to {ref_image_path}")

    state = AnchorVideoTask(
        task_id=task_id,
        creative_name=name,
        anchor_prompt=anchor_prompt,
        anchor_reference_image=ref_image_path,
        script_text=script_text.strip(),
        audio_source=audio_source,
        video_width=video_width,
        video_height=video_height,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
    )

    pipeline = _create_pipeline_for_type(TaskType.ANCHOR, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Anchor] Task created: {task_id}, script_len={len(script_text)} (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


# ═══════════════════════════════════════════════════
# 向后兼容：旧的 POST /api/tasks → 映射到 creative
# ═══════════════════════════════════════════════════


@app.post("/api/tasks")
async def create_task_legacy(
    idea: str = Form(...),
    creative_name: str = Form(""),
    user_requirement: str = Form("3个场景，每个场景10秒，电影质感"),
    style: str = Form("电影质感写实风格"),
    chaining_mode: str = Form("keyframes"),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    reference_image: UploadFile = File(None),
    end_frame_images: List[UploadFile] = File(None),
    use_custom_end_frames: bool = Form(False),
    generate_end_frames_from_ref: bool = Form(True),
):
    """向后兼容旧端点，映射到 create_creative_task。"""
    return await create_creative_task(
        idea=idea,
        creative_name=creative_name,
        user_requirement=user_requirement,
        style=style,
        chaining_mode=chaining_mode,
        video_width=video_width,
        video_height=video_height,
        reference_image=reference_image,
        end_frame_images=end_frame_images,
        use_custom_end_frames=use_custom_end_frames,
        generate_end_frames_from_ref=generate_end_frames_from_ref,
        # 提供音频/字幕默认值（旧端点不传这些参数）
        audio_enabled=False,
        audio_voice="zh-CN-XiaoxiaoNeural",
        audio_rate="+0%",
        subtitle_enabled=True,
        subtitle_font="STHeitiMedium.ttc",
        subtitle_color="white",
        subtitle_fontsize=48,
        subtitle_position="bottom",
        subtitle_stroke_color="black",
        subtitle_stroke_width=2,
        subtitle_bg_color="black@0.5",
    )


# ═══════════════════════════════════════════════════
# 故事创作者任务（Type STORY — v5.1）
# ═══════════════════════════════════════════════════


@app.post("/api/tasks/story")
async def create_story_task(
    story_title: str = Form(""),
    story_genre: str = Form(""),
    story_theme: str = Form(""),
    story_summary: str = Form(""),
    story_synopsis: str = Form(""),
    characters: str = Form("[]"),  # JSON array of character objects
    scenes: str = Form("[]"),       # JSON array of scene objects
    art_style: str = Form("cinematic realistic"),
    camera_style: str = Form("cinematic"),
    color_tone: str = Form("natural"),
    lighting: str = Form("natural lighting"),
    music_mood: str = Form(""),
    aspect_ratio: str = Form("16:9"),
    custom_instructions: str = Form(""),
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("+0%"),
    subtitle_enabled: bool = Form(True),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(48),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
):
    """Create a Master Story Creator task (Type STORY).

    用户传入完整故事数据：角色、场景、风格、自定义指令。
    系统生成视频提示词 → 角色参考 → 逐场景视频 → TTS + 字幕 → 最终视频。
    """
    from models.task import CreateStoryTaskRequest, StoryStyle, AudioConfig, SubtitleConfig, SubtitleStyle

    # Parse characters and scenes from JSON
    char_list = json.loads(characters)
    scene_list = json.loads(scenes)

    # Normalize character fields: description → appearance (model expects "appearance")
    for c in char_list:
        if isinstance(c, dict) and "description" in c:
            c["appearance"] = c.pop("description")

    # Build style
    style = StoryStyle(
        art_style=art_style,
        camera_style=camera_style,
        color_tone=color_tone,
        lighting=lighting,
        music_mood=music_mood,
        aspect_ratio=aspect_ratio,
    )

    # Build audio/subtitle config
    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=subtitle_bg_color,
    )
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=subtitle_style,
    )

    req = CreateStoryTaskRequest(
        story_title=story_title,
        story_genre=story_genre,
        story_theme=story_theme,
        story_summary=story_summary,
        story_synopsis=story_synopsis,
        characters=char_list,
        scenes=scene_list,
        art_style=art_style,
        camera_style=camera_style,
        color_tone=color_tone,
        lighting=lighting,
        music_mood=music_mood,
        aspect_ratio=aspect_ratio,
        custom_instructions=custom_instructions,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
    )

    # Validate aspect ratio
    video_width, video_height = 1152, 768  # 16:9 default
    if aspect_ratio == "9:16":
        video_width, video_height = 768, 1152  # 9:16 portrait
    elif aspect_ratio == "1:1":
        video_width, video_height = 1024, 1024

    return await _create_story_task_impl(
        req=req,
        video_width=video_width,
        video_height=video_height,
    )


async def _create_story_task_impl(req, video_width: int, video_height: int) -> JSONResponse:
    """Internal implementation for story task creation."""
    from models.task import StoryTaskState, StoryCharacter, StoryScene, StoryStyle, TaskType

    state = StoryTaskState(
        task_type=TaskType.STORY,
        creative_name=req.story_title or "Story Video",
        video_width=video_width,
        video_height=video_height,
        story_title=req.story_title,
        story_genre=req.story_genre,
        story_theme=req.story_theme,
        story_summary=req.story_summary,
        story_synopsis=req.story_synopsis,
        characters=req.characters,  # List of dicts → will be converted
        scenes=req.scenes,  # List of dicts → will be converted
        style=StoryStyle(
            art_style=req.art_style,
            camera_style=req.camera_style,
            color_tone=req.color_tone,
            lighting=req.lighting,
            music_mood=req.music_mood,
            aspect_ratio=req.aspect_ratio,
        ),
        custom_instructions=req.custom_instructions,
        audio_config=req.audio_config,
        subtitle_config=req.subtitle_config,
    )

    # Create task and start pipeline
    import uuid, os, time
    task_id = f"story_{uuid.uuid4().hex[:12]}"
    dir_name = f"story_{int(time.time()*1000)}"
    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)

    logger.info(
        "[Story] Task %s created: '%s' (%d characters, %d scenes)",
        task_id, req.story_title, len(state.characters), len(state.scenes),
    )

    # Start pipeline in background
    asyncio.create_task(_run_story_pipeline(task_id, dir_name))

    return JSONResponse({
        "task_id": task_id,
        "status": "created",
        "message": f"Story task '{req.story_title}' created with {len(state.characters)} characters and {len(state.scenes)} scenes",
    })


async def _run_story_pipeline(task_id: str, dir_name: str) -> None:
    """Background task runner for story pipeline."""
    from models.task import StoryTaskState, parse_task_state
    from core.api.agnes_video import AgnesVideoAPI
    from core.screenwriter import Screenwriter
    from core.pipelines.story_video import StoryVideoPipeline
    import traceback

    try:
        logger.info("[Story] Starting pipeline for task %s", task_id)
        tm = TaskManager(task_id, dir_name=dir_name)
        state = tm.load()
        if not isinstance(state, StoryTaskState):
            logger.error("[Story] Invalid state type for task %s", task_id)
            return

        # Convert character dicts to proper objects
        if state.characters and isinstance(state.characters[0], dict):
            state.characters = [
                StoryCharacter(**c) if isinstance(c, dict) else c
                for c in state.characters
            ]

        # Convert scene dicts to proper objects
        if state.scenes and isinstance(state.scenes[0], dict):
            state.scenes = [
                StoryScene(**s) if isinstance(s, dict) else s
                for s in state.scenes
            ]

        api_key = get_api_key()
        style_hint = state.style.art_style if state.style else ""

        video_api = AgnesVideoAPI(api_key=api_key)
        video_api.set_refresh_key_callback(get_api_key)

        pipeline = StoryVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
        )
        pipeline._screenwriter = Screenwriter(api_key=api_key)
        pipeline.video_api = video_api

        final_path = await pipeline.run(state)
        logger.info("[Story] Pipeline completed: %s → %s", task_id, final_path)

    except Exception as e:
        logger.error("[Story] Pipeline error for task %s: %s\n%s", task_id, e, traceback.format_exc())
        try:
            tm = TaskManager(task_id, dir_name=dir_name)
            tm.update_state(status="failed", current_message=str(e))
        except Exception:
            pass


@app.get("/api/poetry-scene-prompt")
async def poetry_scene_prompt(
    poem: str = "",
    scene_count: int = 0,
    scene_durations: str = "",
    total_duration: int = 30,
    style: str = "",
):
    """返回已填充的诗歌分镜提示词（中文），供前端展示与复制。

    参数与内部 LLM 使用的完全一致（scene_count / scene_durations / total_duration / style），
    因此用户拿去任意 LLM 生成、再把「原诗句 | 画面描述」行格式贴回，与系统内生成结果一致。
    """
    import json
    from core.screenwriter import build_poetry_scene_prompt
    try:
        durations = json.loads(scene_durations) if scene_durations else []
    except (ValueError, TypeError):
        durations = []
    if not isinstance(durations, list):
        durations = []
    return build_poetry_scene_prompt(
        poem=poem,
        scene_count=scene_count,
        scene_durations=[int(d) for d in durations if str(d).isdigit()],
        total_duration=total_duration,
        style=style,
    )


@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    # 关键段串行化：check 与 insert 之间存在多个 await 让出点，快速重复 resume
    # 会让两次请求都通过 "task not in active_pipelines" 检查并各自启动 pipeline，
    # 导致同任务双重运行、状态文件交叉写入。
    async with _get_pipeline_lock(task_id):
        if task_id in active_pipelines:
            existing = active_pipelines[task_id]
            if existing._stop_event.is_set():
                logger.info(f"[Resume] Replacing stopped pipeline for task {task_id}")
                del active_pipelines[task_id]
            else:
                raise HTTPException(status_code=400, detail="Task is already running")

        dir_name = _find_dir_name(task_id)
        tm = TaskManager(task_id, dir_name=dir_name)
        state = tm.load()
        if not state:
            raise HTTPException(status_code=404, detail="Task not found")

        if state.status == StepStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="Task is already completed")

        logger.info(f"[Resume] Starting resume for task {task_id}, type={state.task_type}, status={state.status}")

        # v2.0：根据 task_type 选择对应的 Pipeline
        pipeline = _create_pipeline_for_type(state.task_type, api_key, task_id, dir_name)
        active_pipelines[task_id] = pipeline

        _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    if task_id not in active_pipelines and task_id not in _queued_tasks:
        raise HTTPException(status_code=400, detail="Task is not running")

    # 停止运行中的 pipeline
    if task_id in active_pipelines:
        pipeline = active_pipelines[task_id]
        pipeline.stop()

    dir_name = _find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if state and state.status in (StepStatus.RUNNING, StepStatus.QUEUED):
        tm.update_state(status=StepStatus.PENDING)
        logger.info(f"[Stop] Task {task_id} status -> pending")

    logger.info(f"[Stop] Task {task_id} stop requested")
    return {"ok": True, "task_id": task_id}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task and all its generated files from disk."""
    # Check if task is running
    if task_id in active_pipelines:
        raise HTTPException(status_code=400, detail="Cannot delete a running task. Stop it first.")
    if task_id in _queued_tasks:
        _queued_tasks.pop(task_id)
        logger.info(f"[Delete] Removed queued task {task_id}")

    # Find and remove working directory
    dir_name = _find_dir_name(task_id)
    if dir_name:
        task_dir = os.path.join(get_working_dir(), dir_name)
        if os.path.exists(task_dir):
            import shutil
            shutil.rmtree(task_dir, ignore_errors=True)
            logger.info(f"[Delete] Removed task directory: {task_dir}")

    # Remove from active_pipelines if present
    active_pipelines.pop(task_id, None)

    return {"ok": True, "task_id": task_id, "message": "Task deleted"}


# ═══════════════════════════════════════════════════
# 并发状态接口
# ═══════════════════════════════════════════════════


@app.get("/api/concurrency")
async def get_concurrency_status():
    """返回当前并发控制状态：已用权重、上限、排队任务列表。"""
    running_tasks = []
    for tid, pl in active_pipelines.items():
        if tid not in _queued_tasks:
            # 真正在运行的（已获取信号量）
            running_tasks.append({
                "task_id": tid,
                "type": getattr(pl, '_task_type', 'unknown'),
            })

    queued = [
        {"task_id": tid, "weight": w}
        for tid, w in _queued_tasks.items()
    ]

    return {
        "ok": True,
        "max_weight": _pipeline_semaphore.max_weight,
        "current_weight": _pipeline_semaphore.current,
        "utilization": round(_pipeline_semaphore.utilization, 2),
        "running_count": len(running_tasks),
        "queued_count": len(queued),
        "queued_tasks": queued,
        "rate_limit_per_min": _AGNES_RATE_LIMIT,
        "task_weights": {k.value: v for k, v in TASK_TYPE_WEIGHTS.items()},
    }


# ═══════════════════════════════════════════════════
# 回归测试清理
# ═══════════════════════════════════════════════════

@app.post("/api/cleanup-regression")
async def cleanup_regression():
    """安全清理回归测试产物（报告、日志、任务目录）。

    只删除产物清单中记录的内容，不影响用户原有任务数据。
    """
    working_dir = get_working_dir()
    manifest_path = os.path.join(working_dir, ".regression_manifest.json")

    if not os.path.exists(manifest_path):
        raise HTTPException(
            status_code=404,
            detail="未找到回归测试产物清单，可能没有执行过回归测试")

    try:
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"读取清单失败: {e}")

    removed_dirs = 0
    removed_files = 0
    errors: list = []
    project_root = os.path.dirname(os.path.abspath(__file__))
    upload_dir = os.path.join(working_dir, "uploads")

    # 1. 清理任务目录
    for dir_name in manifest.get("task_dirs", []):
        dir_path = os.path.join(working_dir, dir_name)
        if os.path.isdir(dir_path):
            try:
                shutil.rmtree(dir_path)
                removed_dirs += 1
            except OSError as e:
                errors.append(f"删除目录失败 {dir_name}: {e}")

    # 2. 清理上传文件
    for fname in manifest.get("uploads", []):
        fpath = os.path.join(upload_dir, fname)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
                removed_files += 1
            except OSError as e:
                errors.append(f"删除上传文件失败 {fname}: {e}")

    # 3. 清理报告文件
    for rel_path in manifest.get("reports", []):
        abs_path = os.path.join(project_root, rel_path)
        if os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
                removed_files += 1
            except OSError as e:
                errors.append(f"删除报告失败 {rel_path}: {e}")

    # 4. 清理服务器日志
    log_rel = manifest.get("server_log", "")
    if log_rel:
        log_path = os.path.join(project_root, log_rel)
        if os.path.isfile(log_path):
            try:
                os.remove(log_path)
                removed_files += 1
            except OSError as e:
                errors.append(f"删除日志失败: {e}")

    # 5. 清理清单本身
    try:
        os.remove(manifest_path)
        removed_files += 1
    except OSError as e:
        errors.append(f"删除清单失败: {e}")

    scenarios_cleaned = len(manifest.get("scenarios", {}))
    logger.info(
        f"[Cleanup] 回归清理完成: {removed_dirs} 目录, "
        f"{removed_files} 文件, {scenarios_cleaned} 场景")

    return {
        "ok": len(errors) == 0,
        "removed_dirs": removed_dirs,
        "removed_files": removed_files,
        "scenarios_cleaned": scenarios_cleaned,
        "errors": errors,
    }


# ═══════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════


if __name__ == "__main__":
    import uvicorn

    config = uvicorn.Config(app, host="0.0.0.0", port=8765, log_level="info")
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
