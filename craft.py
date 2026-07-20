#!/usr/bin/env python3
"""
Professional Screenwriting Suite — CRAFT
========================================
Research-based, industry-standard screenwriting assistant.

Outputs: beat sheet, treatment, scene outline, full screenplay,
character bible, and shot list — all formatted to Hollywood standards.

Usage:
    python craft.py write --genre thriller --idea "A detective finds..."
    python craft.py beat-sheet --genre action --idea "..."
    python craft.py treatment --genre drama --idea "..."
    python craft.py screenplay --genre horror --idea "..."
    python craft.py character-bible --genre scifi --idea "..."
    python craft.py shot-list --genre action --idea "..."
    python craft.py analyze --file script.txt --type screenplay
    python craft.py export --task-id story_xxx  # from Agnes Video Studio
"""

import argparse
import json
import os
import re
import sys
import textwrap
from datetime import datetime
from typing import List, Optional

# ─── Import from Agnes Video Studio ──────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.screenwriter import Screenwriter
from core.config import load_config

# ─── Constants ───────────────────────────────────────────────────────────────

# Industry standard page-to-minute: ~1 page = 1 minute
PAGE_MINUTE_RATIO = 1.0

# Standard screenplay format constants
PAGE_WIDTH = 132  # monospaced character columns (Courier 12pt, 10-inch margin)
MARGIN_DIALOGUE = 30
MARGIN_ACTION = 1
MARGIN_CHARACTER = 23

# ─── Story Structure Frameworks ──────────────────────────────────────────────

STRUCTURES = {
    "three_act": {
        "name": "Three-Act Structure",
        "description": "Classic Hollywood structure: Setup → Confrontation → Resolution",
        "acts": {
            "Act 1 (25%)": [
                "Opening Image",
                "Theme Stated",
                "Setup / Ordinary World",
                "Catalyst / Inciting Incident",
                "Debate",
                "Plot Point 1: Cross into Act 2"
            ],
            "Act 2A (20%)": [
                "New Situation",
                "Fun & Games (Promises of the Premise)",
                "B Story (Relationship/Subplot)"
            ],
            "Act 2B (30%)": [
                "Midpoint: False Victory or False Defeat",
                "Rising Action / Complications",
                "All Is Lost / Dark Night of the Soul",
                "Plot Point 2: Cross into Act 3"
            ],
            "Act 3 (25%)": [
                "Climax",
                "Final Image"
            ]
        }
    },
    "save_the_cat": {
        "name": "Save the Cat! (Blake Snyder)",
        "description": "15-beat sheet for commercial storytelling",
        "beats": [
            ("Opening Image", 0, "The perfect snapshot of the protagonist's ordinary world"),
            ("Theme Stated", 5, "Someone states the theme the protagonist needs to learn"),
            ("Setup", 1, "Show the protagonist's flaws, life, and the world they live in"),
            ("Catalyst", 12, "Something happens that changes everything — the inciting incident"),
            ("Debate", 12, "The protagonist hesitates. Do they accept the challenge?"),
            ("Break into Two", 25, "Crossing the threshold into the new world/act"),
            ("B Story", 30, "The relationship subplot begins (often love story, but can be friendship/family)"),
            ("Fun & Games", 30, "The promises of the premise — what the audience came to see"),
            ("Midpoint", 50, "False Victory or False Defeat — stakes are raised"),
            ("Bad Guys Close In", 20, "Internal and external pressures mount"),
            ("All Is Lost", 10, "Everything falls apart. Usually includes a 'death' metaphor"),
            ("Dark Night of the Soul", 10, "The protagonist hits bottom. Must face the truth"),
            ("Break into Three", 5, "The 'Aha!' moment — the protagonist finds the solution"),
            ("Finale", 20, "The climax — protagonist applies everything learned"),
            ("Final Image", 1, "Opposite of the opening image — we see how the protagonist has changed")
        ]
    },
    "hero_journey": {
        "name": "Hero's Journey (Campbell/Vogler)",
        "description": "The monomyth — 12 stages of the hero's transformation",
        "acts": {
            "Departure": [
                "Ordinary World",
                "Call to Adventure",
                "Refusal of the Call",
                "Meeting the Mentor",
                "Crossing the Threshold"
            ],
            "Initiation": [
                "Tests, Allies & Enemies",
                "Approach to the Inmost Cave",
                "Ordeal (Central Crisis)",
                "Reward (Seizing the Sword)",
                "The Road Back"
            ],
            "Return": [
                "Resurrection",
                "Return with the Elixir"
            ]
        }
    },
    "fichtean": {
        "name": "Fichtean Curve",
        "description": "Rapid-fire crises — ideal for thrillers, action, horror",
        "beats": [
            "Crisis 1",
            "Crisis 2",
            "Crisis 3",
            "Crisis 4",
            "Crisis 5",
            "Climax",
            "Resolution"
        ]
    },
    "five_act": {
        "name": "Five-Act Structure",
        "description": "Shakespearean/classical drama structure",
        "acts": [
            "Exposition — Introduce characters and world",
            "Rising Action — Complications begin",
            "Climax — The turning point",
            "Falling Action — Consequences unfold",
            "Catastrophe/Resolution — The final outcome"
        ]
    }
}

