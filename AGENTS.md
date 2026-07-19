# AGENTS.md — Agnes Video Generator v2.0

> **面向对象**：SoftwareCompany 团队（产品经理 / 架构师 / 工程师 / QA 工程师）及 AI Agent
> **当前阶段**：🟢 **开发完成（v2.0） — 维护模式**
> **配套文档**：`docs/regression_test_plan.md`（大版本回归）、`docs/plans-v1.0/system_design.md`（v1.0 原始设计）

---

## 〇、新环境部署与验证（AI Agent 必读）

> 本节为 AI Agent（Claude、Cursor、QoderWork 等）在全新环境中部署和验证本项目提供完整指引。

### 0.1 环境检查

在执行任何操作前，先确认目标环境满足以下条件：

```bash
# 检查 Python 版本（需 3.10+）
python3 --version

# 检查 ffmpeg（视频拼接和音频处理依赖）
ffmpeg -version

# 如果 ffmpeg 未安装：
# macOS:   brew install ffmpeg
# Ubuntu:  sudo apt install ffmpeg
# Windows: choco install ffmpeg 或从 https://ffmpeg.org/download.html 下载
```

### 0.2 一键部署

```bash
# 克隆项目（如尚未克隆）
git clone https://github.com/your-org/agnes-video-generator.git
cd agnes-video-generator

# 一键启动（自动创建 venv、安装依赖、启动服务）
./start.sh
```

启动成功后，服务监听在 `http://localhost:8765`。macOS 会自动在浏览器中打开页面。

如需手动部署：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

### 0.3 API Key 配置

Agnes AI API Key 是视频生成的必要前提。两种配置方式：

```bash
# 方式 1：环境变量（推荐 Agent 使用）
export AGNES_API_KEY="your-api-key"

# 方式 2：通过 API 设置（模拟 Web UI 操作）
curl -X POST http://localhost:8765/api/config \
  -H "Content-Type: application/json" \
  -d '{"api_key": "your-api-key"}'
```

### 0.4 部署验证清单

部署完成后，按以下清单逐项验证：

#### 第一层：基础连通性

```bash
# 1. Web UI 可达
curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/
# 期望：200

# 2. API 配置读取正常
curl -s http://localhost:8765/api/config | python3 -m json.tool
# 期望：{"ok": true, "api_key": "...(masked)"}

# 3. TTS 语音列表可达
curl -s http://localhost:8765/api/voices | python3 -m json.tool
# 期望：返回按 13 种项目语言分组的音色目录 JSON

# 4. 任务列表可达
curl -s http://localhost:8765/api/tasks | python3 -m json.tool
# 期望：{"ok": true, "tasks": [...]}
```

#### 第二层：静态分析

```bash
# Python 语法检查（所有 .py 文件）
.venv/bin/python -m py_compile server.py
.venv/bin/python -m py_compile core/config.py
.venv/bin/python -m py_compile core/task_manager.py
.venv/bin/python -m py_compile core/screenwriter.py
.venv/bin/python -m py_compile core/api/agnes_chat.py
.venv/bin/python -m py_compile core/api/agnes_image.py
.venv/bin/python -m py_compile core/api/agnes_video.py
.venv/bin/python -m py_compile core/api/rate_limiter.py
.venv/bin/python -m py_compile core/audio/tts.py
.venv/bin/python -m py_compile core/audio/subtitle.py
.venv/bin/python -m py_compile core/compositor/concatenator.py
.venv/bin/python -m py_compile core/compositor/processor.py
.venv/bin/python -m py_compile core/pipelines/simple_video.py
.venv/bin/python -m py_compile core/pipelines/creative_video.py
.venv/bin/python -m py_compile core/pipelines/manuscript_video.py
.venv/bin/python -m py_compile models/task.py

# 关键模块导入验证
.venv/bin/python -c "from core.api.agnes_video import AgnesVideoAPI; print('AgnesVideoAPI OK')"
.venv/bin/python -c "from core.api.agnes_image import AgnesImageAPI; print('AgnesImageAPI OK')"
.venv/bin/python -c "from core.api.agnes_chat import AgnesChatAPI; print('AgnesChatAPI OK')"
.venv/bin/python -c "from core.api.rate_limiter import get_rate_limiter; print('RateLimiter OK')"
.venv/bin/python -c "from core.audio.tts import EdgeTTSEngine, SilentTTSEngine; print('TTS OK')"
.venv/bin/python -c "from core.audio.subtitle import SubtitleGenerator; print('Subtitle OK')"
.venv/bin/python -c "from core.compositor.concatenator import VideoConcatenator; print('Concatenator OK')"
.venv/bin/python -c "from models.task import parse_task_state, SimpleVideoTask, CreativeVideoTask, ManuscriptVideoTask; print('Models OK')"
```

