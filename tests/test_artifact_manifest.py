"""单元测试：产物规范前置工作（v5.x）。

覆盖：
- ``core.artifacts.build_manifest`` / ``write_manifest`` / ``write_manifest_md``
- ``list_artifacts`` 描述符携带 ``schema_hint``
- ``BasePipeline._save_narration_txt`` 旁白纯文本导出

不依赖 ffmpeg / 网络，秒级运行。
"""
import json
import os

import pytest

from core.artifacts import (
    build_manifest,
    list_artifacts,
    write_manifest,
    write_manifest_md,
)
from core.pipelines import BasePipeline
from models.task import (
    AnchorVideoTask,
    AudioConfig,
    CreativeVideoTask,
    ManuscriptParagraph,
    ManuscriptVideoTask,
    SceneTask,
    SimpleVideoTask,
    StepStatus,
    SubtitleConfig,
)


# ── 构造辅助 ────────────────────────────────────────────────
def _creative(scene_count=2):
    s = CreativeVideoTask(
        task_type="creative",
        creative_name="ut",
        idea="idea",
        style="style",
        chaining_mode="keyframes",
        scene_count=scene_count,
        scene_durations=[5] * scene_count,
        duration_source="manual",
        audio_config=AudioConfig(enabled=True),
        subtitle_config=SubtitleConfig(enabled=True),
    )
    s.scenes = [SceneTask(index=i) for i in range(scene_count)]
    s.status = StepStatus.COMPLETED
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
    s.status = StepStatus.COMPLETED
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


class _MiniPipeline(BasePipeline):
    """最小 BasePipeline 子类（仅用于测试共享工具方法）。"""

    async def run(self, state):
        return ""


# ── build_manifest ──────────────────────────────────────────
def test_build_manifest_creative(monkeypatch, tmp_path):
    monkeypatch.setenv("AGNES_REGRESSION_WORKING_DIR", str(tmp_path))
    task_dir = tmp_path / "taskX"
    task_dir.mkdir()

    state = _creative(scene_count=3)
    manifest = build_manifest(state, "taskX")

    assert manifest["task_id"] == state.task_id
    assert manifest["task_type"] == "creative"
    assert manifest["task_status"] == "completed"
    assert manifest["working_dir"] == str(task_dir)

    # 结构化产物：含 schema_hint / preview_url / path
    script = next(a for a in manifest["artifacts"] if a["artifact_id"] == "creative:script")
    assert script["schema_hint"]
    assert script["path"] == "script.json"
    assert script["editable"] is True
    assert script["preview_url"].startswith(f"/api/tasks/{state.task_id}/artifacts/")
    assert script["generated_by_step"] == "script"

    # 场景级产物存在
    video = next(a for a in manifest["artifacts"] if a["artifact_id"] == "creative:video:0")
    assert video["path"] == "scene_0/video.mp4"

    # 通用文件树字段
    assert isinstance(manifest["files"], list)


def test_build_manifest_simple_falls_back_to_files(monkeypatch, tmp_path):
    monkeypatch.setenv("AGNES_REGRESSION_WORKING_DIR", str(tmp_path))
    task_dir = tmp_path / "taskS"
    task_dir.mkdir()
    (task_dir / "prompt.txt").write_text("hello", encoding="utf-8")

    state = SimpleVideoTask(task_type="simple", creative_name="ut", prompt="p")
    manifest = build_manifest(state, "taskS")

    # 无结构化产物定义 → artifacts 为空，files 兜底
    assert manifest["artifacts"] == []
    paths = {f["path"] for f in manifest["files"]}
    assert "prompt.txt" in paths


def test_build_manifest_manuscript_and_anchor(monkeypatch, tmp_path):
    monkeypatch.setenv("AGNES_REGRESSION_WORKING_DIR", str(tmp_path))
    (tmp_path / "taskM").mkdir()
    (tmp_path / "taskA").mkdir()

    m = build_manifest(_manuscript(), "taskM")
    assert any(a["artifact_id"] == "manuscript:final_video" for a in m["artifacts"])

    a = build_manifest(_anchor(), "taskA")
    assert any(a["artifact_id"] == "anchor:final_video" for a in a["artifacts"])


# ── write_manifest / write_manifest_md ──────────────────────
def test_write_manifest_writes_json(monkeypatch, tmp_path):
    monkeypatch.setenv("AGNES_REGRESSION_WORKING_DIR", str(tmp_path))
    task_dir = tmp_path / "taskX"
    task_dir.mkdir()

    path = write_manifest(_creative(), "taskX")
    assert path == str(task_dir / "manifest.json")
    assert os.path.exists(path)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["format_version"] == "1.0"
    assert data["task_type"] == "creative"


def test_write_manifest_md_content(monkeypatch, tmp_path):
    monkeypatch.setenv("AGNES_REGRESSION_WORKING_DIR", str(tmp_path))
    task_dir = tmp_path / "taskX"
    task_dir.mkdir()

    path = write_manifest_md(_creative(scene_count=2), "taskX")
    assert path == str(task_dir / "MANIFEST.md")
    content = open(path, "r", encoding="utf-8").read()

    assert "任务产物说明" in content
    assert "script.json" in content
    assert str(task_dir) in content
    assert "协作提示" in content


# ── list_artifacts schema_hint ──────────────────────────────
def test_list_artifacts_schema_hint(monkeypatch, tmp_path):
    monkeypatch.setenv("AGNES_REGRESSION_WORKING_DIR", str(tmp_path))
    arts = list_artifacts(_creative(scene_count=2), "task1")
    script = next(a for a in arts if a.artifact_id == "creative:script")
    assert script.schema_hint
    assert "scene_prompt" in script.schema_hint
    video = next(a for a in arts if a.artifact_id == "creative:video:0")
    assert video.schema_hint


# ── BasePipeline._save_narration_txt ─────────────────────────
def test_save_narration_txt_basic(monkeypatch, tmp_path):
    monkeypatch.setenv("AGNES_REGRESSION_WORKING_DIR", str(tmp_path))
    task_dir = tmp_path / "taskA"
    task_dir.mkdir()

    pipe = _MiniPipeline(api_key="k", task_id="t1", dir_name="taskA")
    audio_path = str(task_dir / "combined_narration.mp3")
    txt_path = pipe._save_narration_txt("这是旁白文本", audio_path)

    assert txt_path == str(task_dir / "combined_narration.txt")
    assert open(txt_path, "r", encoding="utf-8").read() == "这是旁白文本"


def test_save_narration_txt_default_name(monkeypatch, tmp_path):
    monkeypatch.setenv("AGNES_REGRESSION_WORKING_DIR", str(tmp_path))
    task_dir = tmp_path / "taskB"
    task_dir.mkdir()

    pipe = _MiniPipeline(api_key="k", task_id="t2", dir_name="taskB")
    txt_path = pipe._save_narration_txt("hello")

    assert txt_path == str(task_dir / "narration.txt")
    assert open(txt_path, "r", encoding="utf-8").read() == "hello"


def test_save_narration_txt_empty_skips(monkeypatch, tmp_path):
    monkeypatch.setenv("AGNES_REGRESSION_WORKING_DIR", str(tmp_path))
    (tmp_path / "taskC").mkdir()

    pipe = _MiniPipeline(api_key="k", task_id="t3", dir_name="taskC")
    assert pipe._save_narration_txt("") == ""
    assert not (tmp_path / "taskC" / "narration.txt").exists()
