# 产物规范（Artifact Standard）— v5.x

> **定位**：定义任务中间产物的**统一规范**（格式、命名、存储位置、可修改性、外部工具协作协议），
> 是 v6.0「手动模式」checkpoint 机制（`docs/plans/v6.0/manual_mode_PRD.md`）的数据基础。
> 本文档描述的准备工作已在 v5.x 落地；v6.0 直接复用，不再重复建设。
>
> **配套实现**：`core/artifacts.py`（产物注册表 + manifest 生成）· `web/routes/video_routes.py`（产物端点）
> · `BasePipeline._save_narration_txt`（旁白纯文本导出）· `web/deps.py`（manifest 自动落盘）。

---

## 1. 目标

让所有中间产物**对用户与外部工具透明、可读、可改、可回填**：

1. 固定目录结构 + 固定文件名，不随机化。
2. 开放文本格式（UTF-8 / JSON indent=2 / 标准 SRT）。
3. 每个任务自动生成**产物清单**（`manifest.json`）与**目录说明**（`MANIFEST.md`）。
4. 通过 API 暴露产物相对路径、字段说明（`schema_hint`）、预览 URL。
5. 外部 Agent（opencode / workbuddy 等）或手动工具（ffmpeg / Python）可依据规范直接处理产物。

---

## 2. 目录与文件规范

### 2.1 目录结构

```
workspaces/<ws>/<YYYYmmdd_HHMMSS>_<task_id>/
├── task_state.json          # 任务状态（既有）
├── manifest.json            # 产物清单（自动生成，本规范新增）
├── MANIFEST.md              # 目录说明（自动生成，本规范新增）
├── story.txt                # 故事（creative）
├── script.json              # 分镜脚本（creative）
├── prompts.json             # 各步骤 prompt 记录
├── character_reference.png  # 角色参考图
├── combined_narration.mp3   # 配音音频（creative）
├── combined_narration.txt   # 旁白纯文本（导出，本规范新增）
├── full_narration.mp3       # 配音音频（manuscript / anchor）
├── full_narration.txt       # 读稿纯文本（导出，本规范新增）
├── full_subtitle.srt        # 字幕（manuscript / anchor）
├── narration.txt            # 全篇朗诵纯文本（poetry，导出）
├── scene_{i}/               # 场景 i（creative / poetry）
│   ├── video.mp4            # 场景视频
│   ├── task.json            # video_id 缓存
│   ├── curl.sh              # 查询 curl 命令
│   └── end_frame.png        # 尾帧图
└── final_video.mp4          # 最终成片
```

### 2.2 文件格式约定

| 类别 | 格式 |
|------|------|
| 文本（TXT） | UTF-8 无 BOM |
| JSON | UTF-8、`indent=2`、`ensure_ascii=False` |
| 字幕（SRT） | 标准 SubRip，UTF-8，序号连续 |
| 图片 | PNG（覆盖上传兼容 jpg/png/webp） |
| 视频 | MP4（H.264 + AAC） |
| 音频 | MP3 |

---

## 3. 产物清单 manifest.json

**生成时机**：任务运行开始与结束时自动落盘（`web/deps.py::run_pipeline`）；
也可通过 `GET /api/tasks/{id}/manifest` 现场构建（旧任务 / 排队中任务）。

**结构**：

```json
{
  "format_version": "1.0",
  "task_id": "abc123",
  "task_type": "creative",
  "task_status": "running",
  "dir_name": "20260813_000000_abc123",
  "working_dir": "/workspaces/ws1/20260813_000000_abc123",
  "artifacts": [
    {
      "artifact_id": "creative:script",
      "name_key": "artScript",
      "category": "json",
      "scope": "task",
      "scope_index": null,
      "path": "script.json",
      "exists": true,
      "size": 5120,
      "editable": true,
      "schema_hint": "分镜脚本 JSON 数组……字段：scenes[].scene_prompt=画面描述；……",
      "generated_by_step": "script",
      "preview_url": "/api/tasks/abc123/artifacts/creative:script/file"
    }
  ],
  "files": [
    { "path": "scene_0/video.mp4", "size": 1024000 }
  ]
}
```

字段说明：

| 字段 | 含义 |
|------|------|
| `artifacts` | **结构化产物**（creative / manuscript / anchor 有定义；simple / poetry 为空，由 `files` 兜底） |
| `files` | **通用文件树**：任务目录全部文件（相对路径 + 大小），任何任务类型均有 |
| `schema_hint` | 人类可读字段说明，供外部 Agent / 工具处理该产物 |
| `preview_url` | 产物预览/下载端点 |
| `editable` | 是否可修改（文本/JSON/SRT 可编辑，图片/视频/音频可覆盖替换） |

---

## 4. 目录说明 MANIFEST.md

任务目录根部的说明文件，供用户与外部 Agent 直接阅读。包含：

- 任务信息（ID / 类型 / 状态 / 工作目录绝对路径）
- 产物清单表（相对路径 / 类别 / 说明）
- 目录文件树
- 协作提示（如何修改、如何回填）

---

## 5. 旁白纯文本导出

所有带旁白/读稿的流水线在音频步骤导出**同名 .txt**：

| 流水线 | 音频 | 导出 TXT |
|--------|------|---------|
| creative | `combined_narration.mp3` | `combined_narration.txt` |
| manuscript | `full_narration.mp3` | `full_narration.txt` |
| anchor | `full_narration.mp3` | `full_narration.txt` |
| poetry | 逐场景 `scene_{i}/narration.mp3` | `narration.txt`（全篇拼接） |
| multi_scene 通用 | `combined_narration.mp3`（可覆写） | 同名推导 |

实现：`BasePipeline._save_narration_txt(text, audio_path)`，空文本跳过。

---

## 6. API 暴露

| 端点 | 说明 |
|------|------|
| `GET /api/tasks/{id}/artifacts` | 产物列表；新增返回 `file_relpath` / `schema_hint` / `preview_url` / `dir_name` |
| `GET /api/tasks/{id}/manifest` | 产物清单（JSON） |
| `GET /api/tasks/{id}/manifest.md` | 目录说明（Markdown） |
| `GET /api/tasks/{id}/artifacts/{artifact_id}/file` | 产物预览/下载（既有） |

---

## 7. 外部工具协作协议

1. 文本 / JSON / SRT：直接修改同名文件或编辑器编辑，回填后触发下游重跑。
2. 图片 / 视频 / 音频：用 ffmpeg / Python 等处理后**覆盖同名文件**，或走产物上传替换。
3. 修改 JSON 仅改动指定字段，保持 UTF-8 + indent=2。
4. 修改后受影响的下游步骤按「产物级联规则」（`core/artifacts.py::get_cascade_plan`）重跑。
5. 示例协作 Prompt 见 `docs/plans/v6.0/manual_mode_PRD.md` §七（v6.0 交付时落地到前端一键复制）。

---

## 8. 与 v6.0 手动模式的关系

v6.0 检查点机制在产物规范之上新增：

- `checkpoint.json`（按检查点聚合产物清单，数据源即 `manifest.json`）
- 暂停 / 审批逻辑（`AWAITING_USER` 状态 + approve/regen 端点）
- 产物回填校验

产物规范本身（本文件）已在 v5.x 完成，v6.0 无需重复建设。
