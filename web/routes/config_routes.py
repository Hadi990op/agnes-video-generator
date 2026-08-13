"""配置类路由：API Key、模型、水印、域名。"""
from __future__ import annotations

import os
import re
import time
from typing import List, Optional

from fastapi import APIRouter, Form, HTTPException

from core.api.agnes_models import fetch_available_models
from core.api.key_manager import reset_key_ring
from core.api.rate_limiter import reset_rate_limiter
from core.config import (
    AGNES_DOMAIN_MAP,
    REGRESSION_WORKING_DIR_ENV,
    WATERMARK_PROMO_TEXT_EN,
    WATERMARK_PROMO_TEXT_ZH,
    delete_api_key,
    get_active_workspace,
    get_agnes_domain,
    get_api_key,
    get_api_key_source,
    get_api_keys,
    get_api_keys_source,
    get_selected_models,
    get_watermark_config,
    get_workspaces,
    set_agnes_domain,
    set_api_key,
    set_api_keys,
    set_selected_models,
    set_watermark_config,
)

router = APIRouter(tags=["config"])

# 模型列表服务端缓存，避免每次页面加载都打外部接口（apihub.agnes-ai.com）导致变慢。
# TTL 默认 5 分钟；?refresh=1 或缓存过期时重新拉取。
_MODEL_CACHE = {"models": None, "ts": 0.0, "ttl": 300}


@router.get("/api/config")
async def get_config():
    key = get_api_key()
    source = get_api_key_source()
    active_ws = get_active_workspace()
    wm = get_watermark_config()
    data = {
        "api_key": key[:8] + "..." if key else "",
        "source": source,
        "can_clear": source == "config",
        "workspaces": get_workspaces(),
        "active_workspace": active_ws,
        "working_dir_source": "regression" if os.environ.get(REGRESSION_WORKING_DIR_ENV) else "config",
        "watermark": wm,
        "watermark_promo_zh": WATERMARK_PROMO_TEXT_ZH,
        "watermark_promo_en": WATERMARK_PROMO_TEXT_EN,
        "models": get_selected_models(),
        "agnes_domain": get_agnes_domain(),
        "agnes_domains": list(AGNES_DOMAIN_MAP.keys()),
    }
    return data


@router.post("/api/config")
async def save_config(api_key: str = Form(...)):
    set_api_key(api_key)
    return {"ok": True}


@router.delete("/api/config")
async def clear_config():
    """Delete the API key(s) from the config file（api_key 与 api_keys 一并清除）。"""
    source = get_api_key_source()
    if source == "env":
        raise HTTPException(
            status_code=400,
            detail="API Key 来自环境变量，无法从界面清除",
        )
    delete_api_key()
    # 清除后重建 KeyRing 与限速器（回退到 env 采集 / 空）
    reset_key_ring()
    reset_rate_limiter()
    return {"ok": True}


# ═══════════════════════════════════════════════════
# 多 API Key（优化 1：多 Key 轮询 + 限流整合）
# ═══════════════════════════════════════════════════

@router.get("/api/config/keys")
async def get_config_keys():
    """返回 Key 数量与来源（永不回传 Key 明文）。

    Returns:
        {"ok": true, "key_count": int, "source": "env:N|config:N|mixed:...|none"}
    """
    keys = get_api_keys()
    return {
        "ok": True,
        "key_count": len(keys),
        "source": get_api_keys_source(),
    }


@router.post("/api/config/keys")
async def save_config_keys(keys_json: str = Form(...)):
    """设置多 API Key（JSON 数组或逗号/换行分隔文本）。

    保存后立即重建 KeyRing 与限速器，使新 Key 数与配额即时生效（无需重启）。
    空数组/空串则回退到 env 采集（移除配置文件中的 api_keys 字段）。

    Args:
        keys_json: JSON 数组字符串（如 '["k1","k2"]'）或普通逗号/换行分隔文本。
    """
    import json as _json

    raw = (keys_json or "").strip()
    keys = []
    if raw:
        try:
            parsed = _json.loads(raw)
            if isinstance(parsed, list):
                keys = [str(k).strip() for k in parsed]
            else:
                keys = [str(parsed).strip()]
        except _json.JSONDecodeError:
            # 非 JSON：按逗号/换行/空白分隔拆分
            keys = [k.strip() for k in re.split(r"[\s,，;；]+", raw)]
    keys = [k for k in keys if k]
    set_api_keys(keys)
    # Key 数变化 → 重建 KeyRing 与限速器（共享桶 + 视频提交桶）
    reset_key_ring()
    reset_rate_limiter()
    return {
        "ok": True,
        "key_count": len(get_api_keys()),
        "source": get_api_keys_source(),
    }


@router.get("/api/models")
async def list_models(refresh: bool = False):
    """拉取 Agnes 可用模型列表，按 text/image/video 分组。

    需已配置 API Key。列表来自 GET /v1/models?all=true（含内测模型）。
    失败时回退到硬编码默认列表。

    结果在服务端缓存 TTL 秒；普通页面加载走缓存瞬时返回，
    仅“刷新列表”按钮（?refresh=1）或缓存过期时才重新请求外部接口。
    """
    key = get_api_key()
    if not key:
        raise HTTPException(status_code=400, detail="未配置 API Key")
    now = time.time()
    if (
        not refresh
        and _MODEL_CACHE["models"] is not None
        and (now - _MODEL_CACHE["ts"]) < _MODEL_CACHE["ttl"]
    ):
        return {"ok": True, "models": _MODEL_CACHE["models"], "cached": True}
    grouped = fetch_available_models(key)
    _MODEL_CACHE["models"] = grouped
    _MODEL_CACHE["ts"] = now
    return {"ok": True, "models": grouped, "cached": False}


@router.post("/api/config/models")
async def save_models(
    text: str = Form(None),
    image: str = Form(None),
    video: str = Form(None),
):
    """保存选中的模型配置。

    text 为必填（目前仅文本模型开放选择）；image/video 接受但不强制，
    置灰时前端仍会随配置保存其值（缺省回退到当前默认值）。
    """
    if text is None or text.strip() == "":
        raise HTTPException(status_code=400, detail="文本模型不能为空")
    result = set_selected_models(
        text=text or None,
        image=image,
        video=video,
    )
    return {"ok": True, "models": result}


@router.post("/api/config/watermark")
async def save_watermark_config(enabled: bool = Form(False)):
    """Save watermark toggle."""
    set_watermark_config(enabled=enabled)
    return {"ok": True, "enabled": enabled}


@router.post("/api/config/domain")
async def save_agnes_domain(domain: str = Form(...)):
    """设置 Agnes API 域名后缀。

    Args:
        domain: "com" 或 "cn"
    """
    domain = domain.strip().lower()
    if domain not in AGNES_DOMAIN_MAP:
        raise HTTPException(
            status_code=422,
            detail=f"域名后缀必须为 {list(AGNES_DOMAIN_MAP.keys())} 之一",
        )
    set_agnes_domain(domain)
    return {"ok": True, "agnes_domain": domain}
