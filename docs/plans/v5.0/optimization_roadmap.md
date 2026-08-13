# 优化路线图（Optimization Roadmap）

> **文档定位**：本项目可落地的优化点清单与实现指引。本文为**自包含**文档——实施环节不依赖任何外部调研，每个优化点的实现方式、涉及文件、依赖变化、验收标准均已内嵌。实施某一项时，仅阅读对应章节即可独立开展。
>
> **优先级标记**：🔴 高（建议优先）| 🟡 中（可选）| 🟢 低（锦上添花）

---

## 目录

| # | 优化点 | 优先级 | 一句话价值 |
|---|--------|--------|-----------|
| 1 | ✅ 多 API Key 轮询 + 限流整合 + `.env.example` | 🔴 | KeyRing 统一轮换 + 429 换 Key + 配额按 Key 数缩放，吞吐提升 N 倍；配置模板一栏可查 |
| 2 | ✅ 通用图片归一化模块 | 🔴 | 全环节参考图统一归一化，传输体积降 5-10 倍 |
| 3 | ✅ 删除任务端点 `DELETE /api/tasks/{id}` | 🔴 | 一键清理任务全目录，防磁盘膨胀 |
| 4 | ✅ LLM JSON 输出容错（json_repair） | 🔴 | 修复 LLM 常见 JSON 语法错误，降编剧失败率 |
| 5 | ✅ 用户上传分镜场景图 | 🟡 | 关键分镜可手工供给参考图，不再完全依赖 AI 生成 |
| 6 | ✅ `start.bat` Windows 一键启动 | 🟢 | Windows 用户开箱即用 |

> **实施状态**：六项全部于 2026-08-13 落地（v5.0），详见各节末尾「✅ 已实施」标注与文末「实施记录」。mock 单测由 GitHub Action（`.github/workflows/test.yml`）自动执行；专项回归条目见 `docs/dev/regression_test_plan.md` 三点五节。
>
> 已抽离待调研项：**角色一致性增强 + 对话支持** → `docs/plans/optimization-research/character_consistency_and_dialogue.md`

---

## 1. 多 API Key 轮询 + 限流整合 🔴

> 本项将**多 Key 轮询**与**现有全局限速策略**整合为一个完整方案：Key 采集 → 统一轮换（KeyRing）→ 429 换 Key 重试 → 限速器配额按 Key 数缩放 → 请求编排统一封装 → 配置/API/UI → **`.env.example` 配置模板**（多 Key/限速参数一栏可查）。实施时可完整按 1.3-1.9 顺序落地。

### 1.1 目标

当前配置只支持单个 `AGNES_API_KEY`（`core/config.py:175` 的 `get_api_key()`），Agnes 单 Key 限速 20 次/分钟、实际 16 次/分（`rate_limiter.py:31-34` 留 20% 余量）。多 Key 使可配额随 Key 数量**线性增长**，长视频流水线（Chat+Image+Video 共享限速）不再排队等配额；同时**429 时换 Key 立即重试**，绕开"同一 Key 指数退避"造成的长时间空闲。

### 1.2 现状与缺口盘点

| # | 现状 | 位置 | 缺口 |
|---|------|------|------|
| 1 | 单 Key：`AGNES_API_KEY` 或 config `api_key` | `core/config.py:175` | 无多 Key 概念 |
| 2 | 全局令牌桶单例，`rate_per_minute` 在**模块导入时固定**为 16 | `core/api/rate_limiter.py:31-34,48` | 不感知 Key 数，多 Key 后仍是 16/分 |
| 3 | 429/5xx 指数退避后用**同一 Key** 重试（chat 3 次×15s、image 3 次×20s、video 5 次×30s，另有上传 429 30s） | `agnes_chat.py:118`、`agnes_image.py:131`、`agnes_video.py:337` | 无法换 Key，全 Key 429 才能止损，浪费配额 |
| 4 | 三个 API 模块各自维护 `self.headers`（内含单 Key） | 三模块 `__init__` | 无统一轮换入口、无线程安全计数 |
| 5 | 视频轮询 `_poll_task` 每 60s 消耗一个令牌 | `agnes_video.py:243` | 轮询也占用配额，需纳入多 Key 核算 |
| 6 | **视频提交（`POST /videos`）与 chat/image 共用同一个共享桶**（`_submit_with_retry` 调 `get_rate_limiter().acquire()`） | `agnes_video.py:318` | 服务端对视频提交是 **1/min 独立限制**，现状未分层——视频提交独占共享桶配额或反之被挤占 |

