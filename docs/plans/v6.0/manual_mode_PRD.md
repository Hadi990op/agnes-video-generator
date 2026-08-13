# v6.0「手动模式」初步方案（PRD 草案）

> **状态**：🟡 初步方案（PRD 草案），待评审确认后细化
> **版本**：v0.2（2026-08）
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
2. 若当前任务为手动模式且该检查点在 `pause_points` 中且**尚未被确认** → 落盘 `AWAITING_USER` 状态 + 记录当前检查点，流水线**正常返回**（非失败）。
3. 用户在 Web 端操作（确认/修改/重新生成）后调用 `approve` → 后端将检查点标记为已确认（或重置受影响的下游步骤）→ 走**现有 `resume` 逻辑**恢复执行。
4. 恢复执行时：已完成的检查点被 `coarse_skip` 跳过；未完成/被重置的步骤重新执行。

> **收益**：不引入新的执行引擎，暂停/恢复天然支持"进程重启后续传"（状态全落盘）。

### 4.2 状态机扩展

在 `models/task.py` 的 `StepStatus` 中新增一个任务级状态：

```python
class StepStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_USER = "awaiting_user"   # v6.0 新增：手动模式等待用户操作
    COMPLETED = "completed"
    FAILED = "failed"
```

流转：

```
创建(mode=manual)
  → QUEUED → RUNNING
  → [每个检查点] AWAITING_USER ──approve──→ RUNNING（继续下一步）
                              ├─modify───→ RUNNING（重置下游步骤后继续）
                              └─regen────→ RUNNING（重新生成当前检查点）
  → … → COMPLETED
任何时刻 ──→ FAILED（异常） / PENDING（用户 stop）
```

### 4.3 检查点设计（Checkpoint）

以 `MultiScenePipeline` 模板方法（`build_scenes → references → videos → audio → subtitle → composite`）为基准，
对用户有意义的产物边界定义 6 个标准检查点：

| # | checkpoint | 触发时机 | 核心产物 | 产物格式 |
|---|-----------|---------|---------|---------|
| 1 | `scenes` | 分镜/剧本/旁白构建完成 | `story.txt`、`script.json`、`prompts.json`、`character_reference.png`、`end_frame_prompts.json` | TXT / JSON / PNG |
| 2 | `references` | 参考图/尾帧图生成完成 | `character_reference.png`、`pregenerated_end_frames/`、`scene_{i}/ref*.png` | PNG |
| 3 | `videos` | 全部视频片段生成完成 | `scene_{i}/video.mp4`（+ `task.json`、`curl.sh`） | MP4 / JSON |
| 4 | `audio` | 配音生成完成 | `combined_narration.mp3`、`combined_narration.txt`（旁白纯文本导出） | MP3 / TXT |
| 5 | `subtitle` | 字幕生成完成 | `full_subtitle.srt`、`subtitle_styles.json` | SRT / JSON |
| 6 | `final` | 合成完成 | `final_video.mp4` | MP4 |

> 说明：
> - creative 内部细粒度步骤（`step_story` / `step_character_ref` / `step_script` / `step_end_frame_prompts`）第一期**合并为 `scenes` 一个检查点**，避免检查点过多。
> - manuscript / poetry / anchor 继承同一模板方法，天然获得同一组检查点（各自身产物文件已对齐，见 `docs/dev/pipeline_products.md`）。
> - simple / simple_image 仅 1~2 步，第一期**不做暂停**，但支持"完成后展示产物清单"。

**暂停点配置（`pause_points`）**：默认手动模式暂停全部 6 点；用户可指定子集（如只暂停 `scenes` 与 `subtitle`），未指定的检查点自动通过。

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
5. **修改回填方式**：文本类产物支持 Web 端编辑框直接修改或文件覆盖；图片/视频类产物支持"替换文件上传"或"在本地目录处理后点已修改"。**回填后由后端统一落盘/校验（格式合法性、必填字段），失败给出明确提示。**

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

### 4.5 修改产物后的重执行（脏标记）

**问题**：现有续传依赖"文件已存在则跳过"。若用户修改了 `script.json`，但 `step_script` 状态仍为 COMPLETED，
恢复执行时该步被跳过，下游 `scene_{i}/video.mp4` 不会重新生成。

**方案**（第一期采用显式声明，简单可靠）：

- `approve` 端点携带可选参数 `modified_artifact_ids: ["script", "narration_txt"]`。
- 后端据此计算**受影响的下游检查点**（内置一张"检查点依赖图"），将其 `step_*` 状态重置为 PENDING 并**删除对应产物文件**，然后恢复执行。
- 依赖图（第一期简化版）：

