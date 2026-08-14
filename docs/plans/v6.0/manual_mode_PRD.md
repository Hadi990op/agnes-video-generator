# v6.0「手动模式」初步方案（PRD 草案）

> **状态**：🟡 初步方案（PRD 草案），待评审确认后细化
> **版本**：v0.7（2026-08）
> **关联文档**：`AGENTS.md` · `docs/dev/pipeline_products.md`（产物逻辑权威参考）· `docs/dev/architecture.md` · `docs/dev/artifact_standard.md`（产物规范权威参考，v5.x 先行落地）· `docs/plans/v4.0/pipeline_refactor.md`（模板方法来源）
> **定位**：本文档为 6.0 大型更新的**需求与方案草案**。按项目流程，评审通过后进入 `system_design.md` 增量设计再实施。
>
> **⚠️ 前置说明**：本文档 §4.4「产物规范（外部可处理性）」中与手动模式机制**无关的准备工作**（旁白 TXT 导出、产物清单 manifest.json、任务目录 MANIFEST.md、产物 schema 说明、artifacts 路径暴露）已**提前到 v5.x 实施**，详见 §四之末「产物规范前置工作（v5.x 已完成）」。

---

## 一、背景与目标

### 1.1 背景

当前所有任务类型（simple / creative / manuscript / anchor / poetry / simple_image）均为**一次性自动执行**：
输入内容后，流水线在后台一次性跑完（分镜 → 参考图 → 视频 → 配音 → 字幕 → 合成），中间产物直接落盘，
用户只能在完成后看到最终视频。过程中无法干预，也无法利用外部工具/AI Agent 优化中间产物。

实际上，**中间产物质量直接决定成片质量**，而很多环节恰恰是外部 Agent 或人工工具的强项：

- 分镜 prompt 的打磨（外部 LLM / 本地 Agent 可做得更细）
- 旁白文案的润色（外部 LLM 更擅长）
- 字幕时间轴/断句的修正（人工或脚本更可靠）
- 参考图的构图处理（本地图像工具 / Agent 调 PIL）
- 视频片段的剪辑处理（ffmpeg 命令）

### 1.2 目标

在 6.0 引入**可选的「手动模式」**，核心诉求：

1. **逐步暂停**：流水线在关键步骤完成后暂停，向用户展示中间产物。
2. **用户可干预**：用户可确认继续、修改产物后继续、或重新生成该步。
3. **对外开放**：所有中间产物的**格式、存储位置、修改方式**都规范到"外部工具可直接处理"的程度；
   提供可复制的示例 prompt，用户可将其交给本地免费 Agent（如 opencode、workbuddy、CodeBuddy CLI 等）处理后再回填。
4. **不破坏现状**：自动模式保持默认与完全兼容；手动模式为显式可选。

### 1.3 非目标（第一期）

- 不做 WebSocket 实时推送（维持轮询模型）
- 不做多用户/多人协作
- 不做在线视频编辑器（产物在本地目录处理，网页仅做预览与确认）

---

## 二、术语与定义

| 术语 | 定义 |
|------|------|
| **自动模式** | 当前形式：输入内容后，流水线一次性执行完，中间不暂停。 |
| **手动模式** | 可选执行模式：在指定**检查点（checkpoint）**完成后暂停，展示产物，等待用户主动操作（确认 / 修改 / 重新生成）后再进入下一步。 |
| **检查点（checkpoint）** | 流水线中一个可暂停的产物边界点，例如"分镜完成"、"视频片段完成"。每个检查点对应一组**已落盘的产物**。 |
| **产物（artifact）** | 检查点产出的中间文件（JSON / TXT / SRT / PNG / MP4 等），遵循统一规范，可被外部工具处理。 |
| **产物清单（manifest）** | 每个检查点附带的 `checkpoint.json`，声明产物路径、格式、字段含义、可修改性、协作 prompt。 |
| **外部 Agent** | 用户自行引入的、可读写本地文件与执行命令的 AI Agent（如 opencode、workbuddy、CodeBuddy CLI），或手动工具（ffmpeg、Python 脚本等）。 |
| **脏标记（dirty flag）** | 产物被用户修改后，强制后续步骤重新执行的标记，避免"文件已存在而跳过"导致的旧产物污染下游。 |
| **页内 AI 修改** | 三种产物处理通道之一：用户提出修改要求，系统按产物类型拼接 prompt 调用内置模型（`agnes-2.0-flash` / i2i / ffmpeg 命令生成）修改产物。 |
| **自行处理** | 三种产物处理通道之一：用户自行编辑本地文件或上传覆盖，改完回来点"已修改，继续"。 |
| **外部 Agent 处理** | 三种产物处理通道之一：用户按指引在任务目录打开自己的本地 Agent，用提示词模板处理后回填，再回来确认。 |

---

## 三、用户场景（User Stories）

**U1. 分镜打磨**：用户想让 LLM 生成的分镜更符合自己审美 → 在"分镜"检查点暂停，把 `script.json` 交给外部 Agent 优化后回填，再继续生成视频。

**U2. 旁白润色**：用户不满意 LLM 旁白 → 在"配音"检查点前修改旁白文本，重新生成配音与字幕。

**U3. 视频片段精修**：用户觉得某场景视频不理想 → 在"视频片段"检查点暂停，用 ffmpeg / 外部 Agent 处理 `scene_2/video.mp4`，或删除该片段让系统重新生成。

**U4. 字幕修正**：用户发现字幕断句/时间轴问题 → 在"字幕"检查点修改 `full_subtitle.srt` 后继续合成。

**U5. 中间导出**：用户想把手头任务的所有中间产物交给其他工具做二次创作 → 一键复制产物清单与协作 prompt。

**U6. 混合流程**：用户希望部分步骤自动、部分步骤人工 → 通过 `pause_points` 按需指定暂停点。

---

## 四、总体设计

### 4.1 核心思路：手动模式 = 受控化的断点续传

当前系统已具备以下基础设施（见 `AGENTS.md` 与 `core/pipelines/multi_scene.py`）：

- `_execute_step` 统一步骤执行器：`coarse_skip` 按步骤状态跳过，**已完成步骤可直接跳过**（`multi_scene.py:159-183`）
- `resume` 端点：从任意状态恢复执行（`web/routes/task_routes.py:76-110`）
- 步骤内部基于文件存在性做细粒度续传（如 `scene_{i}/video.mp4`、`combined_narration.mp3`）
- `_recover_sub_maker`：续传时重采 TTS cues 恢复字幕时间线（`core/pipelines/__init__.py:359-385`）

**手动模式复用这套机制**：

1. 流水线模板方法在每个 `_execute_step` 完成后调用 `_maybe_pause(checkpoint_name)`。
2. 若当前任务为手动模式且该检查点在 `pause_points` 中且**尚未被确认** → 落盘暂停态（`status=PENDING` + `manual_config.enabled=true` + `current_checkpoint` + 检查点清单 `checkpoint.json`），流水线**正常返回**（非失败）。
3. 用户在 Web 端操作（确认/修改/重新生成）后调用 `approve` → 后端将检查点标记为已确认（或按 §4.5 重置受影响的下游步骤）→ 走**现有 `resume` 逻辑**恢复执行。
4. 恢复执行时：已完成的检查点被 `coarse_skip` 跳过；未完成/被重置的步骤重新执行。