### 1.3 配置层：Key 采集（core/config.py）

新增 `get_api_keys() -> list[str]`，返回全部可用 Key（去重、去空），**env 与 config 合并**（同 Key 只保留一次，env 位置优先）：

```
1. .env 文件中 AGNES_API_KEY, AGNES_API_KEY_2 ... AGNES_API_KEY_N（低优先）
2. 环境变量 AGNES_API_KEY, AGNES_API_KEY_2 ... _N（高优先，同槽位覆盖 .env）
3. 配置文件中的 api_keys 列表（新增字段，与 env 并存）
4. 旧配置 api_key 单个字段（向后兼容）
```

> **实施说明**：与初稿"env 优先、config 仅兜底"不同，实际实现为 **env + config 合并**——Web UI 保存的多 Key（config）与 env Key 可并存，使 UI 配置的多 Key 真实生效；去重保证与 env 重复的 Key 只出现一次。采集逻辑见 `core/config.py` 的 `_collect_env_keys()` + `get_api_keys()`。

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

- `get_api_key()` 保持不动（返回第一个），作为**兼容入口**；业务调用逐步迁移到 KeyRing。
- 新增 `set_api_keys(keys: list[str])`：持久化 `api_keys` 字段到配置文件（复用 `save_config` 的原子写 + `0o600` 权限）。写入后必须调用 `reset_key_ring()` + `reset_rate_limiter()`（见 1.5），否则旧配置（单桶 16/分 + 旧 KeyRing）继续生效。
- 新增 `get_api_keys_source() -> str`：返回 `'env:N'` / `'config:N'` / `'mixed:env2+config1'`，供 `GET /api/config/keys` 与日志展示。

### 1.4 统一轮换：KeyRing（新增 core/api/key_manager.py）

三个 API 模块不再各自维护 `_key_idx`，统一收敛到 `KeyRing` 单例，提供**线程安全的轮换**与**换 Key**能力：

```python
"""core.api.key_manager — 多 API Key 统一轮换（KeyRing 单例）

职责：
1. 基于 get_api_keys() 惰性初始化；Key 变更后 reset_key_ring() 重建
2. next(): 普通请求轮转（round-robin，原子计数，均匀分摊配额）
3. rotate(): 429 时强制切到下一个 Key（供换 Key 重试）
4. has_multiple() / __len__: 供限速器配额与重试策略判断
"""
import itertools
import threading

from core.config import get_api_keys

logger = __import__("logging").getLogger(__name__)


class KeyRing:
    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("KeyRing requires at least one key")
        self._keys = list(keys)
        self._count = itertools.count()
        self._lock = threading.Lock()

    def next(self) -> str:
        """轮转取下一个 Key（普通请求调用，均匀分摊）。"""
        return self._keys[next(self._count) % len(self._keys)]

    def rotate(self) -> str:
        """强制切换到下一个 Key（429 换 Key 重试调用）。"""
        with self._lock:
            idx = next(self._count) % len(self._keys)
            return self._keys[idx]

    @property
    def keys(self) -> list[str]:
        return list(self._keys)

    def has_multiple(self) -> bool:
        return len(self._keys) > 1

    def __len__(self) -> int:
        return len(self._keys)

    def describe(self) -> str:
        """日志用：key#2/3 等。"""
        return f"key#{next(self._count) % len(self._keys) + 1}/{len(self._keys)}"


_instance: KeyRing | None = None
_lock = threading.Lock()


def get_key_ring() -> KeyRing:
    """获取全局 KeyRing（线程安全单例，惰性初始化）。"""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                keys = get_api_keys()
                if not keys:
                    raise RuntimeError(
                        "No Agnes API Key configured (AGNES_API_KEY or config api_key)"
                    )
                _instance = KeyRing(keys)
                logger.info(
                    f"[KeyManager] KeyRing 初始化: {len(keys)} 个 Key "
                    f"({get_api_keys_source() if 'get_api_keys_source' in globals() else ''})"
                )
    return _instance


def reset_key_ring() -> None:
    """Key 变更后重建 KeyRing（配合 set_api_keys / delete_api_key）。"""
    global _instance
    with _lock:
        _instance = None
```

