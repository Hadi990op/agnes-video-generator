"""core.pipelines.movie_video — AI 电影制作智能体流水线（类型 8 / v7.0）。

流程（继承 MultiScenePipeline 模板）：
  _build_scenes          → 剧本分析 → 制作圣经 → 镜头拆解（LLM）→ 生成镜头计划
  _build_reference_images → 生成角色/场景 canon 参考图（一致性锚点）
  _generate_videos       → 逐镜头 i2v（复用 canon 参考图，并行提交）
  _generate_audio        → 逐镜头对话 TTS（EdgeTTS，通用实现）
  _generate_subtitles    → 字幕（通用实现）
  _composite_final       → 拼接为完整影片 + 音频 + 字幕

设计原则（§73）：制作圣经与镜头计划持久化到 working_dir，续传时直接复用，
不重复调用 LLM；canon 参考图已存在则跳过生成。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import List, Optional

from core.api.agnes_chat import AgnesChatAPI
from core.api.agnes_image import AgnesImageAPI
from core.api.agnes_video import AgnesVideoAPI
from core.compositor.concatenator import VideoConcatenator
from core.pipelines import MultiScenePipeline, PipelineShutdown
from core.production.bible_builder import ProductionBibleBuilder, compose_shot_prompt
from core.screenwriter import Screenwriter
from models.task import MovieVideoTask, SceneTask, StepStatus

logger = logging.getLogger(__name__)

_PROGRESS_CONCAT_START = 0.80


def _sanitize(name: str) -> str:
    s = re.sub(r"[^\w一-鿿]+", "_", name or "x")
    return s[:40]


class MovieVideoPipeline(MultiScenePipeline):
    """AI 电影制作智能体：把剧本变成结构化、具备连续性的长片。"""

    # 关闭粗粒度 skip：便于 cap 调整后续传补充镜头，且每步内部已做文件级续传
    coarse_skip: bool = False

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: Optional[str] = None,
        chat_model: str = "agnes-2.0-flash",
        image_model: str = "agnes-image-2.1-flash",
        video_model: str = "agnes-video-v2.0",
        progress_callback=None,
        shutdown_event=None,
    ):
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)
        self.video_api = AgnesVideoAPI(api_key=api_key, model=video_model)
        self.video_api.shutdown_event = shutdown_event
        self.screenwriter = Screenwriter(api_key=api_key, model=chat_model)
        self.image_generator = AgnesImageAPI(api_key=api_key, model=image_model)
        self.chat_api = AgnesChatAPI(api_key=api_key, model=chat_model)
        self._state: Optional[MovieVideoTask] = None

    # ------------------------------------------------------------------
    # 阶段一：分析 + 制作圣经 + 镜头拆解
    # ------------------------------------------------------------------

    async def _build_scenes(self) -> None:
        working_dir = self.working_dir
        bible_path = os.path.join(working_dir, "production_bible.json")
        shots_path = os.path.join(working_dir, "shot_plan.json")

        bible = None
        shots: list = []
        if os.path.exists(bible_path) and os.path.exists(shots_path):
            try:
                with open(bible_path, encoding="utf-8") as f:
                    bible = json.load(f)
                with open(shots_path, encoding="utf-8") as f:
                    shots = json.load(f)
            except Exception:
                bible, shots = None, []

        if not bible or not shots:
            await self._emit("build_scenes", "running", "分析剧本，构建制作圣经...", 0.02)
            builder = ProductionBibleBuilder(self.chat_api)
            bible = await builder.analyze_script(
                self._state.script_text, self._state.visual_style_preset
            )
            shots = await builder.build_shot_breakdown(bible)
            try:
                issues = await builder.validate_continuity(bible, shots)
                bible["continuity_issues"] = issues
                if issues:
                    logger.warning("[Movie] continuity issues: %s", issues)
            except Exception as e:
                logger.warning("[Movie] continuity validation failed: %s", e)

            with open(bible_path, "w", encoding="utf-8") as f:
                json.dump(bible, f, ensure_ascii=False, indent=2)
            with open(shots_path, "w", encoding="utf-8") as f:
                json.dump(shots, f, ensure_ascii=False, indent=2)

        self._state.production_bible = bible
        self._state.shot_plan = shots

        # 应用 cap（max_scenes / max_shots），保留原始索引用于镜头目录映射
        selected = self._select_shot_indices(shots)
        scenes: list = []
        for idx in selected:
            shot = shots[idx]
            prompt = compose_shot_prompt(shot, bible, self._state.visual_style_preset)
            scenes.append(
                SceneTask(
                    index=idx,
                    scene_prompt=prompt,
                    narration_text=shot.get("dialogue", "") or "",
                    duration=shot.get("duration", 8),
                    ref_images=[],
                )
            )
        self._state.scenes = scenes
        self.task_manager.update_state(
            scenes=[s.model_dump() for s in scenes],
            production_bible=bible,
            shot_plan=shots,
        )
        await self._emit(
            "build_scenes", "completed",
            f"镜头拆解完成（计划 {len(shots)} 镜，本批生成 {len(scenes)} 镜）",
            0.15,
        )

    def _select_shot_indices(self, shots: list) -> list:
        total = len(shots)
        max_shots = self._state.max_shots
        max_scenes = self._state.max_scenes
        if max_shots and max_shots > 0:
            return list(range(min(total, max_shots)))
        if max_scenes and max_scenes > 0:
            seen = []
            idxs = []
            for i, sh in enumerate(shots):
                sc = sh.get("scene_id")
                if sc not in seen:
                    if len(seen) >= max_scenes:
                        break
                    seen.append(sc)
                idxs.append(i)
            return idxs
        return list(range(total))

    # ------------------------------------------------------------------
    # 阶段二：canon 参考图（一致性锚点）
    # ------------------------------------------------------------------

    async def _build_reference_images(self) -> None:
        working_dir = self.working_dir
        refs_dir = os.path.join(working_dir, "refs")
        os.makedirs(refs_dir, exist_ok=True)

        bible = self._state.production_bible or {}
        char_refs = dict(self._state.character_refs or {})
        loc_refs = dict(self._state.location_refs or {})
        style = self._state.visual_style_preset
        size = f"{self._state.video_width}x{self._state.video_height}"

        await self._emit("reference_images", "running", "生成角色/场景 canon 参考图...", 0.18)

        # 角色：front portrait + full-body
        for ch in bible.get("characters", []):
            name = ch.get("name", "")
            if name and char_refs.get(name):
                continue
            desc = ch.get("description", "")
            imgs = []
            for view in ("front portrait", "full-body"):
                prompt = f"{style}. {desc}. {view}, consistent character design, high detail, centered."
                try:
                    out = await self.image_generator.generate_single_image(prompt=prompt, size=size)
                    p = os.path.join(refs_dir, f"char_{_sanitize(name)}_{view.replace(' ', '_')}.png")
                    out.save(p)
                    imgs.append(p)
                except Exception as e:
                    logger.warning("[Movie] character ref failed %s/%s: %s", name, view, e)
            if imgs:
                char_refs[name] = imgs

        # 场景：establishing
        for loc in bible.get("locations", []):
            name = loc.get("name", "")
            if name and loc_refs.get(name):
                continue
            desc = loc.get("description", "")
            prompt = f"{style}. {desc}. establishing shot, wide angle, cinematic lighting."
            try:
                out = await self.image_generator.generate_single_image(prompt=prompt, size=size)
                p = os.path.join(refs_dir, f"loc_{_sanitize(name)}.png")
                out.save(p)
                loc_refs[name] = [p]
            except Exception as e:
                logger.warning("[Movie] location ref failed %s: %s", name, e)

        self._state.character_refs = char_refs
        self._state.location_refs = loc_refs
        self.task_manager.update_state(character_refs=char_refs, location_refs=loc_refs)

        # 把 canon 图映射到每个镜头的参考图（主角色 face 作为 i2v 一致性锚点）
        shots = self._state.shot_plan or []
        for scene in self._state.scenes:
            shot = shots[scene.index] if scene.index < len(shots) else {}
            refs: list = []
            chars = shot.get("characters", [])
            if chars:
                refs += (char_refs.get(chars[0]) or [])[:1]
            elif shot.get("location") and shot["location"] in loc_refs:
                refs += (loc_refs[shot["location"]] or [])[:1]
            scene.ref_images = refs

        self.task_manager.update_state(scenes=[s.model_dump() for s in self._state.scenes])
        await self._emit("reference_images", "completed", "canon 参考图生成完成", 0.30)

    # ------------------------------------------------------------------
    # 阶段六：拼接为完整影片
    # ------------------------------------------------------------------

    async def _composite_final(self) -> str:
        subtitle_config = self._state.subtitle_config
        output_path = os.path.join(self.working_dir, "final_video.mp4")
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info("[Movie] composite: final video already exists, skipping")
            return output_path
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass

        video_paths = [
            s.video_file for s in self._state.scenes
            if s.video_file and os.path.exists(s.video_file)
        ]
        if not video_paths:
            raise RuntimeError("[Movie] 没有可拼接的镜头视频")

        has_audio = self._state.audio_config.enabled and bool(self._state.combined_audio)
        has_subtitle = subtitle_config.enabled and bool(self._state.combined_subtitle)

        await self._emit(
            "concatenate", "running",
            f"拼接 {len(video_paths)} 个镜头视频...", _PROGRESS_CONCAT_START,
        )

        if has_audio or has_subtitle:
            await asyncio.to_thread(
                VideoConcatenator.concat_videos_with_audio_overlay,
                video_paths=video_paths,
                audio_path=self._state.combined_audio or "",
                srt_path=self._state.combined_subtitle if has_subtitle else None,
                output_path=output_path,
                subtitle_style=subtitle_config.style if has_subtitle else None,
                subtitle_styles_path=self._state.subtitle_styles_path or "",
            )
        else:
            await asyncio.to_thread(
                VideoConcatenator.concat_videos, video_paths, output_path
            )

        logger.info("[Movie] composite: final video → %s", output_path)
        return output_path
