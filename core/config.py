"""
core/config.py — Agnes Video Generator v2.0 配置模块

包含 API Key 管理、工作目录、音频/字幕默认配置工厂函数。
"""

import json
import logging
import os
import threading
import time
from typing import List, Optional

from models.task import AudioConfig, SubtitleConfig, SubtitleStyle

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".agnes_config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def font_dir() -> str:
    """返回项目内置字体目录。"""
    return os.path.join(_PROJECT_ROOT, "resource", "fonts")


# 默认中文字体文件名（需位于 resource/fonts/ 下）
DEFAULT_CHINESE_FONT = "STHeitiMedium.ttc"

# 不支持 CJK 字符的常见字体名（用于向后兼容旧任务）
# 这些字体在 moviepy/pillow TextClip 中无法正确渲染中文，
# 检测到后自动回退到 DEFAULT_CHINESE_FONT。
_NON_CJK_FONTS = frozenset({
    "arial", "arial bold", "arial italic", "arial black",
    "helvetica", "times", "times new roman", "courier",
    "courier new", "verdana", "tahoma", "georgia", "trebuchet ms",
    "impact", "comic sans ms", "lucida console",
})


def resolve_font_path(font: str) -> str:
    """将字体名称解析为 moviepy TextClip 可用的路径。

    优先级：
    1. 绝对路径且文件存在 → 直接返回
    2. 文件名（含扩展名）→ 在 resource/fonts/ 目录下查找
    3. 已知的非 CJK 字体名 → 回退到 DEFAULT_CHINESE_FONT（兼容旧任务）
    4. 其他系统字体名 → 直接返回
    """
    # 已经是绝对路径，直接返回
    if os.path.isabs(font) and os.path.exists(font):
        return font

    # 看起来像文件名（含扩展名），尝试在项目字体目录查找
    if "." in font and "/" not in font and "\\" not in font:
        candidate = os.path.join(font_dir(), font)
        if os.path.exists(candidate):
            return candidate

    # 检查是否为已知的非 CJK 字体（向后兼容：旧任务的 font 可能仍为 "Arial"）
    if font.strip().lower() in _NON_CJK_FONTS:
        fallback = os.path.join(font_dir(), DEFAULT_CHINESE_FONT)
        if os.path.exists(fallback):
            logger.warning(
                f"Font '{font}' does not support CJK characters, "
                f"falling back to {DEFAULT_CHINESE_FONT}"
            )
            return fallback

    # 当作系统字体名称返回
    return font


# ═══════════════════════════════════════════════════
# API Key 管理（多 key 轮转 + 单 key 向后兼容）
# ═══════════════════════════════════════════════════


# ── 多 key 轮转状态（进程内，不持久化） ──
# _key_rotation_lock 串行化 _next_key() 和 mark_key_429()
_key_rotation_lock = threading.Lock()
_key_index = 0           # round-robin 游标
_key_cooldown = {}       # key -> cooldown_until timestamp (0 = 可用)


def _ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    # 目录权限收紧为仅属主可读写执行，避免其他用户读取其中的 api_key
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass


def load_config() -> dict:
    _ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    _ensure_config_dir()
    # 原子写：先写临时文件再 os.replace，避免写入中途崩溃留下损坏 JSON
    tmp_path = CONFIG_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    # 配置含 api_key，权限收紧为仅属主可读写
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, CONFIG_FILE)


def get_api_keys() -> List[str]:
    """返回所有已配置的 API Key 列表（去重、去空）。

    优先级：
    1. 环境变量 AGNES_API_KEYS（逗号分隔，多个）
    2. 环境变量 AGNES_API_KEY（单个，向后兼容）
    3. 配置文件中的 api_keys 列表
    4. 配置文件中的 api_key（单个，向后兼容）
    """
    env_keys = os.environ.get("AGNES_API_KEYS", "")
    if env_keys:
        keys = [k.strip() for k in env_keys.split(",") if k.strip()]
        if keys:
            return _dedup(keys)
    env_key = os.environ.get("AGNES_API_KEY", "")
    if env_key:
        return [env_key]
    config = load_config()
    multi = config.get("api_keys", [])
    if multi:
        return _dedup([k for k in multi if k])
    single = config.get("api_key", "")
    if single:
        return [single]
    return []


