# Pipeline 架构重构方案 v3.0

> 目标：将四种（+诗词视频）视频类型的 pipeline 统一到"多场景视频生成"的通用框架上，
> 通过步骤组合（Strategy Pattern）消除重复代码，提高新类型的扩展效率。

---

## 一、当前问题回顾

### 1.1 已有的好设计

| 组件 | 位置 | 状态 |
|------|------|------|
| `BasePipeline` 基础设施 | `__init__.py` | ✅ emit/shutdown/working_dir 完备 |
| `generate_subtitles_common()` | `__init__.py` | ✅ 字幕统一抽象，Manuscript/Anchor 复用 |
| `fix_double_utf8()` | `__init__.py` | ✅ 所有 pipeline 复用 |
| `save_prompts()` | `__init__.py` | ✅ 所有 pipeline 复用 |
| `get_audio_duration()` | `__init__.py` | ✅ 所有 pipeline 复用 |
| `_run_ffmpeg_async()` | `creative_video.py` | ⚠️ 好实现但仅在一处，应上提 |

### 1.2 当前重复清单

| 重复内容 | 出现次数 | 行数/次 | 总浪费 |
|---------|---------|---------|--------|
| `_check_shutdown()` | 3 | 3 | ~9 行 |
| `_make_curl()` | 4 | 3 | ~12 行 |
| 水印后处理块 | 4 | ~12 | ~48 行 |
| `task.json` 持久化 | 4 | ~15 | ~60 行 |
| TTS 音频生成（Edge→Silent 降级） | 3 | ~40 | ~120 行 |
| 视频 submit + wait + retry | 4 | ~25 | ~100 行 |
| 步骤执行模板（_run_step_*） | ~15 处 | ~15 | ~225 行 |
| `run()` 异常处理模板 | 4 | ~20 | ~80 行 |
| **合计** | | | **~654 行** |

---

## 二、核心洞察：统一工作流

所有视频类型的本质工作流是一致的：

```
输入 → [分镜/拆段] → [参考图生成] → [视频生成] → [配音+字幕] → [合成输出]
```

| 阶段 | 通用逻辑 | 各类型的差异点（信息源不同） |
|------|---------|--------------------------|
| **1. 分镜** | 产出 `List[SceneTask]` | Simple: 无（单场景）/ Creative: LLM 编剧 / Manuscript: 文本拆分 / Anchor: 单段循环 / Poetry: 用户手动或 LLM 生成 |
| **2. 参考图** | 为每个场景生成参考图（可选） | Creative: 角色参考 + 尾帧 / Anchor: 主播形象 / Poetry: 可选风格参考图 / Manuscript: 无 |
| **3. 视频生成** | submit → wait → download，两阶段并行 | 参数来源不同（prompt/duration/ref_images 来自不同字段） |
| **4. 配音+字幕** | EdgeTTS → 字幕叠加 | 文本来源不同（narration/script_text/manuscript） |
| **5. 合成输出** | 拼接+音频叠加+水印 | 合成方式不同（anchor 循环、普通拼接） |

**差异只在"数据从哪来"，不在"流程怎么做"。**

---

## 三、目标架构

```
BasePipeline (ABC)                           ← 基础设施层，不碰
│
└── MultiScenePipeline (ABC)                 ← ★ 新增：多场景视频通用框架
    │   ├── _build_scenes()       → 抽象     ← 各子类提供数据来源
    │   ├── _build_reference_images() → 抽象 ← 可选
    │   ├── _generate_videos()   → 具体     ← 通用视频生成（含 submit/wait/retry）
    │   ├── _generate_audio()    → 具体     ← 通用 TTS（含降级）
    │   ├── _generate_subtitles()→ 具体     ← 通用字幕（含 LLM 样式）
    │   └── _composite_final()   → 抽象     ← 合成方式不同
    │
    ├── CreativeVideoPipeline    ← 继承 MultiScenePipeline，实现 _build_scenes + _build_reference_images
    ├── ManuscriptVideoPipeline  ← 继承 MultiScenePipeline，实现 _build_scenes（拆分文本）
    ├── AnchorPipeline           ← 继承 MultiScenePipeline，实现 _build_scenes + _build_reference_images
    └── PoetryVideoPipeline      ← 继承 MultiScenePipeline，实现 _build_scenes（诗词→分镜）
    
    SimpleVideoPipeline           ← 独立继承 BasePipeline（不做多场景）
```

