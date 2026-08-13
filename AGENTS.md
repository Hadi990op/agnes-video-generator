# AGENTS.md — Agnes Video Generator

> **面向对象**：维护 / 开发本项目的 AI Agent
> **当前阶段**：🟢 **维护模式**
> **配套文档**：
> - 部署/使用：`docs/public/getting-started.md`（四种部署方式）、`docs/public/usage.md`、`docs/public/faq.md`
> - 架构/技术栈：`docs/public/architecture.md`
> - API 端点：`docs/public/api.md`
> - 流水线产物逻辑：`docs/dev/pipeline_products.md`（权威参考）
> - 大版本回归：`docs/dev/regression_test_plan.md`（含场景矩阵、命令、报告）
> - 测试覆盖 & CI：`docs/dev/test_coverage_and_ci.md`
> - 优化路线图：`docs/plans/v5.0/optimization_roadmap.md`（可落地优化点）
> - 待调研存档：`docs/plans/optimization-research/README.md`
> - 发版规范：`docs/dev/release_process.md`（版本号规则 + 新增内容规范 + 发布流程）

---

## 〇、部署与验证（AI Agent 必读）

> 完整部署（手动/Docker/npm/Agent 辅助）见 `docs/public/getting-started.md`。本节仅保留 Agent 执行时必要的部署与验证清单。

### 0.1 环境要求与启动

```bash
python3 --version                 # 需 3.10+
./start.sh                        # 一键：建 venv + 装依赖 + 启动 http://localhost:8765
# 手动：python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python server.py
```

### 0.2 API Key 配置

```bash
export AGNES_API_KEY="your-api-key"    # 方式 1：环境变量
curl -X POST http://localhost:8765/api/config \
  -H "Content-Type: application/json" \
  -d '{"api_key": "your-api-key"}'     # 方式 2：API（等价 Web UI）
```

### 0.3 部署验证清单（4 层）

```bash
# 1. 基础连通性
curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/          # 期望 200
curl -s http://localhost:8765/api/config    | python3 -m json.tool     # ok: true
curl -s http://localhost:8765/api/voices    | python3 -m json.tool     # 13 语言分组音色
curl -s http://localhost:8765/api/tasks     | python3 -m json.tool     # ok: true

# 2. 静态分析（py_compile 所有改动文件 + 关键模块导入）
.venv/bin/python -m py_compile <改动文件>
.venv/bin/python -c "from core.api.agnes_video import AgnesVideoAPI; print('OK')"
.venv/bin/python -c "from core.api.agnes_image import AgnesImageAPI; print('OK')"
.venv/bin/python -c "from core.api.agnes_chat import AgnesChatAPI; print('OK')"
.venv/bin/python -c "from core.audio.tts import EdgeTTSEngine, SilentTTSEngine; print('OK')"
.venv/bin/python -c "from models.task import parse_task_state; print('OK')"

# 3. 任务创建（参数校验）
curl -X POST http://localhost:8765/api/tasks/simple -H "Content-Type: application/json" \
  -d '{"prompt": "一只猫在花园里追蝴蝶", "mode": "t2v", "duration": 5}'
curl -X POST http://localhost:8765/api/tasks/creative -H "Content-Type: application/json" \
  -d '{"idea": "太空探险故事", "video_width": 768, "video_height": 1152}'
curl -X POST http://localhost:8765/api/tasks/manuscript -H "Content-Type: application/json" \
  -d '{"manuscript_text": "这是第一段测试文本。这是第二段测试文本。"}'

# 4. 单测（可选，覆盖率见 docs/dev/test_coverage_and_ci.md）
.venv/bin/python -m pytest tests/ -q
```

---

## 一、项目定位

基于 Agnes AI **完全免费**模型的视频生成工具，支持 **六种任务类型** 的一站式 Web 应用：

