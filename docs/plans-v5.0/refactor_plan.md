# v5.0 工程化重构计划（分批实施）

> 目标：针对代码评估中确认的**真实短板**（非外部通用评审），以「小步、可回退、每批独立交付」的方式逐步消除工程债。
> 配套：`AGENTS.md` 中已登记本文档为**重构唯一状态源**。
> 原则：**每批完成即可上线**（不引入跨批次的半成品）；每批内任务完成后必须更新 §五 状态表。

---

## 一、真实短板清单（来源：架构与代码质量评估）

| # | 短板 | 严重度 | 现状证据 |
|---|------|--------|---------|
| S1 | `server.py` 2050 行单体：36+ 路由、`WeightedSemaphore`、`active_pipelines`、`_pipeline_locks`、工具函数全部堆叠 | P0 | `server.py:101-133`（并发类）、`server.py:175-203`（锁/目录工具）、路由散布 L342~L1920 |
| S2 | 音频生成"EdgeTTS→Silent 降级 + harvest_cues"逻辑三处复制 | P0 | `multi_scene.py:251-335`、`poetry_video.py`（逐场景 TTS）、`creative_video.py:1597`（`_step_audio`） |
| S3 | `CreativeVideoPipeline` 覆写 `_execute_step` 破坏模板契约（粗粒度 skip 语义不一致） | P1 | `creative_video.py:1878-1888` vs `multi_scene.py:128-148` |
| S4 | 任务状态字段未对齐，`hasattr` 鸭子类型探测泛滥 | P1 | `multi_scene.py:261-282`（`audio_config`/`subtitle_config` 探测） |
| S5 | 巨型文件：`screenwriter.py` 1859 行 / `creative_video.py` 1968 行 / `subtitle.py` 1103 行 / `concatenator.py` 653 行 | P1 | 无类组织的模块级函数集合 + 巨型分隔注释 |
| S6 | 僵尸任务中间产物无自动清理，废弃任务长期占用磁盘 | P2 | `core/artifacts.py` 已有级联删除计划，但无自动清理触发 |
| S7 | 配置 `dict.get()` + 手工默认值，无类型校验 | P2 | `core/config.py` `load_config()` |
| S8 | 魔法数字：进度边界 `0.0/0.15/0.30/0.75/0.85/0.90/0.98`、重试间隔 `20*(retry+1)` | P2 | `multi_scene.py:63-96`、`multi_scene.py:240` |
| S9 | 单测避重就轻：编剧/拆段/音频降级等核心逻辑无直接单元测试 | P2 | `tests/test_core.py`（53 用例集中在纯函数） |

---

## 二、总体原则

1. **分批独立交付**：每批自带验收标准，完成后即处于可上线状态；不产生跨批半成品。
2. **行为等价优先**：重构以「不改变对外行为」为第一目标，仅允许修复顺带发现的小 bug。
3. **单一状态源**：本文档 §五 状态表是重构进度唯一权威；AGENTS.md 结构描述随批次同步更新。
4. **回归门槛**：每批完成必须通过 §六 验证清单（py_compile + mock 回归 + 关键端点冒烟）。
5. **批次顺序**：S1/S2（P0）先行；S3/S4 依赖基类与模型层，单独成批避免与 P0 冲突；S5~S9 为收尾。

---

## 三、批次路线图总览

| 批次 | 对应短板 | 主题 | 预计改动量 | 风险 |
|------|---------|------|-----------|------|
| **Batch 1** | S1 | `server.py` 模块化（APIRouter 拆分） | 大（纯移动） | 低（机械性） |
| **Batch 2** | S2 | 音频生成逻辑收敛到共享方法 | 中 | 中（三处行为等价） |
| **Batch 3** | S3+S4 | 模板契约修复 + 状态字段对齐 | 中 | 中（基类+模型层） |
| **Batch 4** | S5 | 巨型文件按职责拆分 | 大 | 中（import 链） |
| **Batch 5** | S6+S7+S8 | 资源清理 + 配置类型化 + 魔法数字收敛 | 小 | 低 |
| **Batch 6** | S9 | 核心逻辑单测补强 | 小 | 低 |

---

## 四、批次详细任务

### Batch 1 — server.py 模块化（S1，P0）