### 关键设计决策

1. **SimpleVideo 不继承 MultiScenePipeline** — 它是单场景、无任何预处理的特例，保持独立更干净
2. **MultiScenePipeline 的 `run()` 是模板方法** — 子类只提供数据源，不重写流程
3. **每种策略的差异通过 hook 方法注入**，不是通过 if/else

---

## 四、MultiScenePipeline 详细设计

### 4.1 类结构

```python
class MultiScenePipeline(BasePipeline):
    """多场景视频生成通用框架。
    
    模板方法 run() 定义标准流程：
        build_scenes → build_reference_images → generate_videos → audio+subtitle → composite
    
    子类只需实现 3 个抽象方法提供数据源，其余步骤自动复用。
    """

    # ═══════════════════════════════════════════════════════════════
    # 模板方法：run()
    # ═══════════════════════════════════════════════════════════════

    async def run(self, state: BaseTaskState) -> str:
        """标准多场景视频流程（模板方法）。"""
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        await self._emit("init", "running", self._get_init_message(), 0.0)

        try:
            # Phase 1: 分镜/拆段 → List[SceneTask]
            await self._execute_step("step_build_scenes", self._build_scenes,
                                     0.0, 0.15, "构建分镜", "分镜构建完成")

            # Phase 2: 参考图（可选，子类可跳过）
            await self._execute_step("step_reference_images",
                                     self._build_reference_images,
                                     0.15, 0.30, "生成参考图", "参考图生成完成")

            # Phase 3: 视频生成（通用）
            await self._execute_step("step_video_generation",
                                     self._generate_videos,
                                     0.30, 0.75, "生成视频", "视频生成完成")

            # Phase 4: 配音
            sub_maker = await self._execute_step("step_audio", self._generate_audio,
                                                  0.75, 0.85, "生成配音", "配音完成")

            # Phase 5: 字幕
            await self._execute_step("step_subtitle",
                                     lambda: self._generate_subtitles(sub_maker),
                                     0.85, 0.90, "生成字幕", "字幕完成")

            # Phase 6: 合成
            final_video = await self._execute_step("step_concatenation",
                                                    self._composite_final,
                                                    0.90, 0.98, "合成视频", "合成完成")

            # 后处理：水印
            final_video = self._apply_watermark(final_video)

            # 完成
            self._state.status = StepStatus.COMPLETED
            self._state.final_video_file = final_video
            self.task_manager.update_state(status=StepStatus.COMPLETED,
                                           final_video_file=final_video)
            await self._emit("done", "completed", "视频生成完成!", 1.0,
                             {"final_video": final_video})
            return final_video

        except PipelineShutdown:
            await self._emit("error", "failed", "任务已被中断，可从任务列表续传", 0.0)
            raise
        except Exception as e:
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(status=StepStatus.FAILED)
            await self._emit("error", "failed", str(e), 0.0)
            raise

    # ═══════════════════════════════════════════════════════════════
    # 子类必须实现（数据源）
    # ═══════════════════════════════════════════════════════════════

    @abstractmethod
    async def _build_scenes(self) -> None:
        """构建场景列表。产出 self._state.scenes（List[SceneTask]）。
        
        各类型的差异：
        - Creative: LLM 编剧 → story → script → scenes
        - Manuscript: 文本拆分 → paragraphs → scenes  
        - Anchor: 单场景（循环用）
        - Poetry: 诗词解析 → LLM 分镜 或 用户手动输入
        """
        ...

    @abstractmethod
    async def _build_reference_images(self) -> None:
        """构建参考图。产出 ref_images dict 或直接写入 scene 对象。
        
        子类可返回 None 表示跳过此阶段。
        - Creative: 角色参考图(t2i) + 尾帧预生成(i2i)
        - Anchor: 主播形象图(t2i)
        - Manuscript: 无（直接 return）
        - Poetry: 可选风格参考图
        """
        ...

    @abstractmethod
    async def _composite_final(self) -> str:
        """合成最终视频。返回视频路径。
        
        - Creative/Manuscript: concat_videos_with_audio_overlay
        - Anchor: composite_anchor_video（循环模式）
        - Poetry: concat_videos_with_audio_overlay
        """
        ...

    # ═══════════════════════════════════════════════════════════════
    # 钩子方法（子类可覆盖）
    # ═══════════════════════════════════════════════════════════════

    def _get_init_message(self) -> str:
        """run() 开始时的提示消息。默认 "开始视频生成..."。"""
        return "开始视频生成..."

    def _get_narration_text(self) -> str:
        """获取配音文本。默认从 state 的通用字段获取。"""
        return ""

    def _get_segment_texts_and_durations(self) -> tuple[List[str], List[float]]:
        """获取字幕分段的文本和时长。"""
        texts = [s.narration_text for s in self._state.scenes] if self._state.scenes else [""]
        durs = [float(s.duration) for s in self._state.scenes] if self._state.scenes else [5.0]
        return texts, durs

    def _get_watermark_language_text(self) -> str:
        """水印语言检测用文本。"""
        return ""

    # ═══════════════════════════════════════════════════════════════
    # 通用实现（所有子类共享）
    # ═══════════════════════════════════════════════════════════════

    async def _execute_step(self, step_name: str, action: Callable,
                            progress_start: float, progress_end: float,
                            running_msg: str, completed_msg: str):
        """统一的步骤执行器，自动处理断点续传、状态标记、进度上报。"""
        if getattr(self._state, step_name, StepStatus.PENDING) == StepStatus.COMPLETED:
            logger.info(f"[Pipeline] Step {step_name}: already completed, skipping")
            return None

        self.task_manager.update_step(step_name, StepStatus.RUNNING)
        await self._emit(step_name, "running", running_msg, progress_start)

        result = await action()

        self.task_manager.update_step(step_name, StepStatus.COMPLETED)
        await self._emit(step_name, "completed", completed_msg, progress_end)
        return result

    async def _generate_videos(self) -> None:
        """通用视频生成：两阶段（批量提交 + 逐个等待）。
        
        每个场景从 SceneTask 对象获取 prompt / duration / ref_images 等参数。
        子类负责在 _build_scenes / _build_reference_images 阶段填好这些字段。
        """
        scenes = self._state.scenes
        total = len(scenes)

        # Phase 1: 批量提交
        pending = []
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
            await self._emit("video_gen", "running",
                             f"等待视频 {j+1}/{len(pending)}...",
                             0.40 + 0.35 * j / max(len(pending), 1))
            video_output = await self._wait_for_video_with_retry(
                video_id, scene_idx, scene_dir=os.path.dirname(video_path))
            video_output.save(video_path)
            self._state.scenes[scene_idx].video_file = video_path
            self.task_manager.update_state(scenes=[s.model_dump() for s in self._state.scenes])

    async def _wait_for_video_with_retry(self, video_id: str, scene_idx: int,
                                          scene_dir: str, max_retries: int = 3) -> object:
        """带重试的视频等待。"""
        for retry in range(max_retries):
            try:
                return await self.video_api.wait_for_video(video_id)
            except Exception as e:
                if retry < max_retries - 1:
                    delay = 20 * (retry + 1)
                    logger.warning(f"Video {video_id[:16]} retry {retry+1}/{max_retries}: {e}")
                    await asyncio.sleep(delay)
                else:
                    # 清理 task.json 以便下次重试
                    tf = os.path.join(scene_dir, "task.json")
                    if os.path.exists(tf):
                        os.remove(tf)
                    raise

    async def _generate_audio(self) -> Optional[object]:
        """通用 TTS 音频生成（EdgeTTS → Silent 降级）。"""
        audio_path = os.path.join(self.working_dir, "combined_narration.mp3")
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            return None

        text = self._get_narration_text()
        if not text:
            return None

        total_duration = sum(float(s.duration) for s in self._state.scenes)
        audio_config = self._state.audio_config if hasattr(self._state, 'audio_config') \
                       else AudioConfig()

        edge_tts = EdgeTTSEngine()
        silent_tts = SilentTTSEngine()

        if audio_config.enabled:
            try:
                _, sub_maker = await edge_tts.generate(
                    text=text, output_path=audio_path,
                    voice=audio_config.voice, rate=audio_config.rate)
                return sub_maker
            except RuntimeError as e:
                logger.warning(f"EdgeTTS failed: {e}, falling back to silent")
                await silent_tts.generate(text=text, output_path=audio_path,
                                          duration_sec=total_duration)
        else:
            await silent_tts.generate(text=text, output_path=audio_path,
                                      duration_sec=total_duration)
        return None

    async def _generate_subtitles(self, sub_maker: Optional[object] = None) -> None:
        """通用字幕生成。"""
        if not self._state.subtitle_config.enabled:
            return
        texts, durs = self._get_segment_texts_and_durations()
        srt_path, styles_path = await self.generate_subtitles_common(
            segment_texts=texts, segment_durations=durs,
            subtitle_config=self._state.subtitle_config,
            sub_maker=sub_maker,
            audio_path=os.path.join(self.working_dir, "combined_narration.mp3"),
            screenwriter=self.screenwriter if hasattr(self, 'screenwriter') else None,
            video_width=self._state.video_width,
            video_height=self._state.video_height,
        )
        # 保持各 state 子类的字段名兼容
        self._set_subtitle_paths(srt_path, styles_path)

    def _apply_watermark(self, video_path: str) -> str:
        """通用水印后处理。"""
        wm_config = get_watermark_config()
        if not wm_config.get("enabled") or not os.path.exists(video_path):
            return video_path
        lang = wm_config.get("language", "auto")
        if lang == "auto":
            lang = detect_language(self._get_watermark_language_text())
        wm_output = video_path + ".wm_tmp.mp4"
        if add_watermark(video_path, wm_output, language=lang):
            os.replace(wm_output, video_path)
        return video_path

    # ═══════════════════════════════════════════════════════════════
    # 通用工具（上提）
    # ═══════════════════════════════════════════════════════════════

    def _check_shutdown(self) -> None:
        if self._is_shutdown():
            raise PipelineShutdown("Pipeline shutdown requested")

    @staticmethod
    def _make_curl(video_id: str) -> str:
        return (f'curl -s -H "Authorization: Bearer $AGNES_API_KEY" '
                f'"https://apihub.agnes-ai.com/agnesapi?video_id={video_id}"')

    def _save_task_json(self, sub_dir: str, data: dict) -> None:
        os.makedirs(sub_dir, exist_ok=True)
        with open(os.path.join(sub_dir, "task.json"), "w") as f:
            json.dump(data, f, indent=2)
        curl_file = os.path.join(sub_dir, "curl.sh")
        with open(curl_file, "w") as f:
            f.write(self._make_curl(data.get("video_id", "")) + "\n")

    def _load_task_json(self, sub_dir: str) -> Optional[str]:
        tf = os.path.join(sub_dir, "task.json")
        if os.path.exists(tf):
            try:
                with open(tf, "r") as f:
                    data = json.load(f)
                return data.get("video_id") or data.get("task_id")
            except Exception:
                pass
        return None

    # ═══════════════════════════════════════════════════════════════
    # 视频阶段钩子（子类按需覆盖）
    # ═══════════════════════════════════════════════════════════════

    def _get_scene_video_prompt(self, scene: SceneTask, index: int) -> str:
        """获取场景的视频 prompt。默认从 scene 对象取。"""
        return getattr(scene, 'end_frame_prompt', '') or getattr(scene, 'scene_prompt', '')

    def _get_scene_ref_images(self, scene: SceneTask, index: int) -> List[str]:
        """获取场景的参考图列表。"""
        return []

    def _get_scene_duration(self, scene: SceneTask, index: int) -> int:
        """获取场景视频时长。"""
        return max(int(scene.duration), 3)

    def _set_subtitle_paths(self, srt_path: str, styles_path: str) -> None:
        """设置字幕路径到 state。子类覆盖以匹配各自的字段名。"""
        pass
```

