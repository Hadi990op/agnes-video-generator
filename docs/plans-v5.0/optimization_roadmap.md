# 优化路线图（Optimization Roadmap）

> **文档定位**：本项目可落地的优化点清单与实现指引。本文为**自包含**文档——实施环节不依赖任何外部调研，每个优化点的实现方式、涉及文件、依赖变化、验收标准均已内嵌。实施某一项时，仅阅读对应章节即可独立开展。
>
> **优先级标记**：🔴 高（建议优先）| 🟡 中（可选）| 🟢 低（锦上添花）

---

## 目录

| # | 优化点 | 优先级 | 一句话价值 |
|---|--------|--------|-----------|
| 1 | 多 API Key 轮询 | 🔴 | 突破单 Key 限速瓶颈，吞吐提升 N 倍 |
| 2 | 通用图片归一化模块 | 🔴 | 全环节参考图统一归一化，传输体积降 5-10 倍 |
| 3 | 删除任务端点 `DELETE /api/tasks/{id}` | 🔴 | 一键清理任务全目录，防磁盘膨胀 |
| 4 | LLM JSON 输出容错（json_repair） | 🔴 | 修复 LLM 常见 JSON 语法错误，降编剧失败率 |
| 5 | 用户上传分镜场景图 | 🟡 | 关键分镜可手工供给参考图，不再完全依赖 AI 生成 |
| 6 | 角色一致性 + 对话（script）支持 | 🟡 | 增强长视频连续性与台词能力 |
| 7 | `start.bat` Windows 一键启动 | 🟢 | Windows 用户开箱即用 |
| 8 | `.env.example` 配置模板 | 🟢 | 多 Key / 端点可配置项一目了然 |

---

## 1. 多 API Key 轮询 🔴

### 1.1 目标

当前配置只支持单个 `AGNES_API_KEY`（`core/config.py:176` 的 `get_api_key()`），Agnes 单 Key 限速 20 次/分钟、实际 16 次/分。多 Key 轮询使可配额随 Key 数量线性增长，长视频流水线（Chat+Image+Video 共享限速）不再排队等配额。

### 1.2 配置层改造（core/config.py）

新增 `get_api_keys() -> list[str]`，返回全部可用 Key，优先级从高到低：

```
0. .env 文件中 AGNES_API_KEY, AGNES_API_KEY_2 ... AGNES_API_KEY_N
1. 环境变量 AGNES_API_KEY, AGNES_API_KEY_2 ... _N（覆盖 .env）
2. 配置文件中的 api_keys 列表（新增字段）
3. 旧配置 api_key 单个字段（向后兼容）
```

**实现要点**（完整实现骨架）：

```python
def get_api_keys() -> list[str]:
    """返回所有可用 API Key（去重、去空），优先级见 docstring。"""
    keys: list[str] = []

    # 0. 从 .env 读取（若引入 python-dotenv；否则跳过此步）
    for i in range(1, 100):
        var = "AGNES_API_KEY" if i == 1 else f"AGNES_API_KEY_{i}"
        val = _dotenv_value(var).strip()
        if val:
            keys.append(val)
        elif i > 1:
            break

    # 1. 环境变量覆盖 .env
    for i in range(1, 100):
        var = "AGNES_API_KEY" if i == 1 else f"AGNES_API_KEY_{i}"
        val = os.environ.get(var, "").strip()
        if val:
            if i <= len(keys):
                keys[i - 1] = val
            else:
                keys.append(val)
        elif i > 1:
            break

    if keys:
        return _dedup(keys)

    # 2. 配置文件 api_keys 列表（新字段）
    config = load_config()
    multi = config.get("api_keys", [])
    if multi:
        return _dedup([k for k in multi if k])

    # 3. 旧字段向后兼容
    single = config.get("api_key", "")
    if single:
        return [single]
    return []


def _dedup(keys: list[str]) -> list[str]:
    seen = set()
    out = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out
```

`get_api_key()` 保持不动（返回第一个/单个），由异常路径改用 `get_api_keys()`。同时新增 `set_api_keys(keys: list[str])` 持久化 `api_keys` 字段到配置文件（复用 `save_config` 的原子写 + `0o600` 权限逻辑）。

**请求层切换**：三个 API 模块 `AgnesChatAPI` / `AgnesImageAPI` / `AgnesVideoAPI` 的 `__init__` 接收 `api_key`。改造为：构造时 `self.api_keys = get_api_keys()`，`self._key_idx` 为线程安全计数。每发一次 HTTP 请求前按 `self._key_idx = (self._key_idx + 1) % len(self.api_keys)` 轮换一个 Key（各请求独享自己的 `headers` 副本）。