GENRE_TEMPLATES = {
    "action": {
        "pacing": "Fast. 60-90 second scenes. Quick cuts. High stakes from page 1.",
        "visual_style": "Dynamic camera, wide establishing shots, tight action close-ups, debris and particles.",
        "protagonist": "Capable but flawed hero with a personal stake. Physical + emotional arc.",
        "antagonist": "Forceful, intelligent adversary. Mirror of the hero.",
        "key_elements": ["Set pieces", "Chase sequences", "Reversals", "Time pressure"]
    },
    "thriller": {
        "pacing": "Building tension. Slow burn → escalating dread → explosive climax.",
        "visual_style": "Noir shadows, Dutch angles, claustrophobic framing, desaturated colors.",
        "protagonist": "Reluctant investigator or everyman caught in something bigger.",
        "antagonist": "Hidden threat. Psychological manipulation over brute force.",
        "key_elements": ["Suspense", "Revelations", "Paranoia", "Race against time"]
    },
    "drama": {
        "pacing": "Character-driven. 90-120 second scenes. Emphasis on dialogue and subtext.",
        "visual_style": "Warm naturalistic lighting, intimate close-ups, slow camera movement.",
        "protagonist": "Deeply flawed person confronting truth about themselves.",
        "antagonist": "Internal conflict + an external force (person, system, society).",
        "key_elements": ["Emotional truth", "Relationships", "Moral dilemmas", "Transformation"]
    },
    "horror": {
        "pacing": "Tension → Release → Greater Tension. Dread builds slowly, payoff is intense.",
        "visual_style": "High contrast, deep shadows, practical effects aesthetic, claustrophobic spaces.",
        "protagonist": "Every person who must overcome terror to survive.",
        "antagonist": "Unknown/inescapable force. Fear of the unseen.",
        "key_elements": ["Atmosphere", "Foreshadowing", "Jump scares (sparingly)", "Psychological dread"]
    },
    "comedy": {
        "pacing": "Rapid exchanges. Rule of three for gags. Escalating absurdity.",
        "visual_style": "Bright, open framing, symmetrical compositions, expressive character acting.",
        "protagonist": "Lovable loser or oblivious fool. Wishes for something impossible.",
        "antagonist": "Obstacle to desire — often a snob, a system, or the protagonist's own flaw.",
        "key_elements": ["Wit", "Timing", "Misunderstandings", "Character-driven humor"]
    },
    "scifi": {
        "pacing": "World-building first, then plot. Slow reveal of the bigger picture.",
        "visual_style": "Futuristic architecture, clean lines, dramatic lighting, practical + CGI blend.",
        "protagonist": "Ordinary person in extraordinary circumstances. Discovery arc.",
        "antagonist": "The world itself, AI, corrupt system, or the cost of progress.",
        "key_elements": ["World rules", "Technology implications", "Philosophical questions", "Scale"]
    },
    "fantasy": {
        "pacing": "Epic, meandering early, then converging. Build the world, then break it.",
        "visual_style": "Rich colors, sweeping vistas, magical effects, detailed costumes.",
        "protagonist": "Unlikely hero discovering destiny. Classic arc: weak → strong.",
        "antagonist": "Dark force threatening the entire world/magic system.",
        "key_elements": ["Magic rules", "Prophecy/destiny", "Ancient evils", "World-building"]
    },
    "romance": {
        "pacing": "Emotional beats timed carefully. Build chemistry → conflict → reunion.",
        "visual_style": "Soft lighting, warm palettes, intimate framing, music-driven moments.",
        "protagonist": "Two people who need each other but can't (yet).",
        "antagonist": "Circumstance, past trauma, social barriers, or another person.",
        "key_elements": ["Chemistry", "Obstacles", "Grand gesture", "Emotional payoff"]
    }
}

# ─── Core Classes ────────────────────────────────────────────────────────────