### 4.2 各子类的改造

#### CreativeVideoPipeline

```python
class CreativeVideoPipeline(MultiScenePipeline):
    """创意长视频 — LLM 编剧全自动生成。"""
    
    def __init__(self, ...):
        super().__init__(...)
        self.screenwriter = Screenwriter(...)
        self.image_generator = AgnesImageAPI(...)
        self.video_api = AgnesVideoAPI(...)
    
    async def _build_scenes(self):
        # 包含原有: resolve_scene_config → image_analysis → story → 
        #           character_reference → script → end_frame_prompts
        # 最终产出: self._state.scenes (List[SceneTask])
        ...
    
    async def _build_reference_images(self):
        # 包含原有: character_ref 生成 + end_frame 预生成
        ...
    
    async def _composite_final(self) -> str:
        # concat_videos_with_audio_overlay
        ...
    
    def _get_narration_text(self):
        return self._state.narrations[0] if self._state.narrations else ""
    
    def _get_watermark_language_text(self):
        return self._state.idea
```

#### ManuscriptVideoPipeline

```python
class ManuscriptVideoPipeline(MultiScenePipeline):
    """稿件长视频 — 用户粘贴文本，自动拆段+生成。"""
    
    async def _build_scenes(self):
        # 原有: split_text → generate_scene_prompts
        # 产出: scenes (每段为一个 scene)
        ...
    
    async def _build_reference_images(self):
        return  # Manuscript 无参考图阶段
    
    async def _composite_final(self) -> str:
        # concat_videos_with_audio_overlay
        ...
    
    def _get_narration_text(self):
        return self._state.manuscript_text
    
    def _get_watermark_language_text(self):
        return self._state.manuscript_text
    
    def _get_scene_video_prompt(self, scene, index):
        # Manuscript 的 prompt 来源：paragraph.scene_prompt
        para = self._state.paragraphs[index]
        return para.scene_prompt
    
    def _get_scene_duration(self, scene, index):
        para = self._state.paragraphs[index]
        return max(int(math.ceil(len(para.text) / _CHARS_PER_SEC)), 3)
```