### 1.3 429 换 Key 重试策略

现状（见 `core/api/agnes_chat.py:118`、`core/api/agnes_image.py:131`）：429/5xx 时指数退避后**用同一 Key** 重试。

改造：429 时先**轮换到下一个 Key 立即重试**（Key 级隔离限速，换 Key 后无需等待），全部 Key 都遭遇 429 后才进入原有指数退避。5xx 保持原逻辑。实现：

```python
for attempt in range(_MAX_RETRIES):
    key = next_key_with_retry()  # 429 换 key，不 429 保持
    resp = post_with(key, payload)
    if resp.status_code == 429 and self._has_other_key():
        rotate_key(); continue       # 换 Key 立即重试，不 sleep
    if self._should_retry(resp) and attempt < _MAX_RETRIES - 1:
        time.sleep(_RETRY_BASE_DELAY * (attempt + 1)); continue
```

### 1.4 限速器配额随之提升（core/api/rate_limiter.py）

当前 `core/api/rate_limiter.py:31-34`：

```python
_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "20"))
_SAFETY_FACTOR = 0.8
_EFFECTIVE_RATE = _AGNES_RATE_LIMIT * _SAFETY_FACTOR   # 16 次/分钟
```

改造：以 Key 数缩放配额，并保持 `max_burst` 与速率匹配。参考口径：每个 Key 20 次/分 × Key 数 × 0.8 安全系数。例如 8 个 Key → `_AGNES_RATE_LIMIT = 160`，`_EFFECTIVE_RATE = 128`。注意 `max_burst`（令牌桶容量）同步上调（如 4×Key 数），否则多 Key 下高并发仍被突发容量卡住。可由新环境变量统一覆盖：

```python
_KEY_COUNT = len(get_api_keys())
_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", str(20 * max(_KEY_COUNT, 1))))
```

### 1.5 涉及文件

| 文件 | 改动 |
|------|------|
| `core/config.py` | 新增 `get_api_keys()` / `set_api_keys()` / `_dedup()` |
| `core/api/rate_limiter.py` | 配额按 Key 数动态计算 |
| `core/api/agnes_chat.py` | 多 Key 轮换 + 429 换 Key 重试 |
| `core/api/agnes_image.py` | 同上 |
| `core/api/agnes_video.py` | 同上 |
| `server.py` / `web/routes/config_routes.py` | 可选：`GET /api/config/keys` 返回 Key 数量/来源，供 UI 显示 |
| `static/index.html` | 可选：设置页支持粘贴多个 Key（逗号分隔或逐行） |

### 1.6 依赖变化

无新增依赖（`python-dotenv` 仅为可选项，不引入时跳过 .env 读取即可）。

### 1.7 验收标准

1. `AGNES_API_KEY` + `AGNES_API_KEY_2` 两个 Key 时，`get_api_keys()` 返回长度为 2 的列表、无重复。
2. 配置文件旧字段 `api_key` 仍可被识别（回退逻辑生效）。
3. `get_api_keys()` 为空（未配置）时各 API 模块行为与现状一致（抛 401 类错误）。
4. 模拟 429 场景：先发 Key1 触发 429 → 自动换 Key2 成功返回，日志输出 Key 轮换记录。
5. 两个 Key 下同时并发多个请求，限速器实际吞吐约等于 2× 原配额。

---

## 2. 通用图片归一化模块 🔴

### 2.1 目标

上传/生成的参考图（角色参考图、尾帧、i2v 首帧、锚点形象、用户尾帧等）未做尺寸/体积统一处理，直接 base64 内联进 JSON body（`core/api/agnes_image.py:_path_to_b64`、`core/api/agnes_video.py:_path_to_b64`）。超大原始图（手机照片动辄 5-10MB）导致请求体臃肿、传输慢、可能触发服务端拒绝。

本项收敛为**一个通用的、各环节整体使用的归一化模块**，取代碎片化的各处实现，实现三件事：尺寸统一、体积压缩、透明处理。

### 2.2 现状盘点（改造前必须对照）

