"""core.compositor.concatenator.audio_overlay — 音频叠加拼接 + 数字人合成（v5.0 Batch 4 / 4.3 拆分）

AudioOverlayMixin：concat_videos_with_audio_overlay / composite_anchor_video；
跨组方法（_parse_srt_to_clips 等）经 MRO 由 ConcatMixin 解析。"""
import json
import logging
import os
import subprocess
from typing import List, Optional

from moviepy import AudioFileClip, CompositeVideoClip, VideoFileClip

from models.task import SubtitleStyle

from .concat import _AUDIO_BITRATE, _AUDIO_CODEC, _AUDIO_FPS, _VIDEO_FPS

logger = logging.getLogger(__name__)


def _rgb_to_ass(color) -> str:
    """Convert a color name or (r,g,b) tuple to ASS &HBBGGRR& format."""
    named = {
        "white": (255, 255, 255),
        "black": (0, 0, 0),
        "red": (255, 0, 0),
        "green": (0, 255, 0),
        "blue": (0, 0, 255),
        "yellow": (255, 255, 0),
        "cyan": (0, 255, 255),
        "magenta": (255, 0, 255),
    }
    if isinstance(color, str):
        rgb = named.get(color.strip().lower(), (255, 255, 255))
    elif isinstance(color, (list, tuple)) and len(color) >= 3:
        rgb = (int(color[0]), int(color[1]), int(color[2]))
    else:
        rgb = (255, 255, 255)
    r, g, b = rgb
    return f"&H{b:02X}{g:02X}{r:02X}&"


