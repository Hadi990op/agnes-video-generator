# Mock 回归测试设计

> 目标：不调用任何外部接口，覆盖 pipeline 全流程，mock 有效性确保"mock 过 → 真实过"。

---

## 一、外部接口边界

```
┌──────────────────────────────────────────────────────┐
│                   Pipeline 层                         │
│  SimpleVideo / Creative / Manuscript / Anchor        │
├──────────────────────────────────────────────────────┤
│  API 封装层（薄）                                      │
│  AgnesVideoAPI  AgnesImageAPI  AgnesChatAPI  EdgeTTS  │
├──────────────────────────────────────────────────────┤
│  网络层（HTTP/HTTPS）        ← Mock 在此切割           │
├──────────────────────────────────────────────────────┤
│  外部服务（apihub.agnes-ai.com / Azure TTS）          │
│                                             ffmpeg   │
│                                    ← 本地二进制，不 mock │
└──────────────────────────────────────────────────────┘
```

| 外部接口 | 作用 | Mock 策略 |
|---------|------|----------|
| `AgnesVideoAPI.submit_video` + `wait_for_video` | 视频生成 | mock 类 → 返回预制 mp4 |
| `AgnesImageAPI.generate_single_image` | 图片生成 | mock 类 → 返回预制 png |
| `AgnesChatAPI.chat` / `chat_multimodal` | LLM 编剧 | mock 类 → 返回预制 JSON |
| `EdgeTTSEngine.generate` | TTS 音频 | 直接用 SilentTTSEngine（已有降级路径） |
| `ffmpeg` | 视频处理 | **不 mock**，本地执行（拼接/水印/字幕叠加） |
| `rate_limiter` | 全局限速 | mock 为 no-op |

---

## 二、Mock 有效性保证

### 核心原则：mock 在"协议边界"切割，不在"逻辑内部"切割

```
❌ 错误做法：mock pipeline 的 _step_xxx 方法
   → 大量内部逻辑被跳过，mock 过不代表真实过

✅ 正确做法：只 mock 网络请求的返回值
   → pipeline 所有编排逻辑、文件 IO、ffmpeg 处理都真实运行
   → 唯一替换的是"网络那头返回什么数据"
```

### 有效性逐层分析

| 层次 | mock 方式 | 覆盖了什么 | 没覆盖什么 |
|------|----------|-----------|-----------|
| `AgnesVideoAPI` 内部逻辑 | 不 mock，但 `requests.post/get` 被替换 | submit_video / _poll_task 的全部逻辑（payload 构建、轮询、状态解析、错误处理） | HTTP 传输层（网络波动、超时重试时序） |
| `AgnesImageAPI` 内部逻辑 | 不 mock，但 `requests.post` 被替换 | `_path_to_b64`、prompt 拼接、response 解析 | HTTP 传输层 |
| `AgnesChatAPI` 内部逻辑 | 不 mock，但 `requests.post` 被替换 | `strip_code_fence`、JSON 解析、retry 逻辑 | HTTP 传输层、LLM 实际输出质量 |
| `VideoConcatenator` | 不 mock | ffmpeg 拼接/字幕叠加/水印全部真实运行 | 无（本地二进制） |
| `SubtitleGenerator` | 不 mock | SRT 生成、LLM 样式全部真实运行 | 无 |

**结论**：mock 回归通过后，唯一未覆盖的是网络传输层和外部服务的实际行为（模型质量、生成时间等）。这些在"外部接口不变更、不故障"的前提下，不影响真实回归通过。

---

## 三、Mock 实现架构

```
tests/mock_regression/
├── __init__.py
├── conftest.py                  # pytest fixtures: tmpdir, mock_api_key, 预制素材路径
├── mock_apis.py                 # MockAgnesVideoAPI / MockAgnesImageAPI / MockAgnesChatAPI
├── fixtures.py                  # 预制素材生成器（test video/image/audio）
├── fixture_data/                # 预制 LLM 响应 JSON
│   ├── story.json               # Screenwriter.develop_story 的 mock 响应
│   ├── script.json              # Screenwriter.write_script 的 mock 响应
│   ├── character_desc.json      # extract_character_description 的 mock 响应
│   ├── end_frame_prompts.json   # generate_end_frame_prompts 的 mock 响应
│   ├── scene_prompts.json       # generate_scene_prompt_for_paragraph 的 mock 响应
│   ├── narration.json           # generate_narration_for_video 的 mock 响应
│   ├── anchor_smooth.json       # generate_anchor_smooth_loop_prompt 的 mock 响应
│   ├── scene_config.json        # extract_scene_info_from_idea 的 mock 响应
│   └── image_analysis.json      # describe_images 的 mock 响应
├── assets/                      # 预制媒体素材（首次运行时自动生成）
│   ├── test_video_5s.mp4        # 5 秒测试视频（ffmpeg testsrc）
│   └── test_image.png           # 测试图片（ffmpeg color）
└── test_pipelines.py            # 主测试文件
```