> **收益**：不引入新的执行引擎，暂停/恢复天然支持"进程重启后续传"（状态全落盘）。

**运行时模式切换（自动 ⇄ 手动）**：

自动模式与手动模式**共享同一套执行流程**，仅 `pause_points` 是否非空决定 `_maybe_pause` 是否命中，因此运行中可**随时互相切换**：

| 切换 | 实现 | 落盘 |
|------|------|------|
| 创建时选手动 | `pause_points` 非空，首个命中检查点即暂停 | `manual_config.enabled=true` + `pause_points` |
| **手动 → 自动**（暂停中，**切换即继续**） | 清空 `pause_points` + 立即走现有 `resume` 继续跑完 | `manual_config.pause_points=[]` |
| **自动 → 手动**（运行中） | **复用现有 stop 中断链路**：`pipeline.stop()` 设置 `_stop_event` → 流水线在下一个安全点抛 `PipelineShutdown` 正常落盘（与中断完全同路径） | `manual_config.enabled=true` + `current_checkpoint=<最近完成边界>` + `status=PENDING` |

- **自动变手动 ≈ 中断**：两者都是"暂停当前任务，用户可对产物操作"，大部分逻辑一致（`_stop_event` 安全点、`PipelineShutdown` 捕获、从 `active_pipelines` 移除、恢复后 `coarse_skip` + 文件存在性细粒度续传全部复用）。**区别仅在恢复后的模式**：中断不改 `manual_config`（恢复仍为自动）；自动变手动置 `enabled=true`，**恢复后执行到下一个命中检查点会再次暂停**（不主动切回则一直是手动）。
- **`current_checkpoint` 的确定**：中断可能发生在步骤中间（如生成到 scene_3/5），遍历检查点依赖图取**最后一个达到完成条件的检查点**作为展示边界，未完整产物标注"进行中"。本质是把 resume 已具备的断点能力"定格展示"给用户。

### 4.2 状态机扩展：复用 PENDING，用字段区分暂停语义

**不新增任务级状态**（原草案的 `AWAITING_USER` 移除）。暂停态直接复用现有 `PENDING`，由 `manual_config` 字段表达恢复语义：

| 场景 | 任务状态 | `manual_config` 特征 | 恢复行为 |
|------|---------|---------------------|---------|
| 中断（现状） | `PENDING` | `enabled=false`（不变） | resume → 仍为自动模式 |
| 手动模式暂停 | `PENDING` | `enabled=true` + `current_checkpoint` 非空 | resume → 执行到下一个命中检查点**再次暂停** |
| 自动变手动 | `PENDING` | `enabled=true` + `current_checkpoint` 非空 | 同上 |

前端判断：`PENDING` + `current_checkpoint` 非空 → 展示"⏸ 等待你操作"检查点视图；`PENDING` 无 checkpoint → 普通中断视图。`sweep` / 清理 / 列表 / 轮询均无需新增状态分支。

流转：

```
创建(mode=manual)
  → QUEUED → RUNNING
  → [每个检查点] _maybe_pause 命中 → 落盘 PENDING(manual, current_checkpoint=cp)
       ├─approve──→ resume → RUNNING（继续下一步）
       ├─modify───→ resume（按 §4.5 重置下游）→ RUNNING
       └─regen────→ resume（重置本检查点）→ RUNNING
  → … → COMPLETED
运行中任何时刻
  ├─ stop（中断）────────────→ PENDING（enabled 不变，恢复仍自动）
  ├─ mode=manual（自动变手动）→ PENDING（enabled=true + current_checkpoint）
  └─ mode=auto（手动变自动）──→ 清空 pause_points + resume 继续跑完
任何时刻 ──→ FAILED（异常）
```

> 说明：`checkpoint.json` 内的 `"status": "awaiting_user"` 保留为**检查点产物级**描述字段，表示"该检查点正等待用户确认"，与任务级状态枚举解耦，不冲突。

### 4.3 检查点设计（Checkpoint）

以 `MultiScenePipeline` 模板方法（`build_scenes → references → videos → audio → subtitle → composite`）为基准，
对用户有意义的产物边界定义 6 个标准检查点：

| # | checkpoint | 触发时机 | 核心产物（creative 示例） | 产物格式 |
|---|-----------|---------|---------|---------|
| 1 | `scenes` | 分镜/剧本/旁白构建完成 | `story.txt`、`script.json`、`prompts.json`、`character_reference.png`、`end_frame_prompts.json` | TXT / JSON / PNG |
| 2 | `references` | 参考图/尾帧图生成完成 | `character_reference.png`、`pregenerated_end_frames/`、`scene_{i}/ref*.png` | PNG |
| 3 | `videos` | 全部视频片段生成完成 | `scene_{i}/video.mp4`（+ `task.json`、`curl.sh`） | MP4 / JSON |
| 4 | `audio` | 配音生成完成 | `combined_narration.mp3`、`combined_narration.txt`（旁白纯文本导出） | MP3 / TXT |
| 5 | `subtitle` | 字幕生成完成 | `combined_narration.srt`、`subtitle_styles.json` | SRT / JSON |
| 6 | `final` | 合成完成 | `final_video.mp4` | MP4 |

> 说明：
> - creative 内部细粒度步骤（`step_story` / `step_character_ref` / `step_script` / `step_end_frame_prompts`）第一期**合并为 `scenes` 一个检查点**，避免检查点过多。
> - **暂停点按任务类型动态推导**：各类型在每个检查点的产物文件不同，`references` 在 manuscript / poetry 为空实现（无参考图，跳过），anchor 的 `audio`/`subtitle` 在 `model` 音频模式下无意义（自动过滤）。**具体产物映射见 §4.8 矩阵**。
> - simple / simple_image 仅 1~2 步，第一期**不做暂停**，但支持"完成后展示产物清单"（只读展示 final 产物，无 approve）。

**暂停点配置（`pause_points`）**：默认手动模式暂停全部 6 点；用户可指定子集（如只暂停 `scenes` 与 `subtitle`），未指定的检查点自动通过。任务创建时按任务类型预填默认暂停点（见 §4.8），用户可增删。

### 4.4 产物规范（外部可处理性）

原则：**所有中间产物对用户透明、可读、可改、可回填**。

1. **固定目录结构 + 固定文件名**：沿用现有 `workspaces/<ws>/<YYYYmmdd_HHMMSS>_<task_id>/` 结构，文件名固定（`script.json`、`combined_narration.mp3` 等），不随机化。
2. **开放文本格式**：
   - JSON：UTF-8、`indent=2`、`ensure_ascii=False`（现状已满足，保持）
   - SRT：标准 SubRip、UTF-8（现状已满足）
   - 旁白文本：额外导出 `combined_narration.txt` 纯文本，便于复制给外部 LLM/Agent（现仅存在于 JSON 内，不便直接投喂）
3. **产物清单 `checkpoint.json`**（每个检查点落盘于 `working_dir/checkpoints/<name>.json`），示例：

