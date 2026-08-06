"""core.pipelines.creative.pipeline — CreativeVideoPipeline 主类（v5.0 Batch 4 / 4.2 拆分）

四步 mixin（script/frames/video/audio）+ MultiScenePipeline 模板方法组合；
AgnesImageAPI/AgnesVideoAPI 在此模块 import 并实例化（mock 回归 patch 目标）。"""
import asyncio
import logging
from typing import Callable, Optional

from core.api.agnes_image import AgnesImageAPI
from core.api.agnes_video import AgnesVideoAPI
from core.pipelines import MultiScenePipeline
from core.screenwriter import Screenwriter
from models.task import CreativeVideoTask

from .steps_audio import AudioStepsMixin
from .steps_frames import FramesStepsMixin
from .steps_script import ScriptStepsMixin
from .steps_video import VideoStepsMixin

logger = logging.getLogger(__name__)


class CreativeVideoPipeline(
    ScriptStepsMixin,
    FramesStepsMixin,
    VideoStepsMixin,
    AudioStepsMixin,
    MultiScenePipeline,
):
    """Creative long-form video generation pipeline with audio/subtitle support.

    Generates multi-scene videos from a user idea, with optional TTS narration
    and subtitle overlays.  Supports three chaining modes (``independent``,
    ``chained/ti2vid``, ``keyframes``) and full resume from any completed step.

    Inherits shared infrastructure (progress callbacks, shutdown control,
    task-manager integration) from :class:`BasePipeline`.
    """

    # v5.0 Batch 3（S3，方案 A）：禁用粗粒度步骤级 skip。
    # 本类依赖各 ``_step_*`` 读盘做细粒度断点续传，通过类属性关闭
    # MultiScenePipeline._execute_step 的粗粒度 skip（原覆写已删除，行为一致）。
    coarse_skip = False

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: Optional[str] = None,
        chat_model: str = "agnes-2.0-flash",
        image_model: str = "agnes-image-2.1-flash",
        video_model: str = "agnes-video-v2.0",
        progress_callback: Optional[Callable] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        """Initialize the creative video pipeline.

        Args:
            api_key: Agnes API key for authentication.
            task_id: Unique identifier for this task.
            dir_name: Optional working-directory name; defaults to *task_id*.
            chat_model: Model name for the screenwriter (LLM chat).
            image_model: Model name for image generation (t2i).
            video_model: Model name for video generation.
            progress_callback: Async callable ``(step, status, message, progress, data)``
                for reporting progress to the caller.
            shutdown_event: External ``asyncio.Event`` that signals a graceful
                shutdown request.
        """
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)

        self.screenwriter = Screenwriter(api_key=api_key, model=chat_model)
        self.image_generator = AgnesImageAPI(api_key=api_key, model=image_model)
        self.video_generator = AgnesVideoAPI(api_key=api_key, model=video_model)
        self.video_generator.shutdown_event = shutdown_event

        self._state: Optional[CreativeVideoTask] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> Optional[CreativeVideoTask]:
        """Current pipeline task state."""
        return self._state

    # ==================================================================
    # v4.0 模板钩子（继承 MultiScenePipeline，复用模板 run() + 步骤编排）
    # ==================================================================
    # Batch 3（S3，方案 A）：不再覆写 _execute_step —— MultiScenePipeline 现支持
    # coarse_skip 开关，本类通过类属性 coarse_skip=False 禁用粗粒度 skip，
    # 依赖各 _step_* 读盘自 skip（保持细粒度 resume，行为与覆写时一致）。

    def _get_init_message(self) -> str:
        return "开始视频生成流程..."

    def _get_watermark_language_text(self) -> str:
        return self._state.idea

    # ------------------------------------------------------------------
    # 数据来源：分镜（编剧 → story → script → narrations）
    # ------------------------------------------------------------------

    async def _build_scenes(self) -> None:
        """LLM 编剧：场景配置 → 图片分析 → 故事 → 角色参考 → 脚本 → 旁白。"""
        await self._step_resolve_scene_config()
        image_context = await self._step_image_analysis(
            self._state.reference_image, self._state.end_frame_images
        )
        self._check_shutdown()
        self._story = await self._step_story(image_context)
        self._check_shutdown()
        self._character_ref_path = await self._step_character_reference(self._story)
        self._check_shutdown()
        self._scenes = await self._step_script(self._story)
        self._check_shutdown()
        await self._step_generate_narrations(self._story, self._scenes)
        self._check_shutdown()

    # ------------------------------------------------------------------
    # 数据来源：参考图（尾帧 prompt + 预生成，仅 keyframes 模式）
    # ------------------------------------------------------------------

    async def _build_reference_images(self) -> None:
        """参考图生成：尾帧 prompt → 预生成（keyframes 模式）。"""
        self._end_frame_prompts = await self._step_end_frame_prompts(
            self._story, self._scenes
        )
        self._check_shutdown()
        self._pregenerated_end_frames = await self._step_pregenerate_end_frames(
            self._scenes, self._end_frame_prompts, self._character_ref_path
        )
        self._check_shutdown()

    # ------------------------------------------------------------------
    # 视频生成（链式 keyframes / ti2vid / independent — 保留原逻辑）
    # ------------------------------------------------------------------

    async def _generate_videos(self) -> None:
        """链式视频生成（覆写通用实现，保留 keyframes/ti2vid/independent 逻辑）。"""
        self._all_video_paths = await self._step_generate_videos(
            self._scenes, self._character_ref_path,
            self._end_frame_prompts, self._pregenerated_end_frames,
        )
        self._check_shutdown()

    # ------------------------------------------------------------------
    # 音频生成（保留原逻辑）
    # ------------------------------------------------------------------

    async def _generate_audio(self) -> object:
        """TTS 配音生成。"""
        sub_maker = await self._step_audio()
        self._check_shutdown()
        return sub_maker

    # ------------------------------------------------------------------
    # 字幕生成（保留原逻辑）
    # ------------------------------------------------------------------

    async def _generate_subtitles(self, sub_maker=None) -> None:
        """字幕生成。"""
        await self._step_subtitle(sub_maker)
        self._check_shutdown()

    # ------------------------------------------------------------------
    # 合成（保留原逻辑）
    # ------------------------------------------------------------------

    async def _composite_final(self) -> str:
        """视频拼接合成。"""
        return await self._step_concatenate(self._all_video_paths)
