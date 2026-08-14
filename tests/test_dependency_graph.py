"""
v6.0 手动模式 — P1 产物依赖图单测（core/dependency_graph.py）

覆盖（对应 docs/plans/v6.0/implementation_plan.md §5.3）：
- 字段级粒度：改 scene_prompt / narration_text 影响不同下游
- 场景级通配：改 scene:{i}/video.mp4 仅影响 audio/subtitle/final
- 产物级：改 character_reference.png / srt
- 参数级：param_updates 按 PARAM_EDGES 计算
- 去重 / 传递闭包 / 越界容错
- checkpoint 级映射

用法:
    .venv/bin/python -m pytest tests/test_dependency_graph.py -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _make_creative_state(scene_count: int = 3):
    """构造 creative 任务状态（scenes 数量可配）。"""
    from models.task import CreativeVideoTask, SceneTask, TaskType

    state = CreativeVideoTask(task_id="t", creative_name="t", task_type=TaskType.CREATIVE)
    state.scenes = [SceneTask(index=i) for i in range(scene_count)]
    return state


def _make_manuscript_state(paragraph_count: int = 2):
    from models.task import ManuscriptParagraph, ManuscriptVideoTask, TaskType

    state = ManuscriptVideoTask(task_id="t", creative_name="t", task_type=TaskType.MANUSCRIPT)
    state.paragraphs = [ManuscriptParagraph(index=i, text=f"p{i}") for i in range(paragraph_count)]
    return state


class TestCreativeFieldLevel:
    """字段级粒度：同一产物的不同字段影响不同下游。"""

    def test_scene_prompt_affects_ref_videos_final_only(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(3)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, ["creative:script:scene_prompt"])

        # 影响：ref 图 / videos / final（audio/subtitle 保留）
        assert "creative:end_frame:0" in plan.affected
        assert "creative:video:0" in plan.affected
        assert "creative:final_video" in plan.affected
        # 保留
        assert "creative:audio" in plan.retained
        assert "creative:subtitle" in plan.retained

    def test_narration_text_affects_audio_subtitle_final_only(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(3)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, ["creative:script:narration_text"])

        assert "creative:audio" in plan.affected
        assert "creative:subtitle" in plan.affected
        assert "creative:final_video" in plan.affected
        # 保留 ref 图 / videos
        assert "creative:end_frame:0" in plan.retained
        assert "creative:video:0" in plan.retained

    def test_whole_script_affects_everything_downstream(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, ["creative:script"])

        # 整个 script 改了 → 字段级并集
        assert "creative:end_frame:0" in plan.affected
        assert "creative:video:0" in plan.affected
        assert "creative:audio" in plan.affected
        assert "creative:subtitle" in plan.affected
        assert "creative:final_video" in plan.affected


class TestScopedArtifacts:
    """场景级产物：scope 通配。"""

    def test_video_affects_audio_subtitle_final(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(3)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, ["creative:video:1"])

        # 自身 + audio/subtitle/final
        assert "creative:video:1" in plan.affected
        assert "creative:audio" in plan.affected
        assert "creative:subtitle" in plan.affected
        assert "creative:final_video" in plan.affected
        # 其他场景视频保留
        assert "creative:video:0" in plan.retained
        assert "creative:video:2" in plan.retained

    def test_all_videos_modification(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(3)
        graph = get_dependency_graph(TaskType.CREATIVE)
        # 无 index → 全部场景视频
        plan = graph.compute_impact(state, ["creative:video"])

        assert "creative:video:0" in plan.affected
        assert "creative:video:1" in plan.affected
        assert "creative:video:2" in plan.affected

    def test_character_ref_affects_videos_final(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, ["creative:character_ref"])

        assert "creative:video:0" in plan.affected
        assert "creative:video:1" in plan.affected
        assert "creative:final_video" in plan.affected
        assert "creative:audio" in plan.retained
        assert "creative:subtitle" in plan.retained

    def test_subtitle_affects_final_only(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, ["creative:subtitle"])

        assert "creative:final_video" in plan.affected
        assert "creative:video:0" in plan.retained
        assert "creative:audio" in plan.retained


class TestParamUpdates:
    """任务参数级依赖。"""

    def test_resolution_affects_videos_audio_subtitle_final(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, [], {"resolution": "768x1152"})

        assert "creative:video:0" in plan.affected
        assert "creative:video:1" in plan.affected
        assert "creative:audio" in plan.affected
        assert "creative:subtitle" in plan.affected
        assert "creative:final_video" in plan.affected
        # 不改 script / ref 图
        assert "creative:script" in plan.retained
        assert "creative:character_ref" in plan.retained

    def test_audio_voice_affects_audio_subtitle_final(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, [], {"audio_voice": "en-US-JennyNeural"})

        assert "creative:audio" in plan.affected
        assert "creative:subtitle" in plan.affected
        assert "creative:final_video" in plan.affected
        assert "creative:video:0" in plan.retained

    def test_unknown_param_ignored(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, [], {"no_such_param": 1})

        assert plan.affected == []  # 无副作用


class TestRobustness:
    """去重 / 传递闭包 / 越界容错。"""

    def test_duplicate_modified_deduped(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(
            state,
            ["creative:video:0", "creative:video:0", "creative:subtitle"],
        )
        # 无重复
        assert len(plan.affected) == len(set(plan.affected))

    def test_unknown_artifact_id_ignored(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, ["creative:no_such_thing"])
        assert plan.affected == []

    def test_wrong_task_type_id_ignored(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        # manuscript id 用于 creative 任务 → 忽略
        plan = graph.compute_impact(state, ["manuscript:video:0"])
        assert plan.affected == []

    def test_empty_modified(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, [])
        assert plan.affected == []
        assert len(plan.retained) > 0

    def test_steps_to_reset_mapping(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, ["creative:subtitle"])
        # 字幕 → 重置 step_subtitle + step_concatenation
        assert "step_subtitle" in plan.steps_to_reset
        assert "step_concatenation" in plan.steps_to_reset


class TestCheckpointMapping:
    """检查点级映射。"""

    def test_affected_checkpoints(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_creative_state(2)
        graph = get_dependency_graph(TaskType.CREATIVE)
        plan = graph.compute_impact(state, ["creative:video:1"])
        assert "videos" in plan.affected_checkpoints
        assert "audio" in plan.affected_checkpoints
        assert "final" in plan.affected_checkpoints

    def test_checkpoint_edges(self):
        from core.dependency_graph import checkpoint_edges

        edges = checkpoint_edges()
        assert "scenes" in edges
        assert "final" in edges
        assert edges["final"] == []
        assert "videos" in edges["scenes"]


class TestManuscript:
    """manuscript 任务类型。"""

    def test_scene_prompts_affects_videos_downstream(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_manuscript_state(2)
        graph = get_dependency_graph(TaskType.MANUSCRIPT)
        plan = graph.compute_impact(state, ["manuscript:scene_prompts"])

        assert "manuscript:video:0" in plan.affected
        assert "manuscript:audio" in plan.affected
        assert "manuscript:final_video" in plan.affected

    def test_video_affects_audio_subtitle_final(self):
        from core.dependency_graph import get_dependency_graph
        from models.task import TaskType

        state = _make_manuscript_state(2)
        graph = get_dependency_graph(TaskType.MANUSCRIPT)
        plan = graph.compute_impact(state, ["manuscript:video:1"])

        assert "manuscript:video:1" in plan.affected
        assert "manuscript:audio" in plan.affected
        assert "manuscript:subtitle" in plan.affected
        assert "manuscript:video:0" in plan.retained


class TestArtifactsCheckpoint:
    """core/artifacts.py checkpoint 分组。"""

    def test_checkpoint_for_artifact(self):
        from core.artifacts import checkpoint_for_artifact

        # v6.1：creative 细粒度检查点（每个有产物的环节独立）
        assert checkpoint_for_artifact("creative:image_analysis") == "image_analysis"
        assert checkpoint_for_artifact("creative:story") == "story"
        assert checkpoint_for_artifact("creative:script") == "script"
        assert checkpoint_for_artifact("creative:character_ref") == "character_ref"
        assert checkpoint_for_artifact("creative:end_frame:2") == "end_frame_gen"
        assert checkpoint_for_artifact("creative:video:1") == "videos"
        assert checkpoint_for_artifact("creative:audio") == "audio"
        assert checkpoint_for_artifact("creative:subtitle") == "subtitle"
        assert checkpoint_for_artifact("creative:final_video") == "final"
        # 非 creative 仍为粗粒度合并
        assert checkpoint_for_artifact("manuscript:scene_prompts") == "scenes"
        assert checkpoint_for_artifact("poetry:script") == "scenes"
        assert checkpoint_for_artifact("anchor:anchor_image") == "references"
        assert checkpoint_for_artifact("bogus:thing") == "other"

    def test_build_checkpoint_manifest(self, tmp_path, monkeypatch):
        import core.artifacts as artifacts_mod
        from core.artifacts import build_checkpoint_manifest
        from models.task import CreativeVideoTask, SceneTask, TaskType

        # build_manifest 内部经 safe_join(get_working_dir(), task_dir) 校验路径，
        # 将工作目录指向临时目录父级使 task_dir 位于其中。
        monkeypatch.setattr(artifacts_mod, "get_working_dir", lambda: str(tmp_path.parent))

        state = CreativeVideoTask(task_id="t", creative_name="t", task_type=TaskType.CREATIVE)
        state.scenes = [SceneTask(index=0), SceneTask(index=1)]
        data = build_checkpoint_manifest(state, str(tmp_path))

        assert data["task_id"] == "t"
        # v6.1：creative 细粒度检查点分组
        assert "story" in data["checkpoints"]
        assert "script" in data["checkpoints"]
        assert "character_ref" in data["checkpoints"]
        assert "videos" in data["checkpoints"]
        assert "final" in data["checkpoints"]
        # story 分组包含 story 产物
        cp_artifacts = {a["artifact_id"] for a in data["checkpoints"]["story"]["artifacts"]}
        assert "creative:story" in cp_artifacts
        # script 分组包含 script 产物
        script_ids = {a["artifact_id"] for a in data["checkpoints"]["script"]["artifacts"]}
        assert "creative:script" in script_ids
        # videos 分组包含场景视频（2 个场景）
        video_ids = {a["artifact_id"] for a in data["checkpoints"]["videos"]["artifacts"]}
        assert "creative:video:0" in video_ids
        assert "creative:video:1" in video_ids
