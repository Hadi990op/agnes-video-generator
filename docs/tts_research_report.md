# 免费 TTS 工具调研报告

> 调研日期：2026-07-12
> 目的：为 Agnes Video Generator 项目寻找潜在的免费 TTS 替代/补充方案，优化旁白配音体验。
> 当前方案：edge_tts（Azure Edge TTS，免费，4 个中文语音）

---

## 一、当前方案分析

### edge_tts 的优势

| 维度 | 评价 |
|------|------|
| 费用 | ✅ 完全免费，无需 API Key |
| 稳定性 | ✅ 基于微软 Azure 基础设施，高可用 |
| 音质 | ✅ 神经网络语音，自然度较好 |
| 中文 | ✅ 支持多种中文语音角色 |
| 时间戳 | ✅ SubMaker 提供逐词 WordBoundary，完美支持字幕 |
| 部署 | ✅ `pip install edge_tts`，零配置，纯 Python |
| 依赖 | ✅ 无 GPU 需求，纯 CPU 推理（API 调用） |
| 生态 | ⚠️ 依赖微软 Azure 服务，非本地推理 |

### edge_tts 的痛点

1. **无法离线使用**：依赖外部 API，网络不稳定时生成失败（已有 2 次重试机制）
2. **语音角色有限**：仅 4 个中文语音（Xiaoxiao/Yunyang/Xiaoyi/Yunxi），用户选择少
3. **情感控制弱**：仅支持语速调节（rate），无法控制情感、笑声、停顿等
4. **可能有风控**：大规模使用可能被 Azure 限流或封锁
5. **隐私问题**：文本数据传输到微软服务器

---

## 二、候选方案概览

| 方案 | 参数量 | 中文 | 本地推理 | 时间戳 | 许可证 | 推荐度 |
|------|--------|------|---------|--------|--------|--------|
| **Kokoro-82M** | 82M | ✅ 优秀 | ✅ CPU | ✅ | Apache 2.0 | ⭐⭐⭐⭐⭐ |
| **MeloTTS** | ~300M | ✅ 优秀 | ✅ CPU | ❌ | MIT | ⭐⭐⭐⭐ |
| **CosyVoice 2** | 0.5B | ✅ 最佳 | ✅ GPU | ✅ | Apache 2.0 | ⭐⭐⭐⭐ |
| **ChatTTS** | ~2GB | ✅ 对话 | ✅ GPU | ✅ | CC BY-NC 4.0 | ⭐⭐⭐ |
| **Fish Speech S2** | 4B | ✅ 最强 | ✅ GPU | ✅ | 研究许可 | ⭐⭐⭐ |
| **GPT-SoVITS** | ~2GB | ✅ 最佳 | ✅ GPU | ❌ | MIT | ⭐⭐⭐ |
| **Piper** | 5-100M | ❌ 弱 | ✅ CPU | ❌ | MIT | ⭐ |

---

## 三、重点方案详细分析

### 3.1 Kokoro-82M — 🏆 首推方案