def _dedup(keys: List[str]) -> List[str]:
    """去重保序。"""
    seen = set()
    result = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result


def set_api_keys(keys: List[str]):
    """保存多个 API Key。同时清除旧的 api_key 字段以避免混淆。"""
    keys = [k.strip() for k in keys if k and k.strip()]
    config = load_config()
    config["api_keys"] = keys
    # 保留 api_key 字段（向后兼容旧代码），设为第一个 key
    if keys:
        config["api_key"] = keys[0]
    else:
        config.pop("api_key", None)
    save_config(config)
    # 重置轮转状态
    global _key_index, _key_cooldown
    with _key_rotation_lock:
        _key_index = 0
        _key_cooldown = {}


def get_api_key() -> str:
    """返回当前轮转到的可用 API Key（向后兼容单 key 调用）。

    若所有 key 都在冷却中，返回最早冷却到期的 key。
    若没有任何 key 配置，返回空字符串。
    """
    keys = get_api_keys()
    if not keys:
        return ""
    if len(keys) == 1:
        return keys[0]
    return _next_key(keys)


def _next_key(keys: List[str]) -> str:
    """Round-robin 选择下一个未冷却的 key。"""
    global _key_index, _key_cooldown
    now = time.time()
    with _key_rotation_lock:
        # 尝试找一个未冷却的 key
        for _ in range(len(keys)):
            idx = _key_index % len(keys)
            _key_index += 1
            key = keys[idx]
            cooldown_until = _key_cooldown.get(key, 0)
            if now >= cooldown_until:
                return key
        # 所有 key 都在冷却中 → 返回最早冷却到期的
        earliest_key = min(keys, key=lambda k: _key_cooldown.get(k, float("inf")))
        logger.warning(
            f"[KeyRotation] All {len(keys)} keys in cooldown, "
            f"using earliest-expiring key"
        )
        return earliest_key


def mark_key_429(key: str, cooldown_seconds: int = 120):
    """标记某个 key 遇到 429，冷却一段时间不用。"""
    global _key_cooldown
    with _key_rotation_lock:
        _key_cooldown[key] = time.time() + cooldown_seconds
        logger.warning(
            f"[KeyRotation] Key {key[:8]}... cooling down for {cooldown_seconds}s"
        )


def get_key_rotation_status() -> dict:
    """返回各 key 的轮转状态（用于 UI 展示）。"""
    keys = get_api_keys()
    now = time.time()
    with _key_rotation_lock:
        status = []
        for i, k in enumerate(keys):
            cd = _key_cooldown.get(k, 0)
            status.append({
                "index": i,
                "masked": k[:8] + "..." if k else "",
                "cooling_down": now < cd,
                "cooldown_remaining": max(0, int(cd - now)),
            })
    return {"total_keys": len(keys), "keys": status}


def set_api_key(key: str):
    """保存单个 API Key（向后兼容）。同时更新 api_keys 列表。"""
    set_api_keys([key] if key else [])


def delete_api_key() -> bool:
    """Remove the API key from the config file.

    Returns:
        True if a key was removed, False if no key existed.

    Note:
        This does NOT affect the AGNES_API_KEY environment variable.
        If the env var is set, get_api_key() will still return it.
    """
    config = load_config()
    had_key = bool(config.get("api_key") or config.get("api_keys"))
    config.pop("api_key", None)
    config.pop("api_keys", None)
    save_config(config)
    global _key_index, _key_cooldown
    with _key_rotation_lock:
        _key_index = 0
        _key_cooldown = {}
    return had_key


def get_api_key_source() -> str:
    """Return the source of the current API key.

    Returns:
        'env' if from AGNES_API_KEY environment variable,
        'config' if from the config file,
        'none' if no key is configured.
    """
    if os.environ.get("AGNES_API_KEY", "") or os.environ.get("AGNES_API_KEYS", ""):
        return "env"
    config = load_config()
    if config.get("api_key") or config.get("api_keys"):
        return "config"
    return "none"