```json
{
  "checkpoint": "scenes",
  "status": "awaiting_user",
  "task_id": "abc123",
  "working_dir": "/workspaces/ws1/20260813_000000_abc123",
  "artifacts": [
    {
      "id": "script",
      "name": "分镜脚本",
      "path": "/workspaces/ws1/20260813_000000_abc123/script.json",
      "format": "json",
      "editable": true,
      "schema_hint": "scenes[].scene_prompt=画面描述; scenes[].narration_text=旁白; scenes[].duration=时长(秒)",
      "preview_url": "/api/tasks/abc123/artifacts/script"
    },
    {
      "id": "narration_txt",
      "name": "旁白纯文本",
      "path": "/workspaces/ws1/20260813_000000_abc123/combined_narration.txt",
      "format": "txt",
      "editable": true,
      "schema_hint": "可直接复制给外部 LLM 润色，回填后触发重新配音",
      "preview_url": "/api/tasks/abc123/artifacts/narration"
    }
  ],
  "cooperation_prompts": [
    {
      "id": "polish_script",
      "title": "外部 Agent 优化分镜",
      "prompt": "请读取 <script.json 路径>，优化每个场景的画面描述……（详见 §七）"
    }
  ]
}
```

4. **任务目录说明文件 `MANIFEST.md`**：任务创建时自动生成，说明每个文件是什么、能否修改、修改后如何生效（哪些下游步骤会重跑），用户与外部 Agent 均可据此操作。
5. **修改回填方式**：所有产物支持三种处理通道（页内 AI 修改 / 自行处理 / 外部 Agent，见 §4.7），由用户自行决定。**回填后由后端统一落盘/校验（格式合法性、必填字段），失败给出明确提示。**

### 产物规范前置工作（v5.x 已完成）

> 以下 §4.4 中的内容不依赖手动模式机制，已提前在 v5.x 落地，v6.0 直接复用：

| 前置项 | v5.x 落地内容 | 位置 |
|--------|--------------|------|
| 固定目录结构 + 固定文件名 | 各流水线产物文件名固定（`story.txt`/`script.json`/`scene_{i}/video.mp4` 等），产物注册表 `list_artifacts` 枚举 | `core/artifacts.py`（既有） |
| JSON / SRT 开放格式 | UTF-8、`indent=2`、`ensure_ascii=False`（既有） | 各流水线 / `TaskManager._save` |
| **旁白纯文本 TXT 导出** | `combined_narration.txt` / `full_narration.txt` / `narration.txt`，与音频同名推导，供外部 Agent 直接投喂 | `BasePipeline._save_narration_txt` + 各流水线音频步骤 |
| **产物清单 manifest.json** | 任务运行开始/结束时自动落盘：产物 id、路径、格式、schema_hint、可编辑性、preview_url + 通用文件树 | `core/artifacts.write_manifest` |
| **任务目录说明 MANIFEST.md** | 自动生成，说明每个产物是什么、能否修改、修改后影响哪些下游步骤 | `core/artifacts.write_manifest_md` |
| **产物 schema 说明** | 产物定义补 `schema_hint`（人类可读字段说明），artifacts 端点返回 | `core/artifacts.py` 产物定义 |
| **artifacts 路径暴露** | 列表端点返回 `file_relpath` / `preview_url` / `schema_hint` | `web/routes/video_routes.py` |

> 规范细节见 `docs/dev/artifact_standard.md`。v6.0 检查点机制仅需在此基础上新增 `checkpoint.json`（按检查点拆分产物清单）与暂停/审批逻辑，产物规范本身不再重复建设。

### 4.5 修改后的重执行（产物级依赖图 + 修改前提示）

**问题**：现有续传依赖"文件已存在则跳过"。若用户修改了 `script.json`，但 `step_script` 状态仍为 COMPLETED，
恢复执行时该步被跳过，下游 `scene_{i}/video.mp4` 不会重新生成。

**方案（产物级依赖图，粒度精确到产物 id，非检查点级）**：

- `approve` 端点携带 `modified_artifact_ids` 与 `param_updates`（任务参数修改，见下）。
- 后端据此计算**受影响的下游产物**（经依赖图模块，见下），**仅删除真正受影响的产物文件**并将对应 `step_*` 状态重置为 PENDING；**不受影响的产物保留、不重跑**，然后恢复执行。
- 产物级依赖（第一期，原则：下游依赖上游的语义字段/文件，才被标记为受影响）：

```
scene_prompt / narration_text / duration / 场景数 ──→ ref 图 / videos / audio / subtitle / final
ref 图（character_reference / end_frame）────────────→ videos / final
video 片段（时长变化）─────────────────────────────→ audio / subtitle / final
audio（时长变化）───────────────────────────────→ subtitle / final
subtitle ────────────────────────────────────→ final
```

**具体规则**：

| 修改对象 | 影响（删除重跑） | 不影响（保留） |
|---------|----------------|---------------|
| 改 `script.json` 的 `scene_prompt` / `end_frame_prompt` | ref 图（i2i 尾帧）/ videos / final | — |
| 改 `script.json` 的 `narration_text` / 旁白 TXT | audio / subtitle / final | ref 图 / videos |
| 改 `scene_{i}/video.mp4`（时长变化） | audio / subtitle / final | 其他场景 video |
| 改 `character_reference.png` | videos / final | audio / subtitle |
| 改 `combined_narration.srt` | final | videos / audio |
| 任务参数（时长 / 场景数 / 分辨率 / 音色等） | 按实际影响的产物计算（如改分辨率 → videos/audio/subtitle/final；改音色 → audio/subtitle/final） | 其余保留 |

**依赖图独立模块（`core/dependency_graph.py`）**：

> 产物依赖关系不内嵌在路由 / pipeline 中，由**相对独立、可复用的模块**统一管理，
> 作为"修改产物时的决策依据"（`impact` 预计算 / `approve` 落盘 / 前端依赖图高亮 三处共用同一数据源）。

```python
# core/dependency_graph.py —— 产物依赖关系模块（纯声明式，无 I/O）
class DependencyGraph:
    """产物依赖图：改了什么 → 会影响什么。"""

    # 1. 产物级依赖（node → downstream nodes），按产物 type 声明
    #    支持 scope 通配（如 "scene:{i}/video" 影响 "task/audio"）
    PRODUCT_EDGES: dict[TaskType, dict[str, set[str]]] = {
        TaskType.CREATIVE: {
            "script:scene_prompt": {"references", "videos", "final"},   # 字段级
            "script:narration_text": {"audio", "subtitle", "final"},
            "character_reference.png": {"videos", "final"},
            "scene:{i}/video.mp4": {"audio", "subtitle", "final"},
            ...
        },
        ...
    }

    # 2. 任务参数级依赖（param → 受影响产物）
    PARAM_EDGES: dict[TaskType, dict[str, set[str]]] = {
        TaskType.CREATIVE: {
            "resolution": {"videos", "audio", "subtitle", "final"},
            "audio_voice": {"audio", "subtitle", "final"},
            ...
        },
        ...
    }

    def compute_impact(self, state, modified_artifacts: list[str],
                       param_updates: dict) -> ImpactPlan:
        """核心决策：给定修改集合 → 返回 {affected: [...], retained: [...]}。"""

    def to_checkpoint_edges(self) -> dict:  # 供前端渲染依赖图 / 高亮
        ...

@dataclass
class ImpactPlan:
    affected: list[str]     # 将删除重跑的产物 id 集合
    retained: list[str]     # 保留的产物 id 集合
    steps_to_reset: list[str]   # 需重置的 step 字段（由 affected 推导）
```