class Director:
    """
    Expert Director persona — makes creative decisions about story, pacing,
    visual style, and cinematic language. Uses industry-standard frameworks
    to guide every decision.
    """

    def __init__(self, screenwriter: Screenwriter):
        self.sw = screenwriter
        self.genre = ""
        self.structure = ""

    def direct_story(self, idea: str, genre: str, structure: str = "three_act",
                     target_runtime: str = "medium", language: str = "zh") -> dict:
        """Full story direction — returns structured story blueprint."""
        self.genre = genre
        self.structure = structure

        genre_info = GENRE_TEMPLATES.get(genre, {})
        structure_info = STRUCTURES.get(structure, STRUCTURES["three_act"])

        if language == "zh":
            sys_prompt = f"""
你是世界级电影导演兼剧本顾问。你精通好莱坞叙事结构、角色弧光、视觉语言，
以及所有类型片的叙事规则。

你将根据用户提供的创意想法，按照选定的叙事结构，生成一份专业的电影故事蓝图。

[选定的结构] {structure_info["name"]}: {structure_info["description"]}
[类型模板]: {genre_info.get("pacing", "")}

重要规则：
1. 使用与输入相同的语言输出所有内容
2. 每个情节节点必须有一个具体的、有冲突的事件，不能只是过渡
3. 角色必须有明确的内在缺陷和外在目标
4. 必须有至少2次情节反转
5. 高潮场景必须同时解决外在冲突（打败反派/解决问题）和内在冲突（角色成长）
6. 对白要简短有力，符合角色性格
7. 视觉描述要具体到可以拍摄的程度

输出格式必须严格遵循：
"""
        else:
            sys_prompt = f"""
You are a world-class film director and screenwriting consultant. You master Hollywood
narrative structures, character arcs, visual language, and genre-specific storytelling rules.

Based on the user's creative idea, generate a professional story blueprint using the
selected narrative structure.

[Selected Structure] {structure_info["name"]}: {structure_info["description"]}
[Genre Template]: {genre_info.get("pacing", "")}

RULES:
1. Output in the SAME LANGUAGE as the input
2. Each beat must have a SPECIFIC CONFLICT event, not just transitions
3. Characters must have clear internal flaws AND external goals
4. Include at least 2 plot twists
5. The climax must resolve BOTH external conflict (defeat villain/fix problem) AND internal conflict (character growth)
6. Dialogue must be SHORT and PUNCHY, matching character voices
7. Visual descriptions must be specific enough to be filmed

Output MUST follow this format exactly:
"""

        user_prompt = f"""
<idea>
{idea}
</idea>

<genre>{genre}</genre>
<structure>{structure}</structure>
<target_runtime>{target_runtime}</target_runtime>

输出 JSON:
"""

        if language == "zh":
            user_prompt += """
{
  "title": "电影标题",
  "logline": "一句话故事梗概（25-35字）——包括主角、目标、冲突、赌注",
  "theme": "主题：故事核心探讨的问题/道德困境",
  "genre_analysis": "为什么选择这个类型，它的叙事期待是什么",
  "characters": [
    {
      "name": "角色名",
      "role": "主角/反派/配角/导师",
      "want": "外在目标——角色想要什么（具体事物或结果）",
      "need": "内在需求——角色真正需要什么（成长/领悟）",
      "flaw": "性格缺陷——阻碍角色成长的核心问题",
      "arc": "角色弧光——从状态A到状态B的转变",
      "appearance": "外貌描述（服装、体型、发型、显著特征，用于视觉一致性）",
      "voice": "说话风格和语气"
    }
  ],
  "structure_map": {
    "beat_name": {
      "act": "第几幕",
      "page": "大约页码（假设~1页=1分钟）",
      "event": "这个节拍发生了什么——具体的冲突事件",
      "purpose": "这个节拍对故事的作用",
      "characters_involved": ["涉及角色名"],
      "visual_moment": "这个节拍最值得拍摄的画面（视觉描述）"
    }
  },
  "key_scenes": [
    {
      "index": 1,
      "name": "场景名",
      "act": "第几幕",
      "location": "地点",
      "conflict": "场景内的核心冲突",
      "tension": "紧张程度（低/中/高/极高）",
      "duration": "建议时长（秒）",
      "visual": "镜头描述",
      "dialogue": "关键对白（1-3句，角色: \"对白\" 格式）"
    }
  ],
  "twists": [
    {
      "description": "反转内容",
      "setup": "之前的铺垫（哪个场景埋了伏笔）",
      "impact": "对角色和故事的影响"
    }
  ],
  "climax": {
    "description": "高潮场景详细描述",
    "external_conflict": "外在冲突如何解决",
    "internal_conflict": "内在冲突如何解决",
    "visual_description": "高潮的视觉呈现"
  },
  "visual_style": {
    "color_palette": "色彩方案",
    "lighting": "用光风格",
    "camera_style": "摄影风格",
    "composition": "构图特点"
  },
  "pacing_guide": "节奏指导——哪里快、哪里慢、哪里留白"
}
"""
        else:
            user_prompt += """
{
  "title": "Movie title",
  "logline": "One-sentence story summary (25-35 words) — includes protagonist, goal, conflict, stakes",
  "theme": "Theme: The core question/moral dilemma the story explores",
  "genre_analysis": "Why this genre and what narrative expectations it creates",
  "characters": [
    {
      "name": "Character name",
      "role": "protagonist/antagonist/supporting/mentor",
      "want": "External goal — what the character wants (specific thing or result)",
      "need": "Internal need — what the character truly needs (growth/understanding)",
      "flaw": "Character flaw — the core issue preventing growth",
      "arc": "Character arc — transformation from state A to state B",
      "appearance": "Appearance description (clothing, body type, hair, distinctive features for visual consistency)",
      "voice": "Speaking style and tone"
    }
  ],
  "structure_map": {
    "beat_name": {
      "act": "Act number",
      "page": "Approximate page number (~1 page = 1 minute)",
      "event": "What SPECIFICALLY happens at this beat",
      "purpose": "What this beat does for the story",
      "characters_involved": ["character names"],
      "visual_moment": "The most filmable visual of this beat"
    }
  },
  "key_scenes": [
    {
      "index": 1,
      "name": "Scene name",
      "act": "Act number",
      "location": "Location",
      "conflict": "Core conflict within the scene",
      "tension": "Tension level (low/medium/high/extreme)",
      "duration": "Suggested duration (seconds)",
      "visual": "Shot description",
      "dialogue": "Key dialogue (1-3 lines, format: Character: \"dialogue\")"
    }
  ],
  "twists": [
    {
      "description": "What the twist is",
      "setup": "Foreshadowing — which scene planted the clue",
      "impact": "Impact on characters and story"
    }
  ],
  "climax": {
    "description": "Detailed description of the climax scene",
    "external_conflict": "How the external conflict is resolved",
    "internal_conflict": "How the internal conflict is resolved",
    "visual_description": "Visual depiction of the climax"
  },
  "visual_style": {
    "color_palette": "Color scheme",
    "lighting": "Lighting approach",
    "camera_style": "Cinematography style",
    "composition": "Composition characteristics"
  },
  "pacing_guide": "Pacing guide — where it speeds up, slows down, breathes"
}
"""

        result = self.sw._chat_json(sys_prompt, user_prompt)
        return result

    def write_screenplay(self, story_blueprint: dict, format_output: str = "industry") -> str:
        """
        Write a full screenplay from the story blueprint in industry-standard format.

        Industry screenplay format:
        - Courier 12pt font (we simulate with monospaced text)
        - Scene heading (slugline): INT./EXT. LOCATION - TIME
        - Action: Present tense, visual only, max 4 lines
        - Character: Centered, uppercase, max 12 chars
        - Parenthetical: (wryly) under character, optional
        - Dialogue: Under character
        - Transition: CUT TO: / FADE OUT. (right-aligned)
        """
        title = story_blueprint.get("title", "Untitled")
        logline = story_blueprint.get("logline", "")
        key_scenes = story_blueprint.get("key_scenes", [])
        characters = story_blueprint.get("characters", [])

        if format_output == "industry":
            return self._write_industry_format(story_blueprint, key_scenes, characters, title, logline)
        elif format_output == "visual":
            return self._write_visual_script(story_blueprint, key_scenes, characters)
        else:
            return self._write_industry_format(story_blueprint, key_scenes, characters, title, logline)

    def _write_industry_format(self, blueprint, key_scenes, characters, title, logline) -> str:
        """Write in standard industry screenplay format."""
        lines = []
        lines.append("=" * 78)
        lines.append(f"  {title}")
        lines.append(f"  LOG LINE: {logline}")
        lines.append("=" * 78)
        lines.append("")

        # Character list
        lines.append("CHARACTERS")
        lines.append("-" * 40)
        for char in characters:
            lines.append(f"  {char['name'].upper():30} {char['role']}")
        lines.append("")

        for scene in key_scenes:
            # Scene heading
            location = scene.get("location", "UNKNOWN LOCATION")
            act = scene.get("act", "")
            lines.append("")
            lines.append(f"  {'INT.' if 'INT' in location.upper() or '室内' in location else 'EXT.'} {location.upper()} - {act}")
            lines.append("")

            # Action
            visual = scene.get("visual", "")
            if visual:
                for line in textwrap.wrap(visual, 70):
                    lines.append(f"  {line}")

            # Dialogue
            dialogue = scene.get("dialogue", "")
            if dialogue:
                # Parse dialogue lines
                for dl in dialogue.split("\n"):
                    dl = dl.strip()
                    if not dl:
                        continue
                    # Match "Character: \"dialogue\""
                    match = re.match(r'(.+?):\s*"(.+?)"', dl)
                    if match:
                        char_name = match.group(1).strip()
                        dialogue_text = match.group(2).strip()
                        lines.append("")
                        # Find character in our list for positioning
                        char_idx = next((c['name'] for c in characters if c['name'] == char_name), char_name)
                        lines.append(f"  {char_idx.upper():35}")
                        lines.append(f"  {dialogue_text}")
                    else:
                        lines.append(f"  {dl}")

        lines.append("")
        lines.append("  FADE OUT.")
        lines.append("")
        return "\n".join(lines)

    def _write_visual_script(self, blueprint, key_scenes, characters) -> str:
        """Write a visual/script format optimized for AI video generation."""
        lines = []
        title = blueprint.get("title", "Untitled")
        lines.append(f"# SCRIPT: {title}")
        lines.append(f"# Generated by CRAFT Screenwriting Suite")
        lines.append(f"# Date: {datetime.now().strftime('%Y-%m-%d')}")
        lines.append("")

        for scene in key_scenes:
            scene_num = scene.get("index", 0)
            location = scene.get("location", "")
            visual = scene.get("visual", "")
            dialogue = scene.get("dialogue", "")
            tension = scene.get("tension", "")
            duration = scene.get("duration", "")

            lines.append(f"{'='*60}")
            lines.append(f"SCENE {scene_num}: {scene.get('name', '')}")
            lines.append(f"  Location: {location}")
            lines.append(f"  Tension: {tension}")
            lines.append(f"  Duration: {duration}s")
            lines.append(f"  Conflict: {scene.get('conflict', '')}")
            lines.append(f"{'='*60}")
            lines.append("")
            if visual:
                lines.append(f"  VISUAL: {visual}")
                lines.append("")
            if dialogue:
                lines.append(f"  DIALOGUE:")
                lines.append(f"  {dialogue}")
                lines.append("")
            lines.append("")

        return "\n".join(lines)

    def review_script(self, script_text: str, genre: str = "",
                      feedback_type: str = "full") -> str:
        """
        Professional script review — like a studio reader's coverage.
        Reviews plot, characters, dialogue, pacing, structure, and marketability.
        """
        if feedback_type == "full":
            review_scope = "Plot, Characters, Dialogue, Pacing, Structure, Marketability"
        elif feedback_type == "plot":
            review_scope = "Plot, Structure, Pacing"
        elif feedback_type == "dialogue":
            review_scope = "Dialogue quality, character voices, subtext"
        elif feedback_type == "characters":
            review_scope = "Character depth, arcs, motivations, consistency"
        else:
            review_scope = review_scope

        sys_prompt = f"""
You are a Hollywood script coverage reader and professional screenwriting consultant.
You have read 10,000+ scripts and provide honest, actionable feedback.

Review the script for: {review_scope}

Rating scale:
- A+: Ready to shoot, production-ready
- A: Excellent, minor tweaks needed
- B+: Very good, some structural issues
- B: Solid foundation, major revisions needed
- B-: Interesting ideas but fundamentally flawed
- C: Not ready for production

Provide:
1. Overall Score (letter grade)
2. Summary (3-4 sentences)
3. Strengths (3-5 bullet points)
4. Weaknesses (3-5 bullet points with SPECIFIC page/scene references)
5. Detailed analysis of each area
6. Actionable revision recommendations
7. Market comparison ("Comparable to: [movie X] meets [movie Y]")
"""

        user_prompt = f"""<genre>{genre or "unspecified"}</genre>
<script>
{script_text[:10000]}
</script>
"""
        return self.sw._chat(sys_prompt, user_prompt)

    def generate_pitch_deck(self, blueprint: dict) -> str:
        """Generate a professional pitch deck outline for presenting to producers."""
        title = blueprint.get("title", "Untitled")
        logline = blueprint.get("logline", "")
        theme = blueprint.get("theme", "")
        characters = blueprint.get("characters", [])
        twists = blueprint.get("twists", [])
        climax = blueprint.get("climax", {})
        visual = blueprint.get("visual_style", {})

        sys_prompt = f"""
You are a Hollywood pitching consultant. Create a compelling pitch deck outline
for presenting this story to producers and studio executives.

The pitch deck must be:
- Professional and industry-standard
- Persuasive and emotionally engaging
- Clear and concise (every slide must earn its place)
- Visual-forward (describe what images would go on each slide)
"""

        user_prompt = f"""
<story_title>{title}</story_title>
<logline>{logline}</logline>
<theme>{theme}</theme>
<characters>{json.dumps(characters, ensure_ascii=False, indent=2)}</characters>
<twists>{json.dumps(twists, ensure_ascii=False, indent=2)}</twists>
<climax>{json.dumps(climax, ensure_ascii=False, indent=2)}</climax>
<visual_style>{json.dumps(visual, ensure_ascii=False, indent=2)}</visual_style>

Output a pitch deck with these slides (one JSON object per slide):
[
  {"slide": "Title Card", "title": "...", "subtitle": "...", "visual": "description of the main poster image"},
  {"slide": "Logline", "title": "The Story", "content": "logline", "notes": "how to deliver this in 10 seconds"},
  {"slide": "Themes", "title": "...", "content": "..."},
  {"slide": "Protagonist", "title": "...", "character": "JSON of protagonist"},
  {"slide": "Antagonist", "title": "...", "character": "JSON of antagonist"},
  {"slide": "Supporting Cast", "title": "...", "characters": ["JSON objects"]},
  {"slide": "Visual Style", "title": "...", "content": "color palette, lighting, camera style"},
  {"slide": "Structure Overview", "title": "...", "content": "beat sheet summary with percentages"},
  {"slide": "Key Scene 1", "title": "...", "visual": "description", "why_important": "..."},
  {"slide": "Key Scene 2", "title": "...", "visual": "description", "why_important": "..."},
  {"slide": "Key Scene 3", "title": "...", "visual": "description", "why_important": "..."},
  {"slide": "The Twists", "title": "...", "content": "setup and impact of each twist"},
  {"slide": "Climax", "title": "...", "content": "how both conflicts resolve"},
  {"slide": "Tone & Comp Titles", "title": "...", "content": "'Comparable to X meets Y'"},
  {"slide": "Why This Story", "title": "...", "content": "emotional hook and market appeal"}
]

Output valid JSON only.
"""

        return self.sw._chat_json(sys_prompt, user_prompt)

    def generate_shot_list(self, scene: dict) -> list:
        """Generate a professional shot list for a single scene."""
        sys_prompt = f"""
You are a professional Director of Photography (DP). Generate a detailed shot list
for filming this scene.

Output JSON:
[
  {{
    "shot_number": 1,
    "type": "WIDE / MEDIUM / CLOSE-UP / EXTREME CLOSE-UP / POV / TRACKING / CRANESHOT",
    "lens": "e.g., 35mm, 85mm, 24mm anamorphic",
    "movement": "STATIC / DOLLY IN / TRACK LEFT / PAN RIGHT / CRANE UP / HANDHELD",
    "description": "What the camera sees",
    "subject": "What/who is in the frame",
    "duration": "estimated seconds",
    "lighting": "key light description",
    "purpose": "Why this shot exists narratively"
  }}
]

Rules:
- 5-12 shots per scene
- Mix shot sizes for visual variety
- Include at least one establishing shot
- Camera movement should serve the emotional beat
- Lens choice should match the mood (wide=epic, telephoto=intimate)
"""

        user_prompt = f"""<scene>
Location: {scene.get('location', '')}
Conflict: {scene.get('conflict', '')}
Visual: {scene.get('visual', '')}
Tension: {scene.get('tension', '')}
</scene>"""

        return self.sw._chat_json(sys_prompt, user_prompt)