#### 第三层：端点功能验证

```bash
# 创建简单视频任务（参数校验）
curl -X POST http://localhost:8765/api/tasks/simple \
  -H "Content-Type: application/json" \
  -d '{"prompt": "一只猫在花园里追蝴蝶", "mode": "t2v", "duration": 5}'

# 创建创意视频任务（参数校验）
curl -X POST http://localhost:8765/api/tasks/creative \
  -H "Content-Type: application/json" \
  -d '{"idea": "太空探险故事", "video_width": 768, "video_height": 1152}'

# 创建稿件视频任务（参数校验）
curl -X POST http://localhost:8765/api/tasks/manuscript \
  -H "Content-Type: application/json" \
  -d '{"manuscript_text": "这是第一段测试文本。这是第二段测试文本。"}'

# 验证任务列表包含三种类型
curl -s http://localhost:8765/api/tasks | python3 -c "
import json, sys
data = json.load(sys.stdin)
types = set(t.get('task_type') for t in data.get('tasks', []))
print(f'Task types found: {types}')
assert 'simple' in types, 'Missing simple task'
assert 'creative' in types, 'Missing creative task'
assert 'manuscript' in types, 'Missing manuscript task'
print('All 3 task types verified!')
"
```

#### 第四层：字幕多行功能验证

```bash
# 验证字幕拆分函数逻辑
.venv/bin/python -c "
from core.audio.subtitle import SubtitleGenerator

# 短文本不拆分
assert SubtitleGenerator._split_long_text('短视频', 14) == '短视频'

# 长中文文本拆为两行
result = SubtitleGenerator._split_long_text('这是一段比较长的中文字幕文本需要拆分显示在视频上方', 14)
assert '\n' in result, f'Expected newline in: {repr(result)}'
lines = result.split('\n')
assert len(lines) == 2, f'Expected 2 lines, got {len(lines)}'

# 标点处优先断行
result = SubtitleGenerator._split_long_text('今天天气真好，我们一起去公园散步吧', 14)
assert result == '今天天气真好，\n我们一起去公园散步吧', f'Got: {repr(result)}'

# 长英文按单词拆分
result = SubtitleGenerator._split_long_text('This is a very long English subtitle text that should be split', 14)
assert '\n' in result

# 空文本和已有换行不处理
assert SubtitleGenerator._split_long_text('', 14) == ''
assert SubtitleGenerator._split_long_text('已有\n换行', 14) == '已有\n换行'

print('All subtitle multi-line tests passed!')
"
```

### 0.5 常见问题排查

| 现象 | 原因 | 解决方案 |
|------|------|---------|
| `ModuleNotFoundError: No module named 'xxx'` | venv 未激活或依赖未装 | `.venv/bin/pip install -r requirements.txt` |
| `ffmpeg not found` | ffmpeg 未安装 | `brew install ffmpeg` 或系统包管理器安装 |
| 端口 8765 被占用 | 上一次服务未关闭 | `lsof -ti:8765 \| xargs kill` 后重试 |
| 视频生成失败 401 | API Key 无效或未配置 | 检查 `AGNES_API_KEY` 环境变量或 `/api/config` |
| 字幕中文显示为方块 | CJK 字体缺失 | 检查 `resource/fonts/STHeitiMedium.ttc` 是否存在 |
| TTS 无声音 | edge_tts 版本过低 | `.venv/bin/pip install 'edge_tts>=6.1.0'` |