### 3.1 Mock API 类设计

```python
# tests/mock_regression/mock_apis.py

class MockAgnesVideoAPI:
    """模拟 Agnes Video API。
    
    关键设计：
    - submit_video 返回确定性 video_id
    - wait_for_video 返回预制 mp4 文件（不发起任何 HTTP 请求）
    - 调用签名与真实 AgnesVideoAPI 完全一致
    """

    def __init__(self, api_key: str, model: str = "agnes-video-v2.0", **kwargs):
        self.api_key = api_key
        self.model = model
        self.shutdown_event = None
        self._submit_count = 0

    async def submit_video(self, prompt, reference_image_paths=None,
                           duration=5, width=768, height=1152,
                           seed=None, negative_prompt=None, **kwargs):
        """返回唯一的 mock video_id，带自增后缀。"""
        self._submit_count += 1
        return f"mock_video_{uuid.uuid4().hex[:12]}_{self._submit_count}"

    async def wait_for_video(self, video_id, progress_callback=None):
        """返回预制测试视频，格式与真实 VideoOutput 一致。"""
        test_video_path = get_test_video_path()  # 指向预制素材
        return VideoOutput(fmt="url", ext="mp4", data=test_video_path)

    async def generate_single_video(self, prompt, **kwargs):
        """
        关键：mock 必须实现此方法，因为 SimpleVideo 直接调用它
        而不是 submit + wait 两步
        """
        video_id = await self.submit_video(prompt, **kwargs)
        return await self.wait_for_video(video_id)

    # 保留 _make_curl 兼容性
    @staticmethod
    def _make_curl(video_id): return f"# mock curl for {video_id}"
```

```python
class MockAgnesImageAPI:
    """模拟 Agnes Image API。
    
    每次 generate_single_image 返回预制 png。
    如果有 reference_image_paths（i2i 模式），也接受但忽略。
    """

    def __init__(self, api_key: str, model: str = "agnes-image-2.1-flash", **kwargs):
        self.api_key = api_key
        self.model = model
        self._gen_count = 0

    async def generate_single_image(self, prompt, reference_image_paths=None,
                                     size="1024x1024", **kwargs):
        """返回预制测试图片。"""
        self._gen_count += 1
        test_img = get_test_image_path()
        return ImageOutput(fmt="url", ext="png", data=test_img)
```

```python
class MockAgnesChatAPI:
    """模拟 Agnes Chat API。
    
    根据 system_prompt 中的关键词匹配对应的 fixture JSON 文件。
    例如 prompt 中包含 "develop_story" → 返回 fixture_data/story.json
    """

    FIXTURE_MAP = {
        "develop_story": "story.json",
        "write_script": "script.json",
        "extract_character": "character_desc.json",
        "end_frame_prompt": "end_frame_prompts.json",
        "scene_prompt_for_paragraph": "scene_prompts.json",
        "narration_for_video": "narration.json",
        "anchor_smooth_loop": "anchor_smooth.json",
        "extract_scene_info": "scene_config.json",
        "describe_images": "image_analysis.json",
    }

    def __init__(self, api_key: str, model: str = "agnes-2.0-flash", **kwargs):
        self.api_key = api_key
        self.model = model

    def chat(self, messages, temperature=0.7, max_tokens=4096, **kwargs):
        """同步聊天，返回匹配的 fixture 内容。"""
        system_prompt = messages[0]["content"] if messages else ""
        fixture_name = self._match_fixture(system_prompt)
        fixture_path = os.path.join(FIXTURE_DIR, fixture_name)
        with open(fixture_path, "r", encoding="utf-8") as f:
            return f.read()

    def chat_multimodal(self, messages, temperature=0.7, max_tokens=4096, **kwargs):
        """多模态聊天，目前仅用文字匹配。"""
        return self.chat(messages, temperature, max_tokens)

    def _match_fixture(self, system_prompt: str) -> str:
        for keyword, filename in self.FIXTURE_MAP.items():
            if keyword in system_prompt:
                return filename
        return "story.json"  # fallback
```

