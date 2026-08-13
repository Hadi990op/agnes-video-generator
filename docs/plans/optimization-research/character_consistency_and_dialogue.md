# R1 角色一致性增强 + 对话（对白）支持

> **状态**：🔍 待调研（暂缓执行，本波不做）
> **归档日期**：2026-08-13
> **来源**：优化路线图原第 6 点，抽出存档
> **对应 `optimization-research/README.md` 索引**：R1

---

## 一、主题

提高创意 / 稿件长视频的叙事能力：

- **角色一致性**：多场景同一角色保持外观稳定；
- **对话支持**：分镜脚本中输出角色台词，旁白 TTS 与角色对白（可用不同音色/语气）区分。

## 二、现状盘点（实代码对照）

### 角色一致性 —— 已建成三层，非空白

| 层 | 现状实现 | 效果 |
|---|---------|------|
| 提示词层 | `core/screenwriter/characters.py:13` `extract_character_description()`（角色参考图 prompt）、`get_character_appearance()`（固定外貌串，程序化拼入尾帧 prompt，见 `steps_frames.py:255`、`steps_video.py:440`）| 已生效 |
| independent 模式 | 每场景提交均传角色参考图 `[character_ref_path]`（`steps_video.py:178`）| 已生效 |
| keyframes 模式 | 多图 i2i 引导：角色图锁身份 + 上一场景尾帧锁环境（`steps_frames.py:265-269`）+ `[PRESERVE]/[CHANGE]` 硬约束程序化注入 | 已生效 |

### 角色一致性 —— 唯一缺口

**chained 模式**（`steps_video.py:243,286`）：`current_image` 逐场景传**上一场景的 `last_frame`**，不传角色参考图。多轮 i2v 身份漂移会累积。可增强为双图提交 `[last_frame, character_ref]`（`submit_video` 已支持多参考图数组）。

### 对话支持 —— 完全空白

- 剧本侧：`core/screenwriter/story.py` `generate_script()` 只产出"场景描述 → 尾帧 prompt"，**无结构化对白段**。
- 语音侧：`story.py:432` `generate_narration_for_video()` 生成**一整条连续旁白**，字幕全部来自旁白。
- 音色侧：`core/audio/tts.py` EdgeTTSEngine 已支持任意音色 + `rate`（±30%），`models/task.py` 音频配置支持多音色。

## 三、拟增强内容（若实施）

### 3.1 对角支持（核心增量，功能空白）

1. **数据结构**：`core/screenwriter/story.py` 生成剧本时增加结构化对白段
   ```json
   {"speaker": "...", "dialogue": "..."}
   ```
2. **音频阶段**：`core/pipelines/creative/steps_audio.py` 将对白与旁白**分开走 TTS**：
   - 对白使用配置的第二音色（或同音色不同 `rate`）；
   - 合并进同一 SRT 时间线；
   - 影视化：旁白男声 + 对白女声等 `voice` 差异化。

### 3.2 角色一致性增强（边际优化）

chained 模式改双图提交 `[last_frame, character_ref]`（`steps_video.py:286`），抑制身份漂移；统一外观串缓存避免每次重算。

### 3.3 涉及文件（预估）

| 文件 | 改动 |
|------|------|
| `core/screenwriter/story.py` | 剧本结构化对白段 |
| `core/screenwriter/characters.py` | 角色外观统一串产出与透传 |
| `core/pipelines/creative/steps_video.py` | chained 双图 + 角色参考图跨场景透传 |
| `core/pipelines/creative/steps_audio.py` | 旁白/对白分离 TTS + 合并时间线 |
| `models/task.py` | 音色 / 对白配置字段 |
| `static/index.html` | 可选音色配置项 |

### 3.4 依赖变化

无（edge_tts 免费，无需 API Key；参考图归一化是前置项，见 roadmap 第 2 项）。

## 四、预判效果与代价

| 子项 | 效果 | 代价 |
|------|------|------|
| 角色一致性增强 | ⭐ 边际提升。现状已较完善，剩余是"chained 补漂移 + 外观串缓存"，视觉提升不明显 | 改动小，回归面小 |
| 对角支持 | ⭐⭐⭐ 从"旁白朗读纪录片"跃升为"可对话短剧"，用户可感知的新能力 | 实质改动：时间线多段混合、SRT 混排、TTS 多角色，回归面大 |

### 硬限制（未实施的关键原因）

1. **模型能力天花板**：Agnes 视频模型对参考图身份保持力有限，多轮走样是模型固有限制，prompt/参考图侧优化收益边际递减。
2. **口型同步缺口（对话支持的核心阻碍）**：普通视频 clip 无真实口型。对白只体现在音频+字幕层，画面张嘴不对 → "配音感"明显。仅侧影 / 无正脸特写场景可用。真口型需 anchor（模型音频）模式，但那是数字口播非叙事镜头。
3. **免费模型 + TTS 限制**：多角色 TTS 免费但表现统一，效果上限低于专业配音。

## 五、验收标准参考（若后续转入可执行）

1. 多场景创意视频中，指定角色在 ≥3 个场景外观基本一致（目测）。
2. 剧本含对白时，SRT 同时包含旁白与对白且时间不冲突；对白落在对应场景视频段内。
3. 对白场景需侧影/无正脸特写（规避口型问题）。
4. 未配置对白/第二音色的任务与现状行为完全一致（向后兼容）。