---

## 一、AI Agent 触发词

| 用户说法 | 主理人应执行的操作 | 说明 |
|---------|-------------------|------|
| **"修复 Bug: ..."** | 启动 `software-engineer`（BugFix 快捷路径） | 定位→修复→自验→汇报 |
| **"执行大版本回归"** | 按 `docs/regression_test_plan.md` 执行全量回归测试 | 10 场景并发 + 端点验证 |
| **"新增功能: ..."** | 启动 `software-product-manager` → 需求分析 | 增量功能开发 |
| **"需求分析" / "只做 PRD"** | 启动 `software-product-manager` | 部分工作流 |
| **"架构评审"** | 启动 `software-architect` | 部分工作流 |
| **"部署项目" / "初始化环境"** | 按「〇、新环境部署与验证」执行 | 全新环境部署 |
| **"验证项目" / "跑一下检查"** | 按「0.4 部署验证清单」执行 | 部署后验证 |

---

## 二、项目定位

基于 Agnes AI **完全免费**模型的视频生成工具，支持 **六种任务类型**（外加简单图片生成）的一站式 Web 应用。

自 v4.0 起，创意 / 稿件 / 数字人 / 诗词四种长视频流水线统一继承 `MultiScenePipeline`（模板方法核心：`build_scenes → build_reference_images → generate_videos → audio+subtitle → composite`），仅简单视频直接继承 `BasePipeline`。

- **简单视频**（simple）：单次调用 Agnes Video API，暴露全部参数的结构化 UI（t2v / i2v / ti2vid / keyframes）
- **创意长视频**（creative）：AI 编剧 → 分镜图生成 → 视频生成 → edge_tts 旁白配音 + 细粒度字幕叠加 → 拼接
- **稿件长视频**（manuscript）：长文本 → 时间估算拆段 → AI 场景 prompt → 逐段视频生成 → 统一 TTS+字幕 → 拼接
- **数字人口播**（anchor）：数字人形象 → 循环 i2v 视频，支持 `post_stitch`（TTS 后拼接音频）与 `model`（模型自带口型音频）两种音频模式
- **诗词视频**（poetry）：古诗 → LLM 拆分场景（原诗句作旁白，场景描述作视频 prompt）→ 逐句 t2v + TTS 朗诵 + 定时对齐字幕 → 拼接
- **简单图片**（simple_image）：单次调用 Agnes Image API 的结构化 t2i / i2i 生成

> 另有 `multi_scene`（多场景通用框架，非独立任务类型，而是上述长视频流水线的共享基类）。

---

## 三、技术栈

| 层 | 选型 |
|------|------|
| 后端框架 | Python FastAPI（进度经任务状态轮询暴露，非 WebSocket） |
| 数据模型 | Pydantic v2 |
| 视频处理 | moviepy + ffmpeg |
| TTS | edge_tts >= 6.1.0（免费，无需 API Key） |
| 字幕 | srt >= 3.5.0 + moviepy（词级细粒度 + 多行换行） |
| 前端 | 原生 HTML/CSS/JS + Tailwind CDN（单文件 `static/index.html`，多 Tab + 13 语言 i18n） |
| LLM | Agnes Chat API (`agnes-2.0-flash`) — 免费 |
| 图片模型 | `agnes-image-2.1-flash` (t2i) / `agnes-image-2.0-flash` (i2i) — 免费 |
| 视频模型 | `agnes-video-v2.0` — 免费 |
| 水印 | moviepy TextClip 生成 PNG + ffmpeg overlay 叠加（避免整片重编码 OOM） |
| 音色 | edge_tts 动态音色目录，按 13 种项目语言分组 + 跨脚本兼容性校验 |
| 日志 | `logging.getLogger(__name__)` |

---

## 四、目录结构

