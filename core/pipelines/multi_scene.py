"""core.pipelines.multi_scene — 多场景视频通用框架（v4.0 重构核心）

模板方法 ``run()`` 定义标准流程：
    build_scenes → build_reference_images → generate_videos → audio+subtitle → composite

子类只需提供数据来源（_build_scenes / _build_reference_images / _composite_final），
并可按需覆写通用步骤（_generate_videos / _generate_audio / _generate_subtitles）或钩子方法。

设计原则（见 docs/plans-v4.0/pipeline_refactor.md）：
    - 差异只在"数据从哪来"，不在"流程怎么做"
    - 通用步骤操作 ``self._state.scenes: List[SceneTask]``，通过钩子读取每场景参数
    - 子类可整体覆写某步骤以保留其特有的（如链式/循环）视频生成逻辑
"""

import asyncio
import logging
import os
from abc import abstractmethod
from typing import Callable, List, Optional

from core.audio.tts import EdgeTTSEngine, SilentTTSEngine
from core.pipelines import BasePipeline, PipelineShutdown
from models.task import SceneTask, StepStatus, AudioConfig, SubtitleConfig

logger = logging.getLogger(__name__)


class MultiScenePipeline(BasePipeline):
    """多场景视频生成通用框架。

    提供统一的步骤编排（模板方法 ``run``）、步骤执行包装器（``_execute_step``）、
    通用水印后处理（继承自 ``BasePipeline``）、以及通用视频/音频/字幕生成实现。

    子类必须实现三个抽象方法提供数据源：
        - ``_build_scenes``         构建 ``self._state.scenes``（List[SceneTask]）
        - ``_build_reference_images`` 生成参考图（可空实现跳过）
        - ``_composite_final``      合成最终视频

    并可通过钩子方法定制参数来源：
        - ``_get_narration_text``        配音文本
        - ``_get_segment_texts_and_durations`` 字幕分段文本与时长
        - ``_get_scene_video_prompt``     单场景视频 prompt
        - ``_get_scene_ref_images``       单场景参考图列表
        - ``_get_scene_duration``         单场景视频时长
        - ``_get_audio_path``             音频文件输出路径
        - ``_set_subtitle_paths``         字幕路径写回 state
    """

    # ==================================================================
    # 模板方法：run()
    # ==================================================================

    async def run(self, state) -> str:
        """标准多场景视频流程（模板方法）。"""
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        await self._emit("init", "running", self._get_init_message(), 0.0)

        try:
            # Phase 1: 分镜/拆段 → List[SceneTask]
            await self._execute_step(
                "step_build_scenes", self._build_scenes,
                0.0, 0.15, "构建分镜", "分镜构建完成",
            )

            # Phase 2: 参考图（可选，子类可空实现跳过）
            await self._execute_step(
                "step_reference_images", self._build_reference_images,
                0.15, 0.30, "生成参考图", "参考图生成完成",
            )

            # Phase 3: 视频生成（通用，子类可覆写保留链式/循环逻辑）
            await self._execute_step(
                "step_video_generation", self._generate_videos,
                0.30, 0.75, "生成视频", "视频生成完成",
            )

            # Phase 4: 配音（通用，子类可覆写）
            sub_maker = await self._execute_step(
                "step_audio", self._generate_audio,
                0.75, 0.85, "生成配音", "配音完成",
            )

            # Phase 5: 字幕（通用，子类可覆写）
            await self._execute_step(
                "step_subtitle",
                lambda: self._generate_subtitles(sub_maker),
                0.85, 0.90, "生成字幕", "字幕完成",
            )

            # Phase 6: 合成
            final_video = await self._execute_step(
                "step_concatenation", self._composite_final,
                0.90, 0.98, "合成视频", "合成完成",
            )

            # 后处理：水印（继承自 BasePipeline）
            final_video = self._apply_watermark(final_video)

            # 完成
            self._state.status = StepStatus.COMPLETED
            self._state.final_video_file = final_video
            self.task_manager.update_state(
                status=StepStatus.COMPLETED,
                final_video_file=final_video,
            )
            await self._emit(
                "done", "completed", "视频生成完成!", 1.0,
                {"final_video": final_video},
            )
            return final_video

        except PipelineShutdown:
            await self._emit("error", "failed", "任务已被中断，可从任务列表续传", 0.0)
            raise
        except Exception as e:
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(status=StepStatus.FAILED)
            await self._emit("error", "failed", str(e), 0.0)
            raise

    # ==================================================================
    # 步骤执行包装器
    # ==================================================================

    async def _execute_step(
        self, step_name: str, action: Callable,
        progress_start: float, progress_end: float,
        running_msg: str, completed_msg: str,
    ):
        """统一的步骤执行器：自动处理断点续传、状态标记、进度上报。

        若 ``self._state`` 上对应步骤字段已为 COMPLETED，则跳过（断点续传）。
        """
        if getattr(self._state, step_name, StepStatus.PENDING) == StepStatus.COMPLETED:
            logger.info(f"[Pipeline] Step {step_name}: already completed, skipping")
            return None

        self.task_manager.update_step(step_name, StepStatus.RUNNING)
        await self._emit(step_name, "running", running_msg, progress_start)

        result = await action()

        self.task_manager.update_step(step_name, StepStatus.COMPLETED)
        await self._emit(step_name, "completed", completed_msg, progress_end)
        return result

    # ==================================================================
    # 抽象方法：数据来源（子类必须实现）
    # ==================================================================

    @abstractmethod
    async def _build_scenes(self) -> None:
        """构建场景列表，产出 ``self._state.scenes``（List[SceneTask]）。"""
        ...

    @abstractmethod
    async def _build_reference_images(self) -> None:
        """构建参考图。可空实现（直接 ``return``）跳过此阶段。"""
        ...

    @abstractmethod
    async def _composite_final(self) -> str:
        """合成最终视频，返回视频路径。"""
        ...

    # ==================================================================
    # 通用步骤实现（操作 self._state.scenes，子类可整体覆写）
    # ==================================================================

    async def _generate_videos(self) -> None:
        """通用视频生成：两阶段（批量提交 + 逐个等待）。

        每个场景从 SceneTask 对象获取 prompt / duration / ref_images（通过钩子）。
        子类（如链式/循环视频）可整体覆写本方法以保留其特有逻辑。
        """
        scenes = self._state.scenes
        total = len(scenes)

        # Phase 1: 批量提交
        pending: list = []
        for i, scene in enumerate(scenes):
            self._check_shutdown()
            scene_dir = os.path.join(self.working_dir, f"scene_{i}")
            os.makedirs(scene_dir, exist_ok=True)
            video_path = os.path.join(scene_dir, "video.mp4")

            if os.path.exists(video_path):
                scene.video_file = video_path
                continue

            video_id = self._load_task_json(scene_dir)
            if video_id:
                scene.video_id = video_id
                pending.append((i, video_id, video_path))
                continue

            prompt = self._get_scene_video_prompt(scene, i)
            ref_images = self._get_scene_ref_images(scene, i)
            duration = self._get_scene_duration(scene, i)

            video_id = await self.video_api.submit_video(
                prompt=prompt,
                reference_image_paths=ref_images,
                duration=duration,
                width=self._state.video_width,
                height=self._state.video_height,
            )
            scene.video_id = video_id
            self._save_task_json(scene_dir, {"video_id": video_id})
            pending.append((i, video_id, video_path))

        self.task_manager.update_state(scenes=[s.model_dump() for s in scenes])

        # Phase 2: 逐个等待
        for j, (scene_idx, video_id, video_path) in enumerate(pending):
            self._check_shutdown()
            await self._emit(
                "video_gen", "running",
                f"等待视频 {j + 1}/{len(pending)}...",
                0.40 + 0.35 * j / max(len(pending), 1),
            )
            video_output = await self._wait_for_video_with_retry(video_id, scene_idx)
            video_output.save(video_path)
            self._state.scenes[scene_idx].video_file = video_path
            self.task_manager.update_state(scenes=[s.model_dump() for s in self._state.scenes])

    async def _wait_for_video_with_retry(
        self, video_id: str, scene_idx: int, max_retries: int = 3
    ):
        """带重试的视频等待。"""
        scene_dir = os.path.join(self.working_dir, f"scene_{scene_idx}")
        for retry in range(max_retries):
            try:
                return await self.video_api.wait_for_video(video_id)
            except Exception as e:
                if retry < max_retries - 1:
                    delay = 20 * (retry + 1)
                    logger.warning(
                        f"Video {video_id[:16]} retry {retry + 1}/{max_retries}: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    tf = os.path.join(scene_dir, "task.json")
                    if os.path.exists(tf):
                        os.remove(tf)
                    raise

    async def _generate_audio(self) -> Optional[object]:
        """通用 TTS 音频生成（EdgeTTS → Silent 降级）。返回 sub_maker。"""
        audio_path = self._get_audio_path()
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            self._state.combined_audio = audio_path
            logger.info("[MultiScene] audio: file already exists, skipping")
            return None

        text = self._get_narration_text()
        if not text:
            logger.info("[MultiScene] audio: empty narration text, skipping")
            return None

        total_duration = sum(float(s.duration) for s in self._state.scenes)
        audio_config = self._state.audio_config if hasattr(self._state, "audio_config") \
            else AudioConfig()

        edge_tts = EdgeTTSEngine()
        silent_tts = SilentTTSEngine()

        await self._emit("audio", "running", f"生成配音 ({len(text)} 字)...", 0.75)

        sub_maker = None
        if audio_config.enabled:
            try:
                _, sub_maker = await edge_tts.generate(
                    text=text, output_path=audio_path,
                    voice=audio_config.voice, rate=audio_config.rate,
                )
            except RuntimeError as e:
                logger.warning(f"[MultiScene] EdgeTTS failed, falling back to silent: {e}")
                await silent_tts.generate(
                    text=text, output_path=audio_path,
                    duration_sec=total_duration,
                )
        else:
            await silent_tts.generate(
                text=text, output_path=audio_path,
                duration_sec=total_duration,
            )

        self._state.combined_audio = audio_path
        self.task_manager.update_state(combined_audio=audio_path)
        return sub_maker

    async def _generate_subtitles(self, sub_maker: Optional[object] = None) -> None:
        """通用字幕生成（复用 BasePipeline.generate_subtitles_common）。"""
        if not getattr(self._state.subtitle_config, "enabled", True):
            return
        texts, durs = self._get_segment_texts_and_durations()
        srt_path, styles_path = await self.generate_subtitles_common(
            segment_texts=texts,
            segment_durations=durs,
            subtitle_config=self._state.subtitle_config,
            sub_maker=sub_maker,
            audio_path=self._state.combined_audio or "",
            screenwriter=self.screenwriter if hasattr(self, "screenwriter") else None,
            video_width=self._state.video_width,
            video_height=self._state.video_height,
        )
        self._set_subtitle_paths(srt_path, styles_path)

    # ==================================================================
    # 钩子方法（子类可覆盖）
    # ==================================================================

    def _get_init_message(self) -> str:
        return "开始视频生成..."

    def _get_narration_text(self) -> str:
        """配音文本。默认拼接各场景 narration_text。"""
        return "\n\n".join(
            s.narration_text for s in self._state.scenes if s.narration_text
        )

    def _get_segment_texts_and_durations(self) -> tuple:
        """字幕分段文本与时长。默认取各场景 narration_text + duration。"""
        texts = [s.narration_text for s in self._state.scenes if s.narration_text] \
            or [""]
        durs = [float(s.duration) for s in self._state.scenes if s.narration_text] \
            or [5.0]
        return texts, durs

    def _get_audio_path(self) -> str:
        """音频输出路径。子类可覆写（如稿件用 full_narration.mp3）。"""
        return os.path.join(self.working_dir, "combined_narration.mp3")

    def _get_scene_video_prompt(self, scene: SceneTask, index: int) -> str:
        """单场景视频 prompt。默认优先 end_frame_prompt，回退 scene_prompt。"""
        return getattr(scene, "end_frame_prompt", "") or getattr(scene, "scene_prompt", "")

    def _get_scene_ref_images(self, scene: SceneTask, index: int) -> List[str]:
        """单场景参考图列表。默认取 scene.ref_images。"""
        return list(getattr(scene, "ref_images", []) or [])

    def _get_scene_duration(self, scene: SceneTask, index: int) -> int:
        """单场景视频时长。默认 max(scene.duration, 3)。"""
        return max(int(getattr(scene, "duration", 5)), 3)

    def _set_subtitle_paths(self, srt_path: str, styles_path: str) -> None:
        """字幕路径写回 state。子类覆写以匹配各自字段名。"""
        self._state.combined_subtitle = srt_path
        if styles_path:
            self._state.subtitle_styles_path = styles_path
        self.task_manager.update_state(
            combined_subtitle=srt_path,
            subtitle_styles_path=styles_path or self._state.subtitle_styles_path,
        )