**目标**：`server.py` 缩减到 <400 行（仅保留 app 组装 + 生命周期），路由全部迁移到 `APIRouter` 模块。

**1.1 提取应用级状态为独立模块 `app_state.py`**
- 迁移：`WeightedSemaphore`（`server.py:101-133`）、`_pipeline_semaphore`、`active_pipelines`、`_queued_tasks`、`_pipeline_locks`、`shutdown_event`、`_launch_background_task`、`TASK_TYPE_WEIGHTS`、`MAX_CONCURRENT_WEIGHT`。
- 产出：`app_state.py` 暴露线程安全访问器，路由模块只依赖该模块。

**1.2 提取共享依赖 `deps.py`**
- 迁移：`_create_pipeline_for_type`、`_run_pipeline`、`_run_pipeline_with_concurrency`、`_get_pipeline_lock`、`_find_dir_name`、`get_upload_dir`。

**1.3 按域拆分为 8 个 router 模块（新建 `routes/` 包）**

| 模块 | 迁移路由 |
|------|---------|
| `routes/config_routes.py` | `/api/config`(GET/POST/DELETE)、`/api/models`、`/api/config/models`、`/api/config/watermark`、`/api/config/domain` |
| `routes/workspace_routes.py` | `/api/workspaces`(GET/POST/DELETE/active/pick-directory) |
| `routes/voice_routes.py` | `/api/voices`、`/api/voices/preview`、`/api/voices/compat` |
| `routes/image_routes.py` | `/api/image/generate`、`/api/image/{task_id}` |
| `routes/video_routes.py` | `/api/video/{task_id}`、`/api/tasks/{task_id}/artifacts*` |
| `routes/task_routes.py` | `/api/tasks`、`/api/tasks/{task_id}`、resume、stop、concurrency |
| `routes/task_creation_routes.py` | simple/creative/manuscript/poetry/anchor/legacy |
| `routes/utility_routes.py` | `/`、`/api/poetry-scene-prompt` |

**1.4 收敛残留工具函数**
- 迁移 `_parse_bg_color`/`_build_position` → `core/utils` 或 `routes/_helpers.py`；
- 音色预览相关（`_preview_cache_key`/`_get_or_generate_preview`/`_resolve_preview_text`/`_validate_voice_compat`）→ `core/audio/voice_preview.py`（也可推迟至 Batch 4，与 S5 合并，任选其一但需在状态表注明）。

**验收标准**
- `server.py` < 400 行；`pytest`/mock 回归全部通过；§六 冒烟端点全部 200。
- 所有 `@app` 装饰器改为 `router = APIRouter(...)` + `app.include_router`，URL 前缀与原路径完全一致。

---

### Batch 2 — 音频生成逻辑收敛（S2，P0）

**目标**：消除五处复制的"EdgeTTS→Silent 降级 + harvest_cues"逻辑（multi_scene/creative/poetry/manuscript/anchor），收敛为 `BasePipeline` 共享方法。

**2.1 在 `core/pipelines/__init__.py`（BasePipeline）新增共享方法**
- `_generate_audio_with_fallback(audio_path, text, ...) -> SubMaker|None`：封装 EdgeTTS 调用 → 失败降级 Silent → cues 不足时的 legacy 启发式 → 统一的日志与降级上报。

**2.2 调用方改造（实际 5 处：发现 manuscript/anchor 亦复制同逻辑）**
- `multi_scene.py:251-335` `_generate_audio`：改为调用共享方法（保留其 `getattr` 兼容层，等待 Batch 3 移除）。
- `poetry_video.py` 逐场景 TTS：改为循环调用共享方法（保留场景间延迟与时长校验增强）。
- `creative_video.py:1597` `_step_audio`：复用共享方法（删除其私有降级分支）。
- `manuscript_video.py:366` / `anchor_video.py:243` `_generate_audio`：同样收敛为共享方法（范围扩展）。

**2.3 行为差异确认**
- 各调用点对"音频关闭 + 字幕开启"（`harvest_cues_when_audio_off`）的处理细节先写对照用例锁定行为，再统一实现（实际产出 4 用例）。

**验收标准**
- 共享方法被 3+ 处调用，私有降级分支全部删除；
- mock 回归 + 新增 3 个音频降级单测通过（Edge 失败→Silent、cues 不足→legacy、audio-off+subtitle-on）。