设计要点：

- **纯声明式 + 无 I/O**：依赖规则全部是数据（边表），不碰文件系统 / state，天然可单测、可扩展、可复用；
- **字段级粒度**：同一产物内不同字段（`scene_prompt` vs `narration_text`）影响不同下游，规则精确到 `artifact:field`；
- **scope 通配**：`scene:{i}/video.mp4` 支持场景索引模板，`task/audio` 等任务级下游；
- **两套边表**：`PRODUCT_EDGES`（改产物）+ `PARAM_EDGES`（改任务参数），`compute_impact` 统一合并；
- **与 `core/artifacts.py` 协作**：`artifacts.py` 负责"产物枚举 + 物理删除计划（CascadePlan）"，`dependency_graph.py` 负责"决策依据"，两者解耦——`impact` 端点调 dependency → 得 affected → 再逐产物调 `artifacts.get_cascade_plan` 拿物理清理计划；
- **单测独立成组**：`tests/test_dependency_graph.py`，每个任务类型 + 字段/参数组合一条用例。

**修改前提示（强制）**：任何修改（产物或参数）提交时，后端先经 `DependencyGraph.compute_impact` 计算影响范围返回 `affected_artifacts` 清单，
前端**弹窗列出"将删除重跑的产物"**，用户确认后才落盘重跑；不影响的产物明示"保留"。

> 第一期**不做** mtime 自动检测（O1）；仅前端做防呆提示（文件 mtime 未变时弹"确认未修改？"），后端不自动检测。

### 4.6 并发与资源

- **暂停等待期间释放并发槽位**：任务暂停（`PENDING` + `current_checkpoint` 非空）时，从 `active_pipelines` 移除（类似 resume 前的清理），
  不占用 `WeightedSemaphore` 槽位（避免"等用户确认"长时间卡住并发）。**自动变手动**走 stop 链路，天然完成同样的槽位释放。
- **继续时重新排队**：`approve` / 模式切换后复用现有 `run_pipeline_with_concurrency`，重新获取槽位执行（有排队等待时前端显示排队状态）。
- **可选超时**：`manual_config.timeout_minutes`（默认不设），超时自动转为 PENDING（用户可随时 resume），避免僵尸任务长期滞留。

### 4.7 产物操作方式（三通道并行，用户自选）

每个检查点暂停后，用户可任选以下三种方式处理当前检查点产物，**所有产物（文本 / 图片 / 视频 / 音频）均支持全部三种方式**：

| 通道 | 名称 | 模型归谁 | 核心流程 | 收口 |
|------|------|---------|---------|------|
| 1 | **页内 AI 修改** | 系统内置（`agnes-2.0-flash` / i2i） | 用户提要求 → 系统按产物类型拼接 prompt 走模型 → 预览对比 → 应用 | `approve(modified_artifact_ids)` |
| 2 | **自行处理** | 无（用户手动/本地工具） | 查看路径 / 预览 / 修改指引 → 本地改文件或上传覆盖 → 已修改，继续 | 同上 |
| 3 | **外部 Agent** | 用户自有 Agent | 复制 `cd <目录> && opencode` + 提示词模板 → Agent 处理回填 → 已修改，继续 | 同上 |

三通道最终都收口到 `approve(modified_artifact_ids=[...])`，触发 §4.5 依赖图重跑，流水线统一走现有 `resume` 恢复。

**通道 1 按产物类型的实现映射**：

| 产物类型 | 通道 1（页内 AI 修改）实现 |
|---------|--------------------------|
| 文本类（JSON / TXT / SRT） | `chat` / `chat_json` 直接改写内容 → 格式校验 → diff 预览 → 应用落盘 |
| 图片类（PNG / JPG） | `chat_multimodal` 读原图分析 → 生成 i2i 修改描述 → 调 Agnes Image i2i（原图为参考）重生成 → 并排预览对比 → 应用 |
| 视频类（MP4） | LLM 生成 ffmpeg 命令（路径限定任务目录内）→ **用户预览并显式确认** → 后端执行 → 对比预览 → 应用 |
| 音频类（MP3） | 优先改写同检查点旁白 TXT → 重新 TTS 生成；或 LLM 生成 ffmpeg 音频命令（同上） |

> 通道 1 的媒体类修改本质是"带要求的重新生成"，区别于 `regen`（无条件整体重生成）：前者基于当前产物定向调整，后者整个检查点推倒重来。视频命令执行须过白名单（仅 `ffmpeg` / `ffprobe`）+ 路径穿越校验（复用 `path_security`），见 §十一 O8。

### 4.8 检查点产物矩阵（按任务类型）

> 产物文件名均为权威定义（`docs/dev/pipeline_products.md` + 各流水线代码核实）。`<ws>` = 工作区，`<dir>` = 任务目录 `workspaces/<ws>/<YYYYmmdd_HHMMSS>_<task_id>/`。

| checkpoint | creative | manuscript | poetry | anchor |
|-----------|----------|-----------|--------|--------|
| `scenes` | `story.txt` / `script.json` / `prompts.json` / `end_frame_prompts.json` | 段落拆分 + 场景 prompt（存于 task state，经 checkpoints 接口导出 JSON） | 逐场景 `scene_prompt` + `narration_text`（诗句，存 state） | `prompts.json`（`anchor_prompt` + `smooth_loop_prompt` / `model_audio_prompt`） |
| `references` | `character_reference.png` / `pregenerated_end_frames/` | —（空实现跳过） | —（空实现跳过） | `anchor.png`（主播形象） |
| `videos` | `scene_{i}/video.mp4` | `scene_{i}/video.mp4` | `scene_{i}/video.mp4` | `clip/clip.mp4`（单段循环） |
| `audio` | `combined_narration.mp3` + `.txt` | `full_narration.mp3` + `.txt` | 逐场景 `scene_{i}/narration.mp3` | `full_narration.mp3` + `.txt`（`post_stitch`；`model` 模式无） |
| `subtitle` | `combined_narration.srt` | `full_subtitle.srt` | 逐场景 `scene_{i}/subtitle.srt` | `full_subtitle.srt`（`post_stitch`；`model` 模式无） |
| `final` | `final_video.mp4` | `final_video.mp4` | `final_video.mp4` | `final_video.mp4` |

**默认暂停点预填**（用户可增删）：

| 任务类型 | 默认暂停点 |
|---------|-----------|
| creative | `scenes` + `references` + `videos` + `subtitle` |
| manuscript | `scenes` + `videos` + `subtitle` |
| poetry | `scenes` + `videos` + `subtitle` |
| anchor | `scenes` + `videos`（`post_stitch` 模式可加 `audio`） |

### 4.9 检查点操作指引（三通道 × 每检查点）

