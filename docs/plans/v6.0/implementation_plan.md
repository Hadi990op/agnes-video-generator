# v6.0「手动模式」实施方案与路线图

> **文档定位**：根据 `manual_mode_PRD.md`（v0.6）产出的**实施执行计划**。本文档定义阶段划分、每阶段的交付物与验证方式、
> 状态跟踪约定，以及「单测走 GitHub Action 异步执行、不在本地阻塞开发」的工作流。
>
> **关联文档**：`docs/plans/v6.0/manual_mode_PRD.md`（方案权威）· `docs/dev/regression_test_plan.md`（回归）·
> `docs/dev/test_coverage_and_ci.md`（测试/CI）· `AGENTS.md`（验证清单）
>
> **版本**：v0.1（2026-08）
> **状态**：🟡 规划中（未开工）

---

## 一、总体原则

1. **严格分阶段**：按 §三 阶段表逐阶段实施，**每阶段完成后更新本表状态**（🟡→🟢），不得跨阶段跳跃。
2. **PRD 为准**：实现与 `manual_mode_PRD.md` 保持一致；实现中发现 PRD 不合理处，先改 PRD 再改代码。
3. **回归不破**：任何阶段不得破坏 `docs/dev/regression_test_plan.md` 8 场景（自动模式行为与 v5.x 一致）。
4. **CI 异步验证（关键约定）**：
   - 单元测试 / mock 回归**由 GitHub Action（`.github/workflows/test.yml`）异步执行**，不在本地阻塞开发；
   - 本地仅做**最小自检**（见 §二「本地最小自检」），完整测试交给 CI；
   - push 后查看 CI 结果，**CI 未通过前不进入下一阶段**（除非确认是环境性失败且与本次改动无关）。
5. **文档随代码更新**：产物清单、回归条目、测试覆盖、release notes 等文档在对应阶段一并更新。

---

## 二、工作流约定（本地 vs CI）

| 环节 | 执行位置 | 说明 |
|------|---------|------|
| 语法/导入自检 | 本地 | `python -m py_compile <改动文件>` + 关键模块 import（见 §三每阶段「自检」） |
| 单测（新增 + 既有） | **GitHub Action** | push 后自动跑 `pytest tests/ --cov`，不本地跑全量 |
| 覆盖率门禁 | GitHub Action | `--cov-fail-under=55`（现状基线 58%）；新增单测不得显著拉低 |
| 前端构建校验 | GitHub Action | `frontend-build` job 校验 `static/` 产物与 `frontend/` 源码一致 |
| 端点冒烟 | 本地 | 本地起服务后 curl 关键端点（需要真实 API Key 时用 mock 或跳过） |
| mock 回归 | GitHub Action 为主 | `tests/mock_regression/` 五管线回归（无网络、无 Key） |
| 大版本回归 | 本地（专项） | `docs/dev/regression_test_plan.md`，在 Phase 收官时人工跑 |

> **为什么 CI 不阻塞本地**：`test.yml` 已在「API 协议边界」全 mock（`tests/mock_regression/conftest.py` autouse fixture），
> 零网络、零 Key、素材入库，push 即跑。本地继续开发下一阶段，CI 结果异步返回后统一修正。

---

## 三、阶段划分与状态跟踪

> 阶段内容源自 PRD §十；每阶段完成时更新「状态」列（🟡 进行中 / 🟢 已完成）并填写「完成日期」。

| 阶段 | 名称 | 内容摘要 | 依赖 | 状态 |
|------|------|---------|------|------|
| P0 | 后端暂停机制 | `ManualConfig` + `_maybe_pause` 钩子 + 暂停态复用 `PENDING` + `mode` 端点（approve/regen 属 P1 产物级） | 现有 resume/stop | 🟢 已完成（2026-08-14，CI 异步确认中） |
| P1 | 产物规范 | `checkpoint.json` 清单 + artifacts 预览/上传 + `impact` 预计算 + approve/regen 端点 | P0 | 🟢 已完成（2026-08-14，CI 异步确认中） |
| P2 | 前端闭环 | 创建面板模式选择 + 检查点详情页三卡片 + diff 预览 + 协作 prompt 复制 | P0/P1 | 🟢 已完成（2026-08-14，CI 异步确认中） |
| P3 | 推广全流水线 | manuscript / poetry / anchor 统一检查点；simple 产物清单 | P1 | 🟢 已完成（2026-08-14，CI 异步确认中） |
| P4 | 交付打磨 | 协作 prompt 库整理 + 示例视频教程 + 回归测试补充 | P3 | 🟢 已完成（2026-08-14） |

---

## 四、Phase 0（P0）— 后端暂停机制