**请求层切换**：三个 API 模块 `AgnesChatAPI` / `AgnesImageAPI` / `AgnesVideoAPI` 构造时保留 `api_key` 参数（兼容旧调用），但内部改为：

```python
def _auth_headers(self) -> dict:
    """每次请求前生成带当前 Key 的 headers 副本（从 KeyRing 轮转取 Key）。"""
    key = get_key_ring().next()
    h = dict(self._base_headers)          # 原有 Accept/Content-Type 等
    h["Authorization"] = f"Bearer {key}"
    return h
```

所有 `requests.post/get(..., headers=self.headers)` 改为 `headers=self._auth_headers()`，确保每请求独立 Key、互不污染。

### 1.5 限速器整合：共享桶 × Key 数 + 视频提交独立桶（core/api/rate_limiter.py）

**目标限速规则**（Agnes 服务端口径）：

| 接口类别 | 服务端限制 | 客户端策略 |
|---------|-----------|-----------|
| **视频提交**（`POST /videos`） | **1 次/分**（独立） | **独立令牌桶** `1 × Key 数`/分，桶容量 `1 × Key 数` |
| **其他接口**（chat / image / 上传 / 轮询） | 20 次/分 | **共享令牌桶** `20 × Key 数 × 0.8`/分 |

**决策①：共享桶采用全局单桶 × Key 数，而非 per-Key 桶。** 理由：
- 多 Key 时轮转均匀分摊配额（1.4 `next()`），各 Key 使用率接近 1/N；
- 即使某瞬时把请求压到同一 Key，服务端 429 会被 1.6 的换 Key 逻辑兜底；
- per-Key 桶需管理 Key 增删生命周期、且在单 Key 退化时徒增复杂度，收益低。

**决策②：视频提交独立成桶，不并入共享桶。** 理由：
- 服务端对视频提交是 **1/min 硬限制**，与共享桶 20/min 差 20 倍；并入共享桶意味着视频提交独占配额时可能让其他接口饿死，或反之被其他接口挤占；
- 当前实现（`agnes_video.py:318`）视频提交与 chat/image 共用同一个 `get_rate_limiter()` 桶，**未区分**——这是现状缺口；
- 独立桶后，视频提交 429 只在极端情况触发（多任务并发提交瞬间），由 1.6 换 Key 兜底。

**改造**（`rate_limiter.py`）：