> 通用前提：任一通道的操作最终都收口到 `approve(modified_artifact_ids=[...], param_updates={...})`；通道 1 返回结果**须用户「应用」才落盘**；**暂停中所有内容（产物 + 任务参数）均可修改**，修改前前端展示受影响产物弹窗，确认后按 §4.5 产物级依赖图**仅删除有影响的产物并重跑，不影响的保留**。下列指引均针对 `<任务目录>` 下文件，路径占位由前端自动填充。

**CP1 `scenes`（分镜 / 剧本 / 旁白）**

| 通道 | 操作流程 | 指引 |
|------|---------|------|
| 🤖 AI 帮我改 | 输入要求（如"第 2 场景画面描述更电影感"）→ `ai-modify` → diff 预览 → 应用 | JSON 类产物按字段粒度走 §4.5 依赖图：改 `scene_prompt`/`end_frame_prompt` → **ref 图/videos/final 重跑**（audio/subtitle 保留）；改 `narration_text` → **audio/subtitle/final 重跑**（ref 图/videos 保留）；改场景数/`duration` → 后续全部受影响项重跑 |
| ✏️ 我自己改 | 复制路径 → 打开 `script.json` 编辑 → 保存 → 「我已修改，继续」 | UTF-8、`indent=2`、`ensure_ascii=False`；只增删改指定字段，禁止新增顶层字段 |
| 🤝 外部 Agent | 复制 `cd <任务目录> && opencode` + 协作 prompt（§七 示例1）→ Agent 处理回填 → 「已修改，继续」 | prompt 模板已限定"保持结构不变、仅增强画面描述" |

**CP2 `references`（参考图 / 尾帧 / 主播形象）**

| 通道 | 操作流程 | 指引 |
|------|---------|------|
| 🤖 AI 帮我改 | 输入要求 → 后端 `chat_multimodal` 读原图分析 → i2i 以原图为参考重生成 → 并排对比 → 应用 | 构图可能变化较大（§十一 O9），不满意可调整要求反复生成 |
| ✏️ 我自己改 | 本地用 PIL / PS 处理 → 上传覆盖（或覆盖原文件）→ 「已修改，继续」 | 保持原尺寸与格式（PNG 768x1152 / 1152x768 等），否则下游视频比例异常 |
| 🤝 外部 Agent | 复制 `cd <任务目录> && opencode` + §七 示例5 → 处理回填 → 继续 | 输出建议命名 `*_v2.png` 再上传，避免覆盖原文件前无备份 |

**CP3 `videos`（视频片段）**

| 通道 | 操作流程 | 指引 |
|------|---------|------|
| 🤖 AI 帮我改 | 输入要求 → 后端生成 ffmpeg 命令 → **预览命令并确认** → 执行 → 对比 → 应用 | 命令白名单（ffmpeg/ffprobe）+ 路径限定任务目录；改后 **audio/subtitle/final 重跑**（时长变化→字幕偏移风险，见 §十一 O4） |
| ✏️ 我自己改 | 本地 ffmpeg 处理 → 覆盖 `scene_{i}/video.mp4`（或上传）→ 继续 | H.264 + AAC、分辨率与原片一致；改了时长须知道下游音频/字幕会重跑 |
| 🤝 外部 Agent | 复制 `cd <任务目录> && opencode` + §七 示例4 → 处理（输出 `video_fixed.mp4`）→ 上传/覆盖 → 继续 | Agent 勿重编码音频流以外的轨，保持画面比例 |

**CP4 `audio`（配音）**

| 通道 | 操作流程 | 指引 |
|------|---------|------|
| 🤖 AI 帮我改 | 输入润色要求 → 改写旁白 TXT（`combined_narration.txt` / `full_narration.txt`）→ 重新 TTS → 试听对比 → 应用 | 只改文案，不改音频格式；poetry 为逐场景 `scene_{i}/narration.mp3`，要求按场景分批提 |
| ✏️ 我自己改 | 直接编辑旁白 TXT → 「已修改，继续」（触发重新 TTS + 字幕重生成） | 每场景一段以空行分隔，段数不变；总字数变化 ≤10% 为宜 |
| 🤝 外部 Agent | 复制 §七 示例2 prompt → Agent 润色写回 TXT → 继续 | 时长估算按 4 字/秒 |

**CP5 `subtitle`（字幕）**

| 通道 | 操作流程 | 指引 |
|------|---------|------|
| 🤖 AI 帮我改 | 输入要求（断句 / 时间轴）→ 修正 SRT → diff → 应用 | 序号连续、时间 `HH:MM:SS,mmm`、中文单条 ≤18 字符；poetry 逐场景改 |
| ✏️ 我自己改 | 打开 `*.srt` 编辑 → 保存 → 继续 | 末条结束时间不超音频时长；相邻不重叠（≥50ms 间隔） |
| 🤝 外部 Agent | 复制 §七 示例3 prompt → Agent 修复回填 → 继续 | Agent 可用 ffprobe 校时（命令已含在模板） |

**CP6 `final`（成片）**

| 通道 | 操作流程 | 指引 |
|------|---------|------|
| 🤖 AI 帮我改 | 输入要求（压缩 / 调色 / 加片头）→ 生成 ffmpeg 命令 → 确认执行 → 对比 → 应用 | 修改后无下游，`approve` 即完成任务 |
| ✏️ 我自己改 | 本地处理 `final_video.mp4` → 覆盖/上传 → 继续 | 保持 H.264 + AAC；如改动较大建议回到上游检查点修改更稳妥 |
| 🤝 外部 Agent | 复制 `cd <任务目录> && opencode` + 自定义 prompt → 处理回填 → 继续 | 成片为最终交付物，建议确认无上游问题时再改 |

---

## 五、API 设计（草案）

### 5.1 创建任务（扩展现有端点）

各 `/api/tasks/*` 端点新增可选参数：

```
execution_mode: str = "auto"        # "auto" | "manual"（默认 auto，完全向后兼容）
pause_points: str = "[]"            # JSON 数组，如 ["scenes","subtitle"]；空=全部检查点
```

新增 `ManualConfig` 模型并入 `BaseTaskState`（缺省自动模式，旧数据兼容）：

```python
class ManualConfig(BaseModel):
    enabled: bool = False           # 是否手动模式
    pause_points: list[str] = []    # 空 = 全部检查点暂停；清空 = 切回自动
    approved_checkpoints: list[str] = []   # 已确认的检查点（恢复执行时跳过暂停）
    modified_artifacts: list[str] = []     # 最近一次回填的产物 id（脏标记）
    current_checkpoint: str = ""    # 当前暂停/待展示的检查点（空 = 无暂停）
    timeout_minutes: int = 0        # 0 = 不超时
```

### 5.2 检查点操作