class BeatSheetGenerator:
    """Generate a professional beat sheet using various story frameworks."""

    def __init__(self, screenwriter: Screenwriter):
        self.sw = screenwriter

    def generate(self, idea: str, genre: str = "action",
                 structure: str = "three_act", language: str = "zh") -> str:
        """Generate beat sheet for the given idea using selected structure."""
        structure_info = STRUCTURES.get(structure, STRUCTURES["three_act"])

        if language == "zh":
            sys_prompt = f"""
你是专业编剧。为以下创意生成一份专业的节拍表（Beat Sheet）。

[结构] {structure_info["name"]}
[类型] {genre}

输出JSON：
{{
  "title": "标题",
  "structure_used": "{structure_info['name']}",
  "genre": "{genre}",
  "beats": [
    {{
      "name": "节拍名称",
      "position": "大约百分比位置（如 25%）",
      "description": "这个节拍发生了什么",
      "purpose": "为什么需要这个节拍",
      "emotional_beat": "观众此刻的感受"
    }}
  ],
  "pacing_analysis": "整体节奏分析",
  "recommended_scenes": 7
}}
"""
        else:
            sys_prompt = f"""
You are a professional screenwriter. Generate a beat sheet for this idea.

[Structure] {structure_info["name"]}
[Genre] {genre}

Output JSON:
{{
  "title": "Title",
  "structure_used": "{structure_info['name']}",
  "genre": "{genre}",
  "beats": [
    {{
      "name": "Beat name",
      "position": "Approximate % position (e.g., 25%)",
      "description": "What happens at this beat",
      "purpose": "Why this beat is needed",
      "emotional_beat": "What the audience feels here"
    }}
  ],
  "pacing_analysis": "Overall pacing analysis",
  "recommended_scenes": 7
}}
"""

        user_prompt = f"<idea>{idea}</idea>"
        result = self.sw._chat_json(sys_prompt, user_prompt)

        # Format as readable text
        lines = [f"{'='*70}", f"  BEAT SHEET: {result.get('title', 'Untitled')}", f"{'='*70}"]
        lines.append(f"Structure: {result.get('structure_used', '')}")
        lines.append(f"Genre: {result.get('genre', '')}")
        lines.append("")

        for i, beat in enumerate(result.get("beats", []), 1):
            lines.append(f"  {i}. [{beat.get('position', '')}] {beat.get('name', '')}")
            lines.append(f"     {beat.get('description', '')}")
            lines.append(f"     Purpose: {beat.get('purpose', '')}")
            lines.append(f"     Audience feels: {beat.get('emotional_beat', '')}")
            lines.append("")

        lines.append(f"{'='*70}")
        lines.append(f"Pacing: {result.get('pacing_analysis', '')}")
        lines.append(f"Recommended scenes: {result.get('recommended_scenes', '')}")

        return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def get_screenwriter() -> Screenwriter:
    """Get screenwriter instance from config."""
    config = load_config()
    api_key = config.get("api_key", "")
    if not api_key:
        print("❌ Please set AGNES_API_KEY environment variable or configure in .agnes_config/")
        sys.exit(1)
    lang = os.environ.get("CRAFT_LANGUAGE", "zh")
    return Screenwriter(api_key=api_key, language=lang)


