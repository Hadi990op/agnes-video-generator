"""
Batch 3（S3）模板契约测试 — MultiScenePipeline._execute_step coarse_skip 开关

覆盖：
- Creative 不再覆写 _execute_step（方案 A：类属性 coarse_skip=False 禁用粗粒度 skip）
- 默认粗粒度 skip：步骤字段 COMPLETED → 整步跳过
- Creative 类属性：步骤字段 COMPLETED 仍执行（依赖 _step_* 读盘细粒度续传）
- 显式 coarse_skip 参数覆盖类属性
- PENDING 步骤总是执行

用法:
    .venv/bin/python -m pytest tests/test_pipeline_contract.py -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from core.pipelines.multi_scene import MultiScenePipeline
from core.pipelines.creative_video import CreativeVideoPipeline
from models.task import CreativeVideoTask, StepStatus, TaskType


class ConcreteMultiScene(MultiScenePipeline):
    """最小具体子类（仅用于契约测试）。"""

    async def _build_scenes(self) -> None:
        pass

    async def _build_reference_images(self) -> None:
        pass

    async def _composite_final(self) -> str:
        return ""


async def _no_emit(*args, **kwargs):
    return None


class _StubTaskManager:
    def update_step(self, *args, **kwargs):
        pass


class TestExecuteStepContract:
    """_execute_step 粗/细粒度 skip 契约测试（Batch 3 / S3）。"""

    def test_creative_no_longer_overrides_execute_step(self):
        """方案 A：Creative 覆写已删除，方法解析指向基类实现。"""
        assert CreativeVideoPipeline._execute_step is MultiScenePipeline._execute_step

    def test_creative_class_attr_coarse_skip_false(self):
        """Creative 通过类属性禁用粗粒度 skip。"""
        assert CreativeVideoPipeline.coarse_skip is False

    def test_default_coarse_skip_true_skips_completed_step(self):
        """默认（coarse_skip=True）：步骤字段 COMPLETED → 整步跳过，action 不执行。"""
        async def run():
            p = ConcreteMultiScene.__new__(ConcreteMultiScene)
            state = CreativeVideoTask(task_type=TaskType.CREATIVE, idea="x")
            state.step_build_scenes = StepStatus.COMPLETED
            p._state, p.task_manager, p._emit = state, _StubTaskManager(), _no_emit

            calls = {"n": 0}

            async def action():
                calls["n"] += 1

            result = await p._execute_step(
                "step_build_scenes", action, 0.0, 0.15, "构建分镜", "完成",
            )
            assert result is None
            assert calls["n"] == 0

        asyncio.run(run())

    def test_creative_coarse_skip_false_executes_completed_step(self):
        """Creative（coarse_skip=False）：步骤字段 COMPLETED 仍执行（细粒度续传）。"""
        async def run():
            p = CreativeVideoPipeline.__new__(CreativeVideoPipeline)
            state = CreativeVideoTask(task_type=TaskType.CREATIVE, idea="x")
            state.step_build_scenes = StepStatus.COMPLETED
            p._state, p.task_manager, p._emit = state, _StubTaskManager(), _no_emit

            calls = {"n": 0}

            async def action():
                calls["n"] += 1

            await p._execute_step("step_build_scenes", action, 0.0, 0.15, "构建分镜", "完成")
            assert calls["n"] == 1

        asyncio.run(run())

    def test_explicit_coarse_skip_overrides_class_attr(self):
        """显式 coarse_skip 参数优先于类属性。"""
        async def run():
            p = CreativeVideoPipeline.__new__(CreativeVideoPipeline)
            state = CreativeVideoTask(task_type=TaskType.CREATIVE, idea="x")
            state.step_build_scenes = StepStatus.COMPLETED
            p._state, p.task_manager, p._emit = state, _StubTaskManager(), _no_emit

            calls = {"n": 0}

            async def action():
                calls["n"] += 1

            await p._execute_step(
                "step_build_scenes", action, 0.0, 0.15, "构建分镜", "完成",
                coarse_skip=True,
            )
            assert calls["n"] == 0

        asyncio.run(run())

    def test_pending_step_always_executes(self):
        """PENDING 步骤无论开关均执行。"""
        async def run():
            p = ConcreteMultiScene.__new__(ConcreteMultiScene)
            p._state = CreativeVideoTask(task_type=TaskType.CREATIVE, idea="x")
            p.task_manager, p._emit = _StubTaskManager(), _no_emit

            calls = {"n": 0}

            async def action():
                calls["n"] += 1

            await p._execute_step("step_build_scenes", action, 0.0, 0.15, "构建分镜", "完成")
            assert calls["n"] == 1

        asyncio.run(run())