| # | 现状实现 | 位置 | 说明 |
|---|---------|------|------|
| 1 | `_normalize_image_to_size()` | `core/pipelines/creative/steps_frames.py:82` | ffmpeg `scale+pad`，等比缩放+黑边，输出到指定 `dst`，`dst` 存在即缓存复用 |
| 2 | `_get_normalized_character_ref()` | `core/pipelines/creative/steps_frames.py:117` | 角色参考图归一化到视频尺寸，缓存到 `working_dir/character_ref_normalized.png`；URL/data 透传；失败回退原路径 |
| 3 | 用户尾帧 ffmpeg 命令 | `core/pipelines/creative/steps_frames.py:221` | 用户上传尾帧直接 `ffmpeg scale+pad` 到视频尺寸 |
| 4 | `_path_to_b64()` | `core/api/agnes_image.py:67` | 图片参考图 base64 编码，**无归一化** |
| 5 | `_path_to_b64()` | `core/api/agnes_video.py:69` | 视频参考图 base64 编码，**无归一化** |
| 6 | `_resolve_image_ref()` | 两 API 模块均有 | 本地文件 → base64 或上传 URL；`http(s)`/`data:` 透传 |

**结论**：已有归一化只覆盖 creative 流水线的角色参考图/用户尾帧（#1-3），simple / anchor / manuscript / poetry / 简单图片 i2i 的参考图全部绕过（#4-5）。

### 2.3 模块设计（新建 `utils/image_normalizer.py`）

独立模块而非塞进现有 API 类，供所有环节 `import`。完整实现指引（自包含）：

```python
"""utils.image_normalizer — 通用图片归一化模块（全环节统一使用）

各流水线 / API 环节的参考图（i2i 参考图、i2v 首帧、角色参考图、用户上传尾帧等）
统一经此模块处理后再编码 / 上传，保证：
1. 尺寸统一：归一化到目标尺寸（视频宽高或生成尺寸），避免模型拉伸/构图错位
2. 体积压缩：默认转 JPEG quality=90，体积约为原图的 1/5 ~ 1/10
3. 透明处理：JPEG 无 alpha，含透明通道 PNG 先合成到背景色（默认白色）再编码
4. 策略可选：PAD=等比缩放+居中填充黑/白边（保留全图）；COVER=等比缩放+居中裁剪填满
5. 缓存复用：目标文件已存在则直接返回
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from PIL import Image
except ImportError:  # Pillow 缺失时降级为不归一化（见 normalize_reference_path）
    Image = None

PAD = "pad"       # 等比缩放 + 居中填充黑/白边（保留全图，主体安全）
COVER = "cover"   # 等比缩放 + 居中裁剪填满（满幅，裁掉边缘）
_DEFAULT_FORMAT = "JPEG"
_DEFAULT_QUALITY = 90


def normalize_image(
    src: str,
    width: int,
    height: int,
    dst: Optional[str] = None,
    strategy: str = PAD,
    fmt: str = _DEFAULT_FORMAT,
    quality: int = _DEFAULT_QUALITY,
    background: Tuple[int, int, int] = (255, 255, 255),
) -> str:
    """将 ``src`` 归一化到精确 ``width x height`` 并写入 ``dst``。

    Args:
        src: 源图片路径（必须是本地文件）。
        width, height: 目标像素尺寸。
        dst: 输出路径；为 None 时同目录生成 ``{stem}_norm.{fmt后缀}``。
             已存在则直接返回（缓存复用）。
        strategy: PAD 或 COVER。
        fmt: 输出格式（JPEG / PNG），JPEG 时按 quality 压缩。
        quality: JPEG 质量（0-100），默认 90。
        background: 透明通道合成用的背景色 RGB。

    Returns:
        归一化后文件路径（即 dst）。

    Raises:
        FileNotFoundError / ValueError / OSError: 源不存在、无法解码或 Pillow 不可用。
    """
    if Image is None:
        raise OSError("Pillow is not available; cannot normalize image")
    # 源图已是目标尺寸且格式匹配时直接复用，避免二次压缩失真
    try:
        with Image.open(src) as _probe:
            if _probe.size == (width, height):
                probe_fmt = (_probe.format or "").upper()
                want_fmt = "JPEG" if fmt.upper() == "JPEG" else fmt.upper()
                if probe_fmt in ("PNG", "WEBP", "JPEG") and (
                    probe_fmt == want_fmt or probe_fmt == "PNG"
                ):
                    logger.debug(f"[ImageNormalizer] {src} already {width}x{height}, reuse")
                    return src
    except OSError:
        pass
    if not dst:
        stem, ext = os.path.splitext(src)
        suffix = ".jpg" if fmt.upper() == "JPEG" else ext or ".png"
        dst = f"{stem}_norm{suffix}"
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        logger.debug(f"[ImageNormalizer] cache hit: {dst}")
        return dst

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with Image.open(src) as im:
        rgb = im.convert("RGBA")
        src_w, src_h = rgb.size
        if strategy == COVER:
            scale = max(width / src_w, height / src_h)
            nw = max(round(src_w * scale), width)
            nh = max(round(src_h * scale), height)
            rgb = rgb.resize((nw, nh), Image.LANCZOS)
            left = (nw - width) // 2
            top = (nh - height) // 2
            rgb = rgb.crop((left, top, left + width, top + height))
        else:
            scale = min(width / src_w, height / src_h)
            nw = max(round(src_w * scale), 1)
            nh = max(round(src_h * scale), 1)
            rgb = rgb.resize((nw, nh), Image.LANCZOS)
            canvas = Image.new("RGBA", (width, height), background + (255,))
            canvas.paste(rgb, ((width - nw) // 2, (height - nh) // 2), rgb)
            rgb = canvas
        if fmt.upper() == "JPEG":
            bg = Image.new("RGB", rgb.size, background)
            bg.paste(rgb, mask=rgb.split()[-1])
            bg.save(dst, "JPEG", quality=quality)
        else:
            rgb.save(dst, fmt)
    logger.info(
        f"[ImageNormalizer] {os.path.basename(src)} -> {width}x{height} "
        f"({strategy}), {os.path.getsize(dst)} bytes"
    )
    return dst


async def normalize_image_async(
    src: str, width: int, height: int, dst: Optional[str] = None,
    strategy: str = PAD, fmt: str = _DEFAULT_FORMAT,
    quality: int = _DEFAULT_QUALITY, background: Tuple[int, int, int] = (255, 255, 255),
) -> str:
    """normalize_image 的异步版本（内部 asyncio.to_thread，不阻塞事件循环）。"""
    return await asyncio.to_thread(
        normalize_image, src, width, height, dst, strategy, fmt, quality, background
    )


def normalize_reference_path(
    ref: str, width: int, height: int, dst: Optional[str] = None,
    strategy: str = PAD, fmt: str = _DEFAULT_FORMAT, quality: int = _DEFAULT_QUALITY,
) -> str:
    """归一化参考图路径的安全封装：非本地文件（URL/data:）或不存在文件原样透传。

    与 normalize_image 的区别：此函数不抛异常，归一化失败时返回原路径，
    保证任何环节接入不会因图片异常而中断流水线。
    """
    if not ref or ref.startswith(("http://", "https://", "data:")):
        return ref
    if not os.path.exists(ref):
        return ref
    try:
        return normalize_image(
            src=ref, width=width, height=height, dst=dst,
            strategy=strategy, fmt=fmt, quality=quality,
        )
    except (OSError, ValueError) as e:
        logger.warning(f"[ImageNormalizer] normalize failed for {ref} ({e}); using original")
        return ref
```