```
agnes-video-generator/
├── server.py                         # FastAPI 主服务，六种任务路由 + 图片生成 + 工作区管理 + artifacts
├── start.sh                          # 一键启动脚本（venv + pip install + run）
├── requirements.txt                  # 依赖（含 edge_tts, srt, tenacity）
│
├── models/
│   ├── __init__.py
│   └── task.py                       # TaskType/VideoMode + BaseTaskState + 6 任务子类
│                                     #   (Simple/Creative/Manuscript/Anchor/Poetry/SimpleImage)
│                                     #   + Subtitle/Audio 配置 + 请求/响应/WS 模型
│
├── core/
│   ├── __init__.py
│   ├── config.py                     # API Key/水印/工作区持久化、字体 CJK 回退、音视频默认配置
│   ├── task_manager.py               # 任务状态持久化，多态反序列化，向后兼容
│   ├── screenwriter.py               # 编剧 Agent（故事/脚本/旁白/角色提取/尾帧/诗词场景 prompt）
│   ├── artifacts.py                  # 中间产物注册表 + 级联删除计划（creative/manuscript/anchor）
│   │
│   ├── pipeline.py                   # 向后兼容别名 → core.pipelines.creative_video
│   ├── image_generator.py            # 向后兼容别名 → core.api.agnes_image
│   ├── video_generator.py            # 向后兼容别名 → core.api.agnes_video
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── agnes_chat.py             # LLM Chat API（text + multimodal + JSON mode）
│   │   ├── agnes_image.py            # 图片生成 API（t2i + i2i + ref image）
│   │   ├── agnes_video.py            # 视频生成 API（t2v/i2v/ti2vid/keyframes + 轮询 + 重试）
│   │   ├── rate_limiter.py           # 全局令牌桶限速器（16 次/分钟，Chat+Image+Video 共享）
│   │   └── error_collector.py        # 模型接口报错收集（prompt/错误类型/详情 → error_logs/）
│   │
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── tts.py                    # EdgeTTSEngine（旁白+词级时间戳）+ SilentTTSEngine
│   │   ├── subtitle.py               # SRT 生成（词级细粒度 + 多行换行）+ moviepy 字幕叠加
│   │   └── voices.py                 # 音色目录（13 语言分组）+ 跨脚本兼容性校验矩阵
│   │
│   ├── compositor/
│   │   ├── __init__.py
│   │   ├── concatenator.py           # 视频拼接 + 统一音频/字幕叠加（MoneyPrinterTurbo 方式）
│   │   ├── processor.py              # 视频缩放/帧提取/定格延长/静音音频生成
│   │   └── watermark.py              # ffmpeg overlay 水印叠加 + 语言检测
│   │
│   └── pipelines/
│       ├── __init__.py               # BasePipeline 抽象基类（共享 shutdown/WS 推送/字幕/水印）
│       ├── multi_scene.py            # MultiScenePipeline 多场景模板方法基类（v4.0 重构核心）
│       ├── simple_video.py           # 类型 1：单 prompt → 单视频（直接继承 BasePipeline）
│       ├── creative_video.py         # 类型 2：创意长视频（继承 MultiScenePipeline）
│       ├── manuscript_video.py       # 类型 3：稿件长视频（继承 MultiScenePipeline）
│       ├── anchor_video.py           # 类型 4：数字人口播（继承 MultiScenePipeline）
│       └── poetry_video.py           # 类型 6：诗词视频（继承 MultiScenePipeline）
│
├── utils/
│   ├── __init__.py
│   ├── image.py                      # 图片下载 / base64 转换 / URL 上传
│   └── video.py                      # 视频下载
│
├── resource/
│   └── fonts/                        # 内置 CJK 字体
│       ├── STHeitiMedium.ttc         # 默认中文字体（CJK 自动回退目标）
│       └── MicrosoftYaHeiNormal.ttc  # 备用中文字体
│
├── static/
│   ├── index.html                    # 多 Tab 前端（简单/创意/稿件/数字人/诗词/图片），13 语言 i18n
│   ├── favicon.ico
│   └── icon.png
│
├── scripts/
│   ├── regression_runner.py          # 大版本回归测试脚本
│   ├── scene_runner.py               # 单场景/端点回归执行器
│   └── run_mock_regression.sh        # mock 回归一键脚本
│
├── tests/
│   ├── test_core.py                  # 核心单元测试
│   └── mock_regression/              # mock 回归框架（mock API + fixture + 流水线测试）
│       ├── conftest.py / mock_apis.py / test_pipelines.py
│       ├── assets/                   # 测试图片/视频
│       └── fixture_data/             # 编剧/场景/字幕等 mock 返回数据
│
└── docs/
    ├── regression_test_plan.md       # 大版本回归测试计划
    ├── tts_research_report.md        # TTS 选型研究
    ├── voice_selector_design.md      # 音色选择器设计
    ├── watermark_*.md                # 水印设计/评估/实现文档
    ├── plans-v1.0/                   # v1.0 计划文档（含 system_design、类图、时序图）
    ├── plans-v2.0/                   # v2.0 计划 & 审查（code review、bug fix、i2i 优化）
    ├── plans-v3.0/                   # v3.0 计划文档
    ├── plans-v4.0/                   # v4.0 计划（mock 回归设计、pipeline 重构）
    └── release-notes/                # v2.0 ~ v3.0 发布说明
```