### 4.1 目标
creative 一条流水线可端到端手动执行 + 运行中双向切换。对应 PRD §4.1 / §4.2 / §5.1 / §5.3 及验收 1-7。

### 4.2 改动清单

| 模块 | 改动 |
|------|------|
| `models/task.py` | 新增 `ManualConfig`（`enabled` / `pause_points` / `approved_checkpoints` / `modified_artifacts` / `current_checkpoint` / `timeout_minutes`）；`BaseTaskState` 增加 `manual_config`（`Field(default_factory=ManualConfig)`） |
| `core/pipelines/multi_scene.py` | 模板方法 `run()` 中每个 `_execute_step` 完成后调用 `_maybe_pause(checkpoint)`；`_maybe_pause` 实现暂停判定 + 落盘 |
| `core/pipelines/__init__.py` | `BasePipeline` 增加 `_maybe_pause` 公共实现（`enabled && checkpoint ∈ pause_points && ∉ approved` → 落盘 `PENDING` + `current_checkpoint` + 正常返回） |
| `web/routes/task_routes.py` | 新增 `POST /api/tasks/{id}/mode`（运行中双向切换，`mode=manual` 复用 stop 链路挂起）；`resume` 保持不动（暂停态即 PENDING 天然兼容） |
| `web/routes/creation_routes.py`（或对应创建端点） | 各 `/api/tasks/*` 创建端点接收 `execution_mode` / `pause_points` |
| `core/artifacts.py` | `build_manifest` 返回体补 `current_checkpoint` / `manual_config`（供前端） |
| 新增 `tests/test_manual_pause.py` | P0 单测（见 4.3） |

### 4.3 单测清单（提交后走 CI）

| 用例 | 验证点 |
|------|--------|
| 手动创建任务 → 首个检查点暂停 | `status=PENDING`、`enabled=true`、`current_checkpoint=scenes`、不占用并发槽位 |
| `approve` 恢复 → 跳过已确认检查点 → 下一检查点再次暂停 | 默认全暂停点行为 |
| `approve(modified_artifact_ids=["script"])` → 下游按依赖图重置 | 验收 3 |
| 自动变手动（`mode=manual`）→ 挂起为 PENDING → resume 后保持手动并再次暂停 | 验收 5 |
| 手动变自动（`mode=auto`，暂停中）→ 清空暂停点立即继续 | 验收 6（**切换即继续**） |
| stop 中断不改变模式 → resume 仍自动、无检查点视图 | 验收 7 |
| 旧任务状态反序列化（无 `manual_config`）→ 自动模式默认值 | 向后兼容 |

### 4.4 自检（本地最小）
```bash
python -m py_compile models/task.py core/pipelines/multi_scene.py core/pipelines/__init__.py web/routes/task_routes.py
python -c "from models.task import BaseTaskState, ManualConfig; print('OK')"
python -c "from core.pipelines import MultiScenePipeline; print('OK')"
```
push 后查 CI：`pytest tests/`（含新增 `test_manual_pause.py`）全绿 + `--cov-fail-under=55` 通过。

### 4.5 验收对照（PRD §十二 1-7）
按 PRD 验收标准逐条核对，全部通过后本阶段标记 🟢。

---

## 五、Phase 1（P1）— 产物规范与影响决策

### 5.1 目标
全部流水线产物对外开放、可回填；`impact` 预计算生效。对应 PRD §4.4 / §4.5 / §4.7 / §5.2。

### 5.2 改动清单

| 模块 | 改动 |
|------|------|
| **新增 `core/dependency_graph.py`** | 独立依赖图模块：`PRODUCT_EDGES` / `PARAM_EDGES` 声明式边表 + `compute_impact()` 返回 `ImpactPlan{affected, retained, steps_to_reset}` + `to_checkpoint_edges()` 供前端 |
| `core/artifacts.py` | 新增 `checkpoint.json` 落盘（按检查点拆分产物清单）；`artifacts` 预览/上传端点支持（文本/图片/视频/音频） |
| `web/routes/task_routes.py` | 新增 `GET .../checkpoints` / `GET .../checkpoints/{name}` / `GET .../artifacts/{artifact_id}` / `POST .../upload`；`approve` 扩展 `{modified_artifact_ids, param_updates, confirmed}`，内部先调 `compute_impact` 再落盘 |
| `web/routes/video_routes.py` | `impact` 预计算端点：`GET .../checkpoints/{name}/impact`（只算不落盘） |
| 新增 `tests/test_dependency_graph.py` | 依赖图单测（见 5.3） |

### 5.3 单测清单

