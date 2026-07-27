# 单元测试覆盖度评估 & GitHub Actions 适配性

> 最近更新：2026-07-27
> 测试套件：**128 个用例全部通过**（含 `tests/test_core.py` 单元、`tests/mock_regression/` 五管线 mock 回归、以及新增 `test_path_security.py` / `test_artifacts.py` / `test_cue_aware_srt.py` / `test_narration_cleaning.py`）
> 总体覆盖率：**58%**（7476 语句 / 3170 未覆盖；含 coverage 工具注入的 `sitecustomize.py` 401 行，实际项目约 7075 行）
> 运行环境：本地 `.venv`（Python 3.13，moviepy / edge_tts / fastapi 已装）

---

## 一、结论速览

| 维度 | 结论 |
|------|------|
| 单元测试覆盖度 | 总 **58%**；**业务编排层（pipeline）已 58%–81% 覆盖**，模型层 98% |
| 能否放进 GitHub Actions | ✅ **非常适合**——测试在 API 边界处全 mock，无网络、无需 API Key，素材已入库 |
| 当前最大缺口 | 外部 API 客户端（被有意 mock）、`server.py` HTTP 层（19%）、`config.py` 环境解析（41%） |
| 立即可补的高价值项 | `server.py` 路由单测（TestClient + mock key）、`config.py` / `error_collector.py` 纯逻辑单测 |

> 本轮已补：`path_security.py`（新增安全模块，0%→**100%**）、`artifacts.py` 级联删除逻辑（19%→**91%**）。

---

## 二、覆盖度怎么评估（方法论）

项目此前**没有任何覆盖率工具、也没有 pytest 配置**。本次补齐了评估链路：

1. **工具**：`pytest` + `pytest-asyncio`（async 用例）+ `coverage` / `pytest-cov`
2. **配置**：`pytest.ini`（`asyncio_mode=auto`、`testpaths=tests`）
3. **依赖**：`requirements-dev.txt`（仅开发/测试用，不进生产镜像）
4. **本地一键评估**：
   ```bash
   .venv/bin/python -m coverage run -m pytest tests/ -q
   .venv/bin/python -m coverage report -m        # 终端按模块明细
   .venv/bin/python -m coverage html -d htmlcov  # 可点击的 HTML 报告
   ```
5. **CI 评估**：见 `.github/workflows/test.yml`，用 `pytest --cov` 并上传 `htmlcov/` 与 `coverage.xml` 作为 artifact，同时把覆盖率写入 **Job Summary** 页面。

> 覆盖率只是一个信号，不是目标本身。本项目约 1/3 代码是「外部 API 客户端 + FastAPI HTTP 层」，这部分本就不该用单元测试覆盖（应走集成测试），所以 58% 是合理水位，不必恐慌。

---

## 三、按模块覆盖率明细

### ✅ 覆盖良好（≥ 70%）—— 核心业务已锁住

| 模块 | 覆盖 | 说明 |
|------|------|------|
| `core/path_security.py` | 100% | **本轮新增**安全模块（路径穿越防护），纯逻辑 |
| `core/artifacts.py` | 91% | **本轮补测**级联删除/清理逻辑（19%→91%） |
| `models/task.py` | 98% | 任务状态机，业务逻辑基石 |
| `tests/test_artifacts.py` | 100% | 本轮新增 |
| `tests/test_path_security.py` | 100% | 本轮新增 |
| `tests/test_core.py` | 99% | 单元核心 |
| `tests/mock_regression/test_pipelines.py` | 99% | 5 条 pipeline 全流程回归 |
| `core/compositor/concatenator.py` | 81% | 视频拼接器 |
| `core/pipelines/anchor_video.py` | 80% | 数字人管线 |
| `core/pipelines/poetry_video.py` | 79% | 诗词管线 |
| `core/pipelines/manuscript_video.py` | 79% | 稿件管线 |
| `core/compositor/watermark.py` | 68% | 水印 |
| `core/pipelines/__init__.py` | 69% | 基类/调度 |

### 🟡 中等（40%–70%）—— 有空间但非紧急

| 模块 | 覆盖 | 说明 |
|------|------|------|
| `core/pipelines/simple_video.py` | 66% | 简单视频管线 |
| `core/audio/subtitle.py` | 65% | 字幕生成（部分分支靠真实渲染触发） |
| `core/pipelines/creative_video.py` | 60% | 创意管线（最大单文件 843 行，分支多） |
| `core/pipelines/multi_scene.py` | 55% | 多场景基类 |
| `core/screenwriter.py` | 54% | 编剧/分镜（大量 LLM 分支，本就被 mock） |
| `core/task_manager.py` | 51% | 任务生命周期 |
| `core/config.py` | 41% | 配置/环境变量解析 |
| `core/audio/tts.py` | 31% | TTS 引擎（EdgeTTS 被 mock） |
| `utils/image.py` / `utils/video.py` | 30% / 33% | 小工具 |

### 🔴 偏低（< 40%）—— 区分「有意不测」与「该补」