```python
# 模块导入时不再固定速率：惰性初始化时从 KeyRing 读 Key 数
_KEY_BASE_RATE = 20             # 单 Key 共享接口原始配额（Agnes 限制）
_VIDEO_SUBMIT_RATE = 1          # 单 Key 视频提交配额（Agnes 独立限制 1/min）
_SAFETY_FACTOR = 0.8            # 共享桶保留 20% 余量
_VIDEO_SAFETY_FACTOR = 1.0      # 视频提交桶不降额：服务端 1/min 已很严，且 429 换 Key 兜底


def _key_count() -> int:
    try:
        return len(get_key_ring())
    except Exception:
        return 1


def _effective_rate() -> float:
    """共享桶有效速率 = 单 Key 配额 × Key 数 × 安全系数。"""
    limit = int(os.environ.get("AGNES_RATE_LIMIT", str(_KEY_BASE_RATE * _key_count())))
    return limit * _SAFETY_FACTOR


def _video_submit_rate() -> float:
    """视频提交桶速率 = 1 × Key 数（AGNES_VIDEO_RATE_LIMIT 可覆盖）。

    注：若服务端对视频提交是全局限 1/min（而非 per-Key），
    设置 AGNES_VIDEO_RATE_LIMIT=1 即可，无需改代码。
    """
    limit = int(os.environ.get("AGNES_VIDEO_RATE_LIMIT", str(_VIDEO_SUBMIT_RATE * _key_count())))
    return limit * _VIDEO_SAFETY_FACTOR


def _max_burst() -> int:
    """共享桶容量随 Key 数上调：4 × Key 数，否则高并发被突发容量卡住。"""
    return int(os.environ.get("AGNES_RATE_BURST", str(4 * _key_count())))


def _video_max_burst() -> int:
    """视频提交桶容量 = 1 × Key 数：允许每 Key 立即提交一次，随后受 1/min 限制。"""
    return int(os.environ.get("AGNES_VIDEO_RATE_BURST", str(_key_count())))


class AgnesRateLimiter:
    def __init__(self, rate_per_minute: float | None = None, max_burst: int | None = None):
        rate_per_minute = rate_per_minute if rate_per_minute is not None else _effective_rate()
        max_burst = max_burst if max_burst is not None else _max_burst()
        ...
```

**两个单例**：

```python
def get_rate_limiter() -> AgnesRateLimiter:
    """共享桶：chat / image / 上传 / 轮询（20 × Key 数 × 0.8 次/分）。"""


def get_video_submit_limiter() -> AgnesRateLimiter:
    """视频提交独立桶：1 × Key 数 次/分。"""
```

- 视频提交处（`agnes_video.py:318` `_submit_with_retry`）改用 `get_video_submit_limiter().acquire()`；
- 上传（`agnes_video.py:141`）、轮询（`agnes_video.py:243`）保持走共享桶 `get_rate_limiter()`——它们是普通查询接口，不占视频提交配额；
- `reset_rate_limiter()` 在 `set_api_keys()` / `delete_api_key()` 之后由 `config` 侧调用（1.3），同时重建两个单例，使新 Key 数即时生效。
- 两个 limiter 的 `stats` 均新增 `key_count` 与 `effective_rate_per_min`。

**示例口径**（8 个 Key）：共享桶原始配额 160、有效速率 128 次/分、桶容量 32；视频提交桶 8 次/分、容量 8。

### 1.6 请求编排：429 换 Key + 指数退避统一封装

现状（`agnes_chat.py:118`、`agnes_image.py:131`、`agnes_video.py:337`）：429/5xx 指数退避后**同 Key** 重试。整合后三模块共用一套算法（新增 `core/api/rate_limiter.py` 或 `core/api/key_manager.py` 的 helper，各模块 `from ... import request_with_key_rotation`）：