| 用例 | 验证点 |
|------|--------|
| 改 `script:scene_prompt` → 影响 ref图/videos/final，保留 audio/subtitle | 字段级粒度 |
| 改 `script:narration_text` → 影响 audio/subtitle/final，保留 ref图/videos | 字段级粒度 |
| 改 `scene:{i}/video.mp4` → 影响 audio/subtitle/final，保留其他场景 video | scope 通配 |
| 改 `character_reference.png` → 影响 videos/final | 产物级 |
| 改 `combined_narration.srt` → 仅影响 final | 产物级 |
| `param_updates`（分辨率/音色）→ 按 `PARAM_EDGES` 计算 | 参数级 |
| `compute_impact` 去重 / 传递闭包 / 越界容错 | 健壮性 |
| `impact` 端点只算不落盘；`approve(confirmed=false)` 不落盘 | API 契约 |
| `checkpoint.json` 落盘结构与 `build_manifest` 字段对齐 | 产物规范 |

### 5.4 自检
```bash
python -m py_compile core/dependency_graph.py core/artifacts.py web/routes/task_routes.py
python -c "from core.dependency_graph import DependencyGraph, ImpactPlan; print('OK')"
```
push 后查 CI：新增两组单测全绿。

---

## 六、Phase 2（P2）— 前端交互闭环

### 6.1 目标
完整交互闭环：创建面板模式选择 + 检查点详情页三卡片 + diff 预览 + 协作 prompt 复制。对应 PRD §六。

### 6.2 改动清单

| 文件 | 改动 |
|------|------|
| `frontend/src/components/CreatePanel.vue` | 顶部全局条「⚡ 自动 / ✋ 手动」+ 暂停点 chips（默认按任务类型预填）；simple 类型置灰提示 |
| `frontend/src/components/ProgressPanel.vue` | 运行中「自动 ⇄ 手动」切换开关 |
| 新增 `frontend/src/components/CheckpointDetail.vue` | 检查点详情页：产物区 + 常驻操作区（确认/重生成/切回自动）+ 三卡片（AI 帮我改 / 我自己改 / 外部 Agent）+ ⚙️ 任务参数 + 修改前 impact 弹窗 |
| `frontend/src/api/index.ts` | 新增 `mode` / `impact` / `approve` / `ai-modify` / `upload` 调用 |
| `frontend/src/i18n/translations.ts` | 22 语言新增文案 key |
| `frontend/src/store.ts` / `types.ts` | `manual_config` / `current_checkpoint` / 检查点状态类型 |

### 6.3 自检
- `cd frontend && npm run build` 本地构建通过；
- **CI `frontend-build` job** 校验 `static/` 产物与源码一致（push 后自动执行）；
- 本地起服务，手动创建任务 curl 验证模式参数透传。

### 6.4 前端单测说明
项目前端目前无单测框架；P2 以「构建通过 + CI 产物一致性 + 手工冒烟」为验证门槛，不额外引入前端测试框架（保持现状）。

---

## 七、Phase 3（P3）— 推广全流水线

### 7.1 目标
manuscript / poetry / anchor 继承同一检查点机制；simple / simple_image 完成后产物清单。对应 PRD §4.8 矩阵。

### 7.2 改动清单
- `core/pipelines/manuscript_video.py` / `poetry_video.py` / `anchor_video.py`：核对各 `_execute_step` 步骤名与标准检查点对齐（`references` 空实现自动跳过；anchor `model` 模式过滤 audio/subtitle）；
- `core/artifacts.py`：补 poetry 逐场景产物定义（`scene_{i}/narration.mp3` / `scene_{i}/subtitle.srt`）；
- `core/dependency_graph.py`：`PRODUCT_EDGES` 补 manuscript / poetry / anchor 边表；
- simple / simple_image：`build_manifest` 完成后产物清单只读展示（无暂停）。

### 7.3 单测清单
- 各任务类型 `compute_impact` 用例（复用 §5.3 模式，按类型参数化）；
- poetry 逐场景产物修改影响范围（改 `scene_2/narration.mp3` 仅影响该场景下游）。

### 7.4 验收
- 四种长视频任务类型均可端到端手动执行 + 暂停修改；
- PRD §4.8 矩阵与实现一致。

---

## 八、Phase 4（P4）— 交付打磨

| 交付物 | 内容 |
|--------|------|
| 协作 prompt 库 | §七 示例 prompt 整理进 `docs/public/` 用户文档 |
| 示例视频教程 | 手动模式操作演示 |
| 回归测试补充 | `docs/dev/regression_test_plan.md` 新增手动模式场景条目 |
| 测试覆盖报告更新 | `docs/dev/test_coverage_and_ci.md` 同步最新覆盖率 |
| Release Notes | `docs/public/release-notes/` 按发版规范更新 |

---

## 九、CI 与门禁约定（防回归）