- **简单视频**（simple）：单次调用 Agnes Video API，暴露全部参数的结构化 UI（t2v / i2v / ti2vid / keyframes）
- **创意长视频**（creative）：AI 编剧 → 分镜图生成 → 视频生成 → edge_tts 旁白配音 + 细粒度字幕叠加 → 拼接
- **稿件长视频**（manuscript）：长文本 → 时间估算拆段 → AI 场景 prompt → 逐段视频生成 → 统一 TTS+字幕 → 拼接
- **数字人口播**（anchor）：数字人形象 → 循环 i2v 视频，支持 `post_stitch`（TTS 后拼接音频）与 `model`（模型自带口型音频）两种音频模式
- **诗词视频**（poetry）：古诗 → LLM 拆分场景（原诗句作旁白，场景描述作视频 prompt）→ 逐句 t2v + TTS 朗诵 + 定时对齐字幕 → 拼接
- **简单图片**（simple_image）：单次调用 Agnes Image API 的结构化 t2i / i2i 生成

自 v4.0 起，创意 / 稿件 / 数字人 / 诗词四种长视频流水线统一继承 `MultiScenePipeline`（模板方法核心：`build_scenes → build_reference_images → generate_videos → audio+subtitle → composite`），仅简单视频直接继承 `BasePipeline`。

---

## 二、技术栈

| 层 | 选型 |
|------|------|
| 后端框架 | Python FastAPI（进度经任务状态轮询暴露，**无 WebSocket**） |
| 数据模型 | Pydantic v2 |
| 视频处理 | moviepy + ffmpeg |
| TTS | edge_tts >= 6.1.0（免费，无需 API Key） |
| 字幕 | srt >= 3.5.0 + moviepy（词级细粒度 + 多行换行） |
| 前端 | 原生 HTML/CSS/JS + Tailwind CDN（单文件 `static/index.html`，多 Tab + 13 语言 i18n） |
| LLM | Agnes Chat API (`agnes-2.0-flash`) — 免费 |
| 图片模型 | `agnes-image-2.1-flash`（t2i / i2i 共用；i2i 默认同 t2i，可用 `AGNES_IMAGE_I2I_MODEL` 回退 2.0） |
| 视频模型 | `agnes-video-v2.0` — 免费 |
| 水印 | moviepy TextClip 生成 PNG + ffmpeg overlay 叠加（避免整片重编码 OOM） |
| 音色 | edge_tts 动态音色目录，按 13 种项目语言分组 + 跨脚本兼容性校验 |
| 日志 | `logging.getLogger(__name__)` |

---

## 三、目录结构

