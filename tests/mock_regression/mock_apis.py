"""tests.mock_regression.mock_apis — Mock API 类

在 API 协议边界切割：模拟网络返回值，保留所有内部逻辑。
"""

import asyncio
import json
import logging
import os
import random
import shutil
import string
import time
from typing import Dict, List, Optional

from core.api.agnes_image import ImageOutput
from core.api.agnes_video import VideoOutput

logger = logging.getLogger(__name__)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixture_data")
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")


def _load_fixture_text(name: str) -> str:
    path = os.path.join(FIXTURE_DIR, f"{name}.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def _load_fixture_json(name: str) -> dict:
    path = os.path.join(FIXTURE_DIR, f"{name}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_test_video_path() -> str:
    path = os.path.join(ASSETS_DIR, "test_video_5s.mp4")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Test video not found: {path}. Run asset generation first.")
    return path


def get_test_image_path() -> str:
    path = os.path.join(ASSETS_DIR, "test_image.png")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Test image not found: {path}. Run asset generation first.")
    return path


# ══════════════════════════════════════════════════════════════════════
# MockAgnesVideoAPI
# ══════════════════════════════════════════════════════════════════════

class MockAgnesVideoAPI:
    """模拟 Agnes Video API。

    关键：调用签名与真实 AgnesVideoAPI 完全一致。
    submit_video → 返回确定性 video_id
    wait_for_video → 返回预制 mp4（不发起任何 HTTP 请求）
    """

    def __init__(self, api_key: str = "", model: str = "agnes-video-v2.0",
                 default_duration: int = 5, max_retries: int = 5,
                 retry_base_delay: float = 30.0, **kwargs):
        self.api_key = api_key
        self.model = model
        self.default_duration = default_duration
        self.shutdown_event = None
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self._submit_count = 0
        self._test_video = get_test_video_path()
        with open(self._test_video, "rb") as f:
            self._test_video_bytes = f.read()

    def _path_to_b64(self, path: str) -> str:
        """与真实 API 相同的 base64 编码（用于非 mock 场景的兼容）。"""
        import base64
        import mimetypes
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"

    async def _resolve_image_ref(self, ref: str) -> str:
        """与真实 API 相同的引用解析（本地路径直接返回）。"""
        if ref.startswith(("http://", "https://", "data:")):
            return ref
        if os.path.exists(ref):
            return ref
        return ref

    def _get_frame_config(self, duration=None, width=1152, height=768):
        return (121, 24)  # 5s default

    async def submit_video(self, prompt: str, reference_image_paths: List[str] = None,
                           duration: int = 5, width: int = 768, height: int = 1152,
                           seed: int = None, negative_prompt: str = None,
                           **kwargs) -> str:
        """返回 mock video_id。模拟 ~0.5s 提交延迟。"""
        await asyncio.sleep(0.1)
        self._submit_count += 1
        ts = int(time.time() * 1000)
        return f"mock_video_{ts}_{self._submit_count}_{random.randint(1000, 9999)}"

    async def wait_for_video(self, video_id: str, progress_callback=None) -> VideoOutput:
        """返回预制测试视频（二进制模式，不发起 HTTP 请求）。"""
        await asyncio.sleep(0.2)
        return VideoOutput(fmt="file", ext="mp4", data=self._test_video_bytes)

    async def generate_single_video(self, prompt: str, reference_image_paths: List[str] = None,
                                     duration: int = None, width: int = 1152, height: int = 768,
                                     seed: int = None, negative_prompt: str = None,
                                     progress_callback=None, **kwargs) -> VideoOutput:
        """单次生成（submit + wait 合并，被 SimpleVideo 直接调用）。"""
        video_id = await self.submit_video(
            prompt=prompt, reference_image_paths=reference_image_paths,
            duration=duration, width=width, height=height,
            seed=seed, negative_prompt=negative_prompt, **kwargs)
        return await self.wait_for_video(video_id, progress_callback)

    async def _upload_image_to_url(self, image_path: str, retries: int = 3) -> Optional[str]:
        return image_path  # mock: 直接返回本地路径

    @staticmethod
    def _make_curl(video_id: str) -> str:
        return f"# mock curl for {video_id}"


# ══════════════════════════════════════════════════════════════════════
# MockAgnesImageAPI
# ══════════════════════════════════════════════════════════════════════

class MockAgnesImageAPI:
    """模拟 Agnes Image API。

    generate_single_image → 返回预制 png（不发起任何 HTTP 请求）。
    """

    def __init__(self, api_key: str = "", model: str = "agnes-image-2.1-flash",
                 i2i_model: str = None, **kwargs):
        self.api_key = api_key
        self.model = model
        self.i2i_model = i2i_model or model
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self._gen_count = 0
        self._test_image = get_test_image_path()
        with open(self._test_image, "rb") as f:
            raw = f.read()
        # ImageOutput.save() 非 url fmt 需要 data URI 字符串格式
        import base64
        self._test_image_data = f"data:image/png;base64,{base64.b64encode(raw).decode()}"

    async def generate_single_image(self, prompt: str,
                                     reference_image_paths: List[str] = None,
                                     size: str = "1024x1024", **kwargs) -> ImageOutput:
        """返回预制测试图片（data URI 格式，不发起 HTTP 请求）。"""
        await asyncio.sleep(0.1)
        self._gen_count += 1
        return ImageOutput(fmt="file", ext="png", data=self._test_image_data)


# ══════════════════════════════════════════════════════════════════════
# MockAgnesChatAPI
# ══════════════════════════════════════════════════════════════════════

# fixture 匹配规则
# (系统提示词关键词, 用户提示词关键词, fixture名称)
# 两个关键词都必须在combined prompt中出现才能匹配
# 如果用户提示词为空字符串，表示只匹配系统提示词
_CHAT_FIXTURES = [
    ("描述图片内容", "", "image_analysis"),
    ("describe the images", "", "image_analysis"),
    ("场景信息提取", "", "scene_config"),
    ("extract scene info", "", "scene_config"),
    ("develop story", "", "story"),
    ("创意想法扩展为结构清晰", "", "story"),
    # write_script: 视频导演 + <story> 标签
    ("视频导演和视觉提示词工程师", "<story>", "script"),
    ("video director and visual prompt engineer", "<story>", "script"),
    # generate_scene_prompt_for_paragraph: 视频导演 + <paragraph> 标签
    ("视频导演和视觉提示词工程师", "<paragraph>", "scene_prompt"),
    ("video director and visual prompt engineer", "<paragraph>", "scene_prompt"),
    ("visual design expert", "", "character_desc"),
    ("生成角色参考图", "", "character_desc"),
    ("character_appearance", "", "character_appearance"),
    ("仅从此故事中提取主要角色的物理外貌", "", "character_appearance"),
    ("end frame prompt", "", "end_frame_prompts"),
    ("generate end frame", "", "end_frame_prompts"),
    ("无缝循环播放", "<anchor_appearance>", "anchor_smooth"),
    ("同时生成视频和音频", "<anchor_appearance>", "anchor_model_audio"),
    ("narration_for_video", "", "narration"),
    ("narration for video", "", "narration"),
    ("视频旁白员和剧本作家", "", "narration"),
    ("subtitle_styles", "", "subtitle_styles"),
    ("subtitle_style_designer", "", "subtitle_styles"),
    ("诗词分镜导演", "<poem>", "poetry_scenes"),
]


class MockAgnesChatAPI:
    """模拟 Agnes Chat API。

    根据 system_prompt + user_prompt 内容匹配对应的 fixture 文件。
    chat() → 返回 fixture 文本
    chat_json() → 返回 fixture JSON 对象
    chat_multimodal() → 与 chat() 相同（忽略图片）
    """

    def __init__(self, api_key: str = "", model: str = "agnes-2.0-flash", **kwargs):
        self.api_key = api_key
        self.model = model
        self._call_count = 0

    def _match_fixture_name(self, system_prompt: str, user_prompt: str) -> str:
        """根据 prompt 关键词匹配 fixture 名称。

        匹配规则：(sys_keyword, user_keyword, fixture_name)
        - 两个关键词都必须出现（user_keyword 为空则只匹配 sys_keyword）
        """
        for sys_kw, user_kw, name in _CHAT_FIXTURES:
            if sys_kw in system_prompt:
                if not user_kw or user_kw in user_prompt:
                    return name
        logger.warning(f"[MockChat] No fixture matched for sys={system_prompt[:80]}... usr={user_prompt[:60]}...")
        return "story"  # fallback

    def chat(self, system_prompt: str, user_prompt: str,
             max_tokens: int = 4096) -> str:
        """返回 fixture 文本内容。"""
        self._call_count += 1
        fixture_name = self._match_fixture_name(system_prompt, user_prompt)
        logger.info(f"[MockChat] chat #{self._call_count} → fixture={fixture_name}")
        return _load_fixture_text(fixture_name)

    def chat_json(self, system_prompt: str, user_prompt: str,
                  max_tokens: int = 4096) -> dict:
        """返回 fixture JSON 对象。"""
        self._call_count += 1
        fixture_name = self._match_fixture_name(system_prompt, user_prompt)
        logger.info(f"[MockChat] chat_json #{self._call_count} → fixture={fixture_name}")
        return _load_fixture_json(fixture_name)

    def chat_multimodal(self, system_prompt: str, text_prompt: str,
                        image_paths: List[str], max_tokens: int = 4096) -> str:
        """多模态聊天，忽略图片，返回 fixture 文本（等同于 chat）。"""
        self._call_count += 1
        fixture_name = self._match_fixture_name(system_prompt, text_prompt)
        logger.info(f"[MockChat] chat_multimodal #{self._call_count} → fixture={fixture_name}")
        return _load_fixture_text(fixture_name)

    def _image_to_b64_uri(self, path: str) -> str:
        """模拟图片转 base64（与真实 API 兼容）。"""
        import base64
        import mimetypes
        if not os.path.exists(path):
            return f"data:image/png;base64,mock"
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"


# ══════════════════════════════════════════════════════════════════════
# MockRateLimiter / MockEdgeTTS
# ══════════════════════════════════════════════════════════════════════

class MockRateLimiter:
    """模拟全局限速器（no-op）。"""
    def acquire(self): pass


class MockEdgeTTSEngine:
    """模拟 Edge TTS（路由到静音，不发起任何 HTTP 请求）。

    直接使用 SilentTTSEngine 的逻辑，返回静音占位音频。
    """

    async def generate(self, text: str, output_path: str,
                       voice: str = "zh-CN-XiaoxiaoNeural",
                       rate: str = "+0%"):
        """生成静音占位音频（复制 SilentTTSEngine 的核心逻辑）。"""
        from core.audio.tts import SilentTTSEngine
        silent = SilentTTSEngine()
        total_duration = max(len(text) / 4.0, 2.0)
        return await silent.generate(text=text, output_path=output_path,
                                      duration_sec=total_duration)