#### AnchorPipeline

```python
class AnchorPipeline(MultiScenePipeline):
    """数字人口播 — 循环单段视频。"""

    async def _build_scenes(self):
        # 单场景（循环用）
        self._state.scenes = [SceneTask(index=0, duration=5)]
    
    async def _build_reference_images(self):
        # 生成主播形象图
        await self._step_generate_anchor()
    
    async def _composite_final(self) -> str:
        # composite_anchor_video（循环模式）
        ...
    
    # 覆盖 _generate_videos 跳过，因为 Anchor 的视频生成逻辑特殊
    async def _generate_videos(self):
        # 单段 i2v + 循环逻辑，不走通用视频生成
        ...
```

#### PoetryVideoPipeline（新增）

```python
class PoetryVideoPipeline(MultiScenePipeline):
    """诗词视频 — 古诗内容生成视频。
    
    输入: 古诗原文 + 可选的分镜描述
    流程: 诗词解析 → 分镜生成(LLM或用户手动) → 参考图 → 视频 → 配音(原诗朗读) + 字幕(原诗)
    """
    
    def __init__(self, ...):
        super().__init__(...)
        self.screenwriter = Screenwriter(...)
        self.image_generator = AgnesImageAPI(...)
        self.video_api = AgnesVideoAPI(...)
    
    async def _build_scenes(self):
        """从诗词生成分镜。
        
        两种模式:
        - manual: 用户已在 request 中提供了 scene_descriptions
        - llm: 调用 screenwriter 解析诗词并生成分镜
        """
        if self._state.scene_source == "manual" and self._state.scene_descriptions:
            # 用户手动输入的分镜
            self._state.scenes = [
                SceneTask(index=i, duration=d, 
                          narration_text=desc,
                          end_frame_prompt=desc)
                for i, (d, desc) in enumerate(zip(
                    self._state.scene_durations, 
                    self._state.scene_descriptions
                ))
            ]
        else:
            # LLM 生成分镜
            scenes_raw = await asyncio.to_thread(
                self.screenwriter.generate_poetry_scenes,
                poem=self._state.poem_text,
                scene_count=self._state.scene_count,
                style=self._state.style,
            )
            self._state.scenes = [
                SceneTask(index=i, duration=d,
                          narration_text=s.get("scene_description", ""),
                          end_frame_prompt=s.get("visual_prompt", ""))
                for i, (s, d) in enumerate(zip(scenes_raw, self._state.scene_durations))
            ]
        
        self.task_manager.update_state(scenes=[s.model_dump() for s in self._state.scenes])
    
    async def _build_reference_images(self):
        """可选：为诗词生成统一的风格参考图。"""
        if not self._state.generate_style_ref:
            return
        # 基于诗词意境生成一张风格参考图
        ...
    
    async def _composite_final(self) -> str:
        return os.path.join(self.working_dir, "final_video.mp4")
        # 由通用框架调用 concat_videos_with_audio_overlay
    
    def _get_narration_text(self) -> str:
        # 配音是古诗原文
        return self._state.poem_text
    
    def _get_watermark_language_text(self) -> str:
        return self._state.poem_text
    
    def _get_init_message(self) -> str:
        return "开始诗词视频生成..."

    def _get_segment_texts_and_durations(self):
        # 字幕每句诗词分开
        lines = [l.strip() for l in self._state.poem_text.replace("，", "，\n").replace("。", "。\n").split("\n") if l.strip()]
        durs = [5.0] * len(lines)  # 均匀分配
        return lines, durs
```

