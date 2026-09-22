"""core.production.bible_builder — 剧本 -> 制作圣经 -> 镜头拆解 -> 连续性校验。

所有 LLM 调用走 Agnes Chat API（最佳文本模型）。本模块是「状态化电影制作流水线」
的情报核心：先做分析（永不拿到剧本直接生成视频），再产出结构化制作圣经与镜头计划。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import List

from core.production.cinematography import (
    CINEMATOGRAPHY_SYSTEM,
    DIRECTOR_PLANNING_SYSTEM,
    lookup_visual_style,
    style_catalog_prompt,
)

logger = logging.getLogger(__name__)


_SYSTEM_ANALYZE = """You are a senior film production planner and script supervisor.
You receive a screenplay / story / novel adaptation / commercial / animation / documentary script.
Your job is to analyze it into a structured production bible BEFORE any video is generated.

""" + CINEMATOGRAPHY_SYSTEM + """

Return ONLY a single JSON object (no markdown, no commentary) with this exact schema:
{
  "logline": str,
  "premise": str,
  "theme": str,
  "visual_style": str,            // MASTER VISUAL STYLE (1-3 sentences, concrete look)
  "cinematography": str,          // camera grammar / lens / movement rules
  "lighting": str,               // lighting language
  "color_script": str,           // color progression across the story
  "audio_plan": str,             // dialogue ambience / foley direction
  "music_plan": str,             // recurring motifs direction
  "vfx_plan": str,               // required visual effects
  "timeline": str,               // chronological master timeline summary
  "characters": [ {"name": str, "role": str, "description": str, "personality": str} ],
  "locations": [ {"name": str, "description": str} ],
  "props": [ {"name": str, "description": str} ],
  "scenes": [                    // story-level scenes (NOT shots)
    {
      "id": "s1",
      "act": str,
      "summary": str,
      "location": str,           // must match a name in "locations" (or "unknown")
      "time_of_day": str,
      "weather": str,
      "characters": [str],        // names from "characters"
      "emotional_beat": str,
      "dialogue_summary": str
    }
  ]
}

Rules:
- Preserve the author's intent; do not invent major plot. Infer ONLY what is necessary.
- Keep character names consistent everywhere.
- Every scene's "location" must reference a location defined in "locations".
- "visual_style" / "cinematography" / "lighting" are reused by EVERY shot prompt.
- "cinematography" must be CONCRETE: name lens choices, movement vocabulary, and
  lighting approaches from the grammar above — not generic phrases like "nice camera work".
"""

_SYSTEM_SHOTS = """You are a storyboard artist and assistant editor.
Given a production bible and its story-level scenes, break the script into concrete SHOTS.
Each shot is a single continuous camera take (max ~20s).

""" + DIRECTOR_PLANNING_SYSTEM + """

Return ONLY a JSON array (no markdown) of shot objects with this schema:
[
  {
    "id": "shot_1",
    "scene_id": "s1",
    "duration": int,              // 4-20 seconds, based on dialogue/action
    "characters": [str],          // names present in this shot
    "location": str,             // location name
    "action": str,               // what happens visually (concrete, continuous)
    "emotion": str,              // emotional state of the shot
    "dialogue": str,             // spoken line(s) / narration for THIS shot (can be "")
    "camera": str,               // shot size + angle + movement
    "lighting": str,             // lighting note for this shot (or "")
    "continuity_in": str,        // state at shot start (who/where/what they hold/weather)
    "continuity_out": str        // state at shot end (for chaining to next shot)
  }
]

Rules:
- Order shots by story time. Maintain screen direction & 180-degree axis within a scene.
- Each shot must logically follow the previous (use continuity_in/out).
- Do NOT exceed 20s per shot; split longer beats.
- Keep character/prop/location names identical to the bible.
- The "camera" field MUST use precise cinematography vocabulary:
  shot size + angle + movement (e.g. "medium close-up, eye-level, slow dolly in").
  Follow the storyboard checklist: vary shot sizes between adjacent shots, use
  establishing shots for new locations, use close-ups for emotional peaks,
  inserts for key props.