```
agnes-video-generator/
├── server.py                         # FastAPI 入口（~200 行）：app 组装 + lifespan + 启动 + 兼容 re-export
├── web/                              # Web 路由层（v5.0 模块化拆分）
│   ├── __init__.py
│   ├── app_state.py                  # 应用级全局状态：并发控制（WeightedSemaphore）/ active_pipelines / 生命周期
│   ├── helpers.py                    # 纯工具函数：字幕样式解析、音色试听/兼容、时长提取、图片 prompt
│   ├── deps.py                       # 共享依赖：Pipeline 工厂 + 并发受控执行器（含下划线兼容别名）
│   └── routes/                       # 8 个 APIRouter 模块（config/workspace/voice/image/video/task/creation/utility）
├── start.sh                          # 一键启动脚本（venv + pip install + run）
├── Dockerfile                        # 多平台 Docker 镜像（Python 3.11 + imageio-ffmpeg 静态二进制）
├── docker-compose.yml                # Docker Compose（bind mount 持久化工作区 + 配置）
├── docker-run.sh                     # 一行 Docker 启动脚本（自动挂载本机数据目录）
├── requirements.txt                  # 依赖（含 edge_tts, srt, tenacity, imageio-ffmpeg）
│
├── models/
│   └── task.py                       # TaskType/VideoMode + BaseTaskState + 6 任务子类
│                                     #   (Simple/Creative/Manuscript/Anchor/Poetry/SimpleImage)
│                                     #   + Subtitle/Audio 配置 + 请求/响应模型
│
├── core/
│   ├── config.py                     # API Key/水印/工作区持久化、字体 CJK 回退、音视频默认配置
│   ├── task_manager.py               # 任务状态持久化，多态反序列化，向后兼容
│   ├── path_security.py              # 路径穿越防护（realpath + 根目录包含校验）
│   ├── artifacts.py                  # 中间产物注册表 + 级联删除计划 + 僵尸任务 sweep
│   ├── screenwriter/                  # 编剧 Agent 包（story/scenes/characters/style mixin）
│   ├── api/
│   │   ├── agnes_chat.py             # LLM Chat API（text + multimodal + JSON mode）
│   │   ├── agnes_image.py            # 图片生成 API（t2i + i2i + ref image）
│   │   ├── agnes_video.py            # 视频生成 API（t2v/i2v/ti2vid/keyframes + 轮询 + 重试）
│   │   ├── agnes_models.py           # 模型列表拉取（text/image/video 分组，含缓存回退）
│   │   ├── rate_limiter.py           # 令牌桶限速器（全局限速，单一共享桶）
│   │   └── error_collector.py        # 模型接口报错收集（prompt/错误类型/详情 → error_logs/）
│   ├── audio/
│   │   ├── tts.py                    # EdgeTTSEngine（旁白+词级时间戳）+ SilentTTSEngine
│   │   ├── subtitle/                  # 字幕包（generator: SRT 生成 + renderer: moviepy 叠加）
│   │   └── voices.py                 # 音色目录（13 语言分组）+ 跨脚本兼容性校验矩阵
│   ├── compositor/
│   │   ├── concatenator/              # 拼接包（concat: 视频拼接 + audio_overlay: 音频叠加）
│   │   ├── processor.py              # 视频缩放/帧提取/定格延长/静音音频生成
│   │   └── watermark.py              # ffmpeg overlay 水印叠加 + 语言检测
│   └── pipelines/
│       ├── __init__.py               # BasePipeline 抽象基类（共享 shutdown/WS 推送/字幕/水印）
│       ├── multi_scene.py            # MultiScenePipeline 多场景模板方法基类（v4.0 重构核心）
│       ├── simple_video.py           # 类型 1：单 prompt → 单视频（直接继承 BasePipeline）
│       ├── creative/                  # 类型 2：创意长视频包（pipeline + steps_script/frames/video/audio）
│       ├── manuscript_video.py       # 类型 3：稿件长视频（继承 MultiScenePipeline）
│       ├── anchor_video.py           # 类型 4：数字人口播（继承 MultiScenePipeline）
│       └── poetry_video.py           # 类型 6：诗词视频（继承 MultiScenePipeline）
│
├── utils/
│   ├── image.py                      # 图片下载 / base64 转换 / URL 上传
│   └── video.py                      # 视频下载
│
├── resource/fonts/                   # 内置 CJK 字体（STHeitiMedium.ttc 默认，MicrosoftYaHeiNormal 备用）
├── static/                           # index.html（多 Tab 前端，13 语言 i18n）
├── scripts/
│   ├── regression_runner.py          # 大版本回归测试脚本（全量/续传/quick）
│   ├── scene_runner.py               # 单场景/端点回归执行器
│   └── run_mock_regression.sh        # mock 回归一键脚本
├── tests/
│   ├── test_core.py                  # 核心单元测试
│   ├── test_audio_fallback.py        # 共享音频降级方法行为对照用例
│   └── mock_regression/              # mock 回归框架（mock API + fixture + 流水线测试）
│
 └── docs/
     ├── plans/                        # 计划文档（分版本存储，v1.0~v5.0；已完成方案标记 _DONE）
     │   └── optimization-research/    #   待调研优化点存档（见 README 流转规则）
     ├── public/                       # 对外资料（README 引用、给用户阅读）
     └── dev/                          # 架构/基础文档（版本无关、当前状态）
 ```

> 注：`core/pipeline.py`、`core/image_generator.py`、`core/video_generator.py`、`core/audio/subtitle.py`、`core/compositor/concatenator.py` 为**向后兼容别名模块**，重导出 `core.pipelines` / `core.api` 中的真实类，勿删。

---

## 四、AI Agent 触发词