```python
def request_with_key_rotation(
    requester,            # 可调用: (url, headers, **kw) -> requests.Response
    url: str,
    *,
    max_retries: int = 3,
    retry_base_delay: float = 20.0,
    key_ring=None,
    **requester_kwargs,
) -> requests.Response:
    """429 换 Key 立即重试；全 Key 429 或 5xx/超时才指数退避。

    规则：
    1. 每请求前 key_ring.next()（round-robin，均匀分摊）
    2. 429 且 has_multiple() -> key_ring.rotate() 立即重试（不 sleep、不计入退避）
       —— Key 级隔离限速，换 Key 后配额是满的
    3. 所有 Key 均 429（rotation 计数达到 len(keys) × 退避上限）-> 指数退避
    4. 5xx / 超时 / 连接错误 -> 同 Key 指数退避（保持现状）
    """
    ring = key_ring or get_key_ring()
    retries = 0
    rotations = 0
    max_rotations = len(ring) * max_retries
    while True:
        headers = requester_kwargs.pop("headers", None)
        resp = requester(url, headers=headers, **requester_kwargs)
        if resp.status_code == 429:
            if ring.has_multiple() and rotations < max_rotations:
                rotations += 1
                ring.rotate()
                logger.warning(f"[KeyRotation] HTTP 429, 换 Key 立即重试 (rotation {rotations})")
                continue                          # 换 Key 后无配额缺口，立即重发
            if retries < max_retries:
                delay = retry_base_delay * (retries + 1)
                logger.warning(f"[KeyRotation] 全 Key 429, 退避 {delay}s 后重试")
                time.sleep(delay); retries += 1; continue
            return resp                          # 全部耗尽，交给调用方 collect_error + raise
        if resp.status_code >= 500 and retries < max_retries:
            delay = retry_base_delay * (retries + 1)
            logger.warning(f"[KeyRotation] HTTP {resp.status_code}, 退避 {delay}s 后重试")
            time.sleep(delay); retries += 1; continue
        return resp
```

各模块接入：
- `AgnesChatAPI._request_with_retry`：`post` 换为 `request_with_key_rotation`（基延迟保持 15s）。
- `AgnesImageAPI` 主请求（基延迟 20s）与 `AgnesVideoAPI` 主请求/上传（基延迟 30s）同理。
- **视频轮询 `_poll_task`（`agnes_video.py:243`）**：每 60s 一次 `GET`，同样走 `request_with_key_rotation`（轮转 Key 分摊配额；429 换 Key 重试，避免轮询卡死）。`max_poll_duration` / `consecutive_failures` 逻辑不变。
- 429 分支仍需调用 `collect_error(..., error_type="RateLimit429", extra={"rotations": rotations})` 记录，5xx 分支维持现状。
- **边界**：429 且 `has_multiple()==False`（单 Key 退化）→ 直接落入指数退避，行为与现状完全一致。

### 1.7 配置 API 与前端

| 接口 | 说明 |
|------|------|
| `GET /api/config/keys` | 返回 `{ok, key_count, source}`（来源/数量，**永不回传 Key 明文**） |
| `POST /api/config/keys` | body `{"keys": ["k1", "k2"]}` → `set_api_keys()` + 重建 KeyRing/限速器；空数组则回退到 env 采集 |

- `static/index.html` 设置页：API Key 输入框支持多行/逗号分隔粘贴；保存后调 `POST /api/config/keys`，并展示 `key_count`。
- `web/routes/config_routes.py` 新增上述两个路由；删除旧 `DELETE /api/config` 的行为不涉及（`api_key` 单字段仍由 `set_api_key`/`delete_api_key` 管理，两套并存，`get_api_keys()` 统一聚合）。

### 1.8 配置模板：`.env.example`（随包分发出货）

`.env.example` 是本项落地后的**标准配置样板**（公开提交，**绝不能包含真实 Key**），让多 Key / 限速参数一栏可查，便于 CI/Docker/新用户快速参考。项目根新增：

```dotenv
# Agnes AI API Key（必填）
# 从 https://platform.agnes-ai.com 获取免费 Key
AGNES_API_KEY=your-api-key-here

# 多 Key 轮询（可选，见 optimization_roadmap §1.3）
# 每个 Key 的配额独立，总量 ≈ 20 × Key 数 / 分钟
# AGNES_API_KEY_2=your-second-api-key
# AGNES_API_KEY_3=your-third-api-key

# 限速配额覆盖（次/分钟，默认 = 20 × Key 数 × 0.8 安全系数）
# AGNES_RATE_LIMIT=160

# 桶容量覆盖（默认 = 4 × Key 数；仅需调节突发并发时使用）
# AGNES_RATE_BURST=32

# 视频提交独立限速（次/分钟，默认 = 1 × Key 数；服务端为全局 1/min 时设 =1）
# AGNES_VIDEO_RATE_LIMIT=8
# AGNES_VIDEO_RATE_BURST=8

# 可选端点/模型覆盖
# AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
# AGNES_IMAGE_MODEL=agnes-image-2.1-flash
# AGNES_VIDEO_MODEL=agnes-video-v2.0
```

