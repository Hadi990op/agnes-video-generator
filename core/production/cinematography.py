"""core.production.cinematography — 开源电影摄影知识库（Open-source cinematography knowledge base）.

汇集自公开影视教育资料（FilmSound, NoFilmSchool, Wikipedia 电影摄影条目等）的
镜头语法、导演调度与分镜规划知识，用于把 LLM 的镜头计划能力从「随手写」
提升到「有意识地设计」。

用法：
    from core.production.cinematography import (
        CINEMATOGRAPHY_SYSTEM, DIRECTOR_PLANNING_SYSTEM,
        VISUAL_STYLES, lookup_visual_style,
    )
"""

# ─────────────────────────────────────────────────────────────
# 1. 景别（Shot Sizes）—— 画面语言的基础词汇
# ─────────────────────────────────────────────────────────────
SHOT_SIZES = {
    "extreme wide": "Extreme Wide Shot (EWS/EWS): 极度远离主体，展示地理环境与孤立感，常用于开场或转场",
    "wide": "Wide / Long Shot: 全身可见并保留环境，确立角色在空间中的位置",
    "full": "Full Shot: 演员全身充满画面，展示肢体语言与服装",
    "medium": "Medium Shot: 腰部以上，对话场景的标准景别，兼顾表情与手势",
    "medium close": "Medium Close-Up: 胸部以上，比 medium 更亲密",
    "close-up": "Close-Up (CU): 面部充满画面，强调情绪与内心",
    "extreme close-up": "Extreme Close-Up (ECU): 眼睛/手部等细节，最大程度的情感冲击",
    "two-shot": "Two Shot: 两人同框，展示关系与张力",
    "over-the-shoulder": "Over-the-Shoulder (OTS): 越过一人肩膀拍另一人，对话中的代入感",
    "insert": "Insert Shot: 特写道具细节，用于强调关键物品",
}

# ─────────────────────────────────────────────────────────────
# 2. 机位角度（Camera Angles）
# ─────────────────────────────────────────────────────────────
CAMERA_ANGLES = {
    "eye-level": "Eye-Level: 平视，中性、客观，大多数对话的默认选择",
    "low angle": "Low Angle: 仰拍，赋予主体权力、威胁或英雄感",
    "high angle": "High Angle: 俯拍，削弱主体、表现弱小或困境",
    "bird's eye": "Bird's-Eye View: 顶部垂直俯瞰，表现宿命或几何构图",
    "worm's eye": "Worm's Eye: 贴地仰拍，极度夸张与压迫",
    "dutch angle": "Dutch Angle (Canted): 倾斜画面，表现失衡、疯狂、不安",
    "over-the-shoulder": "Over-the-Shoulder: 越肩视角，对话构图",
    "pov": "POV (Point of View): 主观镜头，观众直接成为角色",
    "profile": "Profile: 侧面构图，冷静、疏离、经典对峙",
}

# ─────────────────────────────────────────────────────────────
# 3. 运镜（Camera Movement）
# ─────────────────────────────────────────────────────────────
CAMERA_MOVEMENTS = {
    "static": "Static / Locked-off: 固定机位，稳定的、古典的构图",
    "pan": "Pan: 水平摇摄，跟随移动或展示空间",
    "tilt": "Tilt: 垂直摇摄，揭示高度或主体",
    "dolly in": "Dolly In: 推近，增强戏剧张力（慢推是悬念经典）",
    "dolly out": "Dolly Out: 拉远，抽离、孤独或揭示全貌",
    "tracking": "Tracking: 侧面跟随移动，与主体并行",
    "crane": "Crane / Boom: 大范围垂直升降，史诗感转场",
    "handheld": "Handheld: 手持晃动，纪实感、紧张、混乱",
    "steadicam": "Steadicam: 平滑跟随移动，流畅的长镜头感",
    "zoom": "Zoom: 变焦（光学放大，非移动），快速聚焦或制造违和感",
    "whip pan": "Whip Pan: 快速甩镜，节奏切换或幽默转场",
    "dolly zoom": "Dolly Zoom (Vertigo Effect): 推轨+反向变焦，现实崩塌感",
}

# ─────────────────────────────────────────────────────────────
# 4. 镜头/焦段（Lenses）
# ─────────────────────────────────────────────────────────────
LENSES = {
    "wide 14-24mm": "超广角：畸变、宏大空间、压迫感",
    "wide 24-35mm": "广角：环境叙事、多人构图",
    "normal 50mm": "标准：接近人眼透视，中性自然",
    "telephoto 85-135mm": "长焦：压缩空间、浅景深、唯美肖像",
    "long telephoto 200mm+": "超长焦：强烈压缩、窥视感、孤立主体",
    "anamorphic": "变形宽银幕：水平光斑、椭圆焦外、电影感",
    "macro": "微距：微观细节",
    "tilt-shift": "移轴：选择性焦平面",
    "practical/natural": "实拍质感：自然光摄影（Nolan/纪录片风格）",
}