---

## 五、BugFix 工作流

用户说 **"修复 Bug: ..."** 时，主理人按以下流程执行：

```
1. 定位
   - 阅读用户描述的 bug 现象
   - 用 codegraph / grep 定位到相关文件和代码行
   - 复现 bug（如能通过 API 调用复现）

2. 修复
   - 启动 software-engineer 执行修复
   - 确保修复不违反 AGENTS.md 中的共享知识规范

3. 自验
   - bash start.sh 正常启动（Uvicorn 监听 8765 端口无报错）
   - 受影响的端点 curl 验证返回正确结果
   - 已有功能不被破坏

4. 汇报
   - 向用户说明：根因、修复方案、涉及文件
   - 附 curl 验证结果
```

---

## 六、大版本回归测试

用户说 **"执行大版本回归"** 时，主理人加载 `docs/regression_test_plan.md` 按流程执行。

### 核心规则

1. **只创建一轮任务**：严格按场景矩阵创建，每个场景恰好一个任务，不创建超出场景数的任务。
2. **回归不改代码**：回归过程中发现的任何问题，只记录在报告中，不修改业务代码；用户确认后再修复。
3. **失败记录具体原因**：报告中每个失败场景必须记录具体原因（HTTP 状态码、错误信息、超时时长等）。
4. **无明显原因须续传**：失败原因不明确（如超时、API 偶发故障）的场景，通过 `--resume` 续传完成，不跳过。

### 场景矩阵

| ID | 类型 | 场景 | 权重 |
|----|------|------|------|
| S1 | 简单视频 | 关键帧动画 keyframes | 1 |
| C1 | 创意视频 | 带参考图+关键帧+无配音 | 3 |
| C2 | 创意视频 | 参考图生成尾帧+关键帧+无配音 | 3 |
| C3 | 创意视频 | 带字幕+配音+关键帧 | 3 |
| M1 | 稿件视频 | 短稿件+配音 | 4 |
| M2 | 稿件视频 | 短稿件+自定义字幕 | 4 |
| A1 | 数字人口播 | 数字人+后拼接音频 | 2 |
| A2 | 数字人口播 | 数字人+模型音频 | 2 |

### 执行命令

```bash
# 完整回归
python scripts/regression_runner.py --auto-start

# 断点续传（失败场景续传）
python scripts/regression_runner.py --resume --auto-start

# 仅验证已存在产物
python scripts/regression_runner.py --quick

# 单独执行某个场景（避免主 agent 内大量轮询）
python scripts/scene_runner.py --scenario C3

# 端点验证
python scripts/scene_runner.py --endpoints
```

### 报告与问题处理

回归完成后输出三个报告文件：

| 文档 | 路径 | 内容 |
|------|------|------|
| JSON 数据 | `docs/regression_report.json` | 结构化数据，用于续传和程序化分析 |
| 测试报告 | `docs/regression_report.md` | 全部场景的执行结果、检查项、端点验证 |
| 问题清单 | `docs/regression_issues.md` | 仅包含失败/异常/需关注的项目 |

