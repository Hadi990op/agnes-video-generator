# 字幕时间线对齐方案 v2.0（基于 edge_tts cues）

> **前身调研**：[m-bain/whisperX](https://github.com/m-bain/whisperX) v3.8.7（INTERSPEECH 2023）
> **目标**：用准确的时间线替换本项目自研的「音频↔字幕」启发式对齐逻辑
> **评估日期**：2026-07-23（v1.0）/ 2026-07-23（v2.0 重写）
> **评估人**：Senior Developer
> **结论摘要**：**充分利用 edge_tts 在合成期给出的词级 cues（音频真值时间线），把多段场景当前的均匀分配 + 0.8s 重叠补丁替换为 cues 驱动的精确对齐。WhisperX / 强制对齐器方案标记为「废弃」，本项目不涉及外部人声，无需听音对齐。**

---

## 〇、文档状态与废弃声明

| 版本 | 内容 | 状态 |
|------|------|------|
| v1.0（原 §三 / §六 / 附录 A·B） | WhisperX 集成 + 仿照实现轻量 ForcedAligner（`core/audio/aligner.py`、MMS-FA、`align_mode` 配置） | ⚠️ **废弃** — 仅保留为调研归档，不再实施 |
| **v2.0（本文件 §一~§七 / 附录 C）** | **基于 edge_tts cues 的精确时间线对齐（零新增依赖）** | ✅ **生效** — 唯一实施方向 |

**废弃理由（一句话）**：本项目的旁白音频全部由 edge_tts 生成，其 `WordBoundary` cues 就是该段音频的**源头真值**（合成期预测），精度上本就 ≥ 事后声学估计的 whisperX forced align；且项目**不涉及任何外部人声/上传音频**，whisperX 的转录、说话人分离、强制对齐能力 90% 以上用不到，反而引入 ~2.5GB 依赖与 Python 3.13 不兼容（P0）风险。因此「听音对齐」是过度设计，正确动作是**把现有 cues 用起来**。

---

## 一、背景与现状痛点

### 1.1 现状

本项目在 4 条流水线（Creative / Manuscript / Anchor / Poetry）中需要把 TTS 生成的音频与字幕做时间线对齐。当前机制的问题**不是「缺少对齐能力」，而是「已有能力在多段场景被丢弃」**：

| 问题 | 表现 | 根因（已坐实） |
|------|------|----------------|
| 多段场景词级对齐失效 | 段内字幕靠均匀分配 + 0.8s 重叠掩盖 | `generate_subtitles_common` 多段分支把 `sub_maker` 作为 `word_cues` 传给 `_generate_scene_aware_srt`，但**该函数从未读取 `word_cues` 计时**（`subtitle.py:388-509`），改用按句均匀分配 |
| 静音降级无对齐 | **音频关、字幕开**时字幕均匀分布跑偏（路径 B 见 §5.8 修正） | `text_to_srt` 按字符数估算（4 字/秒），与实际朗读无关；v2.0 默认改为 silent 也采集 cues（§5.8 路径 B），此行仅在 `harvest_cues_when_audio_off=False` 时触发 |
| 用 overlap 掩盖不同步 | 字幕前后段重叠 0.8s，常叠两条 | `_generate_scene_aware_srt` 兜底策略，治标不治本 |
| 突出时长启发式搅乱排期 | 短句 1.3x/1.5x 倍率 + 从邻句偷 20% | `subtitle.py:331-341, 479-484`，与均匀分配叠加后越偏 |

### 1.2 期望

让字幕时间戳贴合音频**真实发音位置**——而 edge_tts 在合成期已经算出了这个真实位置（cues），只需在字幕步骤正确使用它。

---

## 二、当前对齐机制梳理（参考）

### 2.1 核心代码路径

```
TTS 阶段    core/audio/tts.py::EdgeTTSEngine.generate()
            └─ edge_tts.Communicate.stream() → 收集 WordBoundary → SubMaker
            └─ 返回 (audio_path, sub_maker)   ← sub_maker.cues 即词级真值时间线

字幕生成    core/pipelines/__init__.py::BasePipeline.generate_subtitles_common()
            ├─ ffprobe 取实际音频时长
            ├─ 多段: _generate_scene_aware_srt()  ← ⚠️ word_cues 传入但未用，段内均匀分配
            ├─ 单段+有 cues: cues_to_srt() → _generate_fine_srt_from_word_cues()  ← ✅ 已用 cues
            ├─ 纯文本: text_to_srt()（4字/秒估算，SilentTTS 兜底）
            └─ enforce_max_lines() 后处理

合成阶段    core/compositor/concatenator.py::concat_videos_with_audio_overlay()
            └─ ffmpeg tpad/apad 补齐 + moviepy 叠加字幕（不变）
```

### 2.2 两条事实

1. **单段路径已正确用 cues**：`_generate_fine_srt_from_word_cues`（`subtitle.py:232-362`）把词级 cues 贪心分组为 ≤1.8s / ≤14 字的可读字幕段，时间全部取自 cues。这条路径质量不差。
2. **多段路径丢弃 cues**：`_generate_scene_aware_srt`（`subtitle.py:388-509`）签名带 `word_cues` 参数，但函数体从未引用它，改用「按句切分 → `usable_dur/seg_count` 均匀分配 → 0.8s 重叠」。creative/manuscript/anchor 全是多段，故主流场景实际跑的是启发式，而非 cues。

**→ 修复点明确且局部**：让多段路径也走 cues，复用 `_generate_fine_srt_from_word_cues` 的分组逻辑，仅替换「时间来源」与「场景时间轴映射」。

---

## 三、WhisperX 调研结论（⚠️ 废弃归档，不实施）

> 本节仅记录 v1.0 的调研，作技术归档。**结论：不采用。** 详见 §〇 废弃理由。

### 3.1 WhisperX 三大能力

| 能力 | 模型 | 对本项目相关性 |
|------|------|----------------|
| 批量转录 | Whisper large-v2 | ❌ 不需要（音频文本已知，且均为 edge_tts 生成） |
| 强制对齐 | wav2vec2 语言特定模型 | ⚠️ 仅当音频非 edge_tts 生成时需要；本项目无此场景 |
| 说话人分离 | pyannote v4 | ❌ 不需要（无外部人声，无多说话人外部音频） |

### 3.2 不采用的关键原因

1. **cues 即真值**：edge_tts `WordBoundary` 是合成期预测，贴合本项目生成的音频；whisperX forced align 是事后声学估计，对同一音频原则上不更准。
2. **Python 3.13 不兼容**（P0）：官方仅支持 3.9–3.12，直接 `pip install whisperx` 在 3.13 上原生扩展编译风险高。
3. **依赖膨胀**：~2.5GB（PyTorch + faster-whisper + pyannote），Docker 镜像 500MB→3GB。
4. **能力冗余**：转录 + 说话人分离对本项目 90% 以上无用。
5. **`whisperx.align()` 假设文本来自自身转录**，对「纯外部已知文本」支持不佳，需先转写再映射——而本项目文本=朗读内容，用 edge_tts cues 更直接。

原 v1.0 的 `core/audio/aligner.py` 骨架、`align_mode` 配置、附录 A/B 的采用导向**一律废弃**，不再实施。

---

## 四、场景可行性（v2.0 修订）

项目共 5 条流水线，4 条涉及字幕。全部音频均来自 edge_tts（无外部人声）：

| 场景 | Pipeline | 音频来源 | cues 可用性 | v2.0 方案 | 可行性 |
|------|----------|----------|-------------|-----------|--------|
| **S1 创意长视频** | CreativeVideoPipeline | edge_tts 整段 TTS | ✅ 整段 `sub_maker` | cues 驱动 + 场景映射 | ✅ 高 |
| **S2 稿件长视频** | ManuscriptVideoPipeline | edge_tts 整段 TTS | ✅ 整段 `sub_maker` | cues 驱动 + 场景映射 | ✅ 高 |
| **S3 数字人口播** | AnchorPipeline (post_stitch) | edge_tts 整段 TTS | ✅ 整段 `sub_maker` | cues 驱动 + 场景映射 | ✅ 高 |
| **S4 诗词视频** | PoetryVideoPipeline | edge_tts 逐场景 TTS | ✅ 逐场景 `sub_maker` | 逐场景 cues（已较优，微调） | ✅ 高 |
| **S5 简单视频** | SimpleVideoPipeline | 无 TTS | — | 无字幕 | ⏭️ 不涉及 |
| ~~S6 数字人(model模式)~~ | AnchorPipeline (model) | 视频模型生成（非 edge_tts） | ❌ 无 cues | **超出范围**：无外部音频处理需求，维持现状（跳过字幕） | ⛔ 不做 |

> **范围边界（明确）**：本项目**不涉及外部人声 / 上传音频 / 换 TTS 引擎**，因此一切「听音对齐 / 转录 / 说话人分离」能力均不在范围内。如遇此类需求，再单独评估（届时参考 §三 归档）。

> **关于「音频关、字幕开」配置**：详见 §5.8 路径 B。该配置下默认仍采集 edge_tts cues（仅丢弃音频字节），字幕享受与音频开模式同级的词级精度；仅当 `harvest_cues_when_audio_off=False` 时退回纯估算。

---

## 五、方案 v2.0：基于 edge_tts cues 的精确时间线对齐（✅ 生效）

### 5.1 核心原理

- **cues = 真值时间线**：edge_tts 在合成整段旁白时，逐词返回 `WordBoundary`（start/end）。这是该段音频的真实发音时间轴，精度由 TTS 引擎保证。
- **整段音频是连续时间轴**：成片按场景拼接，场景 `i` 在成片时间轴覆盖 `[scene_start_i, scene_start_i + dur_i)`。旁白音频从 `t=0` 连续播放，故「在成片时间 `t` 听到的词」=「cues 中 start≈t 的词」。
- **结论**：把每个 cue 按其时间归入对应场景，在场景内复用既有贪婪分组得到可读字幕段，再整体偏移 `scene_start_i`——即可让多段场景直接享受与单段路径同级的词级精度，**零新增依赖**。

### 5.2 数据流 / 架构

```
 _step_audio 决策（cues 采集与音频输出解耦 — 见 §5.8）
   ├─ audio_config.enabled=True
   │      → edge_tts.generate() → 落盘 audio.mp3 + sub_maker.cues
   ├─ audio_config.enabled=False 但 subtitle_config.enabled=True   ← 路径 B
   │      → edge_tts.harvest_cues() → 仅收集 sub_maker.cues（音频字节丢弃，不落盘）
   └─ 两者皆 False
   │      → SilentTTSEngine → (静音 mp3, sub_maker=None)
   │                                          │
   │                                          ▼
   └──────────────────► generate_subtitles_common(segment_texts, scaled_durations, sub_maker, ...)
                                      │
                    ┌─────────────────┴──────────────────┐
                    │  sub_maker 存在？（音频开 或 字幕-only 采集） │
                    ├──────────── 是（cues 路径）─┬──── 否（纯文本兜底）─┐
                    ▼                            ▼                       ▼
            num_segments>1?                num_segments>1?          text_to_srt()
            ├─ 是: generate_cue_aware_srt()  ├─ 是: _generate_scene_aware_srt()
            └─ 否: cues_to_srt()             └─ 否: (不适用)
                    │
                    ▼
      enforce_max_lines() + LLM/模板 样式（不变）
                    │
                    ▼
              full_subtitle.srt
```

### 5.3 关键改造点

| 改造 | 文件 | 说明 |
|------|------|------|
| 新增 `generate_cue_aware_srt()` | `core/audio/subtitle.py` | cues 驱动的多段字幕生成，替代 `_generate_scene_aware_srt` 的均匀分配 |
| 提取 `_group_items_to_srt()` | `core/audio/subtitle.py` | 从 `_generate_fine_srt_from_word_cues` 抽出「词→可读段」分组，单段/多段共用 |
| 多段分支切换 | `core/pipelines/__init__.py::generate_subtitles_common` | 有 cues → `generate_cue_aware_srt`；无 cues → 保留 legacy 兜底 |
| 配置开关 `use_cue_timeline` | `models/task.py::SubtitleConfig` | 默认 `True`；`False` 回退 legacy，便于灰度/回滚 |
| 移除 0.8s 重叠补丁 | `core/audio/subtitle.py` | 精确对齐后重叠仅作视觉缓冲（默认 0.12s，可调） |
| 新增 `EdgeTTSEngine.harvest_cues()` | `core/audio/tts.py` | 路径 B：消费完整合成 stream 收集 WordBoundary，丢弃音频字节，返回 `sub_maker.cues` |
| `_step_audio` 解耦改造 | 各 pipeline `_step_audio` | 判定从 `audio_config.enabled` 改为「audio 或 subtitle 开启即采集 cues」；audio 关 + 字幕开 → `harvest_cues`，不生成静音 mp3 |

### 5.4 算法设计

**场景归属**：两种策略，按可用性选择。

- **策略 A（推荐，文本锚定）**：`segment_texts` 是整段旁白按场景的有序子串。归一化拼接为 `full_norm`（去空格/标点），遍历 cues 累计归一化字符长度，为每个场景记录字符区间 `[c_start, c_end)`；每个 cue 按其字符中点落入的区间归属场景。**优点**：场景边界跟随实际朗读文本，免疫 TTS 在场景间插入的停顿漂移。
- **策略 B（兜底，时间区间）**：当 `segment_texts` 无法可靠还原为整段文本时，用 `scene_start_times`（由 `scaled_durations` 累加得到，和 cues 同处 0..actual_audio_dur 轴）做区间归属：`scene_start_i ≤ cue.start < scene_start_{i+1}`。

**段内分组**：对归属某场景的 cues 子集，调用 `_group_items_to_srt()`（复用现有贪心分组：≤1.8s / ≤14 字 / 自然停顿 >0.4s 断句），得到局部时间字幕段，再整体偏移 `scene_start_i`。**不跨场景分组**，避免一条字幕合并两个场景的词。

**残余归一化**：最后一条 cue 的 end 钳到真实音频时长（edge_tts cues 偶尔与音频长度有几十 ms 尾差，留白未覆盖）。

### 5.5 代码骨架

```python
# core/audio/subtitle.py（新增/重构）

@staticmethod
def _group_items_to_srt(
    items: List[Tuple[float, float, str]],
    max_duration: float = _MAX_SUB_DURATION,
    max_chars: int = _MAX_SUB_CHARS,
) -> str:
    """将 [(start_s, end_s, text), ...] 贪心分组为可读字幕段（SRT 字符串）。

    从 _generate_fine_srt_from_word_cues 抽出，单段/多段共用。
    分组约束：≤ max_duration 秒、≤ max_chars 字符、词间停顿 >0.4s 断句。
    保留既有的尾部合并与突出时长加成逻辑。
    """
    # ... 现有 _generate_fine_srt_from_word_cues 的分组体（232-362 行）平移至此 ...
    # 差异：入参从 word_cues 列表改为已规整的 items 三元组，去掉 _cue_total_seconds 转换


@staticmethod
def generate_cue_aware_srt(
    word_cues: object,               # edge_tts SubMaker（含 .cues）
    segment_texts: List[str],        # 各场景旁白文本（有序）
    scene_start_times: Optional[List[float]] = None,
    scene_durations: Optional[List[float]] = None,
    max_duration: float = _MAX_SUB_DURATION,
    max_chars: int = _MAX_SUB_CHARS,
    overlap_sec: float = 0.12,       # 仅视觉缓冲，不再掩盖不同步
) -> str:
    """基于 edge_tts 词级 cues 的精确时间线对齐字幕生成（替代 _generate_scene_aware_srt）。"""
    raw_cues = getattr(word_cues, "cues", None) or []
    if not raw_cues:
        return ""

    # 1) cues → (start, end, text) 三元组（音频时间轴）
    items = []
    for cue in raw_cues:
        s = SubtitleGenerator._cue_total_seconds(cue.start)
        e = SubtitleGenerator._cue_total_seconds(cue.end)
        t = (cue.content or "").strip()
        if t:
            items.append((s, e, t))
    if not items:
        return ""

    n = len(segment_texts)

    # 2) 计算每个场景的字符区间（策略 A：文本锚定，免疫停顿漂移）
    scene_char_ranges = SubtitleGenerator._scene_char_ranges(segment_texts)
    if scene_char_ranges is None:
        # 策略 B 兜底：时间区间（由 scaled_durations 累加得到）
        starts = scene_start_times or list(itertools.accumulate(
            (scene_durations or [0.0] * n), initial=0.0))[:-1]
        scene_char_ranges = None
        scene_starts = starts
    else:
        # 用 cues 累计归一化长度定位每个 cue 的字符中点
        norm_len = lambda x: len(re.sub(r"\s+|[^\w\u4e00-\u9fff]", "", x))
        cue_char_pos = []
        run = 0
        for _, _, t in items:
            run += norm_len(t)
            cue_char_pos.append(run)

    # 3) 逐场景归属 cues → 分组 → 偏移
    entries = []
    global_idx = 1
    for i in range(n):
        if scene_char_ranges is not None:
            c0, c1 = scene_char_ranges[i]
            scene_items = [it for it, cp in zip(items, cue_char_pos)
                           if c0 <= cp <= c1]
            offset = 0.0  # 文本锚定：cues 时间已是成片时间轴（音频从 0 连续）
        else:
            s0 = scene_starts[i]
            s1 = scene_starts[i + 1] if i + 1 < len(scene_starts) else items[-1][1] + 1.0
            scene_items = [it for it in items if s0 <= it[0] < s1]
            offset = s0

        if not scene_items:
            continue
        local_srt = SubtitleGenerator._group_items_to_srt(
            scene_items, max_duration=max_duration, max_chars=max_chars)
        for sub in srt.parse(local_srt):
            ns = sub.start + timedelta(seconds=offset)
            ne = sub.end + timedelta(seconds=offset)
            entries.append((global_idx, ns, ne, sub.content))
            global_idx += 1

    # 4) 小幅重叠（视觉缓冲）
    if overlap_sec > 0 and len(entries) > 1:
        for k in range(len(entries) - 1):
            _, s, e, t = entries[k]
            nxt = entries[k + 1][1]
            e2 = min(e + timedelta(seconds=overlap_sec), nxt)
            entries[k] = (entries[k][0], s, e2, t)

    entries.sort(key=lambda x: x[1])
    return "\n".join(
        f"{idx}\n{cue_to_srt_time(s)} --> {cue_to_srt_time(e)}\n{t}\n"
        for idx, s, e, t in entries)
```

> 注：`_scene_char_ranges()` 负责把 `segment_texts` 归一化拼接并算出每个场景的字符区间；若文本无法可靠还原（极少），返回 `None` 触发策略 B。该辅助函数与 `_group_items_to_srt` 的单元测试覆盖中英文、含数字/标点场景。

### 5.6 配置扩展

```python
# models/task.py::SubtitleConfig
class SubtitleConfig(BaseModel):
    enabled: bool = True
    style: SubtitleStyle = ...
    use_cue_timeline: bool = True               # ✅ 新增：True=启用 cues 精确对齐；False=回退 legacy
    harvest_cues_when_audio_off: bool = True    # ✅ 新增（路径 B）：音频关但字幕开时，仍采集 edge_tts cues（丢弃音频字节）；False=退回纯估算
```

> 不再需要 v1.0 的 `align_mode`（auto/forced_align/edge_tts/text）——只有 cues 一条路径，配置极简。

### 5.7 集成点改造

```python
# core/pipelines/__init__.py::generate_subtitles_common
# 多段 + 有 cues + 开关开启 → cues 精确对齐（替代 _generate_scene_aware_srt）
if (num_segments > 1
        and sub_maker is not None
        and getattr(subtitle_config, "use_cue_timeline", True)):
    srt_content = SubtitleGenerator.generate_cue_aware_srt(
        sub_maker,
        segment_texts=segment_texts,
        scene_start_times=scene_start_times,   # 由 scaled_durations 累加
        scene_durations=scaled_durations,
    )
# 多段无 cues → 保留 legacy 启发式兜底
elif num_segments > 1:
    srt_content = SubtitleGenerator._generate_scene_aware_srt(
        segment_texts, scaled_durations, word_cues=None)
# 单段 + 有 cues → 现有 cues_to_srt（不变）
elif sub_maker is not None:
    SubtitleGenerator.cues_to_srt(sub_maker, srt_path)
    srt_content = open(srt_path, encoding="utf-8").read()
# 纯文本（SilentTTS 等）→ 现有 text_to_srt（不变）
else:
    SubtitleGenerator.text_to_srt(full_text, srt_path, total_dur)
```

### 5.8 静音 / 字幕-only 模式（路径 B：cues 采集与音频输出解耦）

> **触发场景**：`audio_config.enabled=False` 且 `subtitle_config.enabled=True`（音频关、字幕开）。
> **结论**：路径 B 为默认推荐——即便不保留音频，也仍跑 edge_tts 采集 cues，让 silent 模式字幕享受与音频开模式同级的词级精度，零新增依赖。

#### 5.8.1 现状问题

当前 `audio_config.enabled=False` 时，`_step_audio` 走 `SilentTTSEngine`，返回 `sub_maker=None`（`tts.py:90-146`，注释明确「返回空 cues`）。`generate_subtitles_common` 因此拿到 `None`，多段走均匀分配、单段走 `text_to_srt`（4 字/秒）——即「音频关、字幕开」的字幕是**纯估算**，享受不到新方案精度（详见对话梳理：§5.2 数据流原分支、`__init__.py:238-268`）。

#### 5.8.2 核心设计：解耦「cues 采集」与「音频输出」

字幕只需要**时间线真值**，不需要**音频字节**。因此把 `_step_audio` 的判定从 `if audio_config.enabled` 改为：**只要 audio 或 subtitle 任一开启，就跑 edge_tts 采集 cues**；差异仅在是否把音频字节落盘。

```python
# core/pipelines/..._step_audio（改造后伪码）
audio_enabled = self._state.audio_config.enabled
subtitle_enabled = self._state.subtitle_config.enabled

sub_maker = None
if audio_enabled:
    # 音频开：落盘音频 + 采集 cues（现有逻辑不变）
    audio_path, sub_maker = await edge_tts.generate(text, combined_audio, voice, rate)
elif subtitle_enabled:
    # 路径 B（音频关、字幕开）：只采集 cues，丢弃音频字节，不生成静音 mp3
    sub_maker = await edge_tts.harvest_cues(text, voice, rate)
    # 最终视频无音频轨（has_audio = audio_config.enabled and bool(combined_audio) → False）
# 两者皆关：保持现状，sub_maker=None
```

#### 5.8.3 harvest_cues 实现（tts.py 新增）

```python
class EdgeTTSEngine:
    async def harvest_cues(
        self, text: str,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
    ) -> "edge_tts.SubMaker":
        """仅采集逐词时间戳，不生成/不落盘音频字节（路径 B）。

        edge_tts 的 WordBoundary 与音频数据交织于同一 stream，需消费完整 stream
        才能收齐全部 cues；本方法只把 WordBoundary/SentenceBoundary 喂给 SubMaker，
        音频数据直接丢弃。返回含 .cues 的 sub_maker，供 generate_cue_aware_srt 使用。
        """
        sub_maker = edge_tts.SubMaker()
        communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
        async for chunk in communicate.stream():
            if chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                sub_maker.feed(chunk)
        return sub_maker
```

#### 5.8.4 generate_subtitles_common 的承接

改造后 `sub_maker` 在「音频开」和「字幕-only」两种情况下都非 None，`generate_subtitles_common`（`__init__.py:177`）直接走 cues 路径（`generate_cue_aware_srt` / `cues_to_srt`），**无需为 silent 单独分支**。仅当 audio 与 subtitle 皆关时 `sub_maker=None` → `text_to_srt` 兜底（沿用 §5.7 末支）。

#### 5.8.5 时间轴与视频对齐说明

- cues-only 模式字幕时间轴沿用「合成音频轴」（`0..synth_dur`），与音频开模式一致；最终视频无音频轨，但 moviepy 叠加字幕独立于音频轨，故字幕正常显示。
- 若合成时长与视频总时长存在偏差，`generate_cue_aware_srt` 的残余归一化（最后 cue 钳制 + 可选整体缩放到视频时长，见 §5.4）保证字幕不超出视频范围。
- Poetry 逐场景 TTS：每场景独立 `harvest_cues`，各自生成 cues，逻辑与音频开模式对称，无需特殊处理（每场景 cues 时间轴即该场景本地轴，叠加 `scene_start_i` 偏移即可）。

#### 5.8.6 异常处理

- `harvest_cues` 失败（网络/限流）→ 抛出 `RuntimeError`，由各 pipeline 现有 `except` 捕获，回退 `SilentTTSEngine`（同现有 edge_tts 失败兜底），此时 `sub_maker=None` → 走 legacy 估算，保证流水线不中断。
- 若 `subtitle_config.use_cue_timeline=False`（灰度关闭），即便拿到 cues 也走 legacy（`__init__.py` 开关判定），与 §5.7 一致。

#### 5.8.7 收益、代价与可选开关

- **收益**：silent 模式字幕获得与音频开模式同级的词级精度，零新增依赖，且彻底消除「audio 关 → 字幕退化」的不一致。
- **代价**：silent 模式仍需一次 edge_tts 调用（网络/延迟）。若用户关音频纯粹为省 edge_tts，可经配置跳过 harvest（见下）。
- **可选开关**：在 `SubtitleConfig` 增加 `harvest_cues_when_audio_off: bool = True`；`False` 时 silent 模式退回纯估算（路径 A），供极致省成本场景使用。默认 `True`，即路径 B 生效。

### 5.9 分阶段实施计划

| 阶段 | 内容 | 验收标准 | 预估工作量 |
|------|------|----------|-----------|
| **P0 重构分组** | 从 `_generate_fine_srt_from_word_cues` 抽出 `_group_items_to_srt(items, ...)`，单段路径改用之，行为不变 | 单段视频字幕与改造前逐字节一致 | 0.5 天 |
| **P1 cues 多段对齐（核心）** | 实现 `generate_cue_aware_srt` + `_scene_char_ranges`，多段分支切换 | 多段视频词级字幕误差 < 200ms（相对朗读位置） | 1-2 天 |
| **P1.5 静音/字幕-only 解耦（路径 B）** | `EdgeTTSEngine.harvest_cues` + 各 `_step_audio` 判定解耦；silent 模式采集 cues 不落音频 | 「音频关、字幕开」字幕与音频开模式同级精度；无音频轨不报错 | 0.5-1 天 |
| **P2 配置与回滚** | `SubtitleConfig.use_cue_timeline` + `harvest_cues_when_audio_off`，默认开启；`False` 回退 legacy | 两开关关闭时行为与旧版一致 | 0.5 天 |
| **P3 边界与降级** | 场景归属策略 B（时间区间）兜底、最后 cue 钳到音频时长、SilentTTS 失败回退、poetry 逐场景微调 | 4 条流水线 + 关闭开关全回归通过 | 1 天 |
| **P4 清理废弃** | 删除 v1.0 的 `aligner.py` 计划相关内容、`align_mode` 残留；更新文档指向本方案 | 无死代码、文档一致 | 0.5 天 |

> 总工作量约 **4–5.5 天，零新增依赖**（新增 P1.5 为路径 B 专属，约 0.5-1 天）。

---

## 六、测试与验证计划

### 6.1 对齐精度对比（cues vs legacy）

| 用例 | 文本特征 | 预期 |
|------|----------|------|
| 纯中文短句 | "今天天气真好" | cues 与 legacy 接近，但 cues 贴合发音 |
| 含数字 | "2024 年增长 15.6%" | cues 精确；legacy 均匀分配跑偏 |
| 中英混排 | "使用 GPT-4 模型" | cues 在词边界对齐；legacy 漂移 |
| 长句含标点 | "你好，世界！今天很热。" | cues 捕捉真实停顿；legacy 均匀分布 |
| 多段场景 | 3+ 场景连续旁白 | **核心验收**：cues 方案各场景字幕跟随朗读，无 0.8s 重叠叠加；legacy 有明显不同步 |

**指标**：字幕段 start 与朗读真实位置的 MAE，目标 < 200ms（相对 legacy 的「段内匀速」应有显著改善）。

### 6.2 回归测试

- 复用 `docs/regression_test_plan.md` 10 场景，验证 4 条流水线字幕功能不退化
- 新增 `tests/test_cue_aware_srt.py`：分组逻辑、场景归属（策略 A/B）、边界钳制、开关关闭回退
- 新增 silent/字幕-only（路径 B）用例：`audio_config.enabled=False, subtitle_config.enabled=True` → 字幕与音频开模式同级精度；`harvest_cues_when_audio_off=False` → 退回估算；`harvest_cues` 失败 → 回退 `SilentTTSEngine` 不中断
- 单段路径与改造前产物 diff 一致性测试

### 6.3 性能

- cues 路径零额外计算（cues 已在 TTS 阶段算好），仅做列表映射 + 分组，开销可忽略
- 不影响生成总时长

---

## 七、结论与建议

### 7.1 核心结论

1. **cues 即真值**：edge_tts 词级 cues 是本项目生成音频的源头时间线，多段场景当前只是没用它。
2. **正确动作是「用起来」，不是「换引擎」**：把 cues 接通到多段路径，复用单段路径已验证的分组逻辑，即可让 4 条流水线统一获得词级精度。
3. **WhisperX / 强制对齐器方案废弃**：项目无外部人声，听音对齐属过度设计，且带来 Python 3.13 不兼容与 ~2.5GB 依赖风险。
4. **零新增依赖、约 3.5–5 天**：性价比远高于任何引入对齐器的方案。

### 7.2 实施建议

- **优先级**：先做 P0（分组重构，零风险）→ P1（cues 多段对齐，核心收益）→ P1.5（silent/字幕-only 解耦，路径 B）→ P2（开关/回滚）→ P3（边界降级）→ P4（清理废弃）。
- **灰度**：通过 `use_cue_timeline` + `harvest_cues_when_audio_off` 双开关逐步放量，异常即回退 legacy，不影响线上。
- **路径 B 默认开启**：silent/字幕-only 模式通过 `harvest_cues_when_audio_off=True` 默认采集 cues，消除「audio 关 → 字幕退化」的不一致；极致省成本（连 edge_tts 都不想跑）场景可关闭退回纯估算。
- **范围纪律**：外部人声 / 上传音频 / 换 TTS 引擎需求出现前，不引入任何声学对齐依赖（届时参考 §三 归档重新评估）。

### 7.3 风险提示

- edge_tts `WordBoundary` 在 6.x/7.x 分支与 raw-cue 兜底（subtitle.py:538-582）下本身可能静默降级——`generate_cue_aware_srt` 在 `raw_cues` 不足时自动返回空，由调用方回退 legacy，保证兼容。
- 文本锚定（策略 A）依赖 `segment_texts` 能还原为整段旁白；若流水线对文本做了不可逆变换，自动降级策略 B（时间区间）。
- 个别语言/版本 cues 粒度偏粗时，`_MIN_WORD_CUES_FOR_FINE=6` 阈值已屏蔽空洞字幕，沿用即可。
- 路径 B（silent 采集 cues）依赖一次 edge_tts 调用；若用户对 silent 模式延迟敏感，经 `harvest_cues_when_audio_off=False` 退回估算即可，不影响正确性。`harvest_cues` 失败时由 pipeline 现有 `except` 捕获并回退 `SilentTTSEngine`（同音频开模式的 edge_tts 失败兜底）。

---

## 附录 A（⚠️ 废弃）：WhisperX 关键 API 速查

> 仅技术归档，不实施。

```python
import whisperx
model_a, metadata = whisperx.load_align_model(language_code="zh", device="cpu")
result = whisperx.align(segments=[{"text": "已知文本"}], align_model=model_a,
                        align_language_metadata=metadata, audio=audio_array, device="cpu")
# result["segments"][0]["words"] = [{"word": "...", "start": 0.1, "end": 0.3}, ...]
```

## 附录 B（⚠️ 废弃）：torchaudio forced_align 方案骨架（v1.0）

> 仅技术归档，不实施。原 `core/audio/aligner.py`（ForcedAligner + MMS-FA）方案已废弃，理由见 §〇。

```python
# —— 以下内容 v2.0 起不再新建 ——
# bundle = torchaudio.pipelines.MMS_FA
# model = bundle.get_model(); tokenizer = bundle.get_tokenizer(); aligner = bundle.get_aligner()
# emissions, _ = model(waveform)
# alignment, scores = F.forced_align(emissions[0], token_ids, blank=0)
```

## 附录 C：相关文件清单（v2.0）

| 文件 | 作用 | 改造类型 |
|------|------|----------|
| `core/audio/subtitle.py` | 字幕生成 | **改造**：抽 `_group_items_to_srt`；新增 `generate_cue_aware_srt` / `_scene_char_ranges`；多段分支切换；重叠降级 |
| `core/pipelines/__init__.py` | `generate_subtitles_common` | **改造**：多段有 cues → `generate_cue_aware_srt` |
| `models/task.py` | `SubtitleConfig` | **改造**：新增 `use_cue_timeline: bool = True` |
| `tests/test_cue_aware_srt.py` | 新增：cues 对齐测试 | **新建** |
| `docs/whisperx_alignment_evaluation.md` | 本方案文档 | **重写**（v2.0） |
| ~~`core/audio/aligner.py`~~ | v1.0 ForcedAligner | ⚠️ **废弃，不再新建** |