# ─────────────────────────────────────────────────────────────
# 5. 灯光（Lighting）
# ─────────────────────────────────────────────────────────────
LIGHTING = {
    "three-point": "三点式布光：主光+逆光+补光，经典造型",
    "high-key": "高调：明亮、低对比，喜剧/温情",
    "low-key": "低调：深阴影、高对比，黑色电影/惊悚",
    "chiaroscuro": "明暗对照（chiaroscuro）：强烈光影分割，Caravaggio 风",
    "rembrandt": "伦勃朗光：脸颊三角形光斑，古典人像",
    "backlit": "逆光/轮廓光：神圣、神秘、氛围",
    "silhouette": "剪影：极简叙事，去个体化",
    "naturalistic": "自然光：Golden hour（黄金时刻）/ Blue hour（蓝调时刻）",
    "neon": "霓虹光：赛博朋克/现代都市夜",
    "practical motivated": "场景光源动机照明（台灯/篝火/车灯）",
}

# ─────────────────────────────────────────────────────────────
# 6. 导演调度技巧（Director Planning Techniques）
# ─────────────────────────────────────────────────────────────
DIRECTOR_PLANNING_TECHNIQUES = [
    "180-degree rule (axis of action): 对话双方必须在同一侧，保持空间方向连续性",
    "30-degree rule: 相邻镜头机位至少差 30°，避免跳剪感",
    "Master scene technique: 先拍全景 master，再拍 singles/inserts",
    "Shot-reverse-shot: 对话正反打，OTS 或 singles 交替",
    "Shot size progression: 情绪升压时景别由大到小（W→MS→CU）",
    "Shot variation rule: 相邻镜头的景别/角度必须不同，避免视觉疲劳",
    "Establishing shot: 新场景以定场镜头开始",
    "Reaction beats: 关键台词后接反应镜头，情绪落地",
    "Insert beats: 关键道具/细节插入镜头驱动叙事",
    "Movement mirrors emotion: 角色情绪平静→固定机位；动荡→手持/移动",
    "Cut on action: 在动作中剪辑保持流畅",
    "Rhythm pacing: 短镜头节奏加快制造紧张，长镜头让情绪呼吸",
    "Frame within a frame: 利用门框/窗框构图，暗示囚禁或孤立",
    "Leading lines: 利用线条引导视线到主体",
    "Rule of thirds: 三分法构图，重要元素放在交叉点",
    "Headroom / lead room: 头顶空间与视线空间的呼吸感",
    "Chekhov's gun: 提前埋设关键道具的镜头",
    "Plant & payoff: 镜头伏笔与呼应",
    "Juxtaposition: 蒙太奇并置制造含义（库里肖夫效应）",
    "Rising line: 场景内行动要有上升弧线，镜头组合推向 climax",
]

# ─────────────────────────────────────────────────────────────
# 7. 分镜规划（Storyboard Planning）检查表
# ─────────────────────────────────────────────────────────────
STORYBOARD_CHECKLIST = [
    "每个场景至少一个 establishing shot",
    "对话场景默认 shot-reverse-shot / OTS",
    "相邻镜头景别或角度至少一项改变（shot variation）",
    "关键情绪 beat 用 close-up",
    "关键道具用 insert shot 提示观众",
    "动作高潮用 wide 展示空间关系",
    "每 3-5 个镜头节奏变化一次（景别或运镜）",
    "scene 结束用 hold beat 或 cutaway 过渡",
    "场景内保持 180° 轴线一致",
    "场景内保持光线方向连续",
]

# ─────────────────────────────────────────────────────────────
# 8. 视觉风格库（Visual Style Library）——开源风格词典
#    用户输入自然语言风格名，这里映射到具体的摄影/灯光/调色指令。
# ─────────────────────────────────────────────────────────────
VISUAL_STYLES: dict = {
    "cinematic photorealistic": (
        "Cinematic photorealistic: shot on ARRI Alexa with anamorphic lenses, "
        "shallow depth of field, filmic color grading (teal-orange), natural "
        "three-point lighting, subtle film grain, 2.39:1 letterbox feel"
    ),
    "film noir": (
        "Film noir: hard chiaroscuro lighting, venetian blind shadows, "
        "low-key black and white contrast, deep shadows, fedora silhouettes, "
        "rain-slicked streets, smoke-filled rooms, dutch angles"
    ),
    "wes anderson": (
        "Wes Anderson style: symmetrical centred compositions, pastel color "
        "palettes, flat frontal staging, whip pans, overhead inserts, "
        "nostalgic warm tones, meticulous production design"
    ),
    "documentary realist": (
        "Documentary realism: handheld camera, natural available light, "
 "16mm grain texture, muted desaturated palette, imperfect framing, "
        "direct sound aesthetic, observational distance"
    ),
    "epic fantasy": (
        "Epic fantasy: sweeping crane and aerial shots, golden hour glow, "
        "highly saturated mythic landscapes, volumetric god rays, misty "
        "mountains, painterly compositions reminiscent of classical paintings"
    ),
    "horror": (
        "Horror: extreme low-key lighting, deep blacks, cold desaturated "
        "palette, slow creeping camera movements, negative space, frames "
        "hiding threats in shadows, dutch angles for unease"
    ),
    "romance": (
        "Romance: soft diffused lighting, warm golden tones, creamy "
        "shallow-focus close-ups, slow push-ins, bloom highlights, "
        "romantic rain/light-through-window atmosphere"
    ),
    "science fiction": (
        "Sci-fi: cool blue-teal palette, neon practical lights, sleek "
        "reflective surfaces, volumetric fog, geometric architecture, "
        "wide symmetrical compositions, anamorphic lens flares"
    ),
    "bollywood": (
        "Bollywood: rich saturated colors, warm golden skin tones, vibrant "
        "costumes, dynamic musical camera moves, dramatic slow motion, "
        "expressive lighting, festival color palette"
    ),
    "animation": (
        "Animation: stylized 3D animation look, expressive character "
        "design, vivid saturated colors, dynamic poses, squash-and-stretch "
        "energy, painterly backgrounds"
    ),
}