失败场景按原因分两类处理：

- **可恢复**（超时、API 故障、网络异常）→ `--resume` 续传重试
- **不可恢复**（HTTP 400 提示词错误）→ 记录具体原因，跳过，等用户确认后修复

---

## 七、各角色工作说明

### 7.1 产品经理（许清楚）

**输入**：用户需求描述（新增功能）
**产出**：`PRD_REFACTOR.md`（增量 PRD）

**产出规范**：
- 产品目标（3-5 条）
- 用户故事
- 需求池（P0/P1/P2）
- UI 设计概要（ASCII 布局图）
- 技术选型沿用现有栈，不可引入付费服务

---

### 7.2 架构师（高见远）

**输入**：PRD 文档
**产出**：`docs/plans-v1.0/system_design.md` 增量更新（或新版本架构文档）

---

### 7.3 工程师（寇豆码）

**输入**：Bug 描述 / 架构设计
**产出**：修复代码或新功能代码

**代码风格约束**：
- Python：Google 风格 docstring，类型注解，async/await 用于 IO
- 前端：ES6+，不引入框架
- 所有文件 UTF-8 编码

---

### 7.4 QA 工程师（严过关）

**输入**：工程师完成的代码
**产出**：测试验证报告

**验证层次**：

#### 第一层：静态分析
```
[ ] Python 语法检查：python -m py_compile 所有 .py 文件
[ ] 导入验证：python -c "from core.api.agnes_video import AgnesVideoAPI" 等
[ ] 前端语法：HTML/JS 无语法错误
```

#### 第二层：单元测试
| 模块 | 测试点 |
|------|--------|
| `models/task.py` | 序列化/反序列化、多态 parse_task_state |
| `core/audio/subtitle.py` | SRT 格式输出、`_split_long_text` 多行换行 |
| `core/audio/tts.py` | EdgeTTSEngine + SilentTTSEngine |
| `manuscript_video.py` | split_manuscript() 拆段算法 |
| `core/config.py` | 默认配置结构、resolve_font_path CJK 回退 |
| `core/task_manager.py` | 旧数据兼容（无 task_type → CREATIVE） |

#### 第三层：集成测试
| 端点 | 测试点 |
|------|--------|
| `GET /` | 返回 200，多 Tab HTML |
| `GET /api/config` | 返回 ok: true |
| `GET /api/voices` | 返回按 13 语言分组的音色目录 |
| `POST /api/tasks/simple` | 参数校验 + task_type: simple |
| `POST /api/tasks/creative` | 参数校验 + task_type: creative |
| `POST /api/tasks/manuscript` | 参数校验 + task_type: manuscript |
| `POST /api/tasks/poetry` | 参数校验 + task_type: poetry |
| `POST /api/tasks/anchor` | 参数校验 + task_type: anchor |
| `GET /api/tasks` | 列表含各任务类型 |
| `GET /api/tasks/{id}` | 返回 task_type |
| `POST /api/tasks/{id}/stop` | 停止运行中任务 |
| `GET /api/video/{id}` | 视频文件下载/流式播放 |

---

## 八、共享知识规范

### 8.1 日志前缀

| 前缀 | 模块 |
|------|------|
| `[Startup]` | server.py 启动 |
| `[Resume]` | server.py resume |
| `[Stop]` | server.py stop |
| `[Workspace]` | server.py 工作区管理 |
| `[Concurrency]` | server.py 并发信号量 |
| `[Preview]` | server.py 音色试听 |
| `[Cleanup]` | server.py 回归清理 |
| `[Pipeline]` | 流水线通用（BasePipeline） |
| `[MultiScene]` | multi_scene.py |
| `[Simple]` | simple_video.py |
| `[Creative]` | creative_video.py |
| `[Manuscript]` | manuscript_video.py |
| `[Anchor]` | anchor_video.py |
| `[Poetry]` | poetry_video.py |
| `[EndFrame]` / `[Keyframes]` | 尾帧 / 关键帧处理 |
| `[TTS]` | tts.py |
| `[Subtitle]` | subtitle.py |
| `[Voices]` | voices.py |
| `[Compositor]` | compositor/ concatenator/processor |
| `[Watermark]` | watermark.py |
| `[Image]` | 图片生成流程 |
| `[AgnesImage]` | agnes_image.py |
| `[AgnesVideo]` | agnes_video.py |
| `[AgnesChat]` | agnes_chat.py |
| `[RateLimiter]` | rate_limiter.py |
| `[ErrorCollector]` | error_collector.py |
| `[Artifacts]` | artifacts.py |
| `[TaskManager]` | task_manager.py |
| `[Screenwriter]` | screenwriter.py |