class AudioOverlayMixin:
    """音频叠加拼接与数字人合成方法，v5.0 Batch 4（4.3）拆分。"""

    @staticmethod
    def concat_videos_with_audio_overlay(
        video_paths: List[str],
        audio_path: str,
        srt_path: Optional[str],
        output_path: str,
        subtitle_style: Optional[SubtitleStyle] = None,
        subtitle_styles_path: Optional[str] = None,
    ) -> str:
        """先拼接视频，再统一叠加单条音频 + 单条字幕。

        使用 ffmpeg 做音视频时长对齐（tpad/apad），确保音画精确同步。

        Args:
            video_paths: 按顺序的视频路径列表。
            audio_path: 整段音频文件路径（对应全部视频的总时间轴）。
            srt_path: 整段 SRT 字幕路径（可选）。
            output_path: 最终输出文件路径。
            subtitle_style: 字幕样式配置。

        Returns:
            输出文件路径。
        """
        logger.info(
            f"[Compositor] concat_videos_with_audio_overlay: "
            f"{len(video_paths)} videos + {audio_path} → {output_path}"
        )
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if not video_paths:
            raise RuntimeError("No videos to concatenate")

        # ── Step 1: 拼接视频（无声）──
        silent_path = output_path.replace(".mp4", "_silent.mp4")
        VideoConcatenator.concat_videos(video_paths, silent_path)

        # ── Step 2: 获取音视频时长 ──
        video_dur = VideoConcatenator._get_duration(silent_path)
        audio_dur = VideoConcatenator._get_duration(audio_path)
        final_dur = max(video_dur, audio_dur)
        logger.info(
            f"[Compositor] durations: video={video_dur:.2f}s, "
            f"audio={audio_dur:.2f}s, final={final_dur:.2f}s"
        )

        video_input = silent_path
        tmp_files = [silent_path]

        # ── Step 3: 若视频 < 音频，冻结尾帧补齐 ──
        if video_dur < final_dur - 0.3:
            extend_path = output_path.replace(".mp4", "_vext.mp4")
            tmp_files.append(extend_path)
            pad_dur = final_dur - video_dur
            VideoConcatenator._run_ffmpeg(
                ["ffmpeg", "-y",
                 "-i", silent_path,
                 "-vf", f"tpad=stop_mode=clone:stop_duration={pad_dur:.2f}",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-preset", "fast",
                 extend_path],
                desc=f"extend video by {pad_dur:.1f}s (freeze last frame)",
            )
            video_input = extend_path

        # ── Step 4: 若音频 < 视频，补齐静音 ──
        audio_input = audio_path
        if audio_dur < final_dur - 0.3:
            apad_path = audio_path.replace(".mp3", "_apad.mp3")
            tmp_files.append(apad_path)
            pad_dur = final_dur - audio_dur
            VideoConcatenator._run_ffmpeg(
                ["ffmpeg", "-y",
                 "-i", audio_path,
                 "-af", f"apad=pad_dur={pad_dur:.2f},volume=1.5",
                 "-c:a", "libmp3lame", "-q:a", "2",
                 apad_path],
                desc=f"pad audio by {pad_dur:.1f}s + volume 1.5x",
            )
            audio_input = apad_path
        else:
            # 只做音量放大
            vol_path = audio_path.replace(".mp3", "_vol.mp3")
            tmp_files.append(vol_path)
            VideoConcatenator._run_ffmpeg(
                ["ffmpeg", "-y",
                 "-i", audio_path,
                 "-af", "volume=1.5",
                 "-c:a", "libmp3lame", "-q:a", "2",
                 vol_path],
                desc="boost audio volume 1.5x",
            )
            audio_input = vol_path

        # ── Step 5: moviepy 合成视频+音频+字幕 ──
        video_clip = None
        audio_clip_obj = None
        try:
            video_clip = VideoFileClip(video_input)
            audio_clip_obj = AudioFileClip(audio_input)

            # 掐头去尾确保完全对齐
            target_dur = min(video_clip.duration, audio_clip_obj.duration)
            video_clip = video_clip.subclipped(0, target_dur)
            audio_clip_obj = audio_clip_obj.subclipped(0, target_dur)

            video_with_audio = video_clip.with_audio(audio_clip_obj)

            # ── 叠加字幕 ──
            if srt_path and os.path.exists(srt_path) and subtitle_style:
                try:
                    per_entry_styles = None
                    if subtitle_styles_path and os.path.exists(subtitle_styles_path):
                        with open(subtitle_styles_path, "r", encoding="utf-8") as f:
                            per_entry_styles = json.load(f)

                    subs_clips = VideoConcatenator._parse_srt_to_clips(
                        srt_path, subtitle_style, video_clip.w,
                        video_height=video_clip.h,
                        video_duration=target_dur,
                        subtitle_styles=per_entry_styles,
                    )
                    if subs_clips:
                        final = CompositeVideoClip([video_with_audio, *subs_clips])
                        final.write_videofile(
                            output_path,
                            codec="libx264",
                            audio_codec=_AUDIO_CODEC,
                            audio_bitrate=_AUDIO_BITRATE,
                            audio_fps=_AUDIO_FPS,
                            fps=_VIDEO_FPS,
                            logger="bar",
                        )
                        final.close()
                    else:
                        video_with_audio.write_videofile(
                            output_path,
                            codec="libx264",
                            audio_codec=_AUDIO_CODEC,
                            audio_bitrate=_AUDIO_BITRATE,
                            audio_fps=_AUDIO_FPS,
                            fps=_VIDEO_FPS,
                            logger="bar",
                        )
                except Exception as e:
                    logger.warning(
                        f"[Compositor] Subtitle overlay failed: {e}, writing without subtitles"
                    )
                    video_with_audio.write_videofile(
                        output_path,
                        codec="libx264",
                        audio_codec=_AUDIO_CODEC,
                        audio_bitrate=_AUDIO_BITRATE,
                        audio_fps=_AUDIO_FPS,
                        fps=_VIDEO_FPS,
                        logger="bar",
                    )
            else:
                video_with_audio.write_videofile(
                    output_path,
                    codec="libx264",
                    audio_codec=_AUDIO_CODEC,
                    audio_bitrate=_AUDIO_BITRATE,
                    audio_fps=_AUDIO_FPS,
                    fps=_VIDEO_FPS,
                    logger="bar",
                )

            # Verify the output is non-empty; remove 0KB file and raise if broken
            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                raise RuntimeError(
                    f"[Compositor] concat_videos_with_audio_overlay produced empty file: {output_path}"
                )
        except Exception:
            # Clean up any partial/0KB output so a retry regenerates it
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            raise
        finally:
            if video_clip is not None:
                video_clip.close()
            if audio_clip_obj is not None:
                audio_clip_obj.close()
            for tmp in tmp_files:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

        logger.info(f"[Compositor] concat_videos_with_audio_overlay done: {output_path}")
        return output_path

    @staticmethod
    def composite_anchor_video(
        clip_path: str,
        audio_path: str,
        srt_path: Optional[str],
        output_path: str,
        audio_duration: float,
        subtitle_style: Optional[SubtitleStyle] = None,
        subtitle_styles_path: Optional[str] = None,
        video_width: int = 768,
        video_height: int = 1344,
    ) -> str:
        """将 5 秒主播动态视频片段循环拼接为覆盖完整音频时长，再叠加音频和字幕。

        核心思路：循环拼接 + 裁剪 + 统一叠加音频/字幕。
        接缝处用 ffmpeg xfade 做 0.3 秒交叉淡入淡出过渡。

        Args:
            clip_path: 5 秒主播动态视频片段路径。
            audio_path: TTS 读稿音频路径。
            srt_path: SRT 字幕文件路径（可选）。
            output_path: 最终输出视频路径。
            audio_duration: 音频总时长（秒）。
            subtitle_style: 字幕样式配置。
            subtitle_styles_path: LLM 样式 JSON 路径（可选）。
            video_width: 视频宽度。
            video_height: 视频高度。

        Returns:
            输出文件路径。
        """
        import math
        import subprocess

        logger.info(
            f"[Compositor] composite_anchor_video: {clip_path} + {audio_path} "
            f"(audio={audio_duration:.1f}s) → {output_path}"
        )
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # Step 1: Get clip duration
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", clip_path],
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=15,
        )
        clip_duration = float(probe.stdout.strip() or 5.0)
        if clip_duration <= 0:
            clip_duration = 5.0

        # Step 2: Calculate loop count
        needed = audio_duration + 2.0  # extra 2s padding
        n = math.ceil(needed / clip_duration) + 1

        # Step 3: Build concat file list for ffmpeg
        loop_dir = os.path.dirname(output_path)
        concat_file = os.path.join(loop_dir, "_anchor_concat.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for _ in range(n):
                f.write(f"file '{clip_path}'\n")

        looped_path = output_path.replace(".mp4", "_looped.mp4")

        # Step 4: Loop the clip to cover the full audio duration.
        # Use -stream_loop with re-encode (reliable across codecs/streams).
        # Drop the clip's own audio (-an) — we mux TTS audio separately.
        try:
            subprocess.run(
                ["ffmpeg", "-y",
                 "-stream_loop", str(n - 1), "-i", clip_path,
                 "-an",
                 "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                 "-t", str(needed),
                 looped_path],
                stdin=subprocess.DEVNULL,
                check=True, capture_output=True, timeout=300,
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"[Compositor] stream_loop concat failed: {str(e)[:200]}, trying concat demuxer fallback")

            # Fallback: concat demuxer with stream copy
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_file,
                 "-c", "copy",
                 "-an",
                 "-t", str(needed),
                 looped_path],
                stdin=subprocess.DEVNULL,
                check=True, capture_output=True, timeout=300,
            )

        # Verify looped clip has real duration (catch 0:00 / empty loops)
        looped_dur = VideoConcatenator._get_duration(looped_path)
        if looped_dur <= 0.1:
            raise RuntimeError(
                f"[Compositor] looped anchor video has ~0 duration: {looped_path}"
            )

        # Step 5: Overlay audio + subtitles via ffmpeg streaming.
        # Using ffmpeg (not moviepy) avoids loading the full looped video into
        # memory — this prevents 0KB/OOM failures on long anchor videos.
        try:
            video_filter = None
            if srt_path and os.path.exists(srt_path) and subtitle_style:
                force_style = VideoConcatenator._build_ass_force_style(subtitle_style)
                srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")
                video_filter = f"subtitles='{srt_escaped}'"
                if force_style:
                    video_filter = f"subtitles='{srt_escaped}':force_style='{force_style}'"

            # Validate audio: if missing/empty, output video-only (avoid -shortest → 0:00)
            audio_ok = (
                audio_path and os.path.exists(audio_path)
                and os.path.getsize(audio_path) > 0
                and VideoConcatenator._get_duration(audio_path) > 0.1
            )

            cmd = ["ffmpeg", "-y", "-i", looped_path]
            if audio_ok:
                cmd += ["-i", audio_path]
            if video_filter:
                if audio_ok:
                    cmd += [
                        "-filter_complex",
                        f"[0:v]{video_filter}[v];[1:a]volume=1.5[a]",
                        "-map", "[v]", "-map", "[a]",
                    ]
                else:
                    cmd += ["-vf", video_filter]
            else:
                if audio_ok:
                    cmd += ["-map", "0:v", "-map", "1:a", "-af", "volume=1.5"]
                else:
                    cmd += ["-map", "0:v"]
            cmd += [
                "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k" if audio_ok else "-an",
                output_path,
            ]

            subprocess.run(
                cmd, stdin=subprocess.DEVNULL,
                check=True, capture_output=True, timeout=600,
            )

            # Verify the output has real duration (catch 0:00 / empty output)
            out_dur = VideoConcatenator._get_duration(output_path)
            if out_dur <= 0.1:
                raise RuntimeError(
                    f"[Compositor] composite_anchor_video produced 0:00 video: {output_path}"
                )

            # Verify the output is non-empty; remove 0KB file and raise if broken
            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                raise RuntimeError(
                    f"[Compositor] composite_anchor_video produced empty file: {output_path}"
                )
        except Exception:
            # Clean up any partial/0KB output so a retry regenerates it
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            raise
        finally:
            for tmp in (looped_path, concat_file):
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

        logger.info(f"[Compositor] composite_anchor_video done: {output_path}")
        return output_path

    @staticmethod
    def _build_ass_force_style(style) -> str:
        """Build an ASS force_style string from SubtitleStyle for ffmpeg subtitles."""
        from core.config import resolve_font_path

        parts = []
        if style.font:
            font_path = resolve_font_path(style.font)
            if font_path and os.path.exists(font_path):
                font_dir = os.path.dirname(font_path)
                font_name = os.path.splitext(os.path.basename(font_path))[0]
                # fontsdir must use forward slashes for ffmpeg filter
                parts.append(f"FontName={font_name}")
                parts.append(f"FontFile={font_path.replace(chr(92), '/')}")
        if style.fontsize:
            parts.append(f"FontSize={style.fontsize}")
        if style.color:
            parts.append(f"PrimaryColour={_rgb_to_ass(style.color)}")
        if style.stroke_color:
            parts.append(f"OutlineColour={_rgb_to_ass(style.stroke_color)}")
        if style.stroke_width:
            parts.append(f"Outline={style.stroke_width}")
        # Position → Alignment (1-9 grid)
        pos = style.position
        if isinstance(pos, (list, tuple)) and len(pos) >= 2:
            h, v = str(pos[0]).lower(), str(pos[1]).lower()
            align = 2  # default bottom-center
            if "top" in v:
                align = 8 if h == "center" else (7 if "left" in h else 9)
            elif "bottom" in v:
                align = 2 if h == "center" else (1 if "left" in h else 3)
            elif h == "center":
                align = 5
            parts.append(f"Alignment={align}")
        if style.bg_color:
            r, g, b, a = style.bg_color
            ass_alpha = f"&H{int(a):02X}{b:02X}{g:02X}{r:02X}&"
            # BackColour expects &HAABBGGRR
            parts.append(f"BackColour={ass_alpha}")
            parts.append("BorderStyle=4")  # 4 = background box
        return ",".join(parts)