**GitHub**: [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | **许可证**: Apache 2.0（免费商用）

**核心优势**：
- 仅 82M 参数，CPU 上即可实时推理（3-5x 实时），GPU 上可达 210x 实时
- 支持中文普通话，8+ 种中文音色
- 支持**中英混合**文本（对技术类视频非常有用）
- 支持**时间戳返回**（每句话的时间戳），可直接用于字幕生成
- Docker 一键部署，提供 **OpenAI 兼容 API**（`/v1/audio/speech`）
- 显存需求 < 2.5GB（GPU 模式），CPU 上仅需 2GB 内存

**对本项目的适配性**：
- ✅ 可直接替换 edge_tts，实现**完全离线**的 TTS
- ✅ 提供更多中文音色选择（8+ vs 当前 4）
- ✅ 中英混合文本处理更自然
- ✅ 时间戳支持字幕对齐
- ✅ 可通过 `kokoro-fastapi` Docker 镜像部署为独立服务
- ⚠️ 需要本地部署服务（但 Docker 部署很简单）

**集成方式**：
```python
# 方式 A：独立服务 + HTTP 调用
# docker run -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-cpu
import httpx
response = await httpx.AsyncClient().post(
    "http://localhost:8880/v1/audio/speech",
    json={"model": "kokoro", "input": text, "voice": "zh-CN"}
)

# 方式 B：Python SDK 直接调用
# pip install kokoro>=0.8.2 misaki[zh]>=0.8.2
```

---

### 3.2 MeloTTS — 最轻量的降级方案

**GitHub**: [myshell-ai/MeloTTS](https://github.com/myshell-ai/MeloTTS) | **许可证**: MIT（免费商用）

**核心优势**：
- 纯 CPU 实时推理，RTF 低至 0.41（i7-12700）
- 中英混合输入原生支持
- 支持语速控制（0.5x ~ 2.0x）
- MIT 许可证，无商用限制

**对本项目的适配性**：
- ✅ 极低资源需求，适合降级/兜底方案
- ✅ 中英混合
- ❌ **缺少词级时间戳**，无法生成精细字幕对齐
- ⚠️ 音质不如 Kokoro 和 edge_tts

---

### 3.3 CosyVoice 2 — 阿里开源旗舰

**GitHub**: [FunAudioLLM/CosyVoice](https://github.com/FunAudioLLM/CosyVoice) | **许可证**: Apache 2.0

**核心优势**：
- 阿里达摩院开源，中文效果业界顶尖
- **零样本声音克隆**：3 秒音频即可克隆任意音色
- 支持 18+ 中文方言（粤语、四川话、东北话等）
- **150ms 超低延迟**流式输出
- 自然语言情感控制
- 提供 FastAPI + gRPC + MCP Server 完整生态

**对本项目的适配性**：
- ✅ 中文效果最好的开源方案
- ✅ 声音克隆能力（用户可用自己的声音做旁白）
- ✅ 方言支持（可做方言类视频）
- ❌ 需要 GPU（至少 4GB 显存），部署门槛较高
- ❌ 不适合 CPU-only 环境
- ⚠️ 作为可选增强方案，不适合作为默认引擎

---

### 3.4 ChatTTS — 对话场景专精

**GitHub**: [2noise/ChatTTS](https://github.com/2noise/ChatTTS) | **许可证**: CC BY-NC 4.0（商用需授权）

**核心优势**：
- 专为对话场景设计，自动生成呼吸声、笑声、停顿
- 自然情感标签：`[laugh]`、`[uv_break]`、`[lbreak]`
- 39.3k GitHub Stars，社区活跃

**对本项目的适配性**：
- ✅ 对话类视频（如虚拟主播、口播）效果极佳
- ❌ **CC BY-NC 4.0 许可证不可商用**（需要联系作者获取商业授权）
- ❌ 需要 GPU（至少 4GB 显存）
- ⚠️ 仅适合个人非商业使用

---

### 3.5 Fish Speech S2 — 技术最强但门槛最高

**GitHub**: [fishaudio/fish-speech](https://github.com/fishaudio/fish-speech) | **许可证**: Fish Audio Research License（商用需授权）

**核心优势**：
- 当前开源 TTS 效果最好的模型
- 基于 1000 万+ 小时音频训练
- 零样本克隆仅需 10-30 秒音频
- 支持 50+ 语言、万级情感标签
- 中文 WER 低至 0.54%

**对本项目的适配性**：
- ❌ 需要 24GB+ 显存（旗舰版），远超消费级设备
- ❌ 商用需联系授权（非 Apache/MIT）
- ❌ 对于本项目场景过于重型
- ⚠️ 可考虑云端 API（fish.audio），但不再"免费"

---

## 四、方案对比矩阵

| 维度 | edge_tts（当前） | Kokoro-82M | MeloTTS | CosyVoice 2 |
|------|:---:|:---:|:---:|:---:|
| **离线可用** | ❌ | ✅ | ✅ | ✅ |
| **CPU 可用** | ✅ | ✅ | ✅ | ❌（需 GPU） |
| **中文音质** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **中英混合** | ✅ | ✅ | ✅ | ✅ |
| **词级时间戳** | ✅（SubMaker） | ✅（句级） | ❌ | ✅ |
| **音色数量** | 4 | 8+ | ~5 | 无限（可克隆） |
| **部署复杂度** | 零配置 | Docker 一行 | pip install | GPU + 6GB VRAM |
| **隐私安全** | ❌（微软服务器） | ✅（纯本地） | ✅（纯本地） | ✅（纯本地） |
| **许可证** | 免费使用 | Apache 2.0 商用 | MIT 商用 | Apache 2.0 商用 |
| **情感控制** | ❌ | ❌ | ❌ | ✅（自然语言） |
| **声音克隆** | ❌ | ❌ | ❌ | ✅（3秒零样本） |

---

## 五、推荐实施方案

### 方案 A：渐进式升级（推荐✅）

```
优先级 1：Kokoro-82M 作为新的默认引擎（替换 edge_tts）
优先级 2：保留 edge_tts 作为降级方案
优先级 3：CosyVoice 2 作为 GPU 用户的可选增强
```

**具体步骤**：
1. **新增 `KokoroTTSEngine`**（实现 `TTSEngine` 抽象类）
   - 通过 HTTP 调用 `kokoro-fastapi` Docker 服务
   - 或直接使用 `kokoro` Python SDK
2. **保留 `EdgeTTSEngine`** 作为降级方案
3. **在 `server.py` 启动时自动检测**可用引擎并提示用户
4. **新增 `CosyVoiceTTSEngine`**（可选，需 GPU）
   - 提供声音克隆功能（上传参考音频 → 自定义音色）
   - 方言旁白支持

### 方案 B：多引擎自动降级

```
kokoro-fastapi (本地) → edge_tts (云端) → SilentTTSEngine (静音)
```

当本地 Kokoro 服务不可用时自动回退到 edge_tts，确保服务稳定性。

### 方案 C：纯本地方案

完全移除 edge_tts 依赖，使用 Kokoro-82M 作为唯一引擎。适合对隐私要求极高的场景。

---

## 六、Kokoro-82M 集成详细设计

### 6.1 API 设计（兼容 OpenAI TTS 格式）

```python
# core/audio/kokoro_tts.py
class KokoroTTSEngine(TTSEngine):
    """基于 Kokoro-82M 的本地 TTS 引擎。"""

    def __init__(self, base_url: str = "http://localhost:8880"):
        self.base_url = base_url
        self._client = httpx.AsyncClient(timeout=60.0)
        # 中文音色映射
        self.VOICES = {
            "zh-CN-XiaoxiaoNeural": "af_zh",    # 温柔女声映射
            "zh-CN-YunyangNeural": "am_zh",     # 沉稳男声映射
            # ...更多映射
        }

    async def generate(
        self, text: str, output_path: str,
        voice: str = "af_zh", rate: str = "+0%"
    ) -> Tuple[str, object]:
        """生成 TTS 音频。"""
        # 调用 kokoro-fastapi /v1/audio/speech
        # 返回 (audio_path, word_timestamps)
        ...
```

### 6.2 Docker 部署脚本

```bash
# 一键启动 Kokoro TTS 服务
docker run -d --name kokoro-tts \
  -p 8880:8880 \
  --restart unless-stopped \
  ghcr.io/remsky/kokoro-fastapi-cpu:latest

# 健康检查
curl http://localhost:8880/v1/models
```

### 6.3 引擎自动发现

在 `server.py` 启动时检测可用引擎：

```python
ENGINES = []

# 始终可用的引擎
ENGINES.append(("edge_tts", EdgeTTSEngine()))
ENGINES.append(("silent", SilentTTSEngine()))

# 检测本地 Kokoro 服务
if await _check_kokoro():
    ENGINES.append(("kokoro", KokoroTTSEngine()))
```

---

## 七、风险与注意事项

| 风险 | 说明 | 缓解措施 |
|------|------|---------|
| Kokoro 时间戳粒度 | 仅支持句级时间戳，缺少词级精确对齐 | 字幕拆分算法补偿（已有 `_split_long_text`） |
| Kokoro 社区维护 | 相对较新的项目，长期维护不确定 | 保留 edge_tts 作为 fallback |
| GPU 方案门槛 | CosyVoice/ChatTTS 需要 GPU | 仅作为可选增强，不作为默认 |
| 音色兼容性 | 不同引擎语音角色不同 | 统一音色映射表 + 用户可自由切换 |

---

## 八、结论

1. **Kokoro-82M 是最佳替代方案**：免费、开源（Apache 2.0）、离线可用、CPU 友好、中文优秀、有 Docker 部署方案、API 兼容 OpenAI 格式
2. **MeloTTS 适合极轻量场景**：如果 Kokoro 部署有问题，MeloTTS 是 MIT 许可的最简替代
3. **CosyVoice 2 是天花板选项**：如果用户有 GPU，它可以提供声音克隆和方言支持
4. **edge_tts 建议保留作为 fallback**：稳定性好，网络环境好时仍可用
5. **不建议替换为 ChatTTS 或 Fish Speech**：前者许可证限制商用，后者资源需求过高

**建议下一步**：实施方案 A，先集成 Kokoro-82M 作为新的默认引擎，保留 edge_tts 降级。