def cmd_direct(args):
    """Direct a full story with expert creative direction."""
    sw = get_screenwriter()
    director = Director(sw)

    structure = args.structure or "three_act"
    blueprint = director.direct_story(args.idea, args.genre, structure, args.runtime)

    # Save
    outfile = args.output or f"craft_{args.genre}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(blueprint, f, ensure_ascii=False, indent=2)
    print(f"✅ Story blueprint saved to {outfile}")
    print(f"   Title: {blueprint.get('title', 'N/A')}")
    print(f"   Logline: {blueprint.get('logline', 'N/A')}")
    print(f"   Characters: {len(blueprint.get('characters', []))}")
    print(f"   Key Scenes: {len(blueprint.get('key_scenes', []))}")

    if args.write_screenplay:
        script = director.write_screenplay(blueprint, args.format)
        script_file = args.output.replace('.json', '.txt')
        with open(script_file, 'w', encoding='utf-8') as f:
            f.write(script)
        print(f"✅ Screenplay saved to {script_file}")

    if args.pitch:
        deck = director.generate_pitch_deck(blueprint)
        deck_file = args.output.replace('.json', '_pitch.json')
        with open(deck_file, 'w', encoding='utf-8') as f:
            json.dump(deck, f, ensure_ascii=False, indent=2)
        print(f"✅ Pitch deck saved to {deck_file}")

    return blueprint


