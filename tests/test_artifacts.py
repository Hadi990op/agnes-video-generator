"""单元测试：core.artifacts —— 中间产物注册表与级联删除计划。

覆盖 list_artifacts / resolve_artifact / get_cascade_plan / apply_cascade_plan
以及内部辅助函数。不依赖 ffmpeg / 网络，秒级运行。
"""
import os
import time

import pytest

from core.artifacts import (
    CascadePlan,
    _format_path,
    _get_artifact_defs,
    _get_steps_for_state,
    _step_key_to_field,
    _step_key_to_order,
    apply_cascade_plan,
    get_cascade_plan,
    list_artifacts,
    resolve_artifact,
    sweep_stale_tasks,
)
from models.task import (
    AnchorVideoTask,
    AudioConfig,
    CreativeVideoTask,
    ManuscriptParagraph,
    ManuscriptVideoTask,
    SceneTask,
    StepStatus,
    SubtitleConfig,
)


# ── 构造辅助 ────────────────────────────────────────────────
def _creative(scene_count=3, chaining_mode="keyframes"):
    s = CreativeVideoTask(
        task_type="creative",
        creative_name="ut",
        idea="idea",
        style="style",
        chaining_mode=chaining_mode,
        scene_count=scene_count,
        scene_durations=[5] * scene_count,
        duration_source="manual",
        audio_config=AudioConfig(enabled=True),
        subtitle_config=SubtitleConfig(enabled=True),
    )
    s.scenes = [SceneTask(index=i) for i in range(scene_count)]
    return s


def _manuscript(paragraph_count=2):
    s = ManuscriptVideoTask(
        task_type="manuscript",
        creative_name="ut",
        manuscript_text="a\n\nb",
        audio_config=AudioConfig(enabled=True),
        subtitle_config=SubtitleConfig(enabled=True),
    )
    s.paragraphs = [
        ManuscriptParagraph(index=i, text=f"p{i}") for i in range(paragraph_count)
    ]
    return s


def _anchor(audio_source="post_stitch"):
    return AnchorVideoTask(
        task_type="anchor",
        creative_name="ut",
        script_text="script",
        audio_source=audio_source,
        audio_config=AudioConfig(enabled=True),
        subtitle_config=SubtitleConfig(enabled=True),
    )


# ── 内部辅助函数 ────────────────────────────────────────────
def test_format_path():
    assert _format_path("scene_{i}/video.mp4", 2) == "scene_2/video.mp4"


def test_step_key_to_field():
    steps = [("step_a", "a"), (None, "b"), ("step_c", "c")]
    assert _step_key_to_field(steps, "a") == "step_a"
    assert _step_key_to_field(steps, "b") is None
    assert _step_key_to_field(steps, "missing") is None


def test_step_key_to_order():
    steps = [("step_a", "a"), ("step_c", "c")]
    assert _step_key_to_order(steps, "a") == 0
    assert _step_key_to_order(steps, "c") == 1
    assert _step_key_to_order(steps, "x") == -1


def test_get_steps_for_state_all_types():
    assert len(_get_steps_for_state(_creative())) > 0
    assert len(_get_steps_for_state(_manuscript())) > 0
    assert len(_get_steps_for_state(_anchor("post_stitch"))) > 0
    assert len(_get_steps_for_state(_anchor("model"))) > 0

    class _Dummy:
        task_type = "x"

    assert _get_steps_for_state(_Dummy()) == []


def test_get_artifact_defs_all_types():
    assert len(_get_artifact_defs(_creative())) > 0
    assert len(_get_artifact_defs(_manuscript())) > 0
    # model 模式无音频/字幕/最终视频，产物数少于 post_stitch
    assert len(_get_artifact_defs(_anchor("model"))) < len(
        _get_artifact_defs(_anchor("post_stitch"))
    )