---

## 五、需要新增/修改的模型

### PoetryVideoTask（新增）

```python
class PoetryVideoTask(BaseTaskState):
    """诗词视频任务"""
    task_type: Literal["poetry"] = "poetry"  # 新增 TaskType.POETRY

    # 用户输入
    poem_text: str = ""                    # 古诗原文
    style: str = "中国风水墨画"             # 视觉风格
    scene_source: str = "llm"             # "llm" | "manual"
    scene_count: int = 4
    scene_durations: List[int] = Field(default_factory=lambda: [5, 5, 5, 5])
    scene_descriptions: List[str] = Field(default_factory=list)  # manual 模式用

    # 可选
    generate_style_ref: bool = True         # 是否生成风格参考图
    style_ref_file: str = ""

    # 配置
    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    subtitle_config: SubtitleConfig = Field(default_factory=SubtitleConfig)

    # 步骤状态
    step_build_scenes: StepStatus = StepStatus.PENDING
    step_reference_images: StepStatus = StepStatus.PENDING
    step_video_generation: StepStatus = StepStatus.PENDING
    step_audio: StepStatus = StepStatus.PENDING
    step_subtitle: StepStatus = StepStatus.PENDING
    step_concatenation: StepStatus = StepStatus.PENDING

    # 产物
    scenes: List[SceneTask] = Field(default_factory=list)
    combined_audio: str = ""
    combined_subtitle: str = ""
    subtitle_styles_path: str = ""
    final_video_file: str = ""

    # 实时进度
    current_step: str = ""
    current_status: str = ""
    current_progress: float = 0.0
    current_message: str = ""
```