def cmd_beat_sheet(args):
    """Generate a beat sheet."""
    sw = get_screenwriter()
    bs = BeatSheetGenerator(sw)
    text = bs.generate(args.idea, args.genre, args.structure, os.environ.get("CRAFT_LANGUAGE", "zh"))
    outfile = args.output or "beat_sheet.txt"
    with open(outfile, 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)
    print(f"\n📄 Saved to {outfile}")


def cmd_script(args):
    """Write a full screenplay."""
    sw = get_screenwriter()
    director = Director(sw)

    if args.blueprint:
        with open(args.blueprint, 'r', encoding='utf-8') as f:
            blueprint = json.load(f)
    else:
        blueprint = director.direct_story(args.idea, args.genre, args.structure, args.runtime)

    script = director.write_screenplay(blueprint, args.format)
    outfile = args.output or f"script_{args.genre}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(outfile, 'w', encoding='utf-8') as f:
        f.write(script)
    print(script)
    print(f"\n📄 Saved to {outfile}")


def cmd_review(args):
    """Review a script."""
    sw = get_screenwriter()
    director = Director(sw)

    with open(args.file, 'r', encoding='utf-8') as f:
        script = f.read()

    review = director.review_script(script, args.genre, args.type)
    outfile = args.output or f"review_{os.path.basename(args.file)}.txt"
    with open(outfile, 'w', encoding='utf-8') as f:
        f.write(review)
    print(review)
    print(f"\n📄 Saved to {outfile}")