### 2.4 实施步骤（统一接入全部环节）

> **顺序**：先建模块（2.3），再做 creative 存量收敛（步骤 B），最后统一 API 层兜底（步骤 A）。步骤 A 是"各环节整体使用"的关键——所有经 API 的参考图都会被覆盖。

#### 步骤 A：API 层统一接入（simple / anchor / manuscript / poetry / simple_image 全覆盖）

在 two API 模块的**入参处**归一化（而非 `_path_to_b64` 内部，因为 `_path_to_b64` 不知道目标尺寸）：

1. **`core/api/agnes_image.py:generate_single_image()`**：
   - 目标尺寸从形参 `size`（`"768x1152"` 字符串）解析：`int` 拆分，解析失败回退 `1024x1024`。
   - 在 `resolved = [await self._resolve_image_ref(p) ...]` **之前**，对每个 `p` 先 `await asyncio.to_thread(normalize_reference_path, p, sw, sh)`，用返回路径替换原 `p` 再 resolve。
   - `normalize_reference_path` 自动处理：URL/data 透传、失败回退原图，安全无回归。

2. **`core/api/agnes_video.py:submit_video()`**：
   - 目标尺寸直接用形参 `width`/`height`（默认 1152x768）。
   - 在 `resolved_refs = [] ... for p in reference_image_paths:` 循环内、`_resolve_image_ref` 之前，先 `await asyncio.to_thread(normalize_reference_path, p, width, height)`。