"""

_SYSTEM_VALIDATE = """You are a continuity supervisor.
Given a production bible and a shot list, check for continuity & logic errors.
Return ONLY a JSON array of issue strings (empty array if clean). Examples of issues:
- character appears without being introduced
- location changes without motivation
- wrong character at a location
- timeline contradiction
- prop teleporting / missing
- impossible screen direction
- emotion jump without cause
Only report REAL problems that would break viewer belief. Be concise."""


class ProductionBibleBuilder:
    """封装 剧本 -> 制作圣经 -> 镜头拆解 -> 连续性校验 的 LLM 调用。"""

    def __init__(self, chat_api):
        self.chat = chat_api

    async def analyze_script(self, script: str, style_preset: str) -> dict:
        style_desc = lookup_visual_style(style_preset)
        user = (
            f"MASTER VISUAL STYLE PRESET requested by user: {style_preset}\n"
            f"(concrete interpretation: {style_desc})\n\n"
            f"{style_catalog_prompt()}\n\n"
            f"=== SCRIPT / STORY ===\n{script}\n=== END SCRIPT ==="
        )
        data = await self._json(self.chat, _SYSTEM_ANALYZE, user, max_tokens=8192)
        data.setdefault("characters", [])
        data.setdefault("locations", [])
        data.setdefault("props", [])
        data.setdefault("scenes", [])
        data.setdefault("visual_style", style_preset)
        # 把风格的具体摄影解释写进圣经（每次 shot prompt 复用）
        if style_desc and style_desc != style_preset:
            data["visual_style"] = f"{style_preset}. {style_desc}"
        return data

    async def build_shot_breakdown(self, bible: dict) -> List[dict]:
        user = (
            f"=== PRODUCTION BIBLE ===\n{json.dumps(bible, ensure_ascii=False)}\n"
            f"=== END BIBLE ===\nBreak into shots now."
        )
        shots = await self._json(self.chat, _SYSTEM_SHOTS, user, max_tokens=8192)
        if isinstance(shots, dict):
            shots = shots.get("shots", [])
        if not isinstance(shots, list):
            shots = []
        for i, s in enumerate(shots):
            s.setdefault("id", f"shot_{i+1}")
            s.setdefault("duration", 8)
            s.setdefault("characters", [])
            s.setdefault("location", "unknown")
            s.setdefault("action", "")
            s.setdefault("emotion", "")
            s.setdefault("dialogue", "")
            s.setdefault("camera", "")
            s.setdefault("lighting", "")
            s.setdefault("continuity_in", "")
            s.setdefault("continuity_out", "")
            try:
                s["duration"] = max(4, min(20, int(s["duration"])))
            except Exception:
                s["duration"] = 8
        return self._enforce_shot_variation(shots)

    async def validate_continuity(self, bible: dict, shots: List[dict]) -> List[str]:
        user = (
            f"=== BIBLE ===\n{json.dumps(bible, ensure_ascii=False)}\n"
            f"=== SHOTS ===\n{json.dumps(shots, ensure_ascii=False)}"
        )
        issues = await self._json(self.chat, _SYSTEM_VALIDATE, user, max_tokens=2048)
        if isinstance(issues, dict):
            issues = issues.get("issues", [])
        if not isinstance(issues, list):
            issues = []
        return [str(x) for x in issues]

    @staticmethod
    def _enforce_shot_variation(shots: List[dict]) -> List[dict]:
        """导演规则守门员：相邻镜头的景别/角度至少一项不同。

LLM 偶尔会连续输出相同景别（视觉疲劳）。该函数不改写 LLM 的
创意选择，只对「连续 2 次完全相同的 camera 描述」做机械式修正：
交替使用 OTS / 角度变化，保证 shot variation。
"""
        if not shots:
            return shots

        def _size_rank(camera: str) -> int:
            """0=最远(extreme wide) … 6=最近(extreme close-up)"""
            c = (camera or "").lower()
            ladder = [
                ("extreme wide", 0), ("extreme-wide", 0),
                ("wide", 1), ("full", 2), ("medium close", 4),
                ("medium", 3), ("close", 5), ("ecu", 6),
            ]
            for token, rank in ladder:
                if token in c:
                    return rank
            return 3  # 默认 medium

        for i in range(1, len(shots)):
            prev = (shots[i - 1].get("camera") or "").strip().lower()
            cur = shots[i].get("camera") or ""
            if not prev or not cur:
                continue
            if prev == cur.strip().lower():
                # 连续雷同：交替使用 OTS / 角度变化，保证 shot variation
                angle = "over-the-shoulder" if i % 2 else "high angle"
                shots[i]["camera"] = (
                    f"{cur}, {angle}"
                    if angle not in cur.lower()
                    else cur
                )
        return shots

    @staticmethod
    async def _json(chat, system: str, user: str, max_tokens: int = 4096):
        try:
            # chat_json 内部是同步 requests.post（重试 3 次，最长可达数分钟），
            # 必须放线程池，否则会阻塞整个 asyncio 事件循环（电影模式曾因此假死）。
            return await asyncio.to_thread(chat.chat_json, system, user, max_tokens=max_tokens)
        except Exception as e:  # noqa: BLE001
            logger.warning("[BibleBuilder] chat_json failed (%s); returning empty", e)
            return {}


def compose_shot_prompt(shot: dict, bible: dict, style_preset: str) -> str:
    """将镜头结构化字段 + 制作圣经 组合为模块化视频生成 prompt（§46）。"""
    vis = bible.get("visual_style") or style_preset
    cine = bible.get("cinematography", "")
    light_bible = bible.get("lighting", "")
    chars = shot.get("characters", [])
    char_lines = "\n".join(f"- {c}" for c in chars) or "- (none)"
    loc = shot.get("location", "unknown")
    lighting = shot.get("lighting") or light_bible
    neg = (
        "no character redesign, no face drift, no hairstyle change, "
        "no costume change, no age change, no extra characters, "
        "no missing characters, no duplicate objects, no object teleportation, "
        "no inconsistent architecture, no random camera movement, "
        "no impossible anatomy, no incorrect eye direction"
    )
    parts = [
        f"[MASTER VISUAL STYLE]\n{vis}",
        f"[CHARACTERS]\n{char_lines}",
        f"[LOCATION]\n{loc}",
        f"[ACTION & EMOTION]\n{shot.get('action','')} | emotion: {shot.get('emotion','')}",
        f"[CAMERA]\n{shot.get('camera','')}",
        f"[CINEMATOGRAPHY]\n{cine}",
        f"[LIGHTING]\n{lighting}",
        f"[CONTINUITY]\nIn: {shot.get('continuity_in','')}\nOut: {shot.get('continuity_out','')}",
        f"[NEGATIVE CONSTRAINTS]\n{neg}",
    ]
    return "\n\n".join(p for p in parts if p)