| 端点 | 说明 |
|------|------|
| `GET /api/tasks/{id}/checkpoints` | 列出所有检查点状态 + 产物清单摘要 |
| `GET /api/tasks/{id}/checkpoints/{name}` | 检查点详情（`checkpoint.json` 内容） |
| `GET /api/tasks/{id}/artifacts/{artifact_id}` | 产物预览（文本/图片/视频，视频用 range 流式播放） |
| `GET /api/tasks/{id}/checkpoints/{name}/impact` | **影响预计算**：`query: {modified_artifact_ids?, param_updates?}`；返回「将删除重跑的产物清单 + 保留清单」（**只计算不落盘**，供修改前提示弹窗） |
| `POST /api/tasks/{id}/checkpoints/{name}/approve` | 确认修改并继续下一步；`body: {modified_artifact_ids?: [...], param_updates?: {...}, confirmed: true}`；内部先复用 `impact` 计算 → 落盘删除受影响产物 → 走现有 `resume` |
| `POST /api/tasks/{id}/checkpoints/{name}/regen` | 重新生成当前检查点（重置本检查点 + 下游） |
| `POST /api/tasks/{id}/artifacts/{artifact_id}/upload` | 覆盖回填产物（multipart）；文本类亦可走 `POST .../approve` 内联提交文本 |
| `POST /api/tasks/{id}/checkpoints/{name}/ai-modify` | **通道 1**：页内 AI 修改；`body: {artifact_id, user_request}`；按 §4.7 产物类型映射实现；返回「修改后产物 + 改动摘要」（**不落盘**，由后续 approve 落盘） |
| `POST /api/tasks/{id}/artifacts/{artifact_id}/run-command` | 执行通道 1 生成并经用户确认的命令（视频/音频类）；`body: {command}`；白名单（ffmpeg/ffprobe）+ 路径限定任务目录 |

> `approve` 内部复用现有 `resume` 执行路径（暂停态即 `PENDING`，resume 前无需额外状态迁移）；
> `regen` 等价于 `approve(modified_artifact_ids=[本检查点全部产物], confirmed=true)`；
> `ai-modify` 返回结果须用户显式「应用」才落盘，避免模型输出直接污染产物；
> 流程约定：**修改前先调 `impact` 展示受影响产物 → 用户确认 → 再调 `approve(confirmed=true)`**；`confirmed` 缺省为 false 时 `approve` 仅返回影响清单不落盘（前端可省略单独调 `impact`）。

### 5.3 运行时模式切换

| 端点 | 说明 |
|------|------|
| `POST /api/tasks/{id}/mode` | 切换执行模式；`body: {mode: "auto" \| "manual"}`，**切换即继续** |

行为：

- `mode=manual`（自动变手动）：复用现有 stop 链路挂起流水线（`pipeline.stop()` → 下一安全点 `PipelineShutdown`），
  落盘 `enabled=true` + 计算 `current_checkpoint`，`status=PENDING`。用户随后在检查点视图操作（approve / modify / regen），
  恢复后**保持手动模式**（执行到下一命中检查点再次暂停）。
- `mode=auto`（手动变自动）：
  - 任务暂停中（`PENDING` + 有 checkpoint）→ 清空 `pause_points` + **立即走现有 `resume` 继续跑完**（切换即继续）；
  - 任务运行中 → 仅清空 `pause_points`，当前检查点之后不再暂停。
- 幂等与校验：目标模式与当前一致时返回当前状态不重复操作；`simple` / `simple_image` 类型（无检查点）切换手动返回 400 提示。

### 5.4 任务详情扩展

`GET /api/tasks/{id}` 返回体新增：

```json
{
  "current_mode": "manual",
  "manual_config": { "enabled": true, "pause_points": [...], "approved_checkpoints": [...], "current_checkpoint": "scenes", "timeout_minutes": 0 },
  "checkpoint_manifest": { ... }
}
```

> `current_mode` 与 `manual_config.enabled` 保持一致（冗余导出便于前端直接读取）。

---

## 六、前端交互设计（草案）

> 前端为 Vue 3 + Tailwind（`frontend/`），产物输出到 `static/`。以下为交互流程概要。

### 6.1 创建任务面板

- 执行模式选择：**自动 / 手动**（单选，默认自动）。
- 手动模式下显示"暂停点"多选：分镜 / 参考图 / 视频片段 / 配音 / 字幕 / 合成（**默认按任务类型预填**，见 §4.8，用户可增删）。
- 提示文案："手动模式会在每个暂停点等待你确认或修改产物，可配合外部 AI 工具（opencode / workbuddy 等）使用。运行中也可随时在自动/手动间切换。"
- 切换 simple / simple_image 类型时手动模式置灰并提示"该类型不支持暂停，仅完成后展示产物清单"。

### 6.2 检查点等待页（任务卡片 → 检查点详情）

暂停态（`PENDING` + `current_checkpoint` 非空）展示"⏸ 等待你操作"（区别于 running/failed）：

1. **产物区**：文本产物给只读预览；图片给 `<img>`；视频给 `<video>`（本地路径经 `artifacts` 端点伺服）。每个产物均可复制绝对路径。
2. **操作区**（常驻）：
   - ✅ 确认并继续
   - 🔄 重新生成当前步骤
   - ⚡ 切回自动并继续（调用 `mode=auto`，清空暂停点立即跑完）
3. **处理本检查点**（三卡片并行，任选其一，点开对应面板）：
   - 🤖 **AI 帮我改**：输入修改要求（如"第 2 段旁白更口语化"）→「开始修改」→ 展示修改结果（文本 diff / 图片并排 / 视频命令预览）→「✅ 应用并确认」落盘并继续 /「放弃」
   - ✏️ **我自己改**：展示产物路径 + `schema_hint` + 修改后影响的下游步骤（依赖图高亮）+ 回填方式（本地改好后点「✏️ 我已修改，继续」或上传覆盖）
   - 🤝 **外部 Agent**：展示 `cd <任务目录> && opencode` 一键复制 + 协作 prompt 模板一键复制（§七，占位符已填充真实路径）→ Agent 处理回填后点「🤝 已修改，继续」
   - **⚙️ 任务参数**（暂停中可改）：展示可修改参数（场景数 / 每段时长 / 分辨率 / 音色 / 风格等）→ 修改后与产物一样走 `impact` 预计算受影响产物
4. **修改前提示（强制）**：任何修改提交时先调 `impact` → 弹窗列出「将删除重跑的产物」与「保留的产物」→ 用户确认后 `approve(confirmed=true)` 落盘重跑；文件 mtime 未变的防呆提示同弹窗一并展示。
5. 三卡片最终都收口到 `approve(modified_artifact_ids, param_updates)`，统一触发产物级依赖图重跑。

### 6.3 任务列表

- 暂停中的手动任务显示 `⏸ 等待你操作` 徽标与当前检查点名（判断依据：`PENDING` + `current_checkpoint` 非空）；支持从列表直接进入检查点详情。
- 运行中任务卡片显示执行模式标签（`⚡ 自动` / `✋ 手动`）。

### 6.4 运行时模式切换入口

- **位置**：任务卡片（运行中 / 暂停中）与进度面板常驻一个小开关「自动 ⇄ 手动」。
- **自动 → 手动**（任务运行中）：点击后任务在下一个安全点挂起，弹出检查点视图，展示 `current_checkpoint` 产物。
- **手动 → 自动**（暂停中）：点击后立即继续跑完（**切换即继续**）；运行中点击仅取消后续暂停点。

---

## 七、外部 Agent 协作（示例 Prompt）

> 目标：**用户复制后即可用**。示例面向支持"读取本地文件 + 执行命令"的本地免费 Agent
> （如 opencode、workbuddy、CodeBuddy CLI），以及手动命令行工具。
> 所有 `<...>` 占位由前端根据真实任务目录自动填充，用户零替换成本。