#### 步骤 B：creative 存量收敛（消除碎片实现）

1. `steps_frames.py:82` `_normalize_image_to_size()` 改体：逻辑委托给新模块，保留对外签名与缓存语义：
   ```python
   @staticmethod
   async def _normalize_image_to_size(src, vw, vh, dst):
       if os.path.exists(dst):
           return dst
       return await normalize_image_async(
           src=src, width=vw, height=vh, dst=dst,
           strategy=PAD, fmt="PNG", background=(0, 0, 0),  # 保持黑边
       )
   ```
   注意：内部改成 Pillow，输出 **PNG 保摸底**（仍对 i2i 身份一致性友好）+ **黑边背景**（与 ffmpeg pad 语义一致）。`_get_normalized_character_ref` 无需改（内部已调 `_normalize_image_to_size`）。ffmpeg 黑边语义与原实现一致。
2. `steps_frames.py:221` 用户尾帧的 `ffmpeg scale+pad` 命令替换为 `normalize_image_async(...)`（同样 PAD/PNG/黑边）。
3. 原 `_run_ffmpeg_async` 若仅剩拼接/其他用途则保留；若归一化路径全部迁移后用不到可删（需 grep 确认调用点）。

#### 步骤 C：接入点与尺寸来源汇总

| 环节 | 入口函数 | 目标尺寸来源 |
|------|---------|-------------|
| 简单视频 i2v/ti2vid/keyframes | `AgnesVideoAPI.submit_video` | 请求 `width`/`height` |
| 创意视频 角色/尾帧/多图 i2i | `AgnesImageAPI.generate_single_image` | 请求 `size`（`{vw}x{vh}`） |
| 创意视频 尾帧预生成 | `steps_frames` 既有（步骤 B） | state `video_width`×`video_height` |
| 稿件/诗词 视频参考图 | `AgnesVideoAPI.submit_video` | 各 state `video_width`×`video_height` |
| 数字人锚点形象 | `AgnesImageAPI.generate_single_image` | state `video_width`×`video_height` |
| 简单图片 i2i | `AgnesImageAPI.generate_single_image` | 请求 `size`（默认 1024x1024） |

### 2.5 涉及文件

| 文件 | 改动 |
|------|------|
| `utils/image_normalizer.py` | **新增**：通用归一化模块（2.3 完整代码） |
| `core/api/agnes_image.py` | `generate_single_image` 入参前归一化（步骤 A） |
| `core/api/agnes_video.py` | `submit_video` 入参前归一化（步骤 A） |
| `core/pipelines/creative/steps_frames.py` | `_normalize_image_to_size` 委拖 + 用户尾帧改用模块（步骤 B） |
| `requirements.txt` | 已含 Pillow（moviepy 依赖），**无需新增**（若独立部署需显式确认） |

### 2.6 依赖变化

无新增依赖。Pillow 随 moviepy 已安装（`Pillow 11.x`），模块仍以 `try/except ImportError` 降级（Image=None 时 `normalize_reference_path` 直接返回原路径，行为等于现状）。

### 2.7 验收标准

1. 上传 4000×3000 手机照片作参考图，归一化后输出为请求尺寸的 JPEG（< 300KB），体积缩至 1/5 以下。
2. simple（无参考图纯 t2v / 参考图 i2v）、creative（角色参考图）、anchor（锚点形象）、simple_image（i2i 上传）各跑一遍：`/api/tasks` 正常完成，日志出现 `[ImageNormalizer]` 归一化记录，未出现"normalize failed"异常。
3. **回归保护**：URL / data: 参考图流程不受影响（透传）；Pillow 缺失（模拟 import 失败）时各环节行为与现状一致。
4. creative 尾帧预生成：生成图与改造前视觉一致（黑边填充、等比不拉伸）。
5. 透明 PNG 参考图不崩溃、不出现黑底（JPEG 输出前合成白底验证）。
6. 同一源图在同一任务内多次引用仅归一化一次（第二次走缓存，日志 cache hit / reuse）。

---

## 3. 删除任务端点 `DELETE /api/tasks/{id}` 🔴

### 3.1 目标

当前仅支持删除单个中间产物（`web/routes/video_routes.py:139`）和 `POST /api/tasks/sweep` 清理僵尸任务；用户无法一键删除某个任务及其整个工作目录。长视频任务产物多，`.working_dir` 会无限膨胀。

### 3.2 实现方式

在 `web/routes/video_routes.py` 增加：