---

### Batch 3 — 模板契约修复 + 状态字段对齐（S3+S4，P1）

**目标**：`MultiScenePipeline` 模板方法对所有子类语义一致；消除 `hasattr` 探测。

**3.1 修复 `_execute_step` 契约（S3）**
- 方案 A（推荐）：`MultiScenePipeline._execute_step` 增加 `coarse_skip: bool = True` 参数；Creative 用 `coarse_skip=False`，**删除 `creative_video.py:1878-1888` 的覆写**。
- 方案 B：将 Creative 的细粒度 skip 逻辑上提为通用默认。二选一，决策后在状态表注明。

**3.2 状态字段对齐（S4）**
- `models/task.py`：将 `audio_config` / `subtitle_config` 提升为 `BaseTaskState` 共享字段（`Field(default_factory=...)`），Creative/Manuscript/Anchor/Poetry 统一继承。
- 移除 `multi_scene.py:261-282` 的 `hasattr`/`getattr` 探测，直接访问字段。
- 向后兼容：`parse_task_state()` 保持旧 JSON 数据可反序列化（缺字段自动取默认）。

**验收标准**
- `grep -rn "hasattr" core/pipelines/` 无结果；
- Creative 不再覆写 `_execute_step`；
- 旧任务 JSON（缺 `audio_config` 字段）加载后字段为默认值，resume 正常；
- mock 回归全绿。

---

### Batch 4 — 巨型文件拆分（S5，P1）

**目标**：无单文件超过 ~800 行；职责内聚；import 无循环依赖。

**4.1 拆分 `screenwriter.py`（1859 行）**
- `core/screenwriter/` 包：
  - `story.py`：故事/脚本/旁白生成（`write_story`/`write_script`/`generate_narrations` 等）；
  - `scenes.py`：场景配置解析、拆段、诗词场景拆分（`build_poetry_scene_prompt` 等）；
  - `characters.py`：角色提取、尾帧 prompt；
  - `style.py`：字幕 LLM 样式；
  - `__init__.py`：**保留全部原函数名 re-export**（对外零改动，`server.py`/各 pipeline 的 import 不破坏）。

**4.2 拆分 `creative_video.py`（1968 行）**
- `core/pipelines/creative/` 包：`pipeline.py`（主类 + 模板方法）+ `steps_script.py`（编剧步骤）+ `steps_frames.py`（参考图/尾帧）+ `steps_video.py`（链式视频生成）+ `steps_audio.py`（音频字幕）。
- 拆分后主类通过 mixin 或组合引用 step 方法（决策后注明）。

**4.3 次要文件视需拆分**
- `subtitle.py`（1103 行）拆 `generator.py`（SRT 生成）+ `renderer.py`（moviepy 叠加）；
- `concatenator.py`（653 行）拆拼接 + 音频叠加。

**验收标准**
- 全部文件 ≤ ~800 行（除 `static/index.html` 前端）；
- `python -c "import server"` 与全部 pipeline import 正常，无循环 import；
- mock 回归全绿；`screenwriter` 外部调用点零修改（re-export 生效）。

---

### Batch 5 — 资源清理 + 配置类型化 + 常量收敛（S6+S7+S8，P2）

**5.1 僵尸任务磁盘清理（S6）**
- `core/artifacts.py` 新增 `sweep_stale_tasks(age_days: int = 7)`：扫描工作区中状态非 RUNNING/QUEUED 且 `task.json` 修改时间超龄的任务目录，按 `get_cascade_plan` 级联删除，可手动触发 API + 可选启动时自动执行。
- 需保护：断点续传任务（PENDING 状态）默认不清理，或提供白名单配置。

**5.2 配置类型化（S7）**
- `core/config.py` 引入 Pydantic Settings 模型（`AppSettings`），`load_config()` 返回类型化对象；对外保持 `get_api_key()` 等现有访问函数签名不变，逐步替换 `dict.get()` 内部使用。

**5.3 魔法数字收敛（S8）**
- `multi_scene.py:63-96` 进度边界提取为 `_PROGRESS = StepProgressLimits(...)` 命名常量表；
- `multi_scene.py:240` 重试间隔 `20*(retry+1)` 提取为 `_RETRY_INTERVAL_BASE_SECONDS`；
- 全局搜索 `\d+ \* \(.*\+ 1\)` / 裸进度浮点，逐一收敛。