### SceneTask 补充字段

```python
class SceneTask(BaseModel):
    """场景任务 — 通用模型，所有多场景 pipeline 共用。"""
    index: int
    duration: int = 5
    status: StepStatus = StepStatus.PENDING

    # 视频相关
    video_id: str = ""
    video_status: StepStatus = StepStatus.PENDING
    video_file: str = ""

    # 提示词（各类型来源不同，统一存这里）
    scene_prompt: str = ""          # 场景视觉描述（Manuscript / Poetry 用）
    end_frame_prompt: str = ""      # 尾帧 prompt（Creative 用）
    end_frame_file: str = ""        # 尾帧图片路径

    # 参考图（视频生成用）
    ref_images: List[str] = Field(default_factory=list)

    # 音频/字幕
    narration_text: str = ""        # 旁白文本（或诗词原文）
    narration_audio: str = ""
    subtitle_srt: str = ""
    final_clip: str = ""
```

---

## 六、实施计划

### Phase 1: 基础设施上提（风险最低，改得最少）

| 序号 | 改动 | 影响文件 |
|------|------|---------|
| 1.1 | `_check_shutdown()` 上提到 `BasePipeline` | `__init__.py` + 删除 3 处重复 |
| 1.2 | `_make_curl()` 上提到 `BasePipeline` | `__init__.py` + 删除 4 处重复 |
| 1.3 | `_run_ffmpeg_async()` 上提到 `BasePipeline` | `__init__.py` + `creative_video.py` |
| 1.4 | `_save_task_json()` / `_load_task_json()` 上提到 `BasePipeline` | `__init__.py` + 所有 pipeline |
| 1.5 | `_apply_watermark()` 上提到 `BasePipeline` | `__init__.py` + 删除 4 处重复 |