### 3.2 预制素材生成

```python
# tests/mock_regression/fixtures.py

import os
import subprocess

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixture_data")

def ensure_test_assets():
    """确保预制素材存在，不存在则自动生成。"""
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(FIXTURE_DIR, exist_ok=True)

    # 测试视频 (5s, 768x1152)
    video_path = os.path.join(ASSETS_DIR, "test_video_5s.mp4")
    if not os.path.exists(video_path):
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=5:size=768x1152:rate=30",
            "-f", "mp4", video_path,
        ], check=True, capture_output=True)

    # 测试图片 (768x1152)
    img_path = os.path.join(ASSETS_DIR, "test_image.png")
    if not os.path.exists(img_path):
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:size=768x1152:r=1",
            "-frames:v", "1", img_path,
        ], check=True, capture_output=True)

def get_test_video_path():
    ensure_test_assets()
    return os.path.join(ASSETS_DIR, "test_video_5s.mp4")

def get_test_image_path():
    ensure_test_assets()
    return os.path.join(ASSETS_DIR, "test_image.png")
```

### 3.3 Fixture 数据设计

LLM 响应的 fixture JSON 需满足以下条件才能保证有效性：

1. **格式与真实 API 返回完全一致**（Screenwriter 方法内部会 `strip_code_fence` + `json.loads` 解析）
2. **内容语义合理**，使后续步骤能正常处理
3. **场景数与 pipeline 参数匹配**（如 `scene_count=3` 时 fixture 也返回 3 个场景）

示例 `fixture_data/story.json`：
```json
{
  "story": "这是一个关于勇敢小猫探索花园的温馨故事。小猫从窗户跳出去，在花园里遇到了蝴蝶、蜜蜂和小鸟，最后在夕阳下回到家中。",
  "themes": ["冒险", "自然", "友谊"],
  "tone": "温馨轻松"
}
```

示例 `fixture_data/script.json`：
```json
[
  "场景一：晨光中，一只橘色小猫从窗台跃入花园，阳光洒在它柔软的毛发上，花朵在微风中摇曳。特写小猫好奇的眼神，背景是模糊的绿色植物。",
  "场景二：小猫在花丛中追逐一只蓝蝴蝶，蝴蝶忽高忽低地飞舞。中景镜头跟拍小猫跳跃的动作，背景是盛开的向日葵。",
  "场景三：夕阳西下，小猫满足地趴在窗台上，尾巴轻轻摆动。温暖的逆光勾勒出小猫的轮廓，远处是渐渐暗下来的花园。"
]
```

---

## 四、Pipeline 注入方式

### 方案：Monkey-patch 导入路径（pytest conftest）

不修改 pipeline 源码，通过 `pytest` 的 `monkeypatch` 在测试中替换 API 类的导入。

```python
# tests/mock_regression/conftest.py

import pytest
import sys
from unittest.mock import patch, MagicMock

from .mock_apis import MockAgnesVideoAPI, MockAgnesImageAPI, MockAgnesChatAPI
from .fixtures import ensure_test_assets, get_test_video_path, get_test_image_path


@pytest.fixture(autouse=True)
def mock_external_apis(monkeypatch):
    """全局替换所有外部 API 类为 mock 版本。"""
    ensure_test_assets()

    # 替换 AgnesVideoAPI → MockAgnesVideoAPI
    monkeypatch.setattr(
        "core.api.agnes_video.AgnesVideoAPI",
        MockAgnesVideoAPI
    )
    monkeypatch.setattr(
        "core.pipelines.simple_video.AgnesVideoAPI",
        MockAgnesVideoAPI
    )
    # ... 其他 pipeline 的导入路径

    # 替换 AgnesImageAPI → MockAgnesImageAPI
    monkeypatch.setattr(
        "core.api.agnes_image.AgnesImageAPI",
        MockAgnesImageAPI
    )

    # 替换 AgnesChatAPI → MockAgnesChatAPI
    monkeypatch.setattr(
        "core.api.agnes_chat.AgnesChatAPI",
        MockAgnesChatAPI
    )

    # 强制所有 TTS 走 SilentTTSEngine
    monkeypatch.setattr(
        "core.audio.tts.EdgeTTSEngine",
        type("MockEdgeTTS", (), {
            "generate": lambda self, text, output_path, **kw: (_silent_generate(text, output_path), None)
        })
    )

    # 禁用 rate_limiter
    monkeypatch.setattr(
        "core.api.rate_limiter.get_rate_limiter",
        lambda: MagicMock(acquire=MagicMock())
    )

    yield


@pytest.fixture
def temp_workdir(tmp_path):
    """临时工作目录，测试结束后自动清理。"""
    workdir = tmp_path / "agnes_test"
    workdir.mkdir()
    return str(workdir)


@pytest.fixture
def mock_api_key():
    return "mock_api_key_12345"
```

