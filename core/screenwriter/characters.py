"""core.screenwriter.characters — 角色提取/尾帧/数字人 prompt 方法（Batch 4 拆分）"""
import logging
from typing import List

from core.api.agnes_chat import strip_code_fence

logger = logging.getLogger(__name__)


class ScreenwriterCharactersMixin:
    """角色/尾帧/数字人口播 prompt 方法（Batch 4 拆分）。"""

    def extract_character_description(self, story: str, style: str) -> str:
        system_prompt = self._prompt(
            zh_text="""\
你是一位视觉设计专家。你的任务是从故事中提取主要角色的详细\
图像生成提示词，适用于生成角色参考图。

参考图应展示主要角色以清晰、全身或四分之三\
视角、中性站立姿势呈现，显著特征清晰可见。图片应准确捕捉\
故事中描述的角色外貌，包括：

- 体型与姿态
- 服装与配饰
- 发型与发色
- 面部特征与表情
- 肤色、纹理或材质（非人角色）
- 任何标志性特征、疤痕或特点
- 角色的配色方案

重要提示——参考图将用作 i2i 身份锚点，因此\
提示词还必须指定：
- 清晰、正面的面部，眼睛和嘴巴完全可见
- 无遮挡（手、头发或物体不能挡住面部）
- 均匀、柔和的布光（面部无强阴影）
- 中性或浅笑表情

应为一个段落，3-5 句话，\
视觉细节丰富。包含艺术风格（如"写实电影感"、\
"动漫风格"、"水彩插画"）。

关键要求：使用与输入故事相同的语言输出提示词。\
如果故事是中文，用中文写提示词。如果是英文，用英文写。\
这是强制要求。

只输出图像提示词文本，不要 JSON，不要解释。
""",
            en_text="""\
You are a visual design expert. Your job is to extract a detailed image \
generation prompt for the MAIN CHARACTER from the story, suitable for \
generating a CHARACTER REFERENCE IMAGE.

The reference image should show the main character in a clear, full-body \
or three-quarter view pose, in a neutral standing position, with distinctive \
features clearly visible. The image should capture the character's appearance \
exactly as described in the story, including:

- Body type and posture
- Clothing and accessories
- Hair style and color
- Facial features and expressions
- Skin color, texture, or material (for non-human characters)
- Any distinguishing marks, scars, or features
- Color palette of the character

IMPORTANT — the reference image will be used as an i2i identity anchor, so \
the prompt MUST also specify:
- Clear, front-facing face with eyes and mouth fully visible
- No occlusion (no hands, hair, or objects blocking the face)
- Even, diffused lighting (no harsh shadows on the face)
- Neutral or slight smile expression

It should be a single paragraph, 3-5 sentences, \
rich in visual detail. Include the art style (e.g., "realistic cinematic", \
"anime style", "watercolor illustration").

CRITICAL: Output the prompt in the SAME LANGUAGE as the input story. \
If the story is in Chinese, write the prompt in Chinese. If in English, \
write in English. This is mandatory.

Output ONLY the image prompt text, no JSON, no explanation.
""",
        )
        user_prompt = f"""\
<story>
{story}
</story>

<style>{style}</style>

{self._prompt(
    zh_text="请使用与上方故事相同的语言编写角色图像提示词。",
    en_text='Write the character image prompt in the SAME LANGUAGE as the story above.'
)}
"""
        logger.info("[Screenwriter] Extracting character reference prompt...")
        prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
        logger.info(f"[Screenwriter] Character prompt: {prompt[:100]}...")
        return prompt

    def get_character_appearance(self, story: str) -> str:
        system_prompt = self._prompt(
            zh_text="""\
仅从此故事中提取主要角色的物理外貌。
输出一段简洁的描述，概括其固定外观——包含所有细节：
- 发型与发色
- 面部特征（眼镜等）
- 体型与姿态
- 服装（所有单品：外套、连衣裙、裤子等）
- 鞋子
- 任何配饰

以一段描述性文字输出，3-5 句话。保持客观且可视化\
——像警方画像描述一样。不要包含性格、\
对话或故事情节。

关键要求：使用与输入故事相同的语言输出。如果故事是\
中文，用中文写。如果是英文，用英文写。这是强制要求。

仅输出外貌描述文本。不要 JSON、不要标签、不要 markdown。
""",
            en_text="""\
Extract ONLY the main protagonist's physical appearance from this story.
Output a CONCISE paragraph describing their fixed look — include EVERY detail:
- Hair style and color
- Facial features (glasses, etc.)
- Body type and posture
- Clothing (ALL pieces: coat, dress, pants, etc.)
- Shoes
- Any accessories

Write as a single descriptive paragraph, 3-5 sentences. Keep it factual and
visual — like a police sketch description. Do NOT include their personality,
dialogue, or story events.

CRITICAL: Output in the SAME LANGUAGE as the input story. If the story is in
Chinese, write in Chinese. If in English, write in English. This is mandatory.

Output ONLY the appearance description text. No JSON, no labels, no markdown.
""",
        )
        appearance = strip_code_fence(self._chat(system_prompt, story))
        logger.info(f"[Screenwriter] Character appearance: {appearance[:100]}...")
        return appearance

    def generate_end_frame_prompts(
        self, scenes: List[str], style: str, character_appearance: str = ""
    ) -> List[str]:
        # 批次4：角色外观由批次3的程序化拼入处理，LLM 只输出 [CHANGE] 部分
        # 系统提示中仍提供 character_appearance 作为上下文参考，避免 LLM 描述与角色矛盾
        if character_appearance:
            context_block = self._prompt(
                zh_text=f"""
[上下文 — 角色外貌仅供参考，不要复制到输出中]
{character_appearance}

你的提示词应仅描述场景的尾帧——环境、姿态、\
光线、氛围、拍摄角度。不要重复角色的发型、面部、\
服装或配饰——这些由程序化方式注入。
""",
                en_text=f"""
[CONTEXT — Character appearance for reference only, do NOT copy into output]
{character_appearance}

Your prompt should describe the SCENE'S END FRAME only — environment, pose, \
lighting, mood, camera angle. Do NOT repeat the character's hair, face, \
clothing, or accessories — those are injected programmatically.
""",
            )
        else:
            context_block = ""

        system_prompt = self._prompt(
            zh_text=f"""\
你是一位面向 AI 图像生成的视觉提示词工程师。请生成一个静态\
图像提示词，描述该视频场景在结尾处的画面\
——即视频的最终定格帧。
{context_block}
规则：
- 描述一个静态的定格瞬间，不要使用运动或动作动词。
- 聚焦于：姿态、面部表情、手部位置、身体姿势、拍摄角度、\
光线、背景元素——单个定格帧中可见的一切。
- 包含艺术风格（如"写实电影感"、"动漫"）。
- 3-5 句话，视觉细节丰富。
- 必须使用与输入场景相同的语言。
- 不要描述角色的外貌（发型、服装、面部）——只描述\
场景环境、姿态、光线和氛围。

用词指导：
- 通过视觉氛围构图戏剧性或紧张的元素："充满张力的\
静默"、"定格中的紧张沉寂"、"戏剧性的光影处理"。
- 使用光线和构图传达情感分量："强烈的顶光\
营造阴郁氛围"、"柔和的金色逆光暗示希望"、"冷蓝色调\
增加情感疏离感"。
- 对于情感充沛的场景，聚焦肢体语言和环境叙事：\
"疲惫的姿态映衬在空旷的窗前"、"温暖环境光中的\
温柔亲近"、"画面中央的有力站姿"。
- 让镜头语言承载叙事冲击力——构图、色彩和\
光线来完成叙事。

只输出图像提示词文本，不要 JSON，不要解释。
""",
            en_text=f"""\
You are a visual prompt engineer for AI image generation. Generate a STATIC \
image prompt that represents what this video scene looks like at its very END \
— the final frozen frame of the video.
{context_block}
Rules:
- Describe a STATIC frozen moment, NOT motion or action verbs.
- Focus on: pose, facial expression, hand position, body posture, camera angle, \
lighting, background elements — everything visible in a single frozen frame.
- Include art style (e.g., "realistic cinematic", "anime").
- 3-5 sentences, rich in visual detail.
- MUST be in the SAME LANGUAGE as the input scene.
- Do NOT describe the character's appearance (hair, clothing, face) — only the \
scene environment, pose, lighting, and mood.

VOCABULARY GUIDANCE:
- Frame dramatic or intense elements through visual atmosphere: "charged \
stillness", "tense silence captured in frame", "dramatic shadow work".
- Use lighting and composition to convey emotional weight: "harsh overhead light \
creates a somber mood", "soft golden backlight suggests hope", "cold blue tint \
adds emotional distance".
- For emotionally charged scenes, focus on body language and environmental \
storytelling: "defeated posture silhouetted against a stark window", \
"tender closeness in warm ambient light", "powerful stance centered in frame".
- Let the camera language carry the narrative impact — composition, color, and \
lighting do the storytelling.

Output ONLY the image prompt text, no JSON, no explanation.
""",
        )
        end_frames = []
        for scene_idx, scene_text in enumerate(scenes):
            logger.info(f"[Screenwriter] Generating end frame prompt for scene {scene_idx}...")
            user_prompt = f"""\
<style>{style}</style>

<scene>
{scene_text}
</scene>

{self._prompt(
    zh_text="请为此场景编写静态尾帧图像提示词。描述该场景最终定格帧的样子——场景结束时的姿态、表情、光线和环境。",
    en_text="Write the STATIC end-frame image prompt for this scene. This should describe what the final frozen frame of this scene looks like — the pose, expression, lighting, and environment at the moment this scene ends."
)}
"""
            prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
            end_frames.append(prompt)
            logger.info(f"[Screenwriter] End frame {scene_idx} prompt: {prompt[:80]}...")

        logger.info(f"[Screenwriter] Generated {len(end_frames)} end frame prompts")
        return end_frames

    def generate_anchor_clip_prompt(
        self,
        paragraph_text: str,
        anchor_prompt: str,
        segment_index: int,
        total_segments: int,
    ) -> str:
        """为数字人口播分段生成视频动态 prompt（v3.1 方案 B，语言跟随输入）。

        基于段落语义和主播形象，为每段生成不同的自然动作描述，
        确保相邻段落的动作有变化（说话、点头、手势、微笑等），
        同时保持主播形象一致性，便于 i2v 生成带口型近似匹配的视频。

        Args:
            paragraph_text: 段落文本（本段内容）。
            anchor_prompt: 主播形象描述。
            segment_index: 当前段落索引（0-based）。
            total_segments: 总段落数。

        Returns:
            视频动态 prompt 字符串（语言与输入一致）。
        """
        system_prompt = self._prompt(
            zh_text=f"""\
你是一位专精数字人口播视频的专业视频导演。\
给定一段旁白文本和主播的外貌描述，\
为 AI 视频生成（i2v）生成一个简短的动态提示词。

规则：
- 描述主播在朗读此段落时的自然动作。
- 必须包含细微的嘴唇/口部运动，如同正在朗读旁白。
- 各段落的动作要有变化：配合手势说话、点头、\
轻微歪头、微笑、认真表情、思考停顿等。
- 动作应匹配文本内容的情感基调。
- 保持起止姿势几乎一致（以利于平滑拼接）。
- 动作应温和自然——不做夸张运动。
- 30-60 词，使用与输入旁白文本相同的语言。
- 不要描述环境或光线（这些由主播图像固定）。
- 不要描述主播的服装或外貌（已在参考图中确定）。

情感基调表达：
- 通过面部微表情和细微肢体语言表达情感基调：\
"温暖关切的表情"、"诚恳点头并轻轻加重语气"、\
"思考停顿伴随轻微歪头"、"严肃聚焦的目光"。
- 对于紧张/严肃内容："克制的审慎手势"、"肃穆的\
表情"、"沉稳踏实的姿态"。
- 对于温暖/振奋内容："真诚温暖的微笑"、"开放邀请的\
手势"、"明亮投入的表情"。
- 通过微妙的专业表达传达情感深度——像\
一位资深新闻主播用庄重而不夸张的方式传达分量。

变化上下文：
- 这是第 {segment_index} 段，共 {total_segments} 段。
- 靠前段落：更有活力、欢迎感的手势。
- 中间段落：专注、解说性手势，偶尔加强重点。
- 靠后段落：总结性、收束的手势。

只输出动态提示词文本，不要 JSON，不要解释。
""",
            en_text=f"""\
You are a professional video director specializing in digital human anchorperson videos.
Given a segment of narration text and the anchor's appearance description, \
generate a SHORT motion prompt for AI video generation (i2v).

Rules:
- Describe the anchorperson's NATURAL MOTIONS while speaking this segment.
- MUST include subtle lip/mouth movements as if speaking the narration.
- Vary the gestures across segments: speaking with hand gestures, nodding, \
slight head tilt, smile, earnest expression, thoughtful pause, etc.
- The motion should MATCH the emotional tone of the text content.
- Keep the starting and ending posture nearly identical (for smooth concatenation).
- Motions should be GENTLE and NATURAL — no exaggerated movements.
- 30-60 words, in the SAME LANGUAGE as the input narration text.
- Do NOT describe the environment or lighting (those are fixed from the anchor image).
- Do NOT describe the anchor's clothing or appearance (already in the reference image).

EMOTIONAL TONE EXPRESSION:
- Express emotional tone through facial micro-expressions and subtle body \
language: "warm concerned expression", "earnest nod with gentle emphasis", \
"thoughtful pause with slight head tilt", "serious focused gaze".
- For intense/serious content: "measured deliberate gestures", "solemn \
expression", "composed and grounded posture".
- For warm/uplifting content: "genuine warm smile", "open inviting gesture", \
"bright engaging expression".
- Convey emotional depth through subtle professional delivery — like a \
skilled news anchor conveying gravitas without melodrama.

Context for variation:
- This is segment {segment_index} of {total_segments}.
- Early segments: more energetic, welcoming gestures.
- Middle segments: focused, explanatory gestures with occasional emphasis.
- Later segments: conclusive, summarizing gestures.

Output ONLY the motion prompt text, no JSON, no explanation.
""",
        )

        user_prompt = f"""\
<anchor_appearance>
{anchor_prompt}
</anchor_appearance>

<narration_segment>
{paragraph_text}
</narration_segment>

{self._prompt(
    zh_text="请为此段落生成动态提示词。",
    en_text="Generate the motion prompt for this segment."
)}
"""
        logger.info(
            f"[Screenwriter] Generating anchor clip prompt for segment "
            f"{segment_index + 1}/{total_segments} ({len(paragraph_text)} chars)..."
        )
        prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
        logger.info(f"[Screenwriter] Anchor clip prompt: {prompt[:100]}...")
        return prompt

    def generate_anchor_smooth_loop_prompt(
        self,
        anchor_prompt: str,
    ) -> str:
        """为数字人口播后拼接音频模式生成单段循环优化的动态 prompt（语言跟随输入）。

        只生成一段 5 秒的 i2v 视频，循环播放配合完整 TTS 音频。
        prompt 强调微小幅度动作，确保起止姿态高度一致，循环衔接流畅。

        Args:
            anchor_prompt: 主播形象描述。

        Returns:
            视频动态 prompt 字符串（语言与输入一致）。
        """
        system_prompt = self._prompt(
            zh_text="""\
你是一位专精数字人口播视频的专业视频导演。\
为 AI 视频生成（i2v）生成一个简短的动态提示词。

此视频将被循环播放以覆盖完整旁白时长。\
因此动作必须设计为可无缝循环播放。

关键规则：
- 结束姿势必须与起始姿势几乎完全相同。
- 动作必须极其细微——仅允许几乎不可察觉的微运动。
- 不允许大幅度手势、转头、抬手。
- 仅允许胸/肩部的轻微呼吸运动。
- 极小幅度的微点头或微表情变化（幅度小于 5%）。
- 面部和身体位置应几乎静止——仿佛是静态照片\
  加上最微弱的真人微运动。
- 嘴巴应几乎无运动（这是循环片段，音频在后期添加）。
- 想象"活人肖像"——一张几乎静止但微微呼吸的照片。
- 20-40 词，使用与主播外貌描述相同的语言。
- 不要描述环境、光线、服装或外貌。

情感基调：
- 通过微妙的微表情传达情绪："几乎无法察觉的温柔\
微笑"、"眼神中微妙的温暖"、"隐约的严肃沉稳"、\
"关切真诚的微表情"。
- 所有表达保持在"活人肖像"约束内——仅嘴角和\
眼神的微小变化，无可见表演。

只输出动态提示词文本，不要 JSON，不要解释。
""",
            en_text="""\
You are a professional video director specializing in digital human anchorperson videos.
Generate a SHORT motion prompt for AI video generation (i2v).

This video will be LOOPED (played on repeat) to cover the full narration duration.
Therefore the motion MUST be designed for seamless loop playback.

CRITICAL RULES:
- The ending posture MUST be nearly IDENTICAL to the starting posture.
- Motions must be EXTREMELY SUBTLE — barely perceptible micro-movements only.
- NO large gestures, NO head turning, NO hand raising.
- ONLY subtle breathing motion in the chest/shoulders.
- VERY slight micro-nod or micro-smile changes (under 5% amplitude).
- The face and body position should appear nearly frozen — as if a static image
  with the faintest living-person micro-motions.
- Mouth should have near-zero movement (this is a loop-clip, audio is added in post).
- Think "living portrait" — a photo that barely breathes.
- 20-40 words, in the SAME LANGUAGE as the anchor appearance description.
- Do NOT describe environment, lighting, clothing, or appearance.

EMOTIONAL TONE:
- Use subtle micro-expressions to convey mood: "barely perceptible gentle \
smile", "subtle warmth in the eyes", "faint serious composure", \
"micro-expression of concerned sincerity".
- Keep all expression within the "living portrait" constraint — tiny shifts \
in mouth corners and eyes only, no visible performance.

Output ONLY the motion prompt text, no JSON, no explanation.
""",
        )

        user_prompt = f"""\
<anchor_appearance>
{anchor_prompt}
</anchor_appearance>

{self._prompt(
    zh_text="请为 5 秒循环片段生成平滑循环的动态提示词。",
    en_text="Generate the smooth-loop motion prompt for a 5-second looping clip."
)}
"""
        logger.info(
            f"[Screenwriter] Generating anchor smooth-loop prompt "
            f"({len(anchor_prompt)} chars)..."
        )
        prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
        logger.info(f"[Screenwriter] Anchor smooth-loop prompt: {prompt[:100]}...")
        return prompt

    def generate_anchor_model_audio_prompt(
        self,
        anchor_prompt: str,
        script_text: str,
    ) -> str:
        """为数字人口播模型音频模式生成含口播文本的视频 prompt（语言跟随输入）。

        模型音频模式下，视频模型同时生成视频和音频，
        prompt 需包含说话口型描述和口播文本内容。

        Args:
            anchor_prompt: 主播形象描述。
            script_text: 口播稿件全文。

        Returns:
            视频 prompt 字符串（语言与输入一致）。
        """
        system_prompt = self._prompt(
            zh_text="""\
你是一位专精数字人口播视频的专业视频导演。\
为 AI 视频生成（i2v）生成一个简短的视频提示词。

视频模型将同时生成视频和音频（主播朗读旁白）。\
因此：
- 包含主播匹配语音的嘴唇/口部运动。
- 动作应温和自然——轻微的点头、轻轻的手势。
- 保持身体位置相对稳定。
- 30-50 词，使用与旁白文本相同的语言。
- 不要描述环境、光线、服装或外貌。

语气表达：
- 通过微妙的表达线索传达旁白的情感基调：\
"温暖交谈的语气"、"诚恳真挚的表达"、\
"审慎严肃的态度"、"温柔强调的手势"。
- 所有表达保持在自然、专业的主播表达范围内\
——细腻而不戏剧化。

只输出提示词文本，不要 JSON，不要解释。
""",
            en_text="""\
You are a professional video director specializing in digital human anchorperson videos.
Generate a SHORT video prompt for AI video generation (i2v).

The video model will generate BOTH video and audio (the anchor speaking the narration).
Therefore:
- Include the anchor's lip/mouth movements matching the speech.
- The motion should be gentle and natural — subtle head nods, slight hand gestures.
- Keep body position relatively stable.
- 30-50 words, in the SAME LANGUAGE as the narration text.
- Do NOT describe environment, lighting, clothing, or appearance.

TONE EXPRESSION:
- Express the emotional tone of the narration through subtle delivery cues: \
"warm conversational tone", "earnest and sincere delivery", \
"measured serious demeanor", "gentle emphatic gestures".
- Keep all expression within natural, professional anchor delivery \
— nuanced but not theatrical.

Output ONLY the prompt text, no JSON, no explanation.
""",
        )

        user_prompt = f"""\
<anchor_appearance>
{anchor_prompt}
</anchor_appearance>

<narration>
{script_text[:500]}
</narration>

{self._prompt(
    zh_text="请为此带内置音频的主播片段生成视频提示词。",
    en_text="Generate the video prompt for this anchor segment with built-in audio."
)}
"""
        logger.info(
            f"[Screenwriter] Generating anchor model-audio prompt "
            f"({len(anchor_prompt)} chars, {len(script_text)} script chars)..."
        )
        prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
        logger.info(f"[Screenwriter] Anchor model-audio prompt: {prompt[:100]}...")
        return prompt