### 示例 1：外部 Agent 优化分镜（scenes 检查点）

```
你是资深视频分镜导演。请读取文件 <任务目录>/script.json，对其中每个场景的视频生成描述进行优化：

1. 保持 JSON 结构、场景数量、每个场景的 narration_text（旁白）与 duration 完全不变；
2. 仅增强 scene_prompt / end_frame_prompt 的画面描述，要求：
   - 明确主体、构图、镜头运动（推/拉/摇/移）、光线氛围、色彩基调；
   - 与前后场景的视觉连续性保持一致（统一角色外貌、色调）；
   - 每条不超过 80 个中文字符；
3. 语言与原文一致（中文）；禁止添加 JSON 之外的任何字段；
4. 输出：先给出改动摘要（每条一句话），再输出完整的、可直接覆盖原文件的 JSON 内容。

完成后请将结果写回 <任务目录>/script.json（UTF-8、缩进 2 空格）。
之后用户会在网页上点击"已修改，继续"，系统会基于新分镜重新生成参考图与视频。
```

### 示例 2：外部 Agent 润色旁白（audio 检查点前）

```
请读取文件 <任务目录>/combined_narration.txt（或 script.json 中所有 narration_text 拼接），
将这段视频旁白润色为更适合朗读的口播稿：

1. 保持原意与信息量不变，总字数变化不超过 10%；
2. 句子改为短句、口语化，去掉书面连接词与被动语态；
3. 按 4 字/秒估算，控制总时长约 <总时长> 秒；
4. 分段以空行分隔，段数与顺序保持不变（每段对应一个视频场景）；
5. 只输出润色后的纯文本，不要任何解释。

请将结果写回 <任务目录>/combined_narration.txt。用户在网页点击"已修改，继续"后，
系统会重新生成配音与字幕。
```

### 示例 3：外部 Agent 修正字幕（subtitle 检查点）

```
请检查并修复字幕文件 <任务目录>/full_subtitle.srt：

1. 用 `ffprobe -v error -show_entries format=duration -of csv=p=0 <任务目录>/combined_narration.mp3`
   获取音频实际时长，确保最后一条字幕的结束时间不超出音频时长；
2. 相邻字幕不得重叠（允许 50ms 间隔）；每条字幕时长 ≥ 0.3 秒；
3. 中文单条不超过 18 个字符，或拆分两行；英文按单词断句，每条 ≤ 2 行；
4. 保持序号连续、时间格式 HH:MM:SS,mmm；
5. 输出修改前后对比摘要，并将修复后的完整 SRT 写回 <任务目录>/full_subtitle.srt。
```

### 示例 4：手动/Agent 处理视频片段（videos 检查点）

```
请用 ffmpeg 处理 <任务目录>/scene_2/video.mp4：
1. 抽帧检查：输出第 1、2、3 秒的关键帧到 <任务目录>/scene_2/frames/ 目录（PNG）；
2. 若画面质量可接受，无需改动，直接输出"无需处理"；
3. 若需处理（如裁剪、调色），用 ffmpeg 输出到 <任务目录>/scene_2/video_fixed.mp4，
   并打印所用命令；
4. 不要重新编码音频，保持原有画面比例。
```

> 用户将处理后文件 `video_fixed.mp4` 上传覆盖（或重命名后回填），再点击"已修改，继续"。

### 示例 5：外部 Agent 处理参考图（references 检查点）

```
请用 Python PIL 处理 <任务目录>/character_reference.png：
1. 将主体人物居中，背景虚化（高斯模糊）；
2. 统一输出 768x1152，质量 95 的 PNG；
3. 保存为 <任务目录>/character_reference_v2.png，并打印图片尺寸。
```

### 协作协议约定（供外部 Agent / 工具遵守）

| 项 | 约定 |
|----|------|
| 文本编码 | UTF-8 无 BOM |
| JSON | 缩进 2 空格，`ensure_ascii=False`，只改指定字段 |
| SRT | 标准 SubRip，序号连续 |
| 图片 | PNG（覆盖上传兼容 jpg/png/webp） |
| 视频 | MP4（H.264 + AAC） |
| 回填方式 | 覆盖原文件名 或 上传新文件（approve 时指定替换目标产物） |
| 副作用 | 回填后以下游步骤按 §4.5 依赖图重跑 |

---

## 八、问题上报模板

> 手动模式的核心价值是把"AI 生成不理想"变成"可修改、可重跑"，但**修改后仍不达预期**的 case 需要用户提供必要信息后才能高效排查。
> 检查点等待页提供「📤 反馈问题」入口，按以下模板自动填充任务上下文，用户补充描述后一键复制/跳转 GitHub Issue。

```markdown
### 基本信息
- 项目版本：v6.0.x（或 commit hash）
- 部署方式：本地 / Docker
- 任务类型：creative / manuscript / poetry / anchor
- 执行模式：自动 / 手动（暂停点：scenes,videos,...）
- 问题检查点：scenes / references / videos / audio / subtitle / final
- 使用的处理方式：通道1 页内AI 修改 / 通道2 自行处理 / 通道3 外部 Agent

### 期望结果
（描述你希望通过修改产物达到的效果，如"第 2 场景改为夜景后视频应重新生成"）

### 实际结果
（描述实际发生的情况：修改未生效 / 下游未重跑 / 产物未更新 / 字幕偏移 / 报错等）

### 复现步骤
1. 创建任务（execution_mode=manual，暂停点=…）
2. 在 <检查点> 使用 <通道> 处理产物（操作内容：…）
3. 点击「应用并确认 / 已修改，继续」后出现…

### 关键信息（系统自动填充 + 用户补充）
- 任务 ID：__________
- 任务目录：<路径>
- checkpoint.json 内容：
  ```
  <粘贴产物清单，含产物 id / path / schema_hint>
  ```
- 修改前后产物差异（文本类粘贴相关字段，媒体类描述差异）：
  - 修改前：…
  - 修改后：…
- 外部 Agent 使用的提示词（通道3 时）：…
- 错误日志片段（working_dir 下 logs/ 或 error_logs/，取最后 30~50 行）：…
  ```
  <粘贴>
  ```

### 环境信息
- OS / Python 版本
- 浏览器及版本
- 是否 Docker 部署（若是，贴 docker-run.sh 挂载路径）
```

> 模板由前端在检查点详情页自动生成（任务上下文 + 产物清单预填），用户仅需补充"期望/实际/复现"，降低上报成本。

---

## 九、兼容性与回退

1. **默认自动**：`execution_mode` 缺省 `auto`，全部现有端点/参数/前端行为不变；运行中切换不影响自动任务默认行为。
2. **旧状态兼容**：`BaseTaskState` 新增 `manual_config` 用 `Field(default_factory=ManualConfig)`，旧 JSON 反序列化自动取默认（自动模式）。
3. **暂停中可 stop/resume**：手动暂停态（`PENDING`）与普通中断一样可停止、可恢复；恢复后回到上次暂停的检查点。
4. **回退策略**：手动模式任一检查点操作异常时，可退化为"自动继续"（清空 `pause_points` 恢复执行到完成，等价于 `mode=auto`）。
5. **自动变手动与中断同链路**：自动变手动复用 stop 的 `_stop_event` 安全点与 `PipelineShutdown` 处理，不新增执行路径；恢复后模式差异仅由 `manual_config` 字段表达。
6. **回归门槛**：新增功能不得破坏 `docs/dev/regression_test_plan.md` 8 场景；手动模式单测独立成组。

