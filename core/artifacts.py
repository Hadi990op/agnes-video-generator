"""
core/artifacts.py — 中间产物注册表与级联删除计划

为 creative / manuscript / anchor 三种任务模式提供：
- list_artifacts(): 列举任务的所有中间产物（含存在性检测）
- resolve_artifact(): 根据 artifact_id 解析单个产物描述符
- get_cascade_plan(): 计算删除某产物后的级联删除计划

产物 ID 格式: {mode}:{artifact_type} 或 {mode}:{artifact_type}:{scope_index}
  例如: creative:story, creative:end_frame:2, manuscript:video:1, anchor:anchor_image
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from models.task import (
    AnchorVideoTask,
    BaseTaskState,
    CreativeVideoTask,
    ManuscriptVideoTask,
    StepStatus,
)


# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════


@dataclass
class ArtifactDescriptor:
    """单个中间产物的描述符。"""

    artifact_id: str           # "creative:end_frame:2"
    step_key: str              # 前端 STEPS key, 如 "end_frame_gen"
    step_field: Optional[str]  # state 步骤字段名, 如 "step_end_frame_generation" (None=无独立步骤)
    label_key: str             # i18n key, 如 "artEndFrame"
    category: str              # text/image/video/audio/json/subtitle
    scope: str                 # task/scene/paragraph
    scope_index: Optional[int] # 场景/段落索引, task 级为 None
    file_relpath: Optional[str]  # 相对于 task_dir 的路径
    state_fields: list[str]    # 删除时清空的顶层字段
    exists: bool = False       # 文件是否存在
    size: int = 0              # 文件大小(字节)
    deletable: bool = True     # 是否允许删除


@dataclass
class CascadePlan:
    """级联删除计划。"""

    files_to_delete: list[str] = field(default_factory=list)     # 相对路径
    steps_to_reset: list[str] = field(default_factory=list)      # step 字段名
    fields_to_clear: dict[str, Any] = field(default_factory=dict)  # {顶层字段: 默认值}
    scene_updates: list[dict] = field(default_factory=list)      # scenes/paragraphs 字段更新
    # scene_updates 格式: {"list_field": "scenes", "from_index": 2, "field": "video_file", "value": ""}


# ═══════════════════════════════════════════════════════════════
# 步骤序列定义（有序，用于确定级联范围）
# ═══════════════════════════════════════════════════════════════

# Creative 步骤序列 (step_field, step_key)
_CREATIVE_STEPS = [
    ("step_scene_config", "scene_config"),
    ("step_image_analysis", "image_analysis"),
    ("step_story", "story"),
    ("step_character_ref", "character_ref"),
    ("step_script", "script"),
    ("step_end_frame_prompts", "end_frame_prompts"),
    ("step_end_frame_generation", "end_frame_gen"),
    ("step_video_generation", "video_gen"),
    ("step_audio", "audio"),
    ("step_subtitle", "subtitle"),
    ("step_concatenation", "concatenate"),
]

# Manuscript 步骤序列
_MANUSCRIPT_STEPS = [
    ("step_split", "split_text"),
    ("step_scene_prompts", "scene_prompts"),
    ("step_video_generation", "video_gen"),
    ("step_audio", "audio"),
    ("step_subtitle", "subtitle"),
    ("step_concatenation", "concatenate"),
]

# Anchor post_stitch 步骤序列
_ANCHOR_STEPS_POST_STITCH = [
    ("step_generate_anchor", "generate_anchor"),
    ("step_audio", "audio"),
    (None, "clip_prompts"),           # 无独立 step 字段
    ("step_clip_generation", "clip_gen"),
    ("step_subtitle", "subtitle"),
    ("step_concatenation", "concatenate"),
]

# Anchor model 步骤序列
_ANCHOR_STEPS_MODEL = [
    ("step_generate_anchor", "generate_anchor"),
    (None, "clip_prompts"),
    ("step_clip_generation", "clip_gen"),
]


# ═══════════════════════════════════════════════════════════════
# 产物定义（每种模式的产物模板）
# ═══════════════════════════════════════════════════════════════

def _creative_artifact_defs() -> list[dict]:
    """Creative 模式的产物定义模板。"""
    return [
        {"type": "image_analysis", "step_key": "image_analysis", "label": "artImageAnalysis",
         "category": "text", "scope": "task", "file": "image_analysis.txt", "fields": ["image_analysis_file"]},
        {"type": "story", "step_key": "story", "label": "artStory",
         "category": "text", "scope": "task", "file": "story.txt", "fields": ["story_file"]},
        {"type": "character_ref", "step_key": "character_ref", "label": "artCharacterRef",
         "category": "image", "scope": "task", "file": "character_reference.png",
         "fields": ["character_ref_file", "character_ref_prompt", "character_appearance"]},
        {"type": "script", "step_key": "script", "label": "artScript",
         "category": "json", "scope": "task", "file": "script.json",
         "fields": ["script_file", "narrations"], "extra_files": ["prompts.json"]},
        {"type": "end_frame_prompts", "step_key": "end_frame_prompts", "label": "artEndFramePrompts",
         "category": "json", "scope": "task", "file": "end_frame_prompts.json",
         "fields": ["end_frame_prompts_file"]},
        # 场景级产物
        {"type": "end_frame", "step_key": "end_frame_gen", "label": "artEndFrame",
         "category": "image", "scope": "scene", "file": "scene_{i}/end_frame.png",
         "scene_fields": ["end_frame_file"],
         # step_end_frame_generation 重置后 pregenerated_end_frames 也需清空（pipeline 会重建）
         "clear_top_fields": ["pregenerated_end_frames"]},
        {"type": "video", "step_key": "video_gen", "label": "artVideo",
         "category": "video", "scope": "scene", "file": "scene_{i}/video.mp4",
         "scene_fields": ["video_file", "video_id", "video_status"],
         "extra_files": ["scene_{i}/task.json", "scene_{i}/curl.sh"]},
        # 任务级音频/字幕
        {"type": "audio", "step_key": "audio", "label": "artAudio",
         "category": "audio", "scope": "task", "file": "combined_narration.mp3",
         "fields": [], "scene_fields_all": ["narration_audio"]},
        {"type": "subtitle", "step_key": "subtitle", "label": "artSubtitle",
         "category": "subtitle", "scope": "task", "file": "combined_narration.srt",
         "fields": ["subtitle_styles_path"], "scene_fields_all": ["subtitle_srt"],
         "extra_files": ["subtitle_styles.json"]},
        {"type": "final_video", "step_key": "concatenate", "label": "artFinalVideo",
         "category": "video", "scope": "task", "file": "final_video.mp4",
         "fields": ["final_video_file"]},
    ]


def _manuscript_artifact_defs() -> list[dict]:
    """Manuscript 模式的产物定义模板。"""
    return [
        {"type": "scene_prompts", "step_key": "scene_prompts", "label": "artScenePrompts",
         "category": "json", "scope": "task", "file": "prompts.json",
         "fields": [], "para_fields_all": ["scene_prompt"]},
        {"type": "video", "step_key": "video_gen", "label": "artParaVideo",
         "category": "video", "scope": "paragraph", "file": "para_{i}/video.mp4",
         "para_fields": ["video_file", "video_id"],
         "extra_files": ["para_{i}/task.json", "para_{i}/curl.sh"]},
        {"type": "audio", "step_key": "audio", "label": "artAudio",
         "category": "audio", "scope": "task", "file": "full_narration.mp3",
         "fields": ["combined_audio"]},
        {"type": "subtitle", "step_key": "subtitle", "label": "artSubtitle",
         "category": "subtitle", "scope": "task", "file": "full_subtitle.srt",
         "fields": ["combined_subtitle", "subtitle_styles_path"],
         "extra_files": ["subtitle_styles.json"]},
        {"type": "final_video", "step_key": "concatenate", "label": "artFinalVideo",
         "category": "video", "scope": "task", "file": "final_video.mp4",
         "fields": ["final_video_file"]},
    ]


def _anchor_artifact_defs(is_model_mode: bool) -> list[dict]:
    """Anchor 模式的产物定义模板。"""
    artifacts = [
        {"type": "anchor_image", "step_key": "generate_anchor", "label": "artAnchorImage",
         "category": "image", "scope": "task", "file": "anchor.png",
         "fields": ["anchor_image_path", "anchor_image_url"]},
        {"type": "clip_prompts", "step_key": "clip_prompts", "label": "artClipPrompts",
         "category": "json", "scope": "task", "file": "prompts.json",
         "fields": []},
        {"type": "clip", "step_key": "clip_gen", "label": "artClip",
         "category": "video", "scope": "task", "file": "clip/clip.mp4",
         "fields": []},
    ]
    if not is_model_mode:
        # post_stitch 模式还有音频、字幕、最终视频
        artifacts.extend([
            {"type": "audio", "step_key": "audio", "label": "artAudio",
             "category": "audio", "scope": "task", "file": "full_narration.mp3",
             "fields": ["combined_audio"]},
            {"type": "subtitle", "step_key": "subtitle", "label": "artSubtitle",
             "category": "subtitle", "scope": "task", "file": "full_subtitle.srt",
             "fields": ["combined_subtitle", "subtitle_styles_path"],
             "extra_files": ["subtitle_styles.json"]},
            {"type": "final_video", "step_key": "concatenate", "label": "artFinalVideo",
             "category": "video", "scope": "task", "file": "final_video.mp4",
             "fields": ["final_video_file", "final_video_path"]},
        ])
    return artifacts


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def _get_steps_for_state(state: BaseTaskState) -> list[tuple[Optional[str], str]]:
    """根据 state 类型返回步骤序列。"""
    if isinstance(state, CreativeVideoTask):
        return _CREATIVE_STEPS
    elif isinstance(state, ManuscriptVideoTask):
        return _MANUSCRIPT_STEPS
    elif isinstance(state, AnchorVideoTask):
        if state.audio_source == "model":
            return _ANCHOR_STEPS_MODEL
        return _ANCHOR_STEPS_POST_STITCH
    return []


def _get_artifact_defs(state: BaseTaskState) -> list[dict]:
    """根据 state 类型返回产物定义列表。"""
    if isinstance(state, CreativeVideoTask):
        return _creative_artifact_defs()
    elif isinstance(state, ManuscriptVideoTask):
        return _manuscript_artifact_defs()
    elif isinstance(state, AnchorVideoTask):
        return _anchor_artifact_defs(state.audio_source == "model")
    return []


def _step_key_to_field(steps: list[tuple[Optional[str], str]], step_key: str) -> Optional[str]:
    """根据 step_key 查找对应的 step_field。"""
    for field_name, key in steps:
        if key == step_key:
            return field_name
    return None


def _step_key_to_order(steps: list[tuple[Optional[str], str]], step_key: str) -> int:
    """根据 step_key 查找在步骤序列中的位置索引。"""
    for i, (_, key) in enumerate(steps):
        if key == step_key:
            return i
    return -1


def _format_path(template: str, index: int) -> str:
    """格式化路径模板中的 {i}。"""
    return template.replace("{i}", str(index))


# ═══════════════════════════════════════════════════════════════
# 公共 API
# ═══════════════════════════════════════════════════════════════


def list_artifacts(state: BaseTaskState, task_dir: str) -> list[ArtifactDescriptor]:
    """列举任务的所有中间产物（含存在性检测）。

    Args:
        state: 任务状态（CreativeVideoTask / ManuscriptVideoTask / AnchorVideoTask）
        task_dir: 任务目录绝对路径

    Returns:
        产物描述符列表，按步骤顺序排列
    """
    defs = _get_artifact_defs(state)
    if not defs:
        return []

    # 获取场景/段落数量
    if isinstance(state, CreativeVideoTask):
        scope_count = len(state.scenes)
    elif isinstance(state, ManuscriptVideoTask):
        scope_count = len(state.paragraphs)
    elif isinstance(state, AnchorVideoTask):
        scope_count = len(state.paragraphs) if state.paragraphs else 0
    else:
        scope_count = 0

    result: list[ArtifactDescriptor] = []

    for d in defs:
        if d["scope"] == "task":
            # 任务级产物
            file_relpath = d.get("file")
            exists = False
            size = 0
            if file_relpath:
                abs_path = os.path.join(task_dir, file_relpath)
                if os.path.exists(abs_path):
                    exists = True
                    size = os.path.getsize(abs_path)

            step_field = _step_key_to_field(_get_steps_for_state(state), d["step_key"])
            result.append(ArtifactDescriptor(
                artifact_id=f"{state.task_type.value}:{d['type']}",
                step_key=d["step_key"],
                step_field=step_field,
                label_key=d["label"],
                category=d["category"],
                scope="task",
                scope_index=None,
                file_relpath=file_relpath,
                state_fields=d.get("fields", []),
                exists=exists,
                size=size,
                deletable=True,
            ))
        elif d["scope"] in ("scene", "paragraph"):
            # 场景/段落级产物
            for i in range(scope_count):
                file_relpath = _format_path(d["file"], i)
                abs_path = os.path.join(task_dir, file_relpath)
                exists = os.path.exists(abs_path)
                size = os.path.getsize(abs_path) if exists else 0

                step_field = _step_key_to_field(_get_steps_for_state(state), d["step_key"])
                result.append(ArtifactDescriptor(
                    artifact_id=f"{state.task_type.value}:{d['type']}:{i}",
                    step_key=d["step_key"],
                    step_field=step_field,
                    label_key=d["label"],
                    category=d["category"],
                    scope=d["scope"],
                    scope_index=i,
                    file_relpath=file_relpath,
                    state_fields=[],  # 场景级字段在 scene_updates 中处理
                    exists=exists,
                    size=size,
                    deletable=True,
                ))

    return result


def resolve_artifact(artifact_id: str, state: BaseTaskState, task_dir: str) -> Optional[ArtifactDescriptor]:
    """根据 artifact_id 解析单个产物描述符。

    Args:
        artifact_id: 产物 ID, 如 "creative:end_frame:2"
        state: 任务状态
        task_dir: 任务目录路径

    Returns:
        产物描述符, 或 None 如果未找到
    """
    artifacts = list_artifacts(state, task_dir)
    for art in artifacts:
        if art.artifact_id == artifact_id:
            return art
    return None


def get_cascade_plan(artifact_id: str, state: BaseTaskState, task_dir: str) -> Optional[CascadePlan]:
    """计算删除指定产物后的级联删除计划。

    级联原则:
    1. 删除该产物文件 + 清空对应字段
    2. 重置该产物所在步骤及之后所有步骤的状态为 PENDING
    3. 删除后续步骤的所有产物文件
    4. 对于场景级产物, 级联删除同类型后续场景(scene_N → scene_{N+1..})的产物
    5. 删除 video 时同时删除 task.json/curl.sh 缓存文件

    Args:
        artifact_id: 要删除的产物 ID
        state: 任务状态
        task_dir: 任务目录路径

    Returns:
        级联删除计划, 或 None 如果产物未找到
    """
    artifact = resolve_artifact(artifact_id, state, task_dir)
    if not artifact:
        return None

    steps = _get_steps_for_state(state)
    defs = _get_artifact_defs(state)
    plan = CascadePlan()

    # 1. 找到被删产物所在步骤的位置
    target_order = _step_key_to_order(steps, artifact.step_key)
    if target_order < 0:
        return None

    # 2. 收集所有 order >= target_order 的步骤字段（用于重置）
    for step_field, _ in steps[target_order:]:
        if step_field:  # None 的步骤没有状态字段
            plan.steps_to_reset.append(step_field)

    # 3. 收集所有 order >= target_order 的产物定义
    cascaded_defs = []
    for d in defs:
        d_order = _step_key_to_order(steps, d["step_key"])
        if d_order >= target_order:
            cascaded_defs.append(d)

    # 4. 对于场景级产物, 确定级联起始索引
    cascade_from_index = 0
    if artifact.scope in ("scene", "paragraph") and artifact.scope_index is not None:
        cascade_from_index = artifact.scope_index

    # 4a. 确定场景级产物的级联终止索引
    # keyframes/ti2vid 模式有视觉链依赖，删除 scene_N 会级联到 scene_{N+1..}
    # none 模式场景独立，删除 scene_N 只影响当前场景
    # Manuscript/Anchor 段落间独立，同 none 模式处理
    scene_cascade_to_end = True  # 默认级联到末尾
    if isinstance(state, CreativeVideoTask):
        if state.chaining_mode == "none" and artifact.scope == "scene":
            scene_cascade_to_end = False
    elif isinstance(state, (ManuscriptVideoTask, AnchorVideoTask)):
        if artifact.scope in ("scene", "paragraph"):
            scene_cascade_to_end = False

    # 5. 获取场景/段落数量
    if isinstance(state, CreativeVideoTask):
        scope_count = len(state.scenes)
        list_field = "scenes"
    elif isinstance(state, ManuscriptVideoTask):
        scope_count = len(state.paragraphs)
        list_field = "paragraphs"
    elif isinstance(state, AnchorVideoTask):
        scope_count = len(state.paragraphs) if state.paragraphs else 0
        list_field = "paragraphs"
    else:
        scope_count = 0
        list_field = ""

    # 6. 遍历级联产物定义, 生成删除计划
    for d in cascaded_defs:
        if d["scope"] == "task":
            # 任务级产物
            file_relpath = d.get("file")
            if file_relpath:
                plan.files_to_delete.append(file_relpath)

            # 额外文件
            for ef in d.get("extra_files", []):
                plan.files_to_delete.append(ef)

            # 顶层字段清空
            for f in d.get("fields", []):
                plan.fields_to_clear[f] = ""

            # 场景字段全量清空 (如 narration_audio 对所有 scenes)
            for sf in d.get("scene_fields_all", []):
                for i in range(scope_count):
                    plan.scene_updates.append({
                        "list_field": "scenes",
                        "from_index": i,
                        "field": sf,
                        "value": "",
                    })

            # 段落字段全量清空
            for pf in d.get("para_fields_all", []):
                for i in range(scope_count):
                    plan.scene_updates.append({
                        "list_field": "paragraphs",
                        "from_index": i,
                        "field": pf,
                        "value": "",
                    })

        elif d["scope"] in ("scene", "paragraph"):
            # 场景/段落级产物 - 从 cascade_from_index 开始
            current_list_field = "scenes" if d["scope"] == "scene" else "paragraphs"
            # 确定终止索引：如果场景独立（none模式/manuscript/anchor），只删当前场景
            if scene_cascade_to_end:
                end_idx = scope_count
            else:
                end_idx = cascade_from_index + 1
            for i in range(cascade_from_index, end_idx):
                # 文件
                file_relpath = _format_path(d["file"], i)
                plan.files_to_delete.append(file_relpath)

                # 额外文件
                for ef in d.get("extra_files", []):
                    plan.files_to_delete.append(_format_path(ef, i))

                # 场景/段落字段清空
                for sf in d.get("scene_fields", d.get("para_fields", [])):
                    plan.scene_updates.append({
                        "list_field": current_list_field,
                        "from_index": i,
                        "field": sf,
                        "value": "",
                    })

                    # video_status 需要重置为 pending 而非空字符串
                    if sf == "video_status":
                        plan.scene_updates[-1]["value"] = StepStatus.PENDING

            # 额外顶层字段清空（如 pregenerated_end_frames）
            for f in d.get("clear_top_fields", []):
                if f not in plan.fields_to_clear:
                    plan.fields_to_clear[f] = {}  # dict 类型默认空字典

    # 7. 去重文件列表
    seen = set()
    unique_files = []
    for f in plan.files_to_delete:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    plan.files_to_delete = unique_files

    return plan


def apply_cascade_plan(state: BaseTaskState, plan: CascadePlan) -> dict:
    """将级联计划应用到 state 对象上（原地修改），返回 update_state 的参数字典。

    Args:
        state: 任务状态（将被原地修改）
        plan: 级联删除计划

    Returns:
        dict: 传递给 TaskManager.update_state() 的参数
    """
    update_kwargs: dict[str, Any] = {}

    # 1. 重置步骤状态
    for step_field in plan.steps_to_reset:
        setattr(state, step_field, StepStatus.PENDING)
        update_kwargs[step_field] = StepStatus.PENDING

    # 2. 清空顶层字段（根据字段类型选择正确的默认值）
    for field_name, default_val in plan.fields_to_clear.items():
        if hasattr(state, field_name):
            # 如果默认值已经是正确类型，直接使用
            current_val = getattr(state, field_name)
            if isinstance(current_val, list) and not isinstance(default_val, list):
                default_val = []
            elif isinstance(current_val, dict) and not isinstance(default_val, dict):
                default_val = {}
            setattr(state, field_name, default_val)
            update_kwargs[field_name] = default_val

    # 3. 更新 scenes/paragraphs 列表中的字段
    for su in plan.scene_updates:
        list_field = su["list_field"]
        idx = su["from_index"]
        field_name = su["field"]
        value = su["value"]

        items = getattr(state, list_field, None)
        if items and idx < len(items):
            if hasattr(items[idx], field_name):
                setattr(items[idx], field_name, value)

    # 4. 将更新后的 scenes/paragraphs 加入 update_kwargs
    if isinstance(state, CreativeVideoTask):
        update_kwargs["scenes"] = state.scenes
    elif isinstance(state, (ManuscriptVideoTask, AnchorVideoTask)):
        update_kwargs["paragraphs"] = state.paragraphs

    # 5. 设置任务状态为 PENDING
    state.status = StepStatus.PENDING
    update_kwargs["status"] = StepStatus.PENDING

    return update_kwargs
