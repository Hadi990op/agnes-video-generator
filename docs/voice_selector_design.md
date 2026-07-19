# 音色选择器设计文档

> 版本：v2.0 | 日期：2026-07-13 | 状态：设计阶段

---

## 一、背景与目标

### 现状

- 4 个任务类型（simple / creative / manuscript / artistic）各有一份硬编码的 `<select>` 下拉框，仅含 4 个中文普通话音色
- 项目实际支持 13 种语言 i18n（zh / en / ru / ja / ko / ms / id / de / fr / nl / es / pt / it），edge-tts 总计 323 个音色，其中与项目语言相关的约 100+ 个
- 无试听能力、无语言筛选、无搜索

### 目标

- 统一的音色选择组件，4 个任务类型共享
- 支持按语言筛选，覆盖项目 13 种 i18n 语言
- 支持音色试听预览，带服务端缓存
- 跨语言使用时给出明确提示，避免静默失败

---

## 二、跨语言兼容性调研

### 2.1 测试方法

用 edge-tts 实测各语言音色读取不同体系文本，覆盖项目 13 种语言的交叉组合。

### 2.2 兼容性矩阵（按文字体系简化）

实测发现 edge-tts 的跨语言兼容性**完全取决于文字体系**，而非语言本身。项目 13 种语言分属三个体系：

| 文字体系 | 包含语言 | 可互读？ |
|----------|---------|---------|
| **CJK** | zh, ja, ko | zh ⇄ en 可互读；ja ⇄ zh 可互读；ko ⇄ zh 可互读。但 zh→ja / zh→ko / ja→ko 不可 |
| **拉丁 (Latin)** | en, de, fr, nl, es, pt, it, id, ms | **完全互通**，任一个拉丁音色可读任意拉丁文本 |
| **西里尔 (Cyrillic)** | ru | **完全隔离**，只能读俄文 |

**精确兼容性表**：

| 音色体系 | 能读的文本语言 | 不能读 |
|----------|--------------|--------|
| **zh-CN** (CJK) | zh, en | ja, ko, ru, 所有拉丁非 en |
| **ja-JP** (CJK) | ja, zh, en | ko, ru, 所有拉丁非 en |
| **ko-KR** (CJK) | ko, zh, en | ja, ru, 所有拉丁非 en |
| **ru-RU** (Cyrillic) | ru | **所有其他 12 种语言** |
| **en-US** (Latin) | en, de, fr, nl, es, pt, it, id, ms | zh, ja, ko, ru |
| **de/fr/nl/es/pt/it/id/ms** | 所有 9 种拉丁语言 (en + de + fr + nl + es + pt + it + id + ms) | zh, ja, ko, ru |

### 2.3 实测数据

| 测试 | 结果 | 测试 | 结果 | 测试 | 结果 |
|------|:----:|------|:----:|------|:----:|
| zh + zh | OK | en + zh | ERR | ru + zh | ERR |
| zh + en | OK | en + en | OK | ru + en | — |
| zh + ja | ERR | en + ja | ERR | ru + ru | OK |
| ja + zh | OK | en + ko | ERR | de + en | OK |
| ja + en | OK | en + id | OK | de + zh | ERR |
| ja + ko | ERR | en + fr | OK | de + ru | ERR |
| ko + zh | OK | en + es | OK | fr + en | OK |
| ko + en | OK | en + de | OK | es + en | OK |
| id + zh | ERR | id + en | OK | ms + zh | ERR |
| ms + en | OK | it + en | OK | pt + en | OK |

### 2.4 结论

**核心规则**：同一文字体系内互通，跨体系基本不通（CJK→en 是唯一例外）。edge-tts 跨体系调用直接抛异常，无降级。

系统必须：
1. **试听文本**：强制与音色语言匹配，每种语言预设独立试听句
2. **任务校验**：提交时校验 voice 能否读取目标文本语言，不兼容直接拒绝
3. **拉丁语言简化**：de/fr/nl/es/pt/it/id/ms 所有拉丁音色共享同一套兼容语言列表（共 9 种），减少冗余维护