| 模块 | 覆盖 | 性质 | 建议 |
|------|------|------|------|
| `core/api/agnes_video.py` | 15% | 外部 API 客户端（被 mock） | 走集成测试，单测不经济 |
| `core/api/agnes_image.py` | 25% | 同上 | 同上 |
| `core/api/agnes_chat.py` | 29% | 同上 | 同上 |
| `core/api/agnes_models.py` | 29% | 同上 | 同上 |
| `core/compositor/processor.py` | 25% | 后处理 | 可补 |
| `core/api/rate_limiter.py` | 37% | 限速器（被 mock） | 可单测限流算法本身 |
| `core/audio/voices.py` | 20% | 音色目录（含网络拉取） | 解析/缓存逻辑可 mock 单测 |
| `core/api/error_collector.py` | 19% | **纯逻辑** | ⭐ 易补、易暴露 bug |
| `server.py` | 19% | FastAPI HTTP 层（907 行） | 用 `fastapi.testclient` 做路由单测 |

---

## 四、缺口分析：为什么这些没覆盖

1. **外部 API 客户端（video/image/chat/models）≈ 530 行仅 15%–29%**
   mock 测试在「协议边界」把整类替换成 `MockAgnes*`，所以真实客户端的 HTTP 重试、错误码解析、限流回退等**全部没走到**。这是**有意设计**——它们的正确性应由「带沙箱 key 的集成测试」保证，而非单元测试。

2. **`server.py` 19%（907 行，734 未覆盖）—— 最大单块缺口**
   FastAPI 路由层：鉴权、参数校验、任务 CRUD、文件下载等。当前没有任何 HTTP 层测试。可用 `fastapi.testclient.TestClient` + mock API key 低成本补上，能直接锁住「接口契约」。

3. **`config.py` 41% / `error_collector.py` 19% / `voices.py` 20%**
   均为「输入 → 输出」型纯函数/类，用 `monkeypatch` 注入环境变量或 mock 网络即可覆盖。

4. **`path_security.py` / `artifacts.py` 本轮已补完**
   二者均为纯逻辑、无外部依赖，单测极易写且能抓住真实 bug（路径穿越、误删风险），现覆盖分别达 100% / 91%。

---

## 五、补测建议（按 ROI 排序）

| 优先级 | 目标 | 预期收益 | 成本 |
|--------|------|----------|------|
| ✅ 已完成 | `artifacts.py` 级联删除/清理单测 | 防误删、19%→91% | 低（已落地） |
| ✅ 已完成 | `path_security.py` 安全单测 | 路径穿越防护、0%→100% | 低（已落地） |
| P0 | `server.py` 路由单测（TestClient + mock key） | 锁接口契约、覆盖率 +10% | 中 |
| P1 | `config.py` 环境变量解析单测 | 防配置错误、+6% | 低 |
| P1 | `error_collector.py` 报错归集单测 | +3% | 低 |
| P2 | `voices.py` 解析/缓存单测（mock 网络） | +3% | 低 |
| P2 | `rate_limiter.py` 限流算法单测 | +5% | 低 |
| — | API 客户端 | 留给集成测试（沙箱 key） | 高 |

> 本轮补测后总覆盖率从 55%→58%（代码量因新增已扩到 ~7075 行，补测仍把比率拉高）。
> 按上表补完 P0+P1，预计可到 **65%+**，且补齐的是「最容易出生产事故」的逻辑。

---

## 六、GitHub Actions 适配性：✅ 非常适合

### 为什么天然适合 CI

1. **零网络、零密钥**：`tests/mock_regression/conftest.py` 用 `autouse` fixture，把
   `AgnesVideoAPI` / `AgnesImageAPI` / `AgnesChatAPI` / `EdgeTTSEngine` / `get_rate_limiter`
   在**所有 import 路径**上替换成 Mock。测试不发起任何 HTTP 请求、不需要 `AGNES_API_KEY`。
2. **素材已入库**：`tests/mock_regression/assets/*.mp4|*.png` 与 `fixture_data/*` 已提交，
   `checkout` 后立即可用，无需额外生成步骤（mock 会从这些固定产物拼装视频）。
3. **唯一外部二进制是 ffmpeg**：由 `apt-get install -y ffmpeg` 解决；
   `moviepy` 也自带 `imageio-ffmpeg` 静态二进制兜底。
4. **`test_core.py` / `test_path_security.py` / `test_artifacts.py` 纯单元**：模型/字幕/配置/安全/级联删除，无任何外部依赖。

### 已落地的 `test.yml`

- 触发：**`push` 到任意分支**（`branches: ["**"]`）、所有 `pull_request`、`workflow_dispatch`
- 步骤：Checkout → 设 Python 3.12（带 pip 缓存）→ 装 ffmpeg + `fonts-noto-cjk` → 装依赖 → `pytest --cov` → 上传 `htmlcov/` + `coverage.xml` artifact → 将覆盖率写入 **Job Summary**
- **防回归门禁**：`--cov-fail-under=55`，覆盖率跌破当前基线即小红叉
- 可选：把 `python-version` 改成矩阵可验证 3.11 / 3.12 多版本

> ⚠️ CI 注意点：字幕渲染依赖 CJK 字体 `resource/fonts/STHeitiMedium.ttc`（已入库）。
> 本地通过；ubuntu-latest 上该 `.ttc` 随仓库 checkout 可用，且已补装 `fonts-noto-cjk` 兜底，避免「中文方块/字体缺失」。

---

## 七、下一步

1. ✅ 已完成：补 `artifacts.py` / `path_security.py` 单测（本轮），`--cov-fail-under` 上调至 55。
2. 按第五节 P0 补 `server.py` 路由单测，把 `--cov-fail-under` 逐步提到 65。
3. 后续为 API 客户端单独建「集成测试」workflow（需 `AGNES_API_KEY` 仓库 secret + 沙箱环境），与单元测试解耦。