---

## 五、测试用例设计

### 对每种 pipeline 设计统一验证模式

```python
# tests/mock_regression/test_pipelines.py

class BasePipelineTest:
    """所有 pipeline 测试的基类，定义通用验证模式。
    
    每个具体测试类只需提供：
    - pipeline_class
    - state_factory (构建测试 state)
    - expected_output_filename
    """

    async def _run_and_verify(self, pipeline_class, state, workdir):
        """通用验证流程：创建 pipeline → run → 断言产物。"""
        pipeline = pipeline_class(
            api_key="mock_key",
            task_id="test_task_001",
            dir_name=workdir,
        )
        final_video = await pipeline.run(state)

        # 1. 产物文件存在
        assert os.path.exists(final_video), f"Final video not found: {final_video}"
        assert os.path.getsize(final_video) > 0, "Final video is empty"

        # 2. 状态标记正确
        assert state.status == StepStatus.COMPLETED
        assert state.final_video_file == final_video

        # 3. 步骤状态全部标记（或记录跳过的步骤）
        for field_name in state.model_fields:
            if field_name.startswith("step_") and field_name != "step_audio_subtitle":
                step_status = getattr(state, field_name)
                assert step_status in (StepStatus.COMPLETED, StepStatus.PENDING), \
                    f"{field_name} = {step_status}"

        # 4. prompts.json 存在（如果有 LLM 步骤）
        prompts_path = os.path.join(workdir, "prompts.json")
        if pipeline_class in (CreativeVideoPipeline, ManuscriptVideoPipeline, AnchorPipeline):
            assert os.path.exists(prompts_path), "prompts.json not found"

        return final_video


class TestSimpleVideoPipeline(BasePipelineTest):
    """简单视频 mock 回归。"""

    @pytest.mark.asyncio
    async def test_t2v_basic(self, temp_workdir):
        from core.pipelines.simple_video import SimpleVideoPipeline
        from models.task import SimpleVideoTask, VideoMode

        state = SimpleVideoTask(
            task_type="simple",
            creative_name="mock_simple_t2v",
            prompt="一只猫在花园里",
            mode=VideoMode.T2V,
            duration=5,
            video_width=768,
            video_height=1152,
        )
        await self._run_and_verify(SimpleVideoPipeline, state, temp_workdir)

    # ... i2v / keyframes 等变体


class TestCreativeVideoPipeline(BasePipelineTest):
    """创意视频 mock 回归。"""

    @pytest.mark.asyncio
    async def test_keyframes_mode(self, temp_workdir):
        from core.pipelines.creative_video import CreativeVideoPipeline
        from models.task import CreativeVideoTask

        state = CreativeVideoTask(
            task_type="creative",
            creative_name="mock_creative_keyframes",
            idea="一只小猫的冒险故事",
            style="动画风格",
            chaining_mode="keyframes",
            scene_count=3,
            scene_durations=[5, 5, 5],
            duration_source="manual",
            audio_config=AudioConfig(enabled=True),
            subtitle_config=SubtitleConfig(enabled=True),
        )
        await self._run_and_verify(CreativeVideoPipeline, state, temp_workdir)

    @pytest.mark.asyncio
    async def test_independent_mode(self, temp_workdir):
        # ... chaining_mode="independent" 变体

    @pytest.mark.asyncio
    async def test_ti2vid_mode(self, temp_workdir):
        # ... chaining_mode="ti2vid" 变体


class TestManuscriptVideoPipeline(BasePipelineTest):
    """稿件视频 mock 回归。"""

    @pytest.mark.asyncio
    async def test_manuscript_basic(self, temp_workdir):
        from core.pipelines.manuscript_video import ManuscriptVideoPipeline
        from models.task import ManuscriptVideoTask

        text = (
            "春天来了，万物复苏，花园里的花朵竞相开放。"
            "小猫从窗台跳下来，开始了它的冒险之旅。"
            "它在花丛中追逐蝴蝶，在阳光下打滚。"
            "最后夕阳西下，小猫满足地回家了。"
        )
        state = ManuscriptVideoTask(
            task_type="manuscript",
            creative_name="mock_manuscript",
            manuscript_text=text,
            audio_config=AudioConfig(enabled=True),
            subtitle_config=SubtitleConfig(enabled=True),
        )
        await self._run_and_verify(ManuscriptVideoPipeline, state, temp_workdir)


class TestAnchorVideoPipeline(BasePipelineTest):
    """数字人口播 mock 回归。"""

    @pytest.mark.asyncio
    async def test_post_stitch_mode(self, temp_workdir):
        from core.pipelines.anchor_video import AnchorPipeline
        from models.task import AnchorVideoTask

        state = AnchorVideoTask(
            task_type="anchor",
            creative_name="mock_anchor_stitch",
            script_text="各位观众朋友们大家好，欢迎收看今天的新闻节目。今天的主要内容有...",
            audio_source="post_stitch",
            audio_config=AudioConfig(enabled=True),
            subtitle_config=SubtitleConfig(enabled=True),
        )
        await self._run_and_verify(AnchorPipeline, state, temp_workdir)
```