**预计消重：~150 行**

### Phase 2: 创建 MultiScenePipeline

| 序号 | 改动 | 影响文件 |
|------|------|---------|
| 2.1 | 新建 `core/pipelines/multi_scene.py` | 新文件 |
| 2.2 | 实现模板方法 `run()` | `multi_scene.py` |
| 2.3 | 实现 `_execute_step()` 步骤包装器 | `multi_scene.py` |
| 2.4 | 实现通用 `_generate_videos()` | `multi_scene.py` |
| 2.5 | 实现通用 `_generate_audio()` | `multi_scene.py` |
| 2.6 | 实现通用 `_generate_subtitles()` | `multi_scene.py` |

**预计新增：~300 行，后续消重：~400 行**

### Phase 3: 改造现有 Pipeline 为子类

| 序号 | 改动 | 影响文件 |
|------|------|---------|
| 3.1 | `CreativeVideoPipeline` 继承 `MultiScenePipeline` | `creative_video.py`（大幅精简） |
| 3.2 | `ManuscriptVideoPipeline` 继承 `MultiScenePipeline` | `manuscript_video.py`（大幅精简） |
| 3.3 | `AnchorPipeline` 继承 `MultiScenePipeline` | `anchor_video.py`（大幅精简） |

**预计净减少：~600 行**

### Phase 4: 新增 PoetryVideoPipeline

| 序号 | 改动 | 影响文件 |
|------|------|---------|
| 4.1 | 新增 `PoetryVideoTask` 模型 | `models/task.py` |
| 4.2 | 新增 `PoetryVideoPipeline` | `core/pipelines/poetry_video.py`（~120 行） |
| 4.3 | 新增 API 路由 `/api/tasks/poetry` | `server.py` |
| 4.4 | 新增前端表单 | `static/index.html` |
| 4.5 | 新增 Screenwriter 方法 | `core/screenwriter.py`（`generate_poetry_scenes()`） |

**预计新增：~200 行**

### Phase 5: SceneTask 统一

| 序号 | 改动 | 影响文件 |
|------|------|---------|
| 5.1 | `ManuscriptVideoTask.paragraphs` → `scenes: List[SceneTask]` | `models/task.py` + `manuscript_video.py` |
| 5.2 | 统一 `combined_audio` / `combined_subtitle` 字段到 `BaseTaskState` | `models/task.py` |

---

## 七、风险与收益

| 维度 | 评估 |
|------|------|
| **代码行数变化** | +300 (MultiScenePipeline) - 650 (重复删除) - 600 (子类精简) ≈ **净减 ~950 行** |
| **新增类型成本** | 从 ~550 行 (Anchor) 降至 ~120 行 (Poetry)，**降低 78%** |
| **回归风险** | 中等 — Phase 1 纯上提零风险；Phase 2-3 需逐类型回归验证 |
| **测试策略** | 每种类型创建一条任务跑通全流程即可验证 |
| **向后兼容** | `task.json` 旧数据需确保 `parse_task_state()` 兼容 |

---

## 八、最终文件结构

```
core/pipelines/
├── __init__.py              # BasePipeline + MultiScenePipeline + 导出
├── multi_scene.py           # MultiScenePipeline 核心（模板方法 + 通用步骤）
├── simple_video.py          # SimpleVideoPipeline（独立，~80 行）
├── creative_video.py        # CreativeVideoPipeline（仅分镜+参考图，~250 行）
├── manuscript_video.py      # ManuscriptVideoPipeline（仅分镜，~150 行）
├── anchor_video.py          # AnchorPipeline（仅分镜+循环合成，~200 行）
└── poetry_video.py          # PoetryVideoPipeline（新增，~120 行）
```
