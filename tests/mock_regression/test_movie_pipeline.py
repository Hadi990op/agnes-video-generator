"""tests.mock_regression.test_movie_pipeline — MovieVideoPipeline 回归测试

电影模式（类型 8 / v7.0）全流程回归：
  剧本分析 → 制作圣经 → 镜头拆解 → canon 参考图 → 逐镜头视频 → 拼接

历史 bug（本测试守护）：
  - LLM 调用（chat_json 为同步 requests.post）未放线程池 → 事件循环假死
  - LLM 失败静默返回空 bible/shots → 到合成阶段才以
    "没有可拼接的镜头视频"失败，无从定位
  - 图片 out.save() 在 url 模式下同步下载 → 阻塞事件循环
"""

import os
import pytest

from core.pipelines.movie_video import MovieVideoPipeline
from models.task import MovieVideoTask, StepStatus
from tests.mock_regression.mock_apis import MockAgnesChatAPI


def _make_state():
    return MovieVideoTask(
        task_id="movie_test_001",
        creative_name="movie_test",
        script_text=(
            "INT. COFFEE SHOP - DAY\n\n"
            "LINA sits alone. RAIN pours outside the window.\n\n"
            "LINA: I never thought I'd see you again."
        ),
        max_shots=3,
        video_width=768,
        video_height=1152,
    )


class TestMovieVideoPipeline:

    @pytest.fixture
    def movie_state(self):
        return _make_state()

    async def _make_pipeline(self, temp_workdir, state):
        pipeline = MovieVideoPipeline(
            api_key="mock_key",
            task_id="movie_test_001",
            dir_name=temp_workdir,
        )
        return pipeline

    async def test_movie_basic(self, temp_workdir, movie_state):
        """Movie pipeline 全流程：bible -> shots -> refs -> videos -> composite。"""
        pipeline = await self._make_pipeline(temp_workdir, movie_state)
        final_video = await pipeline.run(movie_state)

        # 1. 最终视频存在且非空
        assert os.path.exists(final_video)
        assert os.path.getsize(final_video) > 0

        # 2. 状态标记
        assert movie_state.status == StepStatus.COMPLETED
        assert movie_state.final_video_file == final_video

        # 3. 制作圣经 / 镜头计划已构建并持久化
        assert movie_state.production_bible, "production bible should be built"
        assert movie_state.shot_plan, "shot plan should be built"
        assert os.path.exists(os.path.join(temp_workdir, "production_bible.json"))
        assert os.path.exists(os.path.join(temp_workdir, "shot_plan.json"))

        # 4. 场景全部生成（fixture movie_shots.json 有 2 个镜头）
        assert len(movie_state.scenes) == 2
        for scene in movie_state.scenes:
            assert scene.video_file and os.path.exists(scene.video_file)

        # 5. canon 参考图已生成
        assert movie_state.character_refs or movie_state.location_refs

    async def test_movie_max_shots_cap(self, temp_workdir, movie_state):
        """max_shots cap：只生成前 N 个镜头。"""
        movie_state.max_shots = 1
        pipeline = await self._make_pipeline(temp_workdir, movie_state)
        await pipeline.run(movie_state)

        # cap 生效：生成 1 个镜头（原始计划 2 个）
        assert len(movie_state.scenes) == 1
        # 但 shot_plan 保留完整 2 镜（用于续传）
        assert len(movie_state.shot_plan) == 2

    async def test_movie_llm_failure_raises_early(self, temp_workdir, movie_state):
        """LLM 返回空 bible → 应尽早失败，而不是合成阶段 '没有可拼接的镜头视频'。"""
        chat = MockAgnesChatAPI()
        original = chat.chat_json

        def _empty_json(system_prompt, user_prompt, max_tokens=4096):
            return {}

        chat.chat_json = _empty_json
        pipeline = await self._make_pipeline(temp_workdir, movie_state)
        pipeline.chat_api = chat

        with pytest.raises(RuntimeError) as exc_info:
            await pipeline.run(movie_state)
        # 失败信息应指明是剧本分析阶段的问题
        assert "剧本分析" in str(exc_info.value)

    async def test_movie_audio_subtitles_disabled(
        self, temp_workdir, movie_state, monkeypatch
    ):
        """电影模式禁用本地 TTS/字幕：_generate_audio/_generate_subtitles 为 no-op。"""
        pipeline = await self._make_pipeline(temp_workdir, movie_state)
        result = await pipeline._generate_audio()
        assert result is None
        await pipeline._generate_subtitles(None)  # 不应抛异常