```
scenes ──→ references ──→ videos ──→ audio ──→ subtitle ──→ final
```

即：修改 `scenes` 产物 → `references / videos / audio / subtitle / final` 全部重跑；
修改 `videos` 产物 → 仅 `audio / subtitle / final` 重跑（音频时长依赖视频时长）等。详细映射在 `system_design.md` 中给出。

> 开放问题：是否引入"文件 mtime 自动检测脏"作为增强（O1，见 §十）。

### 4.6 并发与资源

- **暂停等待期间释放并发槽位**：任务进入 `AWAITING_USER` 时，从 `active_pipelines` 移除（类似 resume 前的清理），
  不占用 `WeightedSemaphore` 槽位（避免"等用户确认"长时间卡住并发）。
- **继续时重新排队**：`approve` 后复用现有 `run_pipeline_with_concurrency`，重新获取槽位执行（有排队等待时前端显示排队状态）。
- **可选超时**：`manual_config.timeout_minutes`（默认不设），超时自动转为 PENDING（用户可随时 resume），避免僵尸任务长期滞留。

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
    pause_points: list[str] = []    # 空 = 全部检查点暂停
    approved_checkpoints: list[str] = []   # 已确认的检查点（恢复执行时跳过暂停）
    modified_artifacts: list[str] = []     # 最近一次回填的产物 id（脏标记）
    timeout_minutes: int = 0        # 0 = 不超时