```python
@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务及其磁盘上全部生成文件。运行中任务拒绝删除。"""
    # 1. 运行中保护
    if task_id in active_pipelines:
        raise HTTPException(status_code=400, detail="Cannot delete a running task. Stop it first.")
    # 2. 若在排队队列中，先行移除
    _queued_tasks.pop(task_id, None)
    # 3. 定位任务工作目录
    dir_name = _find_dir_name(task_id)   # 按 task_id 反查 dir_name，兼容旧任务
    if dir_name:
        task_dir = os.path.join(get_working_dir(), dir_name)
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)
    # 4. 从 active_pipelines 中摘除
    active_pipelines.pop(task_id, None)
    return {"ok": True, "task_id": task_id, "message": "Task deleted"}
```

**需要项目的既有能力辅助**：
- task 工作目录命名规则与 `dir_name` 反查：参照 `server.py` 现有 `_find_dir_name(task_id)`（遍历 `TaskManager("_").list_tasks()` 匹配 `task_id`），此逻辑与 `video_routes.py` 的 artifacts 删除一致，可复用。
- `active_pipelines` / `_queued_tasks` 是应用级全局状态（`web/app_state.py`），注入方式沿用现有 route 依赖。

### 3.3 前端

`static/index.html` 任务列表卡片在"中断任务"旁增加"删除"按钮（仅对非运行中任务显示）。弹确认框（多语言 i18n 文案），成功后调用 `fetch('/api/tasks/{id}', {method: 'DELETE'})` 并刷新列表。文案新增例如 `deleteTask: '删除任务'`、`deleteTaskConfirm: '删除任务及其所有产物文件？此操作不可撤销。'`。

### 3.4 涉及文件

| 文件 | 改动 |
|------|------|
| `web/routes/video_routes.py` | 新增 DELETE 端点 |
| `web/app_state.py` | 确认导出 `_queued_tasks`/`active_pipelines` 访问接口（若未导出则补充） |
| `static/index.html` | 前端按钮 + 确认框 + i18n 文案 |

### 3.5 依赖变化

无。

### 3.6 验收标准

1. 对已完成任务执行 DELETE：返回 `{"ok": true}`，任务目录从 `.working_dir` 消失。
2. 对运行中任务执行 DELETE：返回 400，任务继续运行。
3. 删除后再次 `GET /api/tasks` 列表中不再包含该任务。
4. 连续删除多个任务，工作区磁盘占用显著下降。

---

## 4. LLM JSON 输出容错（json_repair）🔴

### 4.1 目标

编剧/拆段/音色识别等依赖 LLM 返回 JSON 的环节，当前仅正则提取首个 `{...}` 块 + 失败后重试 chat 调用（`core/api/agnes_chat.py:217-250`）。LLM 常见的缺冒号、尾随逗号、单引号等语法错误会导致整轮失败重试，既浪费配额又提高失败率。

### 4.2 实现方式

在正则提取失败、重试 chat 之前，先尝试 `json_repair` 库修复：

```python
# core/api/agnes_chat.py 顶部
try:
    from json_repair import repair_json
except ImportError:
    repair_json = None
```

在提取环节（现有 `_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")` 的 `re.search` + `json.loads` 失败分支后）插入：

```python
# 修复顺序：正则提取 → json.loads → json_repair 修复 → 重试 chat
if match:
    try:
        return json.loads(match.group())
    except (json.JSONDecodeError, ValueError):
        pass
if repair_json is not None:
    try:
        repaired = repair_json(cleaned, return_objects=True)
        if isinstance(repaired, dict):
            logger.info("[AgnesChat] JSON repaired via json_repair")
            return repaired
    except Exception:
        pass
# 仍失败 → 走现有首轮重试逻辑
```