# ═══════════════════════════════════════════════════
# 工作目录管理（多工作目录，同时仅一个 active）
# ═══════════════════════════════════════════════════

# 回归测试专用工作目录环境变量名
REGRESSION_WORKING_DIR_ENV = "AGNES_REGRESSION_WORKING_DIR"

# 默认工作目录的固定名称标识
DEFAULT_WORKSPACE_NAME = "默认空间"


def _default_working_dir() -> str:
    """默认工作目录（项目根目录下的 .working_dir）。"""
    return os.path.join(_PROJECT_ROOT, ".working_dir")


def _default_workspace_entry() -> dict:
    """返回默认工作目录条目。"""
    return {"path": _default_working_dir(), "name": DEFAULT_WORKSPACE_NAME, "is_default": True}


def get_working_dir() -> str:
    """返回当前激活的工作目录。

    优先级：
    1. 环境变量 AGNES_REGRESSION_WORKING_DIR（回归测试专用空间，最高优先级）
    2. 配置文件中的 active_workspace
    3. 默认 .working_dir
    """
    env_dir = os.environ.get(REGRESSION_WORKING_DIR_ENV, "")
    if env_dir:
        return env_dir
    config = load_config()
    active = config.get("active_workspace", "")
    if active:
        return active
    return _default_working_dir()


def get_workspaces() -> list:
    """返回所有已配置的工作目录列表（含默认空间，始终排在首位）。

    Returns:
        [{"path": "...", "name": "...", "is_default": bool}, ...]
    """
    config = load_config()
    user_workspaces = config.get("workspaces", [])
    default_path = _default_working_dir()
    filtered = [ws for ws in user_workspaces if os.path.abspath(ws.get("path", "")) != default_path]
    return [_default_workspace_entry()] + filtered


def add_workspace(path: str, name: str = "") -> dict:
    """添加一个工作目录。若路径已存在则更新名称。

    Returns:
        添加后的工作目录条目
    """
    path = os.path.abspath(path)
    config = load_config()
    workspaces = config.get("workspaces", [])
    for ws in workspaces:
        if os.path.abspath(ws.get("path", "")) == path:
            if name:
                ws["name"] = name
            save_config(config)
            return ws
    entry = {"path": path, "name": name or os.path.basename(path) or path}
    workspaces.append(entry)
    config["workspaces"] = workspaces
    if not config.get("active_workspace"):
        config["active_workspace"] = path
    save_config(config)
    return entry


def remove_workspace(path: str) -> bool:
    """移除一个工作目录。默认空间不可移除。

    若移除的是当前激活项，则激活默认空间。

    Returns:
        True if removed, False if not found or is default
    """
    path = os.path.abspath(path)
    if path == _default_working_dir():
        return False
    config = load_config()
    workspaces = config.get("workspaces", [])
    new_list = [ws for ws in workspaces if os.path.abspath(ws.get("path", "")) != path]
    if len(new_list) == len(workspaces):
        return False
    config["workspaces"] = new_list
    if os.path.abspath(config.get("active_workspace", "")) == path:
        config.pop("active_workspace", None)
    save_config(config)
    return True


def get_active_workspace() -> str:
    """返回当前激活的工作目录路径。"""
    return get_working_dir()


def set_active_workspace(path: str) -> str:
    """设置当前激活的工作目录。路径必须已在列表中（含默认空间）。

    Returns:
        激活的工作目录路径

    Raises:
        ValueError: 路径不在已配置列表中
    """
    path = os.path.abspath(path)
    valid_paths = [os.path.abspath(ws.get("path", "")) for ws in get_workspaces()]
    if path not in valid_paths:
        raise ValueError(f"工作目录未配置: {path}")
    config = load_config()
    if path == _default_working_dir():
        config.pop("active_workspace", None)
    else:
        config["active_workspace"] = path
    save_config(config)
    return path