```

### 5.2 检查点操作

| 端点 | 说明 |
|------|------|
| `GET /api/tasks/{id}/checkpoints` | 列出所有检查点状态 + 产物清单摘要 |
| `GET /api/tasks/{id}/checkpoints/{name}` | 检查点详情（`checkpoint.json` 内容） |
| `GET /api/tasks/{id}/artifacts/{artifact_id}` | 产物预览（文本/图片/视频，视频用 range 流式播放） |
| `POST /api/tasks/{id}/checkpoints/{name}/approve` | 确认产物，继续下一步；`body: {modified_artifact_ids?: [...]}` |
| `POST /api/tasks/{id}/checkpoints/{name}/regen` | 重新生成当前检查点（重置本检查点 + 下游） |
| `POST /api/tasks/{id}/artifacts/{artifact_id}/upload` | 覆盖回填产物（multipart）；文本类亦可走 `POST .../approve` 内联提交文本 |

> `approve` 内部复用现有 `resume` 执行路径；`regen` 等价于 `approve(modified_artifact_ids=[本检查点全部产物])`。

### 5.3 任务详情扩展

`GET /api/tasks/{id}` 返回体新增：

```json
{
  "manual_config": { "enabled": true, "pause_points": [...], "approved_checkpoints": [...], "timeout_minutes": 0 },
  "current_checkpoint": "scenes",
  "checkpoint_manifest": { ... }
}
```

---

## 六、前端交互设计（草案）

> 前端为 Vue 3 + Tailwind（`frontend/`），产物输出到 `static/`。以下为交互流程概要。

### 6.1 创建任务面板

- 执行模式选择：**自动 / 手动**（单选，默认自动）。
- 手动模式下显示"暂停点"多选：分镜 / 参考图 / 视频片段 / 配音 / 字幕 / 合成（默认全选）。
- 提示文案："手动模式会在每个暂停点等待你确认或修改产物，可配合外部 AI 工具（opencode / workbuddy 等）使用。"

### 6.2 检查点等待页（任务卡片 → 检查点详情）

状态变为"等待你操作"（区别于 running/failed），展示：

1. **产物区**：文本产物给只读预览 + 编辑框；图片给 `<img>` 预览；视频给 `<video>` 播放（本地路径经 `artifacts` 端点伺服）。
2. **操作区**：
   - ✅ 确认并继续
   - ✏️ 编辑后继续（文本内联编辑 / 上传覆盖，标注会影响哪些下游步骤）
   - 🔄 重新生成当前步骤
   - 📋 复制产物路径（含工作目录绝对路径）
   - 🤖 复制协作 Prompt（见 §七，一键复制到剪贴板）
3. **协作引导区**：说明"可将以下提示词复制给本地 Agent（opencode / workbuddy 等），处理完成后点「已修改，继续」"。

### 6.3 任务列表

- 手动模式任务显示 `⏸ 等待你操作` 徽标与当前检查点名；支持从列表直接进入检查点详情。

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

## 八、兼容性与回退

1. **默认自动**：`execution_mode` 缺省 `auto`，全部现有端点/参数/前端行为不变。
2. **旧状态兼容**：`BaseTaskState` 新增 `manual_config` 用 `Field(default_factory=ManualConfig)`，旧 JSON 反序列化自动取默认（自动模式）。
3. **暂停中可 stop/resume**：`AWAITING_USER` 状态视为可停止、可恢复；恢复后回到上次暂停的检查点。
4. **回退策略**：手动模式任一检查点操作异常时，可退化为"自动继续"（清空 `pause_points` 恢复执行到完成）。
5. **回归门槛**：新增功能不得破坏 `docs/dev/regression_test_plan.md` 8 场景；手动模式单测独立成组。

---

## 九、实施范围与分期

| 阶段 | 内容 | 依赖 | 交付物 |
|------|------|------|--------|
| **Phase 1（P0）** | 后端暂停机制：`AWAITING_USER` 状态 + `ManualConfig` + `_maybe_pause` 钩子 + `approve/regen` 端点 + 检查点依赖图 | 现有 resume 机制 | creative 一条流水线可端到端手动执行 |
| **Phase 2（P1）** | 产物规范：`checkpoint.json` 清单 + `MANIFEST.md` + `combined_narration.txt` 导出 + artifacts 预览/上传端点 | Phase 1 | 全部流水线产物对外开放、可回填 |
| **Phase 3（P2）** | 前端：创建面板模式选择 + 检查点详情页 + 协作 prompt 一键复制 | Phase 1/2 | 完整交互闭环 |
| **Phase 4（P3）** | 推广到 manuscript / poetry / anchor（MultiScene 统一检查点）；simple / simple_image 产物清单 | Phase 2 | 全部任务类型可用 |
| **Phase 5（P4）** | 协作 prompt 库整理进文档 + 示例视频教程 + 回归测试补充 | Phase 4 | 交付文档 |

---

## 十、风险与开放问题

| # | 问题 | 建议 |
|---|------|------|
| O1 | 产物被外部 Agent 直接改文件后，系统如何感知？是否做 mtime 自动检测？ | 第一期显式声明（用户点"已修改"）；mtime 检测列为增强项，需评估误判风险 |
| O2 | 检查点依赖图的重跑粒度（改 scenes 是否连 references 一起重跑？references 是 i2i 生成的尾帧，改了分镜确实应重跑） | 第一期按 §4.5 简化依赖图；`regen` 支持精确到单检查点 |
| O3 | 暂停等待期间 `sub_maker`（TTS cues）等内存态丢失，恢复后需重采（已有 `_recover_sub_maker`），但有额外 TTS 流量 | 接受；恢复时提示"字幕时间线重新校准" |
| O4 | 用户修改视频片段后音频/字幕重跑，可能出现片段替换导致时长变化 → 字幕偏移 | 依赖图强制 `videos` 修改后重跑 `audio+subtitle`；文档明示 |
| O5 | 并发槽位释放后恢复执行需重新排队，多任务下"继续"可能有等待 | 接受；前端显示排队状态；可配置不释放槽位（`manual_config.hold_slot`） |
| O6 | 手动模式 + 长任务（多场景）暂停点过多导致操作负担 | 默认仅暂停 `scenes` + `videos` + `subtitle` 三个高价值点，用户可增删 |
| O7 | `checkpoint.json` 中绝对路径在不同部署方式（本地/Docker）下对用户可见性问题 | Docker 部署时展示宿主机映射路径（`docker-run.sh` 已支持挂载数据目录） |

---

## 十一、验收标准（Phase 1 达成时的定义）

1. `POST /api/tasks/creative` 传 `execution_mode=manual` 创建任务后，流水线在 `scenes` 检查点暂停，
   状态为 `awaiting_user`，`current_checkpoint=scenes`，且不占用并发槽位。
2. `approve` 后任务恢复，`scenes` 检查点被跳过，进入 `references` 并再次暂停（默认全暂停点）。
3. `approve(modified_artifact_ids=["script"])` 后，`script.json` 修改生效：下游参考图/视频/音频/字幕/合成全部重跑，
   最终视频基于新分镜生成。
4. 修改后重跑时 `_recover_sub_maker` 生效，字幕时间线仍为 cue 精确对齐（非 legacy）。
5. 自动模式任务行为与 v5.0 完全一致（8 场景回归通过）。
6. 产物清单、MANIFEST.md、旁白 TXT 导出、示例 prompt 可一键复制。

---

## 十二、后续步骤

1. 本草案评审（确认检查点集合、依赖图、默认暂停点、开放问题取舍）。
2. 输出 `docs/plans/v6.0/system_design.md` 增量设计（模型/路由/流水线改动清单 + 迁移说明）。
3. 按 Phase 1 → 5 分期实施，每期按 `AGENTS.md` 验证清单自验。