| 用户说法 | 主理人应执行的操作 | 说明 |
|---------|-------------------|------|
| **"修复 Bug: ..."** | 按「BugFix 工作流」定位→修复→自验→汇报 | 直接修复，不委派子 agent |
| **"执行大版本回归"** | 按 `docs/dev/regression_test_plan.md` 执行 | 8 场景 + 端点验证 |
| **"新增功能: ..."** | 需求分析 → PRD → `docs/plans/vX.Y/system_design.md` 增量 → 实现 | 增量功能开发 |
| **"需求分析" / "只做 PRD"** | 产出增量 PRD | 部分工作流 |
| **"架构评审"** | 评审架构设计/实现 | 部分工作流 |
| **"部署项目" / "初始化环境"** | 按 `docs/public/getting-started.md` 部署 | 全新环境部署 |
| **"验证项目" / "跑一下检查"** | 按「〇 部署与验证」执行 | 部署后验证 |
| **"执行优化批次"** | 按 `docs/plans/v5.0/optimization_roadmap.md` 执行对应批次 | 每完成一项按文档验收标准自验 + 更新 `docs/dev/regression_test_plan.md` 回归条目 |
| **"待调研优化点" / "优化调研"** | 按 `docs/plans/optimization-research/README.md` 索引与调研方法评估 | 价值存疑的新点子先存档，转入可执行需移回 `optimization_roadmap.md` |
| **"发版" / "发布" / "release"** | 按 `docs/dev/release_process.md` 执行（确认版本类型 → 升位 → 写 release notes → 打 tag） | 需用户明确版本类型或版本号 |

---

## 五、BugFix 工作流

用户说 **"修复 Bug: ..."** 时按以下流程执行：

```
1. 定位
   - 阅读用户描述的 bug 现象
   - 用 codegraph / grep 定位到相关文件和代码行
   - 复现 bug（如能通过 API 调用复现）

2. 修复
   - 直接执行修复
   - 确保修复不违反「共享知识规范」

3. 自验
   - bash start.sh 正常启动（Uvicorn 监听 8765 端口无报错）
   - 受影响的端点 curl 验证返回正确结果
   - 已有功能不被破坏（必要时跑 mock 回归：./scripts/run_mock_regression.sh）

4. 汇报
   - 向用户说明：根因、修复方案、涉及文件
   - 附 curl 验证结果
```

---

## 六、共享知识规范

### 6.1 日志前缀

| 前缀 | 模块 |
|------|------|
| `[Startup]` / `[Resume]` / `[Stop]` | server.py 生命周期 |
| `[Workspace]` / `[Concurrency]` / `[Preview]` | server.py 工作区/并发/音色试听 |
| `[Pipeline]` | 流水线通用（BasePipeline） |
| `[MultiScene]` | multi_scene.py |
| `[Simple]` / `[Creative]` / `[Manuscript]` / `[Anchor]` / `[Poetry]` | 各流水线 |
| `[EndFrame]` / `[Keyframes]` | 尾帧 / 关键帧处理 |
| `[TTS]` / `[Subtitle]` / `[Voices]` | tts.py / subtitle.py / voices.py |
| `[Compositor]` | compositor/ concatenator/processor |
| `[Watermark]` | watermark.py |
| `[Image]` / `[AgnesImage]` / `[AgnesVideo]` / `[AgnesChat]` | 图片流程 / 各 API 模块 |
| `[RateLimiter]` / `[ErrorCollector]` | rate_limiter.py / error_collector.py |
| `[Artifacts]` | artifacts.py |
| `[TaskManager]` | task_manager.py |
| `[Screenwriter]` | screenwriter.py |

### 6.2 错误处理与全局限速

| 场景 | 策略 |
|------|------|
| 全局限速 | `core/api/rate_limiter.py` 单一共享令牌桶：`get_rate_limiter()`，默认 `AGNES_RATE_LIMIT=20`，`_SAFETY_FACTOR=0.8` → 实际 **16 次/分钟**。**所有** Agnes 调用（Chat / Image / Video 提交与轮询）共用此桶，无独立视频提交桶 |
| LLM Chat | 重试 3 次，间隔 15s 递增；5xx 和 429 均重试 |
| 图片生成 | 重试 4 次，间隔 20s 递增；5xx 和 429 均重试 |
| 视频提交 | 重试 5 次，间隔 30s 递增；5xx、429、超时均重试（仍走共享桶） |
| 视频轮询 | 间隔 60s，每 10 次输出日志；连续 10 次失败放弃；整体超时 1800s |
| 报错收集 | `error_collector.py` 记录失败调用的 prompt/错误类型/详情至工作目录 `error_logs/` |
| PipelineShutdown | 所有流水线统一处理，落盘当前状态 |
| TTS 失败 | 降级为静音 + 字幕 |