---

## 六、与重构方案的对应关系

重构后新增 `MultiScenePipeline` 时，测试也需对应调整：

| 重构阶段 | 对应的 mock 测试 |
|---------|----------------|
| Phase 1: 基础设施上提 | 现有测试继续通过，无需修改（mock 在 API 层切割） |
| Phase 2: MultiScenePipeline 创建 | 新增 `TestMultiScenePipeline` 直接测试通用框架 |
| Phase 3: 改造现有 Pipeline | 每个子类的测试用例不变，验证产出一致 |
| Phase 4: 新增 PoetryVideoPipeline | 新增 `TestPoetryVideoPipeline`，仅需新增 fixture JSON |

**关键不变式**：mock 始终在 API 层切割，无论 pipeline 内部如何重构，测试不需要修改。

---

## 七、运行方式

```bash
# 首次运行：自动生成预制素材（ffmpeg 必需）
.venv/bin/python -m pytest tests/mock_regression/ -v

# 仅跑特定 pipeline
.venv/bin/python -m pytest tests/mock_regression/test_pipelines.py::TestCreativeVideoPipeline -v

# 并行跑（每个 pipeline 独立）
.venv/bin/python -m pytest tests/mock_regression/ -v -n 4

# 查看 fixture 数据
ls -la tests/mock_regression/assets/
ls -la tests/mock_regression/fixture_data/
```

---

## 八、风险与限制

| 风险 | 缓解措施 |
|------|---------|
| fixture JSON 格式变化 | Screenwriter 每次添加新字段时需要同步更新 fixture |
| ffmpeg 版本差异导致字幕叠加不同 | 不做像素级比对，只验证文件存在且非空 |
| mock video 时长与实际不符 | 生成与实际参数一致的测试视频（对应 duration 和分辨率） |
| 新 pipeline 需要新 fixture | 作为新增 pipeline 的 checklist 项 |

### Mock 有效性检查清单

| 检查项 | 说明 |
|--------|------|
| ✅ `AgnesVideoAPI` 调用签名一致 | submit_video / wait_for_video / generate_single_video 签名与真实类一致 |
| ✅ `AgnesImageAPI.save()` 文件格式正确 | 返回的 VideoOutput / ImageOutput 使用相同的 save() 方法 |
| ✅ LLM fixture 为合法 JSON | Screenwriter 内部 `json.loads` 可正常解析 |
| ✅ ffmpeg 路径存在 | 本地 binary 可用 |
| ✅ 不 mock 拼接/水印/字幕 | VideoConcatenator 和 SubtitleGenerator 全部真实运行 |
| ✅ 测试结束后清理 | `tmp_path` fixture 自动清理 |