### 8.2 错误处理与全局限速

| 场景 | 策略 |
|------|------|
| 全局限速 | `core/api/rate_limiter.py` 令牌桶（默认 `AGNES_RATE_LIMIT=20`，`_SAFETY_FACTOR` 留 20% 余量 → 实际 16 次/分钟），Chat+Image+Video 含轮询共享 |
| LLM Chat | 重试 3 次，间隔 15s 递增；5xx 和 429 均重试 |
| 图片生成 | 重试 3 次，间隔 20s 递增；5xx 和 429 均重试 |
| 视频提交 | 重试 5 次，间隔 30s 递增；5xx、429、超时均重试 |
| 视频轮询 | 间隔 60s（见 D14），每 10 次输出日志；连续 10 次失败后放弃 |
| 报错收集 | `error_collector.py` 记录失败调用的 prompt/错误类型/详情至工作目录 `error_logs/` |
| PipelineShutdown | 所有流水线统一处理，落盘当前状态 |
| TTS 失败 | 降级为静音 + 字幕 |

### 8.3 向后兼容

- `TaskManager.load()` 自动将无 `task_type` 字段的旧数据识别为 `CreativeVideoTask`
- 旧 `task_state.json` 字段名保持不变
- `core/pipeline.py`、`core/image_generator.py`、`core/video_generator.py` 为**向后兼容别名模块**（重导出 `core.pipelines` / `core.api` 中的真实类，如 `VideoPipeline = CreativeVideoPipeline`），非废弃空文件，勿删

### 8.4 API 响应格式

```json
// 成功
{"ok": true, "task_id": "...", ...}

// 失败
HTTPException(status_code=4xx/5xx, detail="...")
```

### 8.5 内部进度事件结构（WSMessage）

`WSMessage` 是流水线通过 `BasePipeline._emit` 产生的进度事件结构，落盘到任务状态供前端轮询读取（当前无 WebSocket 推送）：

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

### 8.6 视频-音频同步策略

```python
final_duration = max(audio_duration + 1.0, original_video_duration)
# padding ≤ 1 秒，不足时尾帧 freeze
```

创意视频和稿件视频均采用"MoneyPrinterTurbo 方式"：先拼接所有视频片段，再整体叠加一条合并音频 + 一套字幕，避免逐段叠加导致的 padding 累积误差。TTS 输出自动放大 2.5 倍音量以补偿 edge_tts 默认低音量。

### 8.7 稿件拆段算法

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

### 8.8 字幕多行换行算法

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

### 8.9 SRT 细粒度字幕生成

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

### 8.10 CJK 字体回退机制

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

## 九、API 端点完整列表

> 前端采用**轮询模式**获取进度：任务创建后定期 `GET /api/tasks/{id}` 拉取状态（见 `static/index.html` 的 `pollTaskProgress`），当前版本对外**无 WebSocket 端点**。`WSMessage` 模型与 `BasePipeline._emit` 仅作为内部进度事件结构落盘到任务状态。

### 配置与工作区

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Web UI 页面 |
| GET | `/api/config` | 获取 API Key（脱敏） |
| POST | `/api/config` | 保存 API Key |
| DELETE | `/api/config` | 清除 API Key |
| POST | `/api/config/watermark` | 保存水印开关配置 |
| GET | `/api/workspaces` | 列出工作区 |
| POST | `/api/workspaces` | 新建工作区 |
| DELETE | `/api/workspaces` | 删除工作区 |
| POST | `/api/workspaces/active` | 激活工作区 |
| GET | `/api/workspaces/pick-directory` | 原生目录选择对话框 |