def lookup_visual_style(style_input: str) -> str:
    """把用户的自然语言风格输入映射到具体摄影指令（大小写不敏感）。

    未匹配时原样返回输入（LLM 会在 system prompt 里收到完整风格词典作为参考）。
    """
    if not style_input:
        return VISUAL_STYLES["cinematic photorealistic"]
    key = style_input.strip().lower()
    if key in VISUAL_STYLES:
        return VISUAL_STYLES[key]
    for name, desc in VISUAL_STYLES.items():
        if name.split()[0] == key.split()[0] if key.split() else False:
            return desc
    # 子串匹配（如 "noir"、"anderson"）
    for name, desc in VISUAL_STYLES.items():
        if name in key or key in name:
            return desc
    return style_input


def all_style_names() -> list:
    """返回所有可用风格名（给 UI / API 用）。"""
    return list(VISUAL_STYLES.keys())


# ─────────────────────────────────────────────────────────────
# 9. 组装给 LLM 的 system prompt 片段
# ─────────────────────────────────────────────────────────────

_SHOT_SIZE_TEXT = "\n".join(f"- {v}" for v in SHOT_SIZES.values())
_ANGLE_TEXT = "\n".join(f"- {v}" for v in CAMERA_ANGLES.values())
_MOVEMENT_TEXT = "\n".join(f"- {v}" for v in CAMERA_MOVEMENTS.values())
_LENS_TEXT = "\n".join(f"- {v}" for v in LENSES.values())
_LIGHT_TEXT = "\n".join(f"- {v}" for v in LIGHTING.values())
_TECHNIQUE_TEXT = "\n".join(f"- {t}" for t in DIRECTOR_PLANNING_TECHNIQUES)
_STORYBOARD_TEXT = "\n".join(f"- {t}" for t in STORYBOARD_CHECKLIST)
_STYLE_TEXT = "\n".join(f"- {k}: {v}" for k, v in VISUAL_STYLES.items())


#: 注入给「剧本分析」LLM 的摄影知识
CINEMATOGRAPHY_SYSTEM = f"""
You are trained in CLASSICAL CINEMATOGRAPHY GRAMMAR. Use this vocabulary when directing shots.

SHOT SIZES (景别):
{_SHOT_SIZE_TEXT}

CAMERA ANGLES (机位角度):
{_ANGLE_TEXT}

CAMERA MOVEMENT (运镜):
{_MOVEMENT_TEXT}

LENSES (镜头):
{_LENS_TEXT}

LIGHTING STYLES (灯光):
{_LIGHT_TEXT}
""".strip()


#: 注入给「镜头拆解 / 分镜规划」LLM 的导演调度知识
DIRECTOR_PLANNING_SYSTEM = f"""
You are a working DIRECTOR + STORYBOARD ARTIST. Apply these planning techniques to EVERY shot list.

DIRECTOR PLANNING TECHNIQUES (导演调度技巧):
{_TECHNIQUE_TEXT}

STORYBOARD PLANNING CHECKLIST (分镜检查表):
{_STORYBOARD_TEXT}

CAMERA GRAMMAR — shot sizes:
{_SHOT_SIZE_TEXT}

CAMERA ANGLES:
{_ANGLE_TEXT}

CAMERA MOVEMENTS:
{_MOVEMENT_TEXT}

For each shot's "camera" field, ALWAYS specify: shot_size + angle + movement
(e.g. "medium close-up, eye-level, slow dolly in"). Never leave the camera
field generic like "camera shows the scene" — use precise cinematography
vocabulary from above.
""".strip()


def style_catalog_prompt() -> str:
    """给 LLM 的视觉风格词典（分析剧本时参考）。"""
    return f"VISUAL STYLE LIBRARY (for reference):\n{_STYLE_TEXT}"