---

## 十、实施范围与分期

| 阶段 | 内容 | 依赖 | 交付物 |
|------|------|------|--------|
| **Phase 1（P0）** | 后端暂停机制：`ManualConfig` + `_maybe_pause` 钩子 + 暂停态复用 `PENDING` + `approve/regen/mode` 端点 + 检查点依赖图 | 现有 resume / stop 机制 | creative 一条流水线可端到端手动执行 + 运行中双向切换 |
| **Phase 2（P1）** | 产物规范：`checkpoint.json` 清单 + `MANIFEST.md` + `combined_narration.txt` 导出 + artifacts 预览/上传端点 | Phase 1 | 全部流水线产物对外开放、可回填 |
| **Phase 3（P2）** | 前端：创建面板模式选择 + 检查点详情页三卡片（AI 帮我改 / 我自己改 / 外部 Agent）+ diff 预览 + 协作 prompt 一键复制 | Phase 1/2 | 完整交互闭环 |
| **Phase 4（P3）** | 推广到 manuscript / poetry / anchor（MultiScene 统一检查点）；simple / simple_image 产物清单 | Phase 2 | 全部任务类型可用 |
| **Phase 5（P4）** | 协作 prompt 库整理进文档 + 示例视频教程 + 回归测试补充 | Phase 4 | 交付文档 |

---

## 十一、风险与开放问题

| # | 问题 | 建议 |
|---|------|------|
| O1 | 产物被外部 Agent 直接改文件后，系统如何感知？是否做 mtime 自动检测？ | 第一期显式声明（用户点"已修改"）+ 前端 mtime 防呆提示（未变时弹"确认未修改？"）；后端自动检测列为增强项 |
| O2 | 产物级依赖图的粒度与准确性（改 narration 不该重跑 ref 图） | 由独立模块 `core/dependency_graph.py` 统一维护（§4.5），纯声明式边表 + 字段级粒度，单测独立成组；`impact` 预计算结果供前端确认，降低误删风险 |
| O3 | 暂停等待期间 `sub_maker`（TTS cues）等内存态丢失，恢复后需重采（已有 `_recover_sub_maker`），但有额外 TTS 流量 | 接受；恢复时提示"字幕时间线重新校准" |
| O4 | 用户修改视频片段后音频/字幕重跑，可能出现片段替换导致时长变化 → 字幕偏移 | 依赖图强制 `videos` 修改后重跑 `audio+subtitle`；文档明示 |
| O5 | 并发槽位释放后恢复执行需重新排队，多任务下"继续"可能有等待 | 接受；前端显示排队状态；可配置不释放槽位（`manual_config.hold_slot`） |
| O6 | 手动模式 + 长任务（多场景）暂停点过多导致操作负担 | 默认仅暂停 `scenes` + `videos` + `subtitle` 三个高价值点，用户可增删 |
| O7 | `checkpoint.json` 中绝对路径在不同部署方式（本地/Docker）下对用户可见性问题 | Docker 部署时展示宿主机映射路径（`docker-run.sh` 已支持挂载数据目录） |
| O8 | 通道 1 视频类产物由 LLM 生成 ffmpeg 命令并执行，存在命令注入/误操作风险 | 仅允许 `ffmpeg`/`ffprobe` 白名单 + 参数路径限定任务目录（复用 `path_security`）+ **用户预览并显式确认后才执行** + 默认只读输出到任务目录 |
| O9 | 通道 1 图片类产物用 i2i 重生成，可能与原文构图差异较大 | 展示并排对比预览，用户「应用」才落盘；可反复调整要求重新生成 |

---

## 十二、验收标准（Phase 1 达成时的定义）

1. `POST /api/tasks/creative` 传 `execution_mode=manual` 创建任务后，流水线在 `scenes` 检查点暂停，
   状态为 `PENDING` + `manual_config.enabled=true`，`current_checkpoint=scenes`，且不占用并发槽位。
2. `approve` 后任务恢复，`scenes` 检查点被跳过，进入 `references` 并再次暂停（默认全暂停点）。
3. `approve(modified_artifact_ids=["script"])` 后，`script.json` 修改生效：下游参考图/视频/音频/字幕/合成全部重跑，
   最终视频基于新分镜生成。
4. 修改后重跑时 `_recover_sub_maker` 生效，字幕时间线仍为 cue 精确对齐（非 legacy）。
5. **运行中自动 → 手动**：自动任务运行中调 `mode=manual`，任务挂起为 `PENDING`（`current_checkpoint` 非空），
   resume 后保持手动模式，在下一个命中检查点再次暂停。
6. **运行中手动 → 自动**：暂停中调 `mode=auto`，清空暂停点并立即继续，一次跑完到完成（**切换即继续**）。
7. **中断不改变模式**：自动任务 stop 后 resume，仍为自动模式，不出现检查点视图。
8. **通道 1 文本产物**：对 `script.json` 调 `ai-modify`，返回修改后 JSON + 改动摘要（未落盘）；用户「应用并确认」后落盘，下游按产物级依赖图重跑。
9. **通道 1 视频产物**：对 `scene_2/video.mp4` 调 `ai-modify`，返回 ffmpeg 命令，用户确认执行后产物更新、对比可见。
10. **通道 2 / 通道 3**：用户本地改文件（或外部 Agent 处理后）点「已修改，继续」，`approve(modified_artifact_ids)` 生效并重跑。
11. **影响预计算**：`GET .../impact?modified_artifact_ids=script` 返回"将删除重跑的产物 + 保留产物"清单；`approve` 不带 `confirmed=true` 时不落盘、仅返回影响清单；计算结果来自 `core/dependency_graph.py`（独立模块可单测、可复用）。
12. **修改前提示**：approve 前前端弹窗展示受影响产物，用户确认后 `approve(confirmed=true)` 才删除重跑；改 `narration_text` 时 ref 图 / videos **不被删除**（精确到产物级）。
13. **任务参数修改**：暂停中修改每段时长 / 分辨率后调 `approve(param_updates=...)`，按 §4.5 仅重跑实际受影响产物（如改分辨率重跑 videos/audio/subtitle/final，改音色仅 audio/subtitle/final）。
14. 自动模式任务行为与 v5.0 完全一致（8 场景回归通过）。
15. 产物清单、MANIFEST.md、旁白 TXT 导出、示例 prompt 可一键复制。

---

## 十三、后续步骤

1. ✅ 本草案评审（检查点集合、依赖图、默认暂停点、开放问题取舍均已完成）。
2. ✅ 输出实施方案与路线图 → `docs/plans/v6.0/implementation_plan.md`（阶段划分、验证方式、状态跟踪、CI 异步测试约定）。
3. 按 `implementation_plan.md` P0 → P4 分期实施；单测提交后走 GitHub Action 异步执行，不在本地阻塞开发；每阶段完成更新实施文档状态表。
4. 进入 `system_design.md` 增量设计（模型/路由/流水线改动清单）作为 P0 开工的代码级依据。