**验收标准**
- 清理函数有单测（含 PENDING 保护分支）；配置类型错误在构造期抛错；进度常量引用后行为不变。

---

### Batch 6 — 核心逻辑单测补强（S9，P2）

**6.1 编剧/拆段纯函数单测**
- `screenwriter.py`（拆分后）的 `build_poetry_scene_prompt`、场景拆段、角色提取、字幕样式生成等纯函数补单测（`tests/test_screenwriter.py`）。

**6.2 音频降级链路单测**
- 对 Batch 2 共享方法补 mock `EdgeTTSEngine` 失败的用例（`tests/test_audio_fallback.py`）。

**6.3 路由层集成测试（依赖 Batch 1 完成）**
- `tests/test_routes.py`：用 FastAPI `TestClient` 直接测 router（不经 `server.py` 启动），覆盖 config/workspaces/voices 等无状态路由 + `task_creation` 参数校验。

**验收标准**
- 新增单测 ≥ 40 个；`tests/` 下 mock 回归 + 单测全绿；`pytest --cov` 覆盖率较基线提升（基线在 Batch 6 启动时记录）。

---

## 五、状态跟踪表（单一状态源）

> **约定（强制）**：每完成一个任务，执行者必须：
> 1. 将该任务状态更新为 `✅` 并填写完成日期；
> 2. 运行 §六 验证清单并在此表"验证记录"列简述结果；
> 3. 若涉及目录/文件结构变化，同步更新 `AGENTS.md` §四 目录结构；
> 4. 若任务发生范围调整/废弃，状态标 `⛔` 并注明原因，**不删除历史**。