# ═══════════════════════════════════════════════════
# v2.0 新增：音频 / 字幕默认配置
# ═══════════════════════════════════════════════════

# D3：默认语音角色
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

# D3：可选语音角色列表（v4.0 起改为运行时从 edge_tts 动态加载，见 core.audio.voices）。
# 保留 AVAILABLE_VOICES 作为向后兼容的别名（返回扁平列表），新代码请使用 get_voice_catalog()。
from core.audio.voices import (
    get_voice_catalog,
    get_voice_by_id,
    get_voice_lang,
    is_voice_compatible,
    is_voice_compatible_with_text,
    load_voice_catalog,
    VOICE_PREVIEW_TEXTS,
    LANG_COMPAT,
    PROJECT_LANGUAGES,
)

def AVAILABLE_VOICES() -> list:
    """向后兼容：返回扁平化的 [{id, label}, ...] 列表。

    原接口签名是模块级列表，升级为函数以保证与旧调用方兼容。
    """
    cat = get_voice_catalog()
    result = []
    for group in cat.get("languages", []):
        for v in group.get("voices", []):
            result.append({"id": v["id"], "label": f"{v['name']}（{v['region']}）"})
    return result


def get_default_subtitle_style() -> SubtitleStyle:
    """返回默认字幕样式配置（D4）。"""
    return SubtitleStyle(
        font=DEFAULT_CHINESE_FONT,
        color="white",
        position=("center", "bottom-80"),
        fontsize=48,
        stroke_color="black",
        stroke_width=2,
        bg_color=(0, 0, 0, 128),
    )


def get_default_subtitle_config() -> SubtitleConfig:
    """返回默认字幕配置（v3.0 独立配置）。"""
    return SubtitleConfig(
        enabled=True,
        style=get_default_subtitle_style(),
    )


def get_default_audio_config() -> AudioConfig:
    """返回默认音频配置（D3）。"""
    return AudioConfig(
        enabled=True,
        voice=DEFAULT_VOICE,
        rate="+0%",
    )


# ═══════════════════════════════════════════════════
# 水印配置
# ═══════════════════════════════════════════════════

DEFAULT_WATERMARK_ENABLED = False
DEFAULT_WATERMARK_LANGUAGE = "auto"  # "auto" | "zh" | "en"

WATERMARK_PROMO_TEXT_ZH = "为视频添加 Agnes Video Generator 水印，分享时让更多人发现这个工具"
WATERMARK_PROMO_TEXT_EN = "Add an Agnes Video Generator watermark to help more creators discover this tool"


def get_watermark_config() -> dict:
    """返回水印配置。

    Returns:
        {"enabled": bool, "language": str}
    """
    config = load_config()
    wm = config.get("watermark", {})
    return {
        "enabled": wm.get("enabled", DEFAULT_WATERMARK_ENABLED),
        "language": wm.get("language", DEFAULT_WATERMARK_LANGUAGE),
    }


def set_watermark_config(enabled: bool = None, language: str = None):
    """设置水印配置。

    Args:
        enabled: 是否开启水印，None 表示不修改
        language: 水印语言，None 表示不修改
    """
    config = load_config()
    wm = config.get("watermark", {})
    if enabled is not None:
        wm["enabled"] = enabled
    if language is not None:
        wm["language"] = language
    config["watermark"] = wm
    save_config(config)


# ═══════════════════════════════════════════════════
# 视频参数预设（D7）
# ═══════════════════════════════════════════════════

VIDEO_RESOLUTION_PRESETS = {
    "portrait": {"width": 768, "height": 1152, "label": "竖屏 9:16"},
    "landscape": {"width": 1152, "height": 768, "label": "横屏 16:9"},
    "square": {"width": 1024, "height": 1024, "label": "方形 1:1"},
}

# 时长 → (num_frames, frame_rate) 映射
DURATION_FRAME_MAP = {
    5: (121, 24),
    10: (241, 24),
    15: (361, 24),
    18: (441, 24),
    20: (441, 22),
}