### 音色

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/voices` | 列出可用 TTS 音色（按 13 语言分组） |
| GET | `/api/voices/preview` | 音色试听（生成/缓存样本） |
| GET | `/api/voices/compat` | 音色与目标语言/文本兼容性校验 |

### 图片

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/image/generate` | 生成简单图片（t2i / i2i） |
| GET | `/api/image/{task_id}` | 下载/预览生成的图片 |

### 任务创建

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks/simple` | 创建简单视频任务 |
| POST | `/api/tasks/creative` | 创建创意长视频任务 |
| POST | `/api/tasks/manuscript` | 创建稿件长视频任务 |
| POST | `/api/tasks/poetry` | 创建诗词视频任务 |
| POST | `/api/tasks/anchor` | 创建数字人口播任务 |
| POST | `/api/tasks` | 兼容旧版（映射到 creative） |
| GET | `/api/poetry-scene-prompt` | 诗词场景 prompt 预生成 |

### 任务查询与控制

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 列出所有任务（含 task_type 标识） |
| GET | `/api/tasks/{id}` | 查询任务详情（轮询进度） |
| POST | `/api/tasks/{id}/resume` | 续传中断任务 |
| POST | `/api/tasks/{id}/stop` | 停止运行中的任务 |
| GET | `/api/video/{id}` | 下载/流式播放最终视频 |

### 中间产物（artifacts）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks/{id}/artifacts` | 列举任务的所有中间产物 |
| GET | `/api/tasks/{id}/artifacts/{artifact_id}/file` | 下载单个产物文件 |
| GET | `/api/tasks/{id}/artifacts/{artifact_id}/cascade-preview` | 预览删除某产物的级联影响 |
| DELETE | `/api/tasks/{id}/artifacts/{artifact_id}` | 删除产物（含级联删除） |

### 运维

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/concurrency` | 并发信号量利用率状态 |
| POST | `/api/cleanup-regression` | 清理回归测试产物 |

---

## 十、关键决策记录

| ID | 决策 | 详情 |
|----|------|------|
| D1 | 稿件拆段 | 时间估算 4 字/秒，5-12s/段，不拆句子 |
| D2 | 稿件 scene prompt | AI 生成英文 prompt，原文作旁白+字幕 |
| D3 | TTS 默认语音 | `zh-CN-XiaoxiaoNeural` |
| D4 | 视频 padding | ≤ 1 秒 |
| D5 | 简单视频 prompt | 结构化暴露 Agnes API 全部 9 个参数，不做 AI 增强 |
| D6 | 旧数据兼容 | 无 task_type → CREATIVE |
| D7 | 多语言 | 13 语言 i18n (zh/en/ja/ko/ru/de/fr/nl/es/pt/it/id/ms)，音色按脚本体系分组校验 |
| D8 | TTS 付费方案 | 不引入，仅用 edge_tts（免费） |
| D9 | 字幕多行换行 | 动态计算每行字符数上限，CJK 标点处断行，method="caption" |
| D10 | 音频叠加方式 | MoneyPrinterTurbo 方式：先拼接再整体叠加，避免 padding 累积 |
| D11 | TTS 音量补偿 | 自动 2.5 倍放大，补偿 edge_tts 默认低音量 |
| D12 | 全局 API 限速 | 令牌桶 16 次/分钟（Agnes 限制 20，留 20% 余量），Chat+Image+Video 含轮询共享 |
| D13 | 429 统一重试 | Chat/Image/Video 三个 API 模块均处理 HTTP 429 限流，指数退避重试 |
| D14 | 视频轮询间隔 | 60 秒（从 30s 改为 60s，进一步减少轮询对限速配额消耗） |
| D15 | 回归续传策略 | 可恢复失败（timeout/API 故障）自动重试，不可恢复（400 提示词错误）跳过 |

---

*文档版本：v6.0 | 更新日期：2026-07-15 | 阶段：🟢 维护模式（代码已演进至六种任务类型 + artifacts/水印/多工作区/13 语言音色）*