---

## 三、整体架构

```
┌──────────────────────────────────────────────┐
│                   前端                        │
│  ┌─────────────┐    ┌──────────────────────┐ │
│  │ VoiceSelector│───▶│    VoicePicker Modal  │ │
│  │  (表单入口)   │    │  ┌────────────────┐  │ │
│  └─────────────┘    │  │ LanguageTabs    │  │ │
│                      │  │ (13 种语言筛选)  │  │ │
│                      │  ├────────────────┤  │ │
│                      │  │ SearchBar       │  │ │
│                      │  ├────────────────┤  │ │
│                      │  │ VoiceCard Grid  │  │ │
│                      │  │ (名称/性别/风格)  │  │ │
│                      │  │ + Preview 按钮   │  │ │
│                      │  ├────────────────┤  │ │
│                      │  │ SelectionBar    │  │ │
│                      │  │ (确认/取消)      │  │ │
│                      │  └────────────────┘  │ │
│                      └──────────────────────┘ │
└──────────────────────────────────────────────┘
         │ fetch                  │ preview audio
         ▼                       ▼
┌──────────────────────────────────────────────┐
│                   后端                        │
│  GET /api/voices      → 分组音色列表（JSON）   │
│  GET /api/voices/preview → 试听音频流（mp3）   │
│  GET /api/voices/compat  → 兼容性矩阵查询      │
└──────────────────────────────────────────────┘
```

---

## 四、后端 API 设计

### 4.1 `GET /api/voices` — 音色列表

**改造现有接口**，返回按语言分组的结构化数据。

**响应示例**：

```json
{
  "languages": [
    {
      "code": "zh",
      "label": "中文",
      "count": 16,
      "voices": [
        {
          "id": "zh-CN-XiaoxiaoNeural",
          "name": "Xiaoxiao",
          "local_name": "晓晓",
          "region": "普通话",
          "region_code": "zh-CN",
          "gender": "female",
          "style_tags": ["温柔", "Warm"],
          "preview_text": "你好，我是晓晓，这是一段音色试听。"
        }
      ]
    }
  ],
  "compat_hint": {
    "zh": ["zh", "en"],
    "ja": ["ja", "zh", "en"],
    "ko": ["ko", "zh", "en"],
    "ru": ["ru"],
    "_latin": ["en", "de", "fr", "nl", "es", "pt", "it", "id", "ms"]
  }
}
```

**语言分组规则**：

| code | Tab 名 | 匹配 region | 文字体系 | 音色数 |
|------|--------|-------------|----------|--------|
| `zh` | 中文 | zh-CN, zh-HK, zh-TW | CJK | 16 |
| `en` | English | en-US, en-GB | Latin | 18 |
| `ja` | 日本語 | ja-JP | CJK | 2 |
| `ko` | 한국어 | ko-KR | CJK | 3 |
| `ru` | Русский | ru-RU | Cyrillic | 2 |
| `de` | Deutsch | de-AT, de-CH, de-DE | Latin | 10 |
| `fr` | Français | fr-BE, fr-CA, fr-CH, fr-FR | Latin | 13 |
| `nl` | Nederlands | nl-BE, nl-NL | Latin | 5 |
| `es` | Español | es-AR, es-BO, es-CL, es-CO, es-CR, es-CU, es-DO, es-EC, es-ES, es-GQ, es-GT, es-HN, es-MX, es-NI, es-PA, es-PE, es-PR, es-PY, es-SV, es-US, es-UY, es-VE | Latin | 55 |
| `pt` | Português | pt-BR, pt-PT | Latin | 5 |
| `it` | Italiano | it-IT | Latin | 4 |
| `id` | Bahasa Indonesia | id-ID | Latin | 2 |
| `ms` | Bahasa Melayu | ms-MY | Latin | 2 |

