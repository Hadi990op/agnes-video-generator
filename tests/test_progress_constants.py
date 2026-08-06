"""契约测试：v5.0 Batch 5.3 魔法数字收敛后的进度/重试常量取值不变。

锁定各流水线的进度映射常量与重试间隔基数，保证收敛（字面量 → 命名常量）后
行为与收敛前逐字节一致。任何对进度数值的调整都必须同步修改本文件。
"""
from core.pipelines.multi_scene import (
    StepProgressLimits,
    _PROGRESS,
    _PROGRESS_FAILED,
    _RETRY_INTERVAL_BASE_SECONDS,
)


def test_step_progress_limits_boundaries():
    limits = StepProgressLimits()
    assert limits.build_start == 0.0
    assert limits.build_end == 0.15
    assert limits.reference_end == 0.30
    assert limits.video_end == 0.75
    assert limits.audio_end == 0.85
    assert limits.subtitle_end == 0.90
    assert limits.composite_end == 0.98
    assert limits.done == 1.0
    assert _PROGRESS.done == 1.0
    assert _PROGRESS_FAILED == 0.0
    assert _RETRY_INTERVAL_BASE_SECONDS == 20


def test_manuscript_progress_and_retry_constants():
    from core.pipelines.manuscript_video import (
        _SUBMIT_RETRY_INTERVAL_BASE_SECONDS,
        _WAIT_RETRY_INTERVAL_BASE_SECONDS,
        _PROGRESS_SCENE_PROMPTS_START,
        _PROGRESS_SCENE_PROMPTS_SPAN,
        _PROGRESS_SUBMIT_START,
        _PROGRESS_SUBMIT_SPAN,
        _PROGRESS_WAIT_START,
        _PROGRESS_WAIT_SPAN,
        _PROGRESS_AUDIO_START,
        _PROGRESS_SUBTITLE_START,
        _PROGRESS_CONCAT_START,
    )
    assert _SUBMIT_RETRY_INTERVAL_BASE_SECONDS == 15
    assert _WAIT_RETRY_INTERVAL_BASE_SECONDS == 20
    assert _PROGRESS_SCENE_PROMPTS_SPAN == 0.10
    assert _PROGRESS_SUBMIT_SPAN == 0.20
    assert _PROGRESS_WAIT_SPAN == 0.25
    starts = [
        _PROGRESS_SCENE_PROMPTS_START,
        _PROGRESS_SUBMIT_START,
        _PROGRESS_WAIT_START,
        _PROGRESS_AUDIO_START,
        _PROGRESS_SUBTITLE_START,
        _PROGRESS_CONCAT_START,
    ]
    assert starts == [0.05, 0.15, 0.35, 0.60, 0.75, 0.80]
    # 阶段起始严格单调递增，且不超过 1.0
    assert all(a < b for a, b in zip(starts, starts[1:]))


def test_anchor_progress_constants():
    from core.pipelines.anchor_video import (
        _CLIP_RETRY_INTERVAL_BASE_SECONDS,
        _PROGRESS_ANCHOR_IMAGE,
        _PROGRESS_ANCHOR_IMAGE_DONE,
        _PROGRESS_CLIP_PROMPTS_START,
        _PROGRESS_CLIP_PROMPTS_DONE,
        _PROGRESS_CLIP_GEN_START,
        _PROGRESS_CLIP_GEN_DONE,
        _PROGRESS_AUDIO_START,
        _PROGRESS_AUDIO_DONE,
        _PROGRESS_SUBTITLE_START,
        _PROGRESS_SUBTITLE_DONE,
        _PROGRESS_CONCAT_START,
    )
    assert _CLIP_RETRY_INTERVAL_BASE_SECONDS == 15
    assert _PROGRESS_ANCHOR_IMAGE == 0.02
    assert _PROGRESS_ANCHOR_IMAGE_DONE == 0.08
    assert _PROGRESS_CLIP_PROMPTS_START == 0.12
    assert _PROGRESS_CLIP_PROMPTS_DONE == 0.18
    assert _PROGRESS_CLIP_GEN_START == 0.28
    assert _PROGRESS_CLIP_GEN_DONE == 0.55
    assert _PROGRESS_AUDIO_START == 0.55
    assert _PROGRESS_AUDIO_DONE == 0.28  # 历史回退值，收敛时保持不变
    assert _PROGRESS_SUBTITLE_START == 0.65
    assert _PROGRESS_SUBTITLE_DONE == 0.75
    assert _PROGRESS_CONCAT_START == 0.80


def test_simple_video_progress_constants():
    from core.pipelines.simple_video import (
        _PROGRESS_INIT,
        _PROGRESS_SUBMIT,
        _PROGRESS_WAIT,
        _PROGRESS_DONE,
        _PROGRESS_COMPLETED,
        _PROGRESS_FAILED,
    )
    assert (
        _PROGRESS_INIT,
        _PROGRESS_SUBMIT,
        _PROGRESS_WAIT,
        _PROGRESS_DONE,
        _PROGRESS_COMPLETED,
        _PROGRESS_FAILED,
    ) == (0.0, 0.1, 0.3, 0.9, 1.0, 0.0)