def cmd_export(args):
    """Export from Agnes Video Studio task."""
    import urllib.request, urllib.parse
    try:
        url = "http://localhost:8765/api/tasks/" + args.task_id
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json
            task = json.loads(resp.read())

        blueprint = {
            "title": task.get("story_title", "Untitled"),
            "logline": task.get("story_summary", ""),
            "characters": [
                {
                    "name": c["name"],
                    "role": c.get("role", "unknown"),
                    "appearance": c.get("appearance", ""),
                }
                for c in task.get("characters", [])
            ],
            "key_scenes": [
                {
                    "index": s["index"],
                    "name": f"Scene {s['index']}",
                    "location": s.get("location", ""),
                    "visual": s.get("action", ""),
                    "dialogue": s.get("dialogue", ""),
                    "tension": "medium",
                    "duration": s.get("duration", 30),
                }
                for s in task.get("scenes", [])
            ]
        }

        outfile = args.output or f"export_{args.task_id}.json"
        with open(outfile, 'w', encoding='utf-8') as f:
            json.dump(blueprint, f, ensure_ascii=False, indent=2)
        print(f"✅ Exported to {outfile}")
        print(f"   Title: {blueprint['title']}")
        print(f"   Characters: {len(blueprint['characters'])}")
        print(f"   Scenes: {len(blueprint['key_scenes'])}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="🎬 CRAFT — Professional Screenwriting Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python craft.py direct --genre thriller --idea "A detective finds a body..."
          python craft.py beat-sheet --genre action --structure save_the_cat --idea "Space bounty hunter..."
          python craft.py script --genre drama --blueprint story.json
          python craft.py review --file myscript.txt --genre horror
          python craft.py export --task-id story_xxxxx
        """)
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # direct
    p_direct = subparsers.add_parser("direct", help="🎬 Full story direction with expert creative guidance")
    p_direct.add_argument("--idea", "-i", required=True, help="Creative idea")
    p_direct.add_argument("--genre", "-g", default="action", choices=list(GENRE_TEMPLATES.keys()), help="Genre")
    p_direct.add_argument("--structure", "-s", default="three_act",
                          choices=list(STRUCTURES.keys()), help="Story structure")
    p_direct.add_argument("--runtime", "-r", default="medium", choices=["short", "medium", "feature"], help="Target runtime")
    p_direct.add_argument("--output", "-o", help="Output file")
    p_direct.add_argument("--write-screenplay", action="store_true", help="Also write screenplay")
    p_direct.add_argument("--format", choices=["industry", "visual"], default="industry", help="Screenplay format")
    p_direct.add_argument("--pitch", action="store_true", help="Also generate pitch deck")

    # beat-sheet
    p_bs = subparsers.add_parser("beat-sheet", help="📊 Generate a beat sheet")
    p_bs.add_argument("--idea", "-i", required=True)
    p_bs.add_argument("--genre", "-g", default="action")
    p_bs.add_argument("--structure", "-s", default="three_act", choices=list(STRUCTURES.keys()))
    p_bs.add_argument("--output", "-o")

    # screenplay
    p_script = subparsers.add_parser("script", help="✍️ Write full screenplay")
    p_script.add_argument("--idea", "-i", help="Creative idea (or use --blueprint)")
    p_script.add_argument("--blueprint", "-b", help="Load story blueprint JSON")
    p_script.add_argument("--genre", "-g", default="action")
    p_script.add_argument("--structure", "-s", default="three_act")
    p_script.add_argument("--runtime", "-r", default="medium")
    p_script.add_argument("--format", choices=["industry", "visual"], default="industry")
    p_script.add_argument("--output", "-o")

    # review
    p_review = subparsers.add_parser("review", help="📋 Professional script review")
    p_review.add_argument("--file", required=True, help="Script file to review")
    p_review.add_argument("--genre", "-g", default="")
    p_review.add_argument("--type", "-t", default="full", choices=["full", "plot", "dialogue", "characters"])
    p_review.add_argument("--output", "-o")

    # export
    p_export = subparsers.add_parser("export", help="📤 Export from Agnes Video Studio task")
    p_export.add_argument("--task-id", required=True)
    p_export.add_argument("--output", "-o")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "direct": cmd_direct,
        "beat-sheet": cmd_beat_sheet,
        "script": cmd_script,
        "review": cmd_review,
        "export": cmd_export,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