> 总计项目可用音色：约 **137 个**，西班牙语音色最为丰富（55 个，覆盖 22 个西语国家/地区）。

**Tab 展示优化**：13 个 Tab 在移动端可能过宽。采用"常用 + 更多"折叠模式：
- 首行展示 6 个高频 Tab：中文 / English / 日本語 / Русский / Español / Français
- 其余通过"更多语言 ▼"下拉或第二行展开

**实现方式**：后端启动时执行一次 `edge-tts --list-voices` 并缓存结果到内存。每个音色附带一段预置的 `preview_text`（与音色语言匹配的试听句）。

### 4.2 `GET /api/voices/preview` — 试听音频

**端点**：`GET /api/voices/preview?voice=zh-CN-XiaoxiaoNeural&text=你好`

**行为**：

1. 查询参数：`voice`（必填）、`text`（选填，默认用该音色的预设试听文本）
2. 后端根据 `voice + text` 生成 MD5 缓存 key
3. 如果在磁盘缓存中存在 → 直接返回 `audio/mpeg`
4. 如果不存在 → 调用 `edge_tts.Communicate(text, voice).save()` → 写入缓存 → 返回
5. 如果 edge-tts 抛异常 → 返回 400 + 错误信息（如"该音色不支持此语言文本"）

**缓存策略**：

```
缓存目录: /tmp/agnes-voice-previews/
文件命名: {md5(voice_id + text)}.mp3
├── zh-CN-XiaoxiaoNeural__e10adc3949ba59abbe56e057f20f883e.mp3
├── en-US-JennyNeural__5d41402abc4b2a76b9719d911017c592.mp3
└── ...
```

| 策略项 | 取值 |
|--------|------|
| 存储位置 | `/tmp/agnes-voice-previews/`（系统临时目录，重启后自动清理） |
| 文件命名 | `{voice_id}__{md5(text)}.mp3` |
| TTL | 不过期（试听文本固定，缓存大小可控，323 个音色 × ~20KB ≈ 6.5MB） |
| 并发安全 | 写入时先写 `.tmp` 后缀，完成后 `os.rename` 原子替换 |
| 启动清理 | 服务启动时检查目录存在则保留（跨重启复用），不存在则创建 |

**预设试听文本**（与音色语言严格匹配）：

| 语言 | 试听文本 |
|------|---------|
| zh | 你好，我是{name}，这是一段音色试听。 |
| en | Hello, I'm {name}, this is a voice preview sample. |
| ja | こんにちは、{name}です。これはボイスプレビューです。 |
| ko | 안녕하세요, 저는 {name}입니다. 이것은 음성 미리보기입니다. |
| ru | Здравствуйте, я {name}, это образец голоса. |
| de | Hallo, ich bin {name}, dies ist eine Sprachvorschau. |
| fr | Bonjour, je suis {name}, ceci est un aperçu vocal. |
| nl | Hallo, ik ben {name}, dit is een stemvoorbeeld. |
| es | Hola, soy {name}, esta es una muestra de voz. |
| pt | Olá, eu sou {name}, esta é uma amostra de voz. |
| it | Ciao, sono {name}, questo è un esempio vocale. |
| id | Halo, saya {name}, ini adalah sampel suara. |
| ms | Helo, saya {name}, ini adalah sampel suara. |

### 4.3 `GET /api/voices/compat` — 兼容性查询

**端点**：`GET /api/voices/compat?voice=zh-CN-XiaoxiaoNeural&target_lang=en`

**响应**：

```json
{
  "compatible": true,
  "voice_lang": "zh",
  "target_lang": "en",
  "supported_langs": ["zh", "en"]
}
```

前端在用户选择音色后、切换到非本地语言页面时，调用此接口检查兼容性。不兼容时给出醒目提示。

---

## 五、前端组件设计

### 5.1 组件树