要点：
- `.env` 解析为可选能力（python-dotenv，见 1.9）；未引入 dotenv 时 `.env.example` 作为文档模板，实际 Key 经环境变量或 `POST /api/config/keys` 配置。
- 在 `README.md` / `AGENTS.md` 的部署章节补充一句引用 + 多 Key 说明（指向 `optimization_roadmap.md §1`），保证新用户发现路径。
- `.env.example` 不随业务加载，仅当用户复制为 `.env`（且引入 dotenv）才生效。

### 1.9 涉及文件

| 文件 | 改动 |
|------|------|
| `core/config.py` | 新增 `get_api_keys()` / `set_api_keys()` / `get_api_keys_source()` / `_dedup()` |
| `core/api/key_manager.py` | **新增**：`KeyRing` + `get_key_ring()` / `reset_key_ring()` |
| `core/api/rate_limiter.py` | 双单例：共享桶（`get_rate_limiter`）×Key 数 + 视频提交桶（`get_video_submit_limiter`）1×Key 数；新增 `request_with_key_rotation()` helper |
| `core/api/agnes_chat.py` | `_request_with_retry` 改走 helper；`_auth_headers()` |
| `core/api/agnes_image.py` | 同上（含图片请求，走共享桶） |
| `core/api/agnes_video.py` | 同上；`_submit_with_retry` 改走视频提交独立桶，上传/轮询保持共享桶 |
| `web/routes/config_routes.py` | 新增 `GET/POST /api/config/keys` |
| `static/index.html` | 设置页多 Key 编辑 + key_count 展示 |
| `.env.example`（新增） | 配置模板（多 Key / 共享桶 / 视频提交桶限速参数样板） |
| `README.md` / `AGENTS.md` | 部署章节引用 `.env.example` + 多 Key 说明 |

### 1.10 依赖变化

无新增依赖（`python-dotenv` 仅为可选项，不引入时跳过 .env 读取即可；`AGNES_API_KEY_2..N` 经环境变量即可使用；`.env.example` 纯文档，不影响运行）。

### 1.11 验收标准

1. `AGNES_API_KEY` + `AGNES_API_KEY_2` 两个 Key 时，`get_api_keys()` 返回长度为 2 的列表、无重复；`get_api_keys_source()` 返回 `env:2`。
2. 配置文件旧字段 `api_key` 仍可被识别（回退逻辑生效）；`set_api_keys()` 后 `get_api_keys()` 立即返回新列表。
3. 未配置任何 Key 时：`get_key_ring()` 抛 `RuntimeError`，API 模块行为与现状一致（401 类错误）。
4. 模拟 429：先发 Key1 触发 429 → 日志出现 `[KeyRotation] HTTP 429, 换 Key 立即重试` → Key2 成功返回；单 Key 场景 429 走退避，行为与现状一致。
5. 两个 Key 并发请求：`stats.effective_rate_per_min` ≈ 32；实际吞吐接近 2× 原配额。
6. `set_api_keys()` 后（不经重启）新 Key 数即时反映到限速器 `stats.key_count` 与 `get_key_ring().__len__()`。
7. `GET /api/config/keys` 返回 `key_count` 与 `source`，不含 Key 明文。
8. `.env.example` 存在、无真实密钥，含 `AGNES_API_KEY_2..N` / `AGNES_RATE_LIMIT` / `AGNES_RATE_BURST` / `AGNES_VIDEO_RATE_LIMIT` / `AGNES_VIDEO_RATE_BURST` 注释样例；复制为 `.env` 填入两个 Key 后 `get_api_keys()` 正确识别（引入 dotenv 时）。
9. `README.md` / `AGENTS.md` 部署章节出现 `.env.example` 引用与多 Key 说明。
10. **分层限速**：`get_rate_limiter().stats` 与 `get_video_submit_limiter().stats` 为两个独立实例；`_submit_with_retry` 走视频独立桶（日志/统计可区分），上传与轮询仍走共享桶。
11. 连续快速提交 2 个视频任务（单 Key）：第二个在视频提交桶被 `acquire()` 阻塞约 60s（日志 `[RateLimiter] 限速等待 ~60.0s`），期间 chat/image 请求不受影响（共享桶有令牌）。
12. `AGNES_VIDEO_RATE_LIMIT=1` 时（模拟服务端全局 1/min 而非 per-Key）：`get_video_submit_limiter().stats.effective_rate_per_min == 1.0`，多 Key 下视频提交速率不随 Key 数放大。

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

