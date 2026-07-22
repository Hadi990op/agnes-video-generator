"""core.api.agnes_models — 拉取 Agnes 可用模型列表（v5.0）

封装 GET /v1/models?all=true，按模型 ID 前缀分组为 text/image/video 三类。
接口失败（网络/鉴权/非 200）时回退到硬编码默认列表，保证 UI 始终可用。
"""

import logging

import requests

from core.api.agnes_chat import BASE_URL
from core.config import (
    DEFAULT_TEXT_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODEL,
)

logger = logging.getLogger(__name__)

# 带 beta 开关的模型列表端点：裸 /v1/models 会被网关过滤掉内测模型，
# 加 ?all=true（等价 X-Beta-Access: true / ?include_beta=true）才会返回全量（含 2.5-flash）。
MODELS_ENDPOINT = f"{BASE_URL}/models?all=true"

REQUEST_TIMEOUT = 20

# 分组失败时的兜底列表
_FALLBACK = {
    "text": [DEFAULT_TEXT_MODEL],
    "image": [DEFAULT_IMAGE_MODEL],
    "video": [DEFAULT_VIDEO_MODEL],
}


def _classify(model_id: str) -> str:
    """根据模型 ID 前缀判断分组。

    - ``agnes-image*`` → image
    - ``agnes-video*`` → video
    - 其余（如 ``agnes-2.0-flash`` / ``agnes-2.5-flash``）→ text
    """
    if model_id.startswith("agnes-image"):
        return "image"
    if model_id.startswith("agnes-video"):
        return "video"
    return "text"


def fetch_available_models(api_key: str) -> dict:
    """拉取并按类型分组 Agnes 可用模型。

    Args:
        api_key: Agnes API Key（Bearer Token）。

    Returns:
        {"text": [model_id, ...], "image": [...], "video": [...]}
        接口失败（网络/鉴权/非 200）时返回硬编码兜底列表。
    """
    try:
        resp = requests.get(
            MODELS_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(
                "[AgnesModels] /v1/models returned HTTP %s, using fallback",
                resp.status_code,
            )
            return dict(_FALLBACK)
        data = resp.json()
        grouped = {"text": [], "image": [], "video": []}
        for item in data.get("data", []):
            mid = item.get("id")
            if not mid:
                continue
            grouped[_classify(mid)].append(mid)
        # 任一分类为空则补回默认，避免 UI 空下拉
        for k, default in _FALLBACK.items():
            if not grouped[k]:
                grouped[k] = list(default)
        return grouped
    except Exception as e:  # noqa: BLE001
        logger.warning("[AgnesModels] fetch failed (%s), using fallback", e)
        return dict(_FALLBACK)