def test_creative_steps_progress_constants():
    from core.pipelines.creative.steps_video import (
        _PROGRESS_WAIT_START,
        _PROGRESS_WAIT_SPAN,
        _PROGRESS_CACHED_START,
        _PROGRESS_CACHED_SPAN,
        _PROGRESS_KEYFRAME_SUBMIT_START,
        _PROGRESS_KEYFRAME_SUBMIT_SPAN,
        _PROGRESS_KEYFRAME_WAIT_START,
        _PROGRESS_KEYFRAME_WAIT_SPAN,
    )
    from core.pipelines.creative.steps_script import (
        _PROGRESS_SCENE_CONFIG_DONE,
        _PROGRESS_SCENE_CONFIG_FAILED,
        _PROGRESS_IMAGE_ANALYSIS_START,
        _PROGRESS_IMAGE_ANALYSIS_DONE,
        _PROGRESS_SCENE_EXTRACT_START,
        _PROGRESS_STORY_START,
        _PROGRESS_STORY_DONE,
        _PROGRESS_CHARACTER_REF_START,
        _PROGRESS_CHARACTER_REF_T2I,
        _PROGRESS_CHARACTER_REF_DONE,
        _PROGRESS_SCRIPT_START,
        _PROGRESS_SCRIPT_DONE,
        _PROGRESS_END_FRAME_PROMPTS_START,
        _PROGRESS_END_FRAME_PROMPTS_DONE,
    )
    from core.pipelines.creative.steps_audio import (
        _PROGRESS_NARRATIONS_START,
        _PROGRESS_AUDIO_START,
        _PROGRESS_AUDIO_DONE,
        _PROGRESS_SUBTITLE_START,
        _PROGRESS_SUBTITLE_DONE,
        _PROGRESS_CONCAT_START,
        _PROGRESS_CONCAT_DONE,
    )
    from core.pipelines.creative.steps_frames import _PROGRESS_END_FRAME_PREGEN_DONE

    # steps_video 三模式映射
    assert (_PROGRESS_WAIT_START, _PROGRESS_WAIT_SPAN) == (0.38, 0.42)
    assert (_PROGRESS_CACHED_START, _PROGRESS_CACHED_SPAN) == (0.35, 0.45)
    assert (_PROGRESS_KEYFRAME_SUBMIT_START, _PROGRESS_KEYFRAME_SUBMIT_SPAN) == (0.35, 0.05)
    assert (_PROGRESS_KEYFRAME_WAIT_START, _PROGRESS_KEYFRAME_WAIT_SPAN) == (0.40, 0.40)
    assert _PROGRESS_END_FRAME_PREGEN_DONE == 0.35

    # steps_script 编剧阶段线性推进 0.0 → 0.25（含 scene_config 分支）
    script_starts = [
        _PROGRESS_IMAGE_ANALYSIS_START,
        _PROGRESS_IMAGE_ANALYSIS_DONE,
        _PROGRESS_SCENE_EXTRACT_START,
        _PROGRESS_STORY_START,
        _PROGRESS_STORY_DONE,
        _PROGRESS_CHARACTER_REF_START,
        _PROGRESS_CHARACTER_REF_T2I,
        _PROGRESS_CHARACTER_REF_DONE,
        _PROGRESS_SCRIPT_START,
        _PROGRESS_SCRIPT_DONE,
        _PROGRESS_END_FRAME_PROMPTS_START,
        _PROGRESS_END_FRAME_PROMPTS_DONE,
    ]
    assert script_starts == [0.0, 0.05, 0.01, 0.05, 0.1, 0.1, 0.12, 0.15, 0.15, 0.2, 0.2, 0.25]
    assert _PROGRESS_SCENE_CONFIG_DONE == 0.02
    assert _PROGRESS_SCENE_CONFIG_FAILED == 0.0

    # steps_audio 旁白 → 音频 → 字幕 → 拼接
    assert (
        _PROGRESS_NARRATIONS_START,
        _PROGRESS_AUDIO_START,
        _PROGRESS_AUDIO_DONE,
        _PROGRESS_SUBTITLE_START,
        _PROGRESS_SUBTITLE_DONE,
        _PROGRESS_CONCAT_START,
        _PROGRESS_CONCAT_DONE,
    ) == (0.12, 0.82, 0.86, 0.86, 0.9, 0.92, 0.95)


def test_poetry_progress_constants():
    from core.pipelines.poetry_video import (
        _PROGRESS_AUDIO_SCENE,
        _PROGRESS_SUBTITLE_SCENE,
        _PROGRESS_COMPOSITE_SCENE,
    )
    assert (
        _PROGRESS_AUDIO_SCENE,
        _PROGRESS_SUBTITLE_SCENE,
        _PROGRESS_COMPOSITE_SCENE,
    ) == (0.75, 0.87, 0.90)


def test_api_retry_base_constants():
    from core.screenwriter import _DESCRIBE_RETRY_BASE_DELAY_SECONDS
    from core.api.agnes_video import _UPLOAD_RETRY_BASE_DELAY_SECONDS
    from core.api.agnes_image import _READ_TIMEOUT_BASE_SECONDS
    assert _DESCRIBE_RETRY_BASE_DELAY_SECONDS == 15
    assert _UPLOAD_RETRY_BASE_DELAY_SECONDS == 30
    assert _READ_TIMEOUT_BASE_SECONDS == 120