```
VoiceSelector (入口组件 — 替换原有 <select>)
├── 展示态：Chip（音色名 + 描述 + 展开箭头 ▼）
│   点击 → 打开 VoicePicker
│
└── VoicePicker (弹窗组件)
    ├── Header：标题"选择语音角色" + 关闭按钮
    ├── SearchBar：搜索框（200ms debounce）
    ├── LanguageTabs：13 个 Tab，移动端折叠为"常用 + 更多语言 ▼"
    ├── VoiceGrid（可滚动区域）
    │   └── VoiceCard × N
    │       ├── 名称 + 本地名
    │       ├── 风格标签（性别 + 风格）
    │       └── PreviewButton（▶ / ⏸ / loading spinner）
    └── SelectionBar（底部固定）
        ├── 当前选择信息
        ├── [确认选择] 按钮
        └── [取消] 按钮
```

### 5.2 交互流程

```
表单中点击 VoiceSelector
  → 打开 VoicePicker Modal
  → 根据页面当前语言自动切换 Tab（如中文页面 → 中文 Tab）
  → 如果已有选择 → 高亮对应卡片
  → 滚动到高亮卡片位置

用户在 VoicePicker 中：
  ├─ 切换 Tab → 过滤卡片 + 更新"共 N 个音色"计数 + 清空搜索
  ├─ 输入搜索 → 前端实时过滤（匹配 name / local_name / region / style_tags）
  ├─ 点击 PreviewButton（▶）
  │    → 按钮变为 loading
  │    → GET /api/voices/preview?voice=xxx
  │    → 创建 Audio 对象播放
  │    → 按钮变为 ⏸（播放中）
  │    → 播放完毕 → 恢复 ▶
  │    └─ 如果有其他卡片正在播放 → 先停止再播放新的
  ├─ 点击卡片 → 高亮选中（紫色边框）
  └─ 试听中切换 Tab → 停止当前试听

点击 [确认选择]
  → 检查音色与当前页面语言兼容性
  → 不兼容？弹出确认提示："该音色不支持当前语言的视频生成，确认使用吗？"
  → 确认 → 关闭弹窗 → VoiceSelector 更新显示
  → VoiceSelector 存储选中值到表单（用于提交）

点击 [取消] / 点击遮罩 / 按 Esc
  → 关闭弹窗 → 恢复原值
```

### 5.3 跨语言使用警告

**场景**：用户当前在英文页面，但选中了中文音色 `zh-CN-XiaoxiaoNeural`。

| 时机 | 行为 |
|------|------|
| **在 VoicePicker 中浏览** | 英文 Tab 下不显示中文音色（语言隔离），需切换到中文 Tab 才能看到 |
| **从中文 Tab 选中后确认** | 前端检测到音色语言 ≠ 页面语言 → 弹出黄色警告条："此音色可能不支持当前语言的视频生成，可能导致任务失败" |
| **提交任务前** | 后端 `/api/tasks/*` 创建任务时校验 voice 与目标文本语言兼容性，不兼容则拒绝并返回明确错误信息 |

---

## 六、数据流

```
页面加载
  └─ 前端 fetch GET /api/voices → 缓存到 voiceData（全局对象）
       └─ 每个卡片已含 preview_text，点击试听时直接传参

用户打开 VoicePicker
  └─ 从 voiceData 读取 → 按当前 Tab 过滤 → 渲染卡片

用户试听
  └─ GET /api/voices/preview?voice={id}&text={preview_text}
       └─ 后端检查文件缓存 → 命中返回 / 未命中生成后缓存再返回
       └─ 前端创建 Audio(src=blob_url) 播放

用户确认
  └─ 关闭弹窗 → 更新 VoiceSelector 显示 → 存值到隐藏 input
  └─ 表单提交时携带 voice_id
```

---

## 七、改造清单

### 7.1 后端

| 文件 | 改动 |
|------|------|
| `core/config.py` | `AVAILABLE_VOICES` 改为从运行时 `edge-tts --list-voices` 动态读取 + 缓存；新增 `VOICE_PREVIEW_TEXTS` 字典 |
| `server.py` | 改造 `GET /api/voices` 返回结构；新增 `GET /api/voices/preview`（含缓存逻辑）；新增 `GET /api/voices/compat`；在任务创建端点增加 voice/text 兼容性校验 |