| 任务 | 批次 | 状态 | 完成日期 | 验证记录 |
|------|------|------|---------|---------|
| 1.1 提取 `app_state.py` | B1 | ✅ | 2026-08-04 | py_compile + import OK；并发状态/生命周期事件集中管理 |
| 1.2 提取 `deps.py` | B1 | ✅ | 2026-08-04 | py_compile + import OK；Pipeline 工厂与执行器，含下划线兼容别名 |
| 1.3 拆分 8 个 router 模块 | B1 | ✅ | 2026-08-04 | 36 端点全量挂载（40 条 method+path 含 root/static/docs）；`import server` 无循环依赖 |
| 1.4 收敛残留工具函数 | B1 | ✅ | 2026-08-04 | `server.py` 2050→145 行；helper 迁入 `web/helpers.py`；兼容 re-export 使 `tests/test_core.py` 53 用例通过 |
| 2.1 BasePipeline 共享音频方法 | B2 | ✅ | 2026-08-05 | `_generate_audio_with_fallback` 落位 BasePipeline（含 cues 不足→legacy 启发式）；py_compile/import OK，逐批 push 触发 GitHub Actions 回归 |
| 2.2 调用方改造（5 处） | B2 | ✅ | 2026-08-05 | 范围扩展：原计划 3 处，实际发现 manuscript/anchor 亦复制同逻辑，共收敛 5 处（multi_scene/creative/poetry/manuscript/anchor）；`grep EdgeTTSEngine core/pipelines/` 仅剩 `__init__.py` 函数级 import；私有降级分支全部删除 |
| 2.3 行为差异对照用例 | B2 | ✅ | 2026-08-05 | 新增 `tests/test_audio_fallback.py` 4 用例（Edge 失败→Silent / cues 不足→legacy / audio-off+subtitle-on / 成功返回 sub_maker）锁定行为矩阵 |
| 3.1 修复 `_execute_step` 契约 | B3 | ✅ | 2026-08-06 | 方案 A：`_execute_step` 增加 `coarse_skip` 参数（显式覆盖，缺省取类属性 `self.coarse_skip`，默认 True）；Creative 以类属性 `coarse_skip=False` 禁用，覆写已删除（方法解析指向基类）；6 个契约用例（tests/test_pipeline_contract.py）锁定行为矩阵 |
| 3.2 状态字段对齐 | B3 | ✅ | 2026-08-06 | `audio_config`/`subtitle_config` 上提 `BaseTaskState`（default_factory），Creative/Manuscript/Anchor/Poetry 子类重复声明移除；`multi_scene.py` hasattr/getattr 探测全部移除（含 `screenwriter` 上提 BasePipeline 初始化为 None）；`grep hasattr core/pipelines/` 清零；新增 3 个兼容用例（旧 JSON 缺字段取默认/含字段保留/6 类继承） |
| 4.1 拆分 `screenwriter.py` | B4 | ✅ | 2026-08-06 | `core/screenwriter/` 包：story（旁白清洗+故事/脚本/旁白）/scenes（分镜/段落场景/诗词场景）/characters（角色/尾帧/数字人）/style（字幕 LLM 样式）4 个 mixin + `__init__.py` 组合（核心聊天基础设施保留本模块，保证 mock 回归 patch 目标 `core.screenwriter.AgnesChatAPI` 有效）；全部原符号 re-export（外部调用点零修改）；29 个符号（3 模块级函数+26 方法）与拆分前逐字节一致（inspect.getsource）；新增 tests/test_screenwriter_package.py 8 契约用例；本地 80 用例通过，GitHub Actions 149 passed、覆盖率 59% |
| 4.2 拆分 `creative_video.py` | B4 | ✅ | 2026-08-06 | `core/pipelines/creative/` 包：pipeline.py 主类（mixin 组合 + 模板钩子 + state 属性，AgnesVideoAPI/AgnesImageAPI import 与实例化所在，mock 回归 patch 目标）+ steps_script（编剧 6 步）/steps_frames（参考图/尾帧/场景任务落盘）/steps_video（三模式视频生成）/steps_audio（旁白/音频/字幕/拼接）4 个职责 mixin；`creative_video.py` 变 23 行兼容 re-export（外部调用点零修改）；conftest.py 两处 patch 目标迁移至 `core.pipelines.creative.pipeline.*`（实例化位置）；31 个类成员（30 方法 + state 属性）+ 6 模块级 helper + 2 常量与拆分前逐字节一致（inspect.getsource，含 property fget）；Batch 3 方案 A 不回退（coarse_skip=False、_execute_step 解析到 MultiScenePipeline）；新增 tests/test_creative_package.py 8 契约用例；修复 steps_video.py 缺失 `import re`（ti2vid 用例 NameError，本地复跑确认后提交）；本地 89 用例通过；GitHub Actions 158 passed、覆盖率 59%（含 mock 回归全绿） |
| 4.3 拆分 subtitle/concatenator | B4 | ✅ | 2026-08-06 | `core/audio/subtitle/` 包：generator.py（SubtitleSrtMixin，15 个 SRT 生成方法 + 6 常量）/renderer.py（SubtitleRenderMixin，2 个 moviepy 叠加方法）；`core/compositor/concatenator/` 包：concat.py（ConcatMixin，5 个纯拼接方法 + 4 常量）/audio_overlay.py（AudioOverlayMixin，2 个音频叠加方法，常量经 `from .concat import` 复用）；两包 `__init__.py` mixin 组合 + **运行时注入**（方法内显式类名自引用 `SubtitleGenerator.xxx`/`VideoConcatenator.xxx` 在模块级延迟解析到组合类，方法体逐字节不变）；旧 module 路径 16 行 re-export（外部调用点零修改，poetry_video/steps_audio/anchor_video 下游 import 验证 identity）；17+7 方法逐字节一致（inspect.getsource，含嵌套函数），注释行 fidelity 通过（67/31）；新增 tests/test_subtitle_concatenator_package.py 12 契约用例；本地 119 用例通过；GitHub Actions 171 passed、覆盖率 59.57%（含 mock 回归全绿） |
| 5.1 僵尸任务磁盘清理 | B5 | ✅ | 2026-08-06 | `core/artifacts.py` 新增 `sweep_stale_tasks(age_days=7, protect_statuses=None)`：扫描工作区中 `task_state.json` 超龄且状态非活跃的任务目录，realpath 校验后整目录 rmtree（等价级联删除全部产物）；默认保护 RUNNING/QUEUED/PENDING（断点续传候选不误删），`protect_statuses` 可显式覆盖；新增 `POST /api/tasks/sweep`（task_routes.py，活跃 pipeline 一律跳过）+ lifespan 可选启动自动执行（`AGNES_SWEEP_AGE_DAYS` 环境变量，失败不阻断）；7 个单测（tests/test_artifacts.py 含 PENDING 保护分支/白名单放开/损坏 JSON errors/非任务目录跳过/age_days=0 边界）；本地全量非 mock 测试通过；GitHub Actions 178 passed、覆盖率 59.78%（含 mock 回归全绿） |
| 5.2 配置 Pydantic 化 | B5 | ✅ | 2026-08-06 | `core/config.py` 引入 Pydantic v2 严格模式模型（`AppSettings`/`WorkspaceEntry`/`WatermarkSettings`，`ConfigDict(strict=True)`：构造期类型错误抛 ValidationError，未知 key 忽略保持向后兼容）；新增 `load_settings()` 统一读取入口，`get_api_key`/`get_api_key_source`/`get_working_dir`/`get_workspaces`/`get_watermark_config`/`get_selected_models`/`get_agnes_domain` 7 个读函数内部由 `dict.get()` 切换为类型化访问；`load_config`/`save_config`/`set_*` 写路径不变（外部调用点零修改）；新增 tests/test_config_settings.py 15 用例（默认值/strict 类型错误/未知 key 忽略/conf_file fixture/损坏 JSON/读函数行为等价/set_* roundtrip）；本地全量非 mock 测试通过；GitHub Actions 199 passed、覆盖率 61.37%（含 mock 回归全绿） |
| 5.3 魔法数字收敛 | B5 | ✅ | 2026-08-06 | `multi_scene.py` 进度边界提取为 `StepProgressLimits` 命名常量表（`_PROGRESS`，0.0→1.0 八段边界）+ `_PROGRESS_FAILED` + 重试基数 `_RETRY_INTERVAL_BASE_SECONDS=20`；全局 grep 逐一收敛裸进度浮点/`\d+*(attempt+1)` 重试基数：manuscript（8 常量 0.05→0.80 阶段映射 + 重试基数 15/20）、anchor（11 常量 0.02→0.80，含 post_stitch 音频完成 0.28 历史回退值）、creative steps_video（independent 0.38+0.42 / cached 0.35+0.45 / keyframes 0.35+0.05、0.40+0.40）、steps_script（12 常量编剧线性推进 0.0→0.25 + scene_config 2 常量）、steps_audio（7 常量 0.12→0.95）、steps_frames（尾帧预生成 0.35）、simple_video（6 常量 0.0→1.0）、poetry（3 常量 0.75/0.87/0.90）、screenwriter 图片描述重试基数 15、agnes_video 上传 429 基数 30、agnes_image 读超时基数 120；全部取值与收敛前逐字节一致（grep 收敛验证清零，仅剩 opacity/时序/温度等语义值）；新增 tests/test_progress_constants.py 7 契约用例锁定常量取值；本地 171 用例通过；GitHub Actions 199 passed、覆盖率 61.37%（含 mock 回归全绿） |
| 6.1 编剧/拆段单测 | B6 | ✅ | 2026-08-06 | 新增 tests/test_screenwriter.py 42 用例：`_parse_poetry_scene_lines`（行格式/编号前缀/场景标签行跳过/围栏剥离/空行）、`_poetry_scene_prompts` + 模块级 `build_poetry_scene_prompt`（count/duration/style hint，与内部构造逐字一致）、`generate_poetry_scenes` mock `_chat` 全链路、`_validate_styles`/`_fallback_styles`（index 去重/越界/字号 clamp/缺失条目位置池填充）、`extract_scene_info_from_idea`（成功/2-30s clamp/三路 RuntimeError）、`develop_story` XML 注入转义、`generate_narration_for_video` 旁白清洗、`_split_text` 拆段（贪心合并/长句不拆/尾段回并/换行切块/resume/序号）、`fix_double_utf8`；本地全量非 mock 测试通过；GitHub Actions 291 passed、覆盖率 63.18%（含 mock 回归全绿，基线 61.37% → +1.81pp） |
| 6.2 音频降级单测 | B6 | ✅ | 2026-08-06 | tests/test_audio_fallback.py 追加 8 用例补齐降级矩阵：空文本无占位跳过不落盘、空文本有占位 Silent 落盘、harvest 关闭仅 Silent、路径 B harvest 失败仍 Silent 返回 None、Edge 成功 sub_maker=None 不降级、非 RuntimeError 异常传播不落盘、duration_sec=0 省略 kwarg、voice/rate 透传 EdgeTTS；本地全量非 mock 测试通过；GitHub Actions 291 passed、覆盖率 63.18%（含 mock 回归全绿，基线 61.37% → +1.81pp） |
| 6.3 路由层集成测试 | B6 | ✅ | 2026-08-06 | 新增 tests/test_routes.py 42 用例：TestClient 直接挂载 Batch 1 拆分的 4 个 router（config/workspaces/voices/task_creation，不经 server.py）；config（Key 脱敏/env 来源 DELETE 400/写入 patch/watermark/models/domain 校验）、workspaces（列表/创建空路径与不安全路径 422/成功建 uploads 目录/删除 404/激活 422）、voices（目录结构/兼容查询 zh-zh 与 zh-ru 跨脚本/preview 400+422）、task_creation 参数校验矩阵（无 Key 400/非法 mode/duration/长度/JSON/场景数 422 + 五端点合法创建，pipeline 工厂/后台任务/TaskManager 全打桩不触网不写盘）、legacy POST /api/tasks、poetry-scene-prompt 工具端点；**发现并修复真实 bug**：legacy 端点自 v3.x 起传已移除的 `user_requirement` 且直接调用时 `Form()` 默认值是对象导致 422/ValidationError（fix(Batch6/S12) cdd795b，显式传全部 v3.x 参数）；本地全量非 mock 263 用例通过；GitHub Actions 291 passed、覆盖率 63.18%（含 mock 回归全绿，基线 61.37% → +1.81pp；另修复 CI 依赖：starlette>=1.4 TestClient 需 httpx2，requirements-dev.txt 补充 f3c42f8） |