**注意**：`repair_json(cleaned, return_objects=True)` 返回的是解析好的对象（非字符串），且要求 `cleaned` 是去除 markdown 围栏（```json ... ```）后的纯文本。若当前代码是先对整段内容做 `re.search`，则 `cleaned` 应为完整 content 去围栏（与 `_JSON_BLOCK_RE` 提取逻辑并行：先 normalize 掉 ``` 包裹，再尝试全量 repair）。

### 4.3 涉及文件

| 文件 | 改动 |
|------|------|
| `core/api/agnes_chat.py` | 顶部可选导入 + repair 分支 |
| `requirements.txt` | 新增 `json-repair`（PyPI 包名 `json-repair`，import 名 `json_repair`） |

### 4.4 依赖变化

新增 `json-repair`。**必须做成可选依赖**（`try/except ImportError`），保证未安装时行为与现状完全一致。

### 4.5 验收标准

1. 构造含尾随逗号/缺冒号的 JSON 片段调用 `chat`，返回正确 dict（不再走失败重试路径），日志出现 `[AgnesChat] JSON repaired`。
2. 未安装 `json-repair` 时，原失败重试路径行为不变。
3. 非法 JSON（无法修复，如纯文本响应）仍走原重试/报错流程。

---

## 5. 用户上传分镜场景图 🟡

### 5.1 目标

创意视频（creative）流水线中，分镜场景的视频生成依赖 AI 生成的场景参考图。关键分镜（如角色出场、标志性构图）仅靠 prompt 生成不可控。允许用户为指定场景上传参考图，流水线以其为准。

### 5.2 实现方式

1. **数据模型**（`models/task.py` 的 `CreativeVideoTask` / 场景配置）：`SceneConfig` 增加可选 `user_reference_image: str | None`（存上传文件路径，放入任务工作目录下的 `uploads/`）。
2. **API 层**：`POST /api/tasks/creative` 请求体支持每场景可选 `reference_image` 字段（multipart/form-data 或 JSON base64），在 `web/helpers.py` 已有图片处理工具基础上落盘到该任务 `uploads/` 目录。
3. **流水线**（`core/pipelines/creative/steps_frames.py` 场景任务落盘处）：构建场景任务时，若存在 `user_reference_image`，则跳过该场景的 AI 图生成步骤，直接用用户图作为该场景视频生成的参考图（视频生成与现有 `keyframes`/`ti2vid` 链式模式的参考图通路共用 `_resolve_image_ref`）。
4. **前端**：创意类型 tab 的场景配置区，每个场景行增加"上传参考图"按钮与缩略图；提交时随任务一起上传。

### 5.3 涉及文件

| 文件 | 改动 |
|------|------|
| `models/task.py` | `CreativeVideoTask` / 场景配置模型加字段 |
| `web/routes/video_routes.py`（creative 路由） | 接收并落盘用户参考图 |
| `core/pipelines/creative/steps_frames.py` | 有用户图时跳过 AI 生成 |
| `core/pipelines/creative/steps_video.py` | 场景参考图来源优先取用户图 |
| `static/index.html` | 场景行上传按钮 + 缩略图 |

### 5.4 依赖变化

无（复用现有上传/路径安全工具）。

### 5.5 验收标准

1. 创意任务某个场景上传参考图后，该场景视频生成使用该图（日志显示跳过 AI 分镜图、video 请求使用用户图）。
2. 不传参考图的场景行为与现状一致（AI 生成分镜图）。
3. 上传文件纳入任务 `uploads/` 目录，随任务删除/清理一并回收。
4. 上传路径经路径安全检查（复用 `core/path_security.py` 的 realpath + 根目录包含校验）。

---

## 6. 角色一致性 + 对话支持 🟡

### 6.1 目标

提高创意/稿件长视频的叙事能力：
- **角色一致性**：多场景同一角色保持外观稳定；
- **对话支持**：分镜脚本中输出角色台词，旁白 TTS 与角色对白（可用不同音色/语气）区分。

### 6.2 实现方式

1. **角色一致性**：创意流水线已有"角色提取/尾帧/数字人 prompt"基础（`core/screenwriter/characters.py`）。增强为：首场景生成的角色形象图作为后续场景的常驻参考图透传（复用第 2 项通用归一化模块产物），并在每个场景的图片 prompt 末尾追加统一的角色外观描述串。角色外观串由 `Screenwriter` 首次调用时一次性产出、存进任务状态。
2. **对话支持**：`core/screenwriter/story.py` 生成剧本时增加结构化对白段（`{"speaker": "...", "dialogue": "..."}`）。音频阶段（`core/pipelines/creative/steps_audio.py`）将对白与旁白分开走 TTS：对白使用 configured 的第二音色（或同音色不同 `rate`），合并进同一 SRT 时间线；影视感可加 `voice` 差异化（如男声旁白+女声对白）。

### 6.3 涉及文件

| 文件 | 改动 |
|------|------|
| `core/screenwriter/characters.py` | 角色外观描述统一串产出与透传 |
| `core/screenwriter/story.py` | 剧本生成支持结构化对白 |
| `core/pipelines/creative/steps_video.py` | 角色参考图跨场景透传 |
| `core/pipelines/creative/steps_audio.py` | 旁白/对白分离 TTS + 合并时间线 |
| `models/task.py` | 音色/对白配置字段 |
| `static/index.html` | 可选音色配置项 |

### 6.4 依赖变化

无。

### 6.5 验收标准

1. 多场景创意视频中，指定角色在 ≥3 个场景外观基本一致（目测）。
2. 剧本含对白时，SRT 同时包含旁白与对白且时间不冲突。
3. 未配置对白/第二音色的任务与现状行为完全一致。

---

## 7. `start.bat` Windows 一键启动 🟢

### 7.1 目标

目前仅 `start.sh`（Linux/macOS）。Windows 用户需手动建 venv、装依赖、确认 ffmpeg 存在。

### 7.2 实现方式

项目根目录新增 `start.bat`，逻辑与 `start.sh` 平行：

```bat
@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM 1) 检查 Python 3.10+，不满足则报错退出
python --version >nul 2>&1
if %errorlevel% neq 0 (echo [错误] 未找到 Python… & pause & exit /b 1)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
…
REM 2) 检查 ffmpeg（where ffmpeg >nul 2>&1），缺失提示下载地址
REM 3) 若 .venv 不存在则 python -m venv .venv
REM 4) .venv\Scripts\pip install -r requirements.txt
REM 5) .venv\Scripts\python server.py 并自动打开浏览器（起服务后用 start http://localhost:8765）
```

要点：`chcp 65001` 保证中文提示不乱码；venv 在 Windows 下解释器路径为 `.venv\Scripts\python.exe`；版本检查用 `python -c` 判断。注释/提示文案与 `start.sh` 保持一致（中文）。

### 7.3 涉及文件

| 文件 | 改动 |
|------|------|
| `start.bat`（新增） | 一键启动脚本 |

### 7.4 依赖变化

无。

### 7.5 验收标准

在 Windows 10/11 双击 `start.bat`：无 Python→明确报错；有 Python 无 ffmpeg→明确提示；环境齐全→自动建 venv、装依赖、起服务并打开 `http://localhost:8765`。