# ── list_artifacts ──────────────────────────────────────────
def test_list_artifacts_creative_counts(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    arts = list_artifacts(_creative(scene_count=3), "task1")
    ids = {a.artifact_id for a in arts}
    assert "creative:story" in ids
    assert "creative:end_frame:0" in ids and "creative:end_frame:2" in ids
    assert "creative:video:0" in ids
    # 场景级产物 = 2 种(scene 级) * 3 场景 = 6
    scene_arts = [a for a in arts if a.scope == "scene"]
    assert len(scene_arts) == 6


def test_list_artifacts_manuscript(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    arts = list_artifacts(_manuscript(paragraph_count=2), "task1")
    ids = {a.artifact_id for a in arts}
    assert "manuscript:scene_prompts" in ids
    assert "manuscript:video:0" in ids and "manuscript:video:1" in ids
    assert "manuscript:final_video" in ids


def test_list_artifacts_anchor_post_stitch(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    arts = list_artifacts(_anchor("post_stitch"), "task1")
    ids = {a.artifact_id for a in arts}
    assert "anchor:anchor_image" in ids
    assert "anchor:clip" in ids
    assert "anchor:final_video" in ids  # post_stitch 含最终视频


def test_list_artifacts_anchor_model(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    arts = list_artifacts(_anchor("model"), "task1")
    ids = {a.artifact_id for a in arts}
    assert "anchor:anchor_image" in ids
    assert "anchor:clip" in ids
    assert "anchor:final_video" not in ids  # model 模式无最终视频


def test_list_artifacts_detects_existing_file(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    task_dir = tmp_path / "taskX"
    task_dir.mkdir()
    (task_dir / "story.txt").write_text("hello", encoding="utf-8")
    arts = list_artifacts(_creative(scene_count=1), "taskX")
    story = next(a for a in arts if a.artifact_id == "creative:story")
    assert story.exists is True
    assert story.size == 5


# ── resolve_artifact ────────────────────────────────────────
def test_resolve_artifact_hit_and_miss(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    state = _creative(scene_count=2)
    hit = resolve_artifact("creative:story", state, "task1")
    assert hit is not None and hit.artifact_id == "creative:story"
    miss = resolve_artifact("creative:nonexistent", state, "task1")
    assert miss is None


# ── get_cascade_plan ────────────────────────────────────────
def test_cascade_plan_task_level_story(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    plan = get_cascade_plan("creative:story", _creative(scene_count=2), "task1")
    assert isinstance(plan, CascadePlan)
    # story 及其之后的步骤应被重置
    assert "step_story" in plan.steps_to_reset
    assert "step_script" in plan.steps_to_reset
    assert "step_video_generation" in plan.steps_to_reset
    assert "step_subtitle" in plan.steps_to_reset
    assert "step_concatenation" in plan.steps_to_reset
    # story 之前的步骤不应被重置
    assert "step_scene_config" not in plan.steps_to_reset
    assert "step_image_analysis" not in plan.steps_to_reset
    # 后续任务级产物文件应纳入删除
    assert "script.json" in plan.files_to_delete
    assert "final_video.mp4" in plan.files_to_delete


def test_cascade_plan_scene_keyframes_cascades_all(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    plan = get_cascade_plan(
        "creative:end_frame:1", _creative(scene_count=3, chaining_mode="keyframes"), "task1"
    )
    # keyframes 模式场景关联：级联 scene_1 及之后所有场景
    assert any(f.startswith("scene_1/") for f in plan.files_to_delete)
    assert any(f.startswith("scene_2/") for f in plan.files_to_delete)
    # scene_0 不应被级联
    assert not any(f.startswith("scene_0/") for f in plan.files_to_delete)


def test_cascade_plan_scene_none_only_current(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    plan = get_cascade_plan(
        "creative:end_frame:1", _creative(scene_count=3, chaining_mode="none"), "task1"
    )
    # none 模式场景独立：只级联当前场景
    assert any(f.startswith("scene_1/") for f in plan.files_to_delete)
    assert not any(f.startswith("scene_2/") for f in plan.files_to_delete)
    assert not any(f.startswith("scene_0/") for f in plan.files_to_delete)


def test_cascade_plan_unknown_id_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    assert get_cascade_plan("creative:does_not_exist", _creative(scene_count=2), "task1") is None


def test_cascade_plan_out_of_range_scene_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    assert get_cascade_plan("creative:end_frame:99", _creative(scene_count=2), "task1") is None


# ── apply_cascade_plan ──────────────────────────────────────
def test_apply_cascade_plan_resets_state(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    state = _creative(scene_count=2)
    state.step_story = StepStatus.COMPLETED
    state.step_video_generation = StepStatus.COMPLETED
    state.status = StepStatus.COMPLETED
    plan = get_cascade_plan("creative:story", state, "task1")
    kwargs = apply_cascade_plan(state, plan)
    assert state.step_story == StepStatus.PENDING
    assert state.step_video_generation == StepStatus.PENDING
    assert state.status == StepStatus.PENDING
    assert kwargs["status"] == StepStatus.PENDING
    assert "step_video_generation" in kwargs


def test_apply_cascade_plan_video_status_pending(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    state = _creative(scene_count=2, chaining_mode="none")
    state.scenes[1].video_status = StepStatus.COMPLETED
    plan = get_cascade_plan("creative:video:1", state, "task1")
    apply_cascade_plan(state, plan)
    # video_status 应重置为 PENDING 而非空字符串
    assert state.scenes[1].video_status == StepStatus.PENDING
    assert state.scenes[1].video_file == ""


def test_apply_cascade_plan_returns_scenes_kwargs(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    state = _creative(scene_count=2)
    plan = get_cascade_plan("creative:video:0", state, "task1")
    kwargs = apply_cascade_plan(state, plan)
    assert "scenes" in kwargs
    assert kwargs["scenes"] is state.scenes


# ── sweep_stale_tasks：僵尸任务磁盘清理（v5.0 Batch 5 / 5.1）──────────────────

def _make_task(working, name, status, age_days=30, broken=False):
    """在 working 下构造任务目录：task_state.json（可指定 mtime 距今天数）。"""
    d = working / name
    d.mkdir(parents=True)
    payload = '{"broken' if broken else f'{{"status": "{status}", "task_type": "creative"}}'
    f = d / "task_state.json"
    f.write_text(payload, encoding="utf-8")
    if age_days is not None:
        ts = time.time() - age_days * 86400
        os.utime(f, (ts, ts))
    return d


def test_sweep_removes_stale_completed(monkeypatch, tmp_path):
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    _make_task(tmp_path, "old_done", "completed", age_days=30)
    _make_task(tmp_path, "old_failed", "failed", age_days=30)
    result = sweep_stale_tasks(age_days=7)
    assert result["swept"] == ["old_done", "old_failed"]
    assert result["protected"] == []
    assert not (tmp_path / "old_done").exists()


def test_sweep_protects_running_queued_pending(monkeypatch, tmp_path):
    """活跃/排队/断点续传状态即使超龄也不清理（默认保护集合）。"""
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    _make_task(tmp_path, "t_run", "running", age_days=30)
    _make_task(tmp_path, "t_queued", "queued", age_days=30)
    _make_task(tmp_path, "t_pending", "pending", age_days=30)
    result = sweep_stale_tasks(age_days=7)
    assert result["swept"] == []
    assert sorted(result["protected"]) == ["t_pending", "t_queued", "t_run"]
    assert (tmp_path / "t_pending").exists()


def test_sweep_keeps_fresh_tasks(monkeypatch, tmp_path):
    """未超龄任务即使已完成也不清理。"""
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    _make_task(tmp_path, "fresh_done", "completed", age_days=1)
    result = sweep_stale_tasks(age_days=7)
    assert result["swept"] == []
    assert result["protected"] == ["fresh_done"]


def test_sweep_protect_statuses_override(monkeypatch, tmp_path):
    """调用方可用 protect_statuses 放开 PENDING（白名单配置）。"""
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    _make_task(tmp_path, "t_pending", "pending", age_days=30)
    result = sweep_stale_tasks(
        age_days=7, protect_statuses={StepStatus.RUNNING, StepStatus.QUEUED}
    )
    assert result["swept"] == ["t_pending"]


def test_sweep_skips_non_task_dirs_and_reports_broken(monkeypatch, tmp_path):
    """无 task_state.json 的目录跳过；损坏 JSON 记录 errors 不删除。"""
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    (tmp_path / "uploads").mkdir()
    _make_task(tmp_path, "broken", "completed", age_days=30, broken=True)
    result = sweep_stale_tasks(age_days=7)
    assert result["swept"] == []
    assert result["protected"] == []
    assert len(result["errors"]) == 1
    assert (tmp_path / "broken").exists()
    assert (tmp_path / "uploads").exists()


def test_sweep_zero_age_days(monkeypatch, tmp_path):
    """age_days=0 时所有非保护任务均视为超龄。"""
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))
    _make_task(tmp_path, "any_done", "completed", age_days=0)
    _make_task(tmp_path, "any_pending", "pending", age_days=0)
    result = sweep_stale_tasks(age_days=0)
    assert result["swept"] == ["any_done"]
    assert result["protected"] == ["any_pending"]


def test_sweep_missing_working_dir(monkeypatch, tmp_path):
    """工作区不存在时安全返回空结果。"""
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path / "nope"))
    result = sweep_stale_tasks(age_days=7)
    assert result == {"swept": [], "protected": [], "errors": []}