状态值：`🔲 未开始` / `🔄 进行中` / `✅ 已完成` / `⛔ 已取消（注明原因）`

---

## 六、每批完成必须通过的验证清单

```bash
# 1. 静态编译（全部 .py）
.venv/bin/python -m py_compile $(find . -name "*.py" -not -path "./.venv/*" -not -path "./.git/*" -not -path "./node_modules/*")

# 2. 单元测试 + mock 回归
.venv/bin/python -m pytest tests/ -q

# 3. mock 回归一键脚本（含并发场景）
./scripts/run_mock_regression.sh

# 4. 关键端点冒烟（若服务可起）
curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/            # 期望 200
curl -s http://localhost:8765/api/voices  | python3 -m json.tool > /dev/null   # 期望 ok
```

> 若批次涉及模型层（Batch 3）或路由层（Batch 1/6），另需验证**旧任务 JSON 兼容性**：用 v4.0 产出的 `task.json` 样本执行 `parse_task_state` 反序列化。

---

## 七、批次执行顺序与依赖关系

```
Batch 1 (S1) ──► Batch 3 (S3+S4) ──► Batch 4 (S5)
      │                                     ▲
      ▼                                     │
Batch 2 (S2) ──► Batch 6 (S9, 依赖 B1/B2) ──┘
Batch 5 (S6+S7+S8) 可随时插入（改动面独立）
```

- Batch 1 先行：为 Batch 6.3（路由集成测试）铺路，且不触碰 pipeline 逻辑。
- Batch 3 依赖 Batch 2 之后做：字段对齐会改写 `multi_scene.py` 中 Batch 2 刚收敛的共享方法调用点，避免同一文件两批竞争。
- Batch 4 尽量在 Batch 3 之后：拆分时直接按"已对齐字段"写新文件，减少返工。
- Batch 5 无强依赖，可并行插入任意批次间隙。

---

## 八、风险与回退策略

| 风险 | 缓解 |
|------|------|
| Batch 1 路由拆分后行为漂移 | 每拆分一个 router 立即跑 §六 冒烟；URL 前缀逐一对照原 `server.py` |
| Batch 2 三处降级行为细节不一致 | 先写行为对照用例（2.3），后统一实现 |
| Batch 3 字段对齐导致旧任务 resume 失败 | 保留 `parse_task_state` 兼容层 + 旧 JSON 样本测试 |
| Batch 4 import 循环 | 先搭包骨架 + re-export，再移动实现；用 `python -c "import server"` 全量验证 |
| 任一批次回归失败 | 单批回退：本批改动独立 commit，`git revert` 该批即可，不影响其他批 |