---

## 8. `.env.example` 配置模板 🟢

### 8.1 目标

多 Key / 端点配置项目前仅存在于代码注释，用户不易发现。提供带注释的配置模板，随包分发出货，也便于 CI/Docker 等场景快速参考。

### 8.2 实现方式

项目根新增 `.env.example`（公开提交，**绝不能包含真实 Key**）：

```dotenv
# Agnes AI API Key（必填）
# 从 https://platform.agnes-ai.com 获取免费 Key
AGNES_API_KEY=your-api-key-here

# 多 Key 轮询（可选，配合优化点 1）
# AGNES_API_KEY_2=your-second-api-key
# AGNES_API_KEY_3=your-third-api-key

# 限速配额覆盖（次/分钟，默认 = 20 × Key 数）
# AGNES_RATE_LIMIT=160

# 可选端点/模型覆盖
# AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
# AGNES_IMAGE_MODEL=agnes-image-2.1-flash
# AGNES_VIDEO_MODEL=agnes-video-v2.0
```

在 `README`/`AGENTS.md` 的部署章节补充一句引用及多 Key 说明。

### 8.3 涉及文件

| 文件 | 改动 |
|------|------|
| `.env.example`（新增） | 配置模板 |
| `README.md` / `AGENTS.md` | 简要引用 |

### 8.4 依赖变化

无（纯文档/模板；`.env` 解析为可选，见优化点 1）。

### 8.5 验收标准

1. `.env.example` 存在且无真实密钥。
2. README 出现多 Key 配置说明。
3. 将模板复制为 `.env` 并填入两个 Key，配合优化点 1 的 `get_api_keys()` 正确识别。

---

## 实施建议

1. **第一梯队（🔴）做批次一**：1 → 4 → 3 → 2，均为独立小改动、低回归风险、收益直接（吞吐×N、失败率↓、磁盘回收、传输体积↓）。
2. 每完成一项，在 `docs/regression_test_plan.md` 增加对应验收条目；涉及 API 模块的改动跑一遍 `scripts/regression_runner.py` 回归。
3. 优化点 1 与 8 强相关（`.env.example` 提供多 Key 样例），可同批落地；优化点 2 是 5、6 的底层依赖，先做 2 再做 5/6。
4. 优化点 5、6 贴近创意视频核心路径，改动面较大，建议作为独立小版本（v5.1.x）推进并对创意类型做专项回归。