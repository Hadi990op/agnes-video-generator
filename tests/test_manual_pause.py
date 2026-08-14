"""
v6.0 手动模式 — P0 后端暂停机制单元测试

覆盖（对应 docs/plans/v6.0/implementation_plan.md §4.3）：
- models/task.py: ManualConfig 默认值 / is_manual / 序列化
- core/pipelines: _maybe_pause 命中判定、CheckpointPause、compute_current_checkpoint
- web/routes/task_creation_routes: _build_manual_config 参数校验
- 旧任务状态反序列化向后兼容（无 manual_config → 自动模式）

用法:
    .venv/bin/python -m pytest tests/test_manual_pause.py -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

import pytest


# ═══════════════════════════════════════════════════
# 1. ManualConfig 模型
# ═══════════════════════════════════════════════════

class TestManualConfig:
    def test_default_is_auto(self):
        from models.task import ManualConfig
        mc = ManualConfig()
        assert mc.enabled is False
        assert mc.pause_points == []
        assert mc.current_checkpoint == ""
        assert mc.is_manual is False

    def test_manual_requires_pause_points(self):
        from models.task import ManualConfig
        # enabled 但 pause_points 空 → 视为自动（清空 = 切回自动）
        mc = ManualConfig(enabled=True, pause_points=[])
        assert mc.is_manual is False
        # enabled + 非空 pause_points → 手动
        mc2 = ManualConfig(enabled=True, pause_points=["scenes"])
        assert mc2.is_manual is True

    def test_serialization_roundtrip(self):
        from models.task import ManualConfig
        mc = ManualConfig(enabled=True, pause_points=["scenes", "videos"],
                          current_checkpoint="scenes")
        data = mc.model_dump()
        assert data["enabled"] is True
        assert data["pause_points"] == ["scenes", "videos"]
        assert data["current_checkpoint"] == "scenes"
        # 反序列化
        mc2 = ManualConfig(**data)
        assert mc2 == mc


# ═══════════════════════════════════════════════════
# 2. _maybe_pause 命中判定
# ═══════════════════════════════════════════════════

class TestMaybePause:
    def _make_pipeline(self, manual_config=None):
        """构造一个最小 Pipeline 实例（不触真实 API）。"""
        from core.pipelines import BasePipeline
        from models.task import CreativeVideoTask, ManualConfig, StepStatus, TaskType

        state = CreativeVideoTask(
            task_id="t_manual_test",
            creative_name="test",
            task_type=TaskType.CREATIVE,
        )
        if manual_config is not None:
            state.manual_config = manual_config

        # 子类化避免抽象方法；run 不执行
        class _P(BasePipeline):
            async def run(self, state):
                return ""

        pipeline = _P(api_key="test", task_id="t_manual_test", dir_name="d_manual_test")
        pipeline._state = state
        # 用临时目录（不真实建任务）
        pipeline.task_manager._task_file = None
        return pipeline, state

    def test_auto_mode_never_pauses(self):
        from models.task import ManualConfig
        pipeline, state = self._make_pipeline(ManualConfig())  # 默认自动
        # 不应抛异常，返回 False
        result = asyncio.run(pipeline._maybe_pause("step_build_scenes"))
        assert result is False
        assert state.status.value == "pending"

    def test_manual_hits_pause_point(self):
        from models.task import ManualConfig, StepStatus
        mc = ManualConfig(enabled=True, pause_points=["scenes"])
        pipeline, state = self._make_pipeline(mc)

        with pytest.raises(Exception) as exc_info:
            asyncio.run(pipeline._maybe_pause("step_build_scenes"))
        from core.pipelines import CheckpointPause
        assert isinstance(exc_info.value, CheckpointPause)
        assert exc_info.value.checkpoint == "scenes"
        # 落盘：PENDING + current_checkpoint
        assert state.status == StepStatus.PENDING
        assert mc.current_checkpoint == "scenes"

    def test_manual_skips_unlisted_checkpoint(self):
        from models.task import ManualConfig
        mc = ManualConfig(enabled=True, pause_points=["videos"])
        pipeline, state = self._make_pipeline(mc)
        result = asyncio.run(pipeline._maybe_pause("step_build_scenes"))
        assert result is False
        assert mc.current_checkpoint == ""

    def test_approved_checkpoint_skips(self):
        from models.task import ManualConfig
        mc = ManualConfig(enabled=True, pause_points=["scenes"],
                          approved_checkpoints=["scenes"])
        pipeline, state = self._make_pipeline(mc)
        result = asyncio.run(pipeline._maybe_pause("step_build_scenes"))
        assert result is False

    def test_unknown_step_never_pauses(self):
        from models.task import ManualConfig
        mc = ManualConfig(enabled=True, pause_points=["scenes"])
        pipeline, state = self._make_pipeline(mc)
        result = asyncio.run(pipeline._maybe_pause("step_unknown_thing"))
        assert result is False


# ═══════════════════════════════════════════════════
# 3. compute_current_checkpoint
# ═══════════════════════════════════════════════════

class TestComputeCurrentCheckpoint:
    def test_no_completed_steps(self):
        from core.pipelines import compute_current_checkpoint
        from models.task import CreativeVideoTask, TaskType
        state = CreativeVideoTask(task_id="t", creative_name="t", task_type=TaskType.CREATIVE)
        assert compute_current_checkpoint(state) == ""

    def test_mid_video_generation(self):
        from core.pipelines import compute_current_checkpoint
        from models.task import CreativeVideoTask, StepStatus, TaskType
        state = CreativeVideoTask(task_id="t", creative_name="t", task_type=TaskType.CREATIVE)
        state.step_build_scenes = StepStatus.COMPLETED
        state.step_reference_images = StepStatus.COMPLETED
        state.step_video_generation = StepStatus.RUNNING  # 中断在视频生成中间
        # 最近完成边界 = references
        assert compute_current_checkpoint(state) == "references"

    def test_completed_videos(self):
        from core.pipelines import compute_current_checkpoint
        from models.task import CreativeVideoTask, StepStatus, TaskType
        state = CreativeVideoTask(task_id="t", creative_name="t", task_type=TaskType.CREATIVE)
        state.step_build_scenes = StepStatus.COMPLETED
        state.step_reference_images = StepStatus.COMPLETED
        state.step_video_generation = StepStatus.COMPLETED
        assert compute_current_checkpoint(state) == "videos"


# ═══════════════════════════════════════════════════
# 4. 创建端点 _build_manual_config 参数校验
# ═══════════════════════════════════════════════════

class TestBuildManualConfig:
    def test_auto_default(self):
        from web.routes.task_creation_routes import _build_manual_config
        mc = _build_manual_config("auto", "")
        assert mc.enabled is False
        assert mc.pause_points == []

    def test_manual_empty_points_means_all(self):
        from web.routes.task_creation_routes import _build_manual_config
        from core.pipelines import ALL_CHECKPOINTS
        mc = _build_manual_config("manual", "")
        assert mc.enabled is True
        assert mc.pause_points == ALL_CHECKPOINTS

    def test_manual_subset(self):
        from web.routes.task_creation_routes import _build_manual_config
        mc = _build_manual_config("manual", '["scenes", "videos"]')
        assert mc.enabled is True
        assert mc.pause_points == ["scenes", "videos"]

    def test_invalid_mode(self):
        from web.routes.task_creation_routes import _build_manual_config
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            _build_manual_config("hack", "")

    def test_invalid_pause_points(self):
        from web.routes.task_creation_routes import _build_manual_config
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            _build_manual_config("manual", '["nonexistent"]')

    def test_bad_json(self):
        from web.routes.task_creation_routes import _build_manual_config
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            _build_manual_config("manual", "not-json")


# ═══════════════════════════════════════════════════
# 5. 向后兼容：旧任务状态无 manual_config
# ═══════════════════════════════════════════════════

class TestBackwardCompat:
    def test_old_state_parses_without_manual_config(self):
        from models.task import parse_task_state
        # 模拟 v5.x 旧数据：无 manual_config 字段
        old = {
            "task_id": "abc123",
            "creative_name": "old",
            "task_type": "creative",
            "status": "completed",
        }
        state = parse_task_state(old)
        assert state.manual_config is not None
        assert state.manual_config.enabled is False
        assert state.manual_config.is_manual is False

    def test_old_state_with_status_only(self):
        from models.task import parse_task_state
        # 更早的数据：无 task_type → 自动识别为 creative（D6）
        old = {
            "task_id": "abc123",
            "creative_name": "old",
            "status": "pending",
        }
        state = parse_task_state(old)
        assert state.task_type.value == "creative"
        assert state.manual_config.is_manual is False


# ═══════════════════════════════════════════════════
# 6. POST /api/tasks/{id}/mode 运行时切换（集成）
# ═══════════════════════════════════════════════════

class TestModeSwitchEndpoint:
    """用 TestClient 挂载 task_routes，打桩 TaskManager / app_state 验证切换逻辑。"""

    def _make_app(self, monkeypatch, state, active=None, queued=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from web.routes import task_routes

        app = FastAPI()
        app.include_router(task_routes.router)
        client = TestClient(app)

        # 打桩 helpers.find_dir_name → 直接返回 dir_name
        monkeypatch.setattr(task_routes.helpers, "find_dir_name", lambda tid: "d_test")
        # 打桩 TaskManager.load → 返回传入 state
        class _TM:
            def __init__(self, task_id, dir_name=None):
                self.state = state

            def load(self):
                return self.state

            def update_state(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self.state, k, v)
                return None

        monkeypatch.setattr(task_routes, "TaskManager", _TM)
        # 打桩 app_state 容器
        monkeypatch.setattr(task_routes.app_state, "active_pipelines", dict(active or {}))
        monkeypatch.setattr(task_routes.app_state, "_queued_tasks", dict(queued or {}))

        resume_calls = []

        async def fake_resume(tid):
            resume_calls.append(tid)
            return {"ok": True, "task_id": tid, "resumed": True}

        monkeypatch.setattr(task_routes, "resume_task", fake_resume)
        return client, resume_calls

    def test_switch_to_manual_reuses_stop(self, monkeypatch):
        """自动任务运行中 → mode=manual：pipeline.stop 被调用 + 落盘 manual 状态。"""
        from models.task import CreativeVideoTask, StepStatus, TaskType

        state = CreativeVideoTask(
            task_id="t1", creative_name="t1", task_type=TaskType.CREATIVE,
            status=StepStatus.RUNNING,
        )
        state.step_build_scenes = StepStatus.COMPLETED
        state.step_reference_images = StepStatus.COMPLETED

        stopped = {"called": False}
        class _FakePipeline:
            _stop_event = type("E", (), {"is_set": lambda self: True})()
            def stop(self):
                stopped["called"] = True

        client, _ = self._make_app(
            monkeypatch, state,
            active={"t1": _FakePipeline()},
        )
        resp = client.post("/api/tasks/t1/mode", data={"mode": "manual"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "manual"
        assert body["changed"] is True
        assert body["current_checkpoint"] == "references"  # 最近完成边界
        # 复用 stop 链路
        assert stopped["called"] is True
        # 落盘：PENDING + enabled + checkpoint
        assert state.status == StepStatus.PENDING
        assert state.manual_config.enabled is True
        assert state.manual_config.current_checkpoint == "references"

    def test_switch_to_auto_resumes_when_paused(self, monkeypatch):
        """手动任务暂停中 → mode=auto：清空暂停点 + 立即 resume（切换即继续）。"""
        from models.task import CreativeVideoTask, ManualConfig, StepStatus, TaskType

        state = CreativeVideoTask(
            task_id="t2", creative_name="t2", task_type=TaskType.CREATIVE,
            status=StepStatus.PENDING,
        )
        state.manual_config = ManualConfig(
            enabled=True, pause_points=["scenes", "videos"],
            current_checkpoint="scenes",
        )

        client, resume_calls = self._make_app(monkeypatch, state)
        resp = client.post("/api/tasks/t2/mode", data={"mode": "auto"})
        assert resp.status_code == 200
        assert resp.json()["resumed"] is True
        assert resume_calls == ["t2"]
        # 清空暂停点 → 永不暂停
        assert state.manual_config.pause_points == []
        assert state.manual_config.current_checkpoint == ""

    def test_switch_to_auto_not_paused_no_resume(self, monkeypatch):
        """手动任务运行中（未暂停）→ mode=auto：仅清空暂停点，不 resume。"""
        from models.task import CreativeVideoTask, ManualConfig, StepStatus, TaskType

        state = CreativeVideoTask(
            task_id="t3", creative_name="t3", task_type=TaskType.CREATIVE,
            status=StepStatus.RUNNING,
        )
        state.manual_config = ManualConfig(enabled=True, pause_points=["scenes"])

        client, resume_calls = self._make_app(monkeypatch, state)
        resp = client.post("/api/tasks/t3/mode", data={"mode": "auto"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "auto"
        assert resume_calls == []  # 未暂停不触发 resume
        assert state.manual_config.pause_points == []

    def test_switch_manual_rejected_for_simple(self, monkeypatch):
        """simple 任务不支持手动模式 → 400。"""
        from models.task import SimpleVideoTask, StepStatus, TaskType

        state = SimpleVideoTask(
            task_id="t4", creative_name="t4", task_type=TaskType.SIMPLE,
            status=StepStatus.RUNNING,
        )
        client, _ = self._make_app(monkeypatch, state)
        resp = client.post("/api/tasks/t4/mode", data={"mode": "manual"})
        assert resp.status_code == 400

    def test_invalid_mode_value(self, monkeypatch):
        from models.task import CreativeVideoTask, TaskType
        state = CreativeVideoTask(task_id="t5", creative_name="t5", task_type=TaskType.CREATIVE)
        client, _ = self._make_app(monkeypatch, state)
        resp = client.post("/api/tasks/t5/mode", data={"mode": "hack"})
        assert resp.status_code == 422

    def test_manual_idempotent_when_paused(self, monkeypatch):
        """已在手动暂停态 → mode=manual 幂等（changed=False，不再调 stop）。"""
        from models.task import CreativeVideoTask, ManualConfig, StepStatus, TaskType

        state = CreativeVideoTask(
            task_id="t6", creative_name="t6", task_type=TaskType.CREATIVE,
            status=StepStatus.PENDING,
        )
        state.manual_config = ManualConfig(
            enabled=True, pause_points=["scenes"], current_checkpoint="scenes",
        )

        client, _ = self._make_app(monkeypatch, state)
        resp = client.post("/api/tasks/t6/mode", data={"mode": "manual"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["changed"] is False
        assert body["current_checkpoint"] == "scenes"