> 多 API Key 轮询 / 分层限速（视频提交独立桶 1×Key/min + 共享桶 20×Key×0.8）为**规划方案（未实施）**，见 `docs/plans/v5.0/optimization_roadmap.md §1`。当前实现为单一共享桶。

### 6.3 向后兼容

- `TaskManager.load()` 自动将无 `task_type` 字段的旧数据识别为 `CreativeVideoTask`
- 旧 `task_state.json` 字段名保持不变
- 兼容别名模块（重导出真实类，如 `VideoPipeline = CreativeVideoPipeline`），**非废弃空文件，勿删**

### 6.4 API 响应格式

```json
// 成功
{"ok": true, "task_id": "...", ...}

// 失败
HTTPException(status_code=4xx/5xx, detail="...")
```

### 6.5 内部进度事件结构（WSMessage）

`WSMessage` 是流水线通过 `BasePipeline._emit` 产生的进度事件结构，落盘到任务状态供前端轮询读取（**无 WebSocket 推送**）：

```json
{
  "type": "progress",
  "task_id": "...",
  "step": "video_split",
  "status": "running",
  "message": "正在拆分文本...",
  "progress": 0.3,
  "data": {"current": 2, "total": 5}
}
```

### 6.6 视频-音频同步策略

```python
final_duration = max(audio_duration + 1.0, original_video_duration)
# padding ≤ 1 秒，不足时尾帧 freeze
```

创意视频和稿件视频均采用"MoneyPrinterTurbo 方式"：先拼接所有视频片段，再整体叠加一条合并音频 + 一套字幕，避免逐段叠加导致的 padding 累积误差。TTS 输出自动放大 2.5 倍音量以补偿 edge_tts 默认低音量。

### 6.7 稿件拆段算法

```python
def split_manuscript(text: str) -> list[dict]:
    """
    1. 按句号/问号/感叹号拆分为候选句子
    2. 每个句子 est_duration = len(text) / 4.0
    3. 贪心合并：累计时长 ∈ [5, 12] 秒
    4. 长句（> 12s）接受，不拆
    5. 短句（< 5s）合并到前一段
    """
```

### 6.8 字幕多行换行算法

```python
def _split_long_text(txt: str, max_chars_per_line: int) -> str:
    """
    1. 检测文本是否含 CJK 字符
    2. CJK 文本：按字符数判断，超过阈值则拆为两行
       - 优先在中间附近的标点符号（，。、；！？）处断开
       - 无标点则在正中间拆分
    3. 非 CJK 文本：按单词数判断，超过阈值按单词拆为两行
    4. max_chars_per_line 动态计算 = (video_width - 40) // fontsize
    """
```

字幕渲染使用 `method="caption"` 替代 `method="label"`，配合 `size=(available_w, None)` 实现宽度约束内的自动换行。

### 6.9 SRT 细粒度字幕生成

```python
def _generate_fine_srt_from_word_cues(word_cues, max_duration=2.5, max_chars=18):
    """
    1. 将 edge_tts SubMaker 词级 cues 转为 (start, end, text) 三元组
    2. 计算词间停顿（gap）
    3. 贪心分组：按 max_duration 和 max_chars 约束
       - 持续时长超限 → 断开
       - 字符数超限 → 断开
       - 停顿 > 0.4s 且已积累内容 → 断开
    4. 后处理：合并过短的尾部组
    5. 确保每组 ≥ 0.3s，相邻组不重叠
    """
```

> 自 v5.1 起，字幕时间线以 edge_tts `SubMaker.cues`（词级时间戳）为"真值"（`generate_cue_aware_srt`，策略 A 文本锚定 / 策略 B 时间区间兜底），详见 `docs/dev/pipeline_products.md` §1.2。

### 6.10 CJK 字体回退机制

```python
def resolve_font_path(font: str) -> str:
    """
    优先级：
    1. 绝对路径且存在 → 直接返回
    2. 文件名 → 在 resource/fonts/ 查找
    3. 已知非 CJK 字体名（Arial, Helvetica 等）→ 回退到 STHeitiMedium.ttc
    4. 其他 → 当作系统字体返回
    """
```

---

## 七、大版本回归

用户说 **"执行大版本回归"** 时，加载 `docs/dev/regression_test_plan.md` 按流程执行。

### 核心规则

1. **只创建一轮任务**：严格按场景矩阵创建，每个场景恰好一个任务，不创建超出场景数的任务。
2. **回归不改代码**：回归过程中发现的任何问题，只记录在报告中，不修改业务代码；用户确认后再修复。
3. **失败记录具体原因**：报告中每个失败场景必须记录具体原因（HTTP 状态码、错误信息、超时时长等）。
4. **无明显原因须续传**：失败原因不明确（如超时、API 偶发故障）的场景，通过 `--resume` 续传完成，不跳过。

### 场景矩阵（S1 / C1-C3 / M1-M2 / A1-A2，共 8 场景）

| ID | 类型 | 场景 |
|----|------|------|
| S1 | 简单视频 | 关键帧动画 keyframes |
| C1 | 创意视频 | 带参考图+关键帧+无配音 |
| C2 | 创意视频 | 参考图生成尾帧+关键帧+无配音 |
| C3 | 创意视频 | 带字幕+配音+关键帧 |
| M1 | 稿件视频 | 短稿件+配音 |
| M2 | 稿件视频 | 短稿件+自定义字幕 |
| A1 | 数字人口播 | 数字人+后拼接音频 |
| A2 | 数字人口播 | 数字人+模型音频 |

### 执行命令

```bash
python scripts/regression_runner.py --auto-start   # 完整回归
python scripts/regression_runner.py --resume --auto-start  # 断点续传
python scripts/regression_runner.py --quick        # 仅验证已存在产物
python scripts/scene_runner.py --scenario C3       # 单场景（避免主 agent 内大量轮询）
python scripts/scene_runner.py --endpoints         # 端点验证
```

### 报告与问题处理

回归完成后输出三个报告文件（`docs/dev/regression_report.json` / `regression_report.md` / `regression_issues.md`）。

失败场景按原因分两类处理：

- **可恢复**（超时、API 故障、网络异常）→ `--resume` 续传重试
- **不可恢复**（HTTP 400 提示词错误）→ 记录具体原因，跳过，等用户确认后修复

---

## 八、Release 发布工作流

用户说 **"发版" / "发布" / "release"** 时，加载 `docs/dev/release_process.md` 按流程执行。

### 核心规则

1. **版本号三种类型**：大版本 `X.0.0` / 中版本 `X.Y.0` / 小版本 `X.Y.Z`，对应版本号三位；**升位由用户要求触发**，Agent 不得自行升版。
2. **release 文档 = 使用方式 + 新增内容**：使用方式沿用现有各 release 包用法；新增内容含「大的功能更新」「大的代码层面优化/重构（开源价值）」「集中的小 bug 修复」。
3. **红线不写**：文档整理、纯营收向 SEO/引流优化、镜像同步等对用户无作用的工作，一律不提及；小型重构也不写。
4. **SEO 与独立检索**：release 内容后续供官网板块展示，标题/Overview 覆盖核心功能关键词、自包含可独立检索；但只做内容型 SEO，不做关键词堆砌等作弊。
5. **产出**：`docs/public/release-notes/release_notes_vX.Y.Z.md` + git tag，CI 自动组 GitHub Release（body = 使用方式 + 新增内容）。

### 版本号映射

| 用户要求 | 升位 | 新增内容侧重 |
|----------|------|--------------|
| 发个小版本 | `Z+1` | 以 Bug 修复为主，按类归纳 |
| 发布中版本 | `Y+1`，`Z` 清零 | 功能更新 + 修复并重 |
| 发大版本 | `X+1`，`Y/Z` 清零 | 以功能更新为主，分节介绍 |
| 升到 vX.Y.Z | 直接采用 | 按实际变化写 |

---

## 九、开发规范

- **Python**：Google 风格 docstring，类型注解，async/await 用于 IO
- **前端**：ES6+，不引入框架
- 所有文件 UTF-8 编码
- 改动完成后运行：`.venv/bin/python -m py_compile <改动文件>`；涉及流水线跑 `./scripts/run_mock_regression.sh`
- 新增功能按「四、AI Agent 触发词」→「新增功能」流程：需求分析 → 增量 PRD → `docs/plans/vX.Y/system_design.md` 增量 → 实现

---

*文档版本：v7.2 | 更新日期：2026-08-13 | 阶段：🟢 维护模式（六种任务类型 + artifacts/水印/多工作区/13 语言音色）*