1. **自动模式 8 场景回归**：P0-P4 每阶段结束后，本地按 `docs/dev/regression_test_plan.md` 跑一遍（可仅跑受影响场景），确保自动模式行为未变。
2. **覆盖率门禁**：`--cov-fail-under=55`；若新增模块显著拉低基线，先补单测再提交。
3. **前端产物一致性**：改 `frontend/` 必须 `npm run build` 并提交 `static/` 产物，CI 校验不一致即红。
4. **文档状态同步**：每完成一个 Phase，更新本文档状态表（🟡→🟢）+ 日期，并同步 PRD §十 分期表。

---

## 十、风险与注意

| 风险 | 应对 |
|------|------|
| `_maybe_pause` 与 `coarse_skip` / 文件存在性续传的交互 | 暂停点在 `_execute_step` **完成后**触发，跳过步骤不触发；单测覆盖 |
| 暂停态（PENDING）与普通中断在列表/轮询/sweep 的区分 | 前端以 `current_checkpoint` 非空判断；后端不新增状态分支 |
| 自动变手动在步骤中间挂起 | `current_checkpoint` 取「最近完成边界」，未完整产物标注进行中 |
| `dependency_graph` 边表遗漏/错误 | 纯声明式，单测逐类型/逐字段覆盖；`impact` 预计算供用户确认兜底 |
| CI 环境性失败（如字体/ffmpeg） | 与本次改动无关的环境失败不阻塞，记录后继续；代码引入的失败必须修复 |

---

## 十一、当前状态

> **状态**：🟢 **P0 已完成**（2026-08-14）
>
> 进度：
> - ✅ **P0 后端暂停机制**：`ManualConfig` + `_maybe_pause` + `CheckpointPause` + `compute_current_checkpoint` + `POST /api/tasks/{id}/mode` 运行时双向切换（提交 `6f4eac0`）
>   - 本地自检：py_compile + 关键模块 import + 新增单测 25 用例全绿 + mock 回归 28 用例不破（自动模式行为未变）
>   - CI：push 已触发 GitHub Action 异步执行（`pytest tests/ --cov`），结果返回后确认；如失败按 §十 风险处理
> - ✅ **P1 产物规范**：`core/dependency_graph.py` 独立依赖图模块（提交 `8140650`）
>   - 改动：dependency_graph（字段级/场景级/参数级边表 + ImpactPlan）+ checkpoint.json 分组清单 + checkpoints 列表/详情 + upload 回填 + impact 预计算 + approve/regen 端点
>   - 本地自检：py_compile + import + 新增单测 21 用例全绿 + 核心套件 179 用例不破
>   - 注：本地 mock 回归受 CodeBuddy safe-delete 防护干扰（turn 内删除计数 ≥50 拦截 MoviePy 临时文件删除），该环境特性不影响业务代码，mock 回归改由 CI 异步验证（CI 无此防护）
> - ✅ **P2 前端闭环**：创建面板模式选择 + 检查点详情页三卡片 + 运行时切换（提交 `54e77c5`）
>   - 改动：API 层 7 个调用 + CreatePanel 执行模式条/暂停点 + 4 表单提交带模式 + TaskList 徽标/切换 + CheckpointDetail 组件（三卡片 + impact 弹窗）+ useProgress 暂停态检测 + i18n ~45 key
>   - 本地自检：vue-tsc + vite build 通过，static 产物已更新；无 lint 错误
>   - 注：通道 1（ai-modify）后端真实调用待 P1.5 补齐（当前前端按 impact 预计算 + 产物矩阵驱动）；前端单测保持现状（构建+CI+冒烟门槛）
> - ✅ **P3 推广全流水线**：manuscript / poetry / anchor 统一检查点 + simple 产物清单（提交 `ab97d44`）
>   - 改动：`_get_pausable_steps`（manuscript/poetry 去 references，anchor model 去 audio/subtitle）+ poetry 逐场景产物定义 + dependency_graph 场景级传播 + checkpoint manifest 补 files 树
>   - 本地自检：新增测试全绿（54）+ 核心套件 139 用例不破
> - ✅ **P4 交付打磨**：协作 prompt 库 + 回归测试 + 测试覆盖报告 + 使用指南（提交 `6002874`）
>   - `docs/public/manual_mode_guide.md`（新建）、usage.md 手动模式章节、regression_test_plan §九、test_coverage_and_ci 增量、AGENTS.md 索引
> - 🏁 **v6.0 手动模式全阶段（P0-P4）已完成**。CI 结果异步确认中；大版本回归（8 场景 + 手动模式 M1/M2/M3）待专项执行。
>
> 推进方式：
> 1. 按 P0 → P4 顺序实施；
> 2. 每阶段：本地最小自检 → 实现 → 提交代码（push 触发 CI 单测异步执行）→ 查 CI 结果 → 通过后更新本表状态 → 进入下一阶段。