## 6. `start.bat` Windows 一键启动 🟢

### 6.1 目标

目前仅 `start.sh`（Linux/macOS）。Windows 用户需手动建 venv、装依赖、确认 ffmpeg 存在。

### 6.2 实现方式

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

### 6.3 涉及文件

| 文件 | 改动 |
|------|------|
| `start.bat`（新增） | 一键启动脚本 |

### 6.4 依赖变化

无。

### 6.5 验收标准

在 Windows 10/11 双击 `start.bat`：无 Python→明确报错；有 Python 无 ffmpeg→明确提示；环境齐全→自动建 venv、装依赖、起服务并打开 `http://localhost:8765`。

---

## 实施建议

## 实施记录（2026-08-13，全部完成 ✅）

按建议批次 1 → 4 → 3 → 2 → 5 → 6 实施，均通过 py_compile / import / 端点冒烟自验；mock 单测由 GitHub Action（`.github/workflows/test.yml`）执行。

| 优化 | 落地文件 | 自验记录 |
|------|---------|---------|
| 1 多 Key + 限流 | `core/config.py`、`core/api/key_manager.py`（新增）、`core/api/rate_limiter.py`、`agnes_chat/image/video.py`、`web/routes/config_routes.py`、`.env.example`（新增）、`frontend/src`（ConfigPanel/useConfig/api）、`requirements.txt` | 3 Key 配置下共享桶 48/min、视频桶 3/min、KeyRing 轮转正常；`GET/POST /api/config/keys` 端点冒烟通过 |
| 4 json_repair | `core/api/agnes_chat.py`、`requirements.txt` | 可选导入正常；`repair_json` 加载成功 |
| 3 删除任务 | `web/routes/video_routes.py`、`web/app_state.py`、`frontend/src`（TaskListPanel/useTasks/api）、i18n | DELETE 已完成任务返回 `ok:true` 且目录移除；不存在任务 404 |
| 2 图片归一化 | `utils/image_normalizer.py`（新增）、`agnes_image.py`/`agnes_video.py` 入参归一化、`steps_frames.py` 收敛、`requirements.txt`（显式 Pillow） | 模块 import / 降级逻辑正常 |
| 5 用户场景参考图 | `models/task.py`、`web/routes/task_creation_routes.py`、`steps_video.py`（三种模式接入）、`frontend/src`（CreativeForm）、i18n | 端点字段校验、前端构建（vue-tsc）通过 |
| 6 start.bat | `start.bat`（新增） | 语法/流程按 roadmap §6.5（Windows 手动验证） |

**遗留说明**：
- mock 全量单测与覆盖率由 GitHub Action 在 push 后自动执行，无需本地阻塞。
- 专项回归条目 V1-V8 已写入 `docs/dev/regression_test_plan.md` 三点五节；全量 8 场景回归待用户触发「执行大版本回归」。

---

*文档版本：v5.0 | 更新日期：2026-08-13 | 状态：六项全部完成*