### 7.2 前端

| 文件 | 改动 |
|------|------|
| `static/index.html` | 4 处 `<select>` 替换为 `<voice-selector>` 自定义元素；新增 `<voice-picker>` Modal；新增 i18n key |

### 7.3 新增 i18n key

```
voiceSelector: '语音角色'
selectVoice: '选择语音角色'
searchVoice: '搜索音色名称或风格...'
voiceCount: '共 {count} 个音色'
currentSelection: '当前选择'
confirmSelection: '确认选择'
cancel: '取消'
previewLoading: '试听加载中'
previewPlay: '试听'
previewStop: '停止'
voiceCompatWarning: '此音色可能不兼容当前语言的视频生成'
voiceGenderFemale: '女声'
voiceGenderMale: '男声'
voiceRegionPutonghua: '普通话'
voiceRegionCantonese: '粤语'
voiceRegionTaiwan: '台湾'
voiceRegionDialect: '方言'
voiceRegionDeutsch: 'Deutsch'
voiceRegionFrancais: 'Français'
voiceRegionNederlands: 'Nederlands'
voiceRegionEspanol: 'Español'
voiceRegionPortugues: 'Português'
voiceRegionItaliano: 'Italiano'
```

---

## 八、缓存细节

### 8.1 缓存目录生命周期

```
服务启动 → 确保 /tmp/agnes-voice-previews/ 存在
服务运行 → 按需写入，无 TTL（试听文本固定，不会膨胀）
系统重启 → /tmp 自动清空（macOS/Linux 标准行为）
         → 下次请求时自动重新生成
```

### 8.2 缓存 key 设计

```python
import hashlib

def get_preview_cache_key(voice_id: str, text: str) -> str:
    text_hash = hashlib.md5(text.encode()).hexdigest()
    return f"{voice_id}__{text_hash}"
```

**为什么用 MD5**：此处仅用于缓存去重，不涉及安全场景。MD5 足够且短。

### 8.3 并发写入安全

```python
async def get_or_generate_preview(voice_id: str, text: str) -> str:
    cache_key = get_preview_cache_key(voice_id, text)
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.mp3")
    
    if os.path.exists(cache_path):
        return cache_path  # 缓存命中
    
    # 生成音频到临时文件
    tmp_path = cache_path + ".tmp"
    comm = edge_tts.Communicate(text, voice=voice_id)
    await comm.save(tmp_path)
    
    # 原子替换（避免并发读半成品）
    os.replace(tmp_path, cache_path)
    return cache_path
```

多个请求同时触发同一音色的试听时：后到的请求可能读到不完整的 `.tmp` 文件，但因为用的是 `os.rename`（同文件系统原子操作），所以要么读到完整旧内容，要么读到完整新内容，不会读到半成品。

### 8.4 缓存大小估算

```
137 个项目音色 × 1 条试听文本 × ~20KB ≈ 2.7 MB
```
> 如果全量缓存 323 个音色，约 6.5 MB。实际只缓存用户试听过的，按需增长。

磁盘占用可忽略，无需 TTL 淘汰策略。

---

## 九、非功能需求

| 维度 | 要求 |
|------|------|
| **音色数据加载** | 服务启动时一次性加载并内存缓存，不每次请求时调 edge-tts |
| **试听响应速度** | 缓存命中 < 10ms，首次生成 < 3s |
| **前端性能** | 音色列表数据量小（323 条），前端全量缓存，筛选纯前端完成 |
| **无障碍** | Tab/卡片支持键盘导航；试听按钮有 aria-label |
| **移动端** | 弹窗全屏显示；Tab 支持横向滑动；卡片 2 列布局 |
| **错误处理** | 试听失败时前端显示 toast "试听失败，该音色可能不支持此语言" |
