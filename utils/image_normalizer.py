"""utils.image_normalizer — 通用图片归一化模块（全环节统一使用）

各流水线 / API 环节的参考图（i2i 参考图、i2v 首帧、角色参考图、用户上传尾帧等）
统一经此模块处理后再编码 / 上传，保证：
1. 尺寸统一：归一化到目标尺寸（视频宽高或生成尺寸），避免模型拉伸/构图错位
2. 体积压缩：默认转 JPEG quality=90，体积约为原图的 1/5 ~ 1/10
3. 透明处理：JPEG 无 alpha，含透明通道 PNG 先合成到背景色（默认白色）再编码
4. 策略可选：PAD=等比缩放+居中填充黑/白边（保留全图）；COVER=等比缩放+居中裁剪填满
5. 缓存复用：目标文件已存在则直接返回
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from PIL import Image
except ImportError:  # Pillow 缺失时降级为不归一化（见 normalize_reference_path）
    Image = None

PAD = "pad"       # 等比缩放 + 居中填充黑/白边（保留全图，主体安全）
COVER = "cover"   # 等比缩放 + 居中裁剪填满（满幅，裁掉边缘）
_DEFAULT_FORMAT = "JPEG"
_DEFAULT_QUALITY = 90


def normalize_image(
    src: str,
    width: int,
    height: int,
    dst: Optional[str] = None,
    strategy: str = PAD,
    fmt: str = _DEFAULT_FORMAT,
    quality: int = _DEFAULT_QUALITY,
    background: Tuple[int, int, int] = (255, 255, 255),
) -> str:
    """将 ``src`` 归一化到精确 ``width x height`` 并写入 ``dst``。

    Args:
        src: 源图片路径（必须是本地文件）。
        width, height: 目标像素尺寸。
        dst: 输出路径；为 None 时同目录生成 ``{stem}_norm.{fmt后缀}``。
             已存在则直接返回（缓存复用）。
        strategy: PAD 或 COVER。
        fmt: 输出格式（JPEG / PNG），JPEG 时按 quality 压缩。
        quality: JPEG 质量（0-100），默认 90。
        background: 透明通道合成用的背景色 RGB。

    Returns:
        归一化后文件路径（即 dst）。

    Raises:
        FileNotFoundError / ValueError / OSError: 源不存在、无法解码或 Pillow 不可用。
    """
    if Image is None:
        raise OSError("Pillow is not available; cannot normalize image")
    # 源图已是目标尺寸且格式匹配时直接复用，避免二次压缩失真
    try:
        with Image.open(src) as _probe:
            if _probe.size == (width, height):
                probe_fmt = (_probe.format or "").upper()
                want_fmt = "JPEG" if fmt.upper() == "JPEG" else fmt.upper()
                if probe_fmt in ("PNG", "WEBP", "JPEG") and (
                    probe_fmt == want_fmt or probe_fmt == "PNG"
                ):
                    logger.debug(f"[ImageNormalizer] {src} already {width}x{height}, reuse")
                    return src
    except OSError:
        pass
    if not dst:
        stem, ext = os.path.splitext(src)
        suffix = ".jpg" if fmt.upper() == "JPEG" else ext or ".png"
        dst = f"{stem}_norm{suffix}"
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        logger.debug(f"[ImageNormalizer] cache hit: {dst}")
        return dst

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with Image.open(src) as im:
        rgb = im.convert("RGBA")
        src_w, src_h = rgb.size
        if strategy == COVER:
            scale = max(width / src_w, height / src_h)
            nw = max(round(src_w * scale), width)
            nh = max(round(src_h * scale), height)
            rgb = rgb.resize((nw, nh), Image.LANCZOS)
            left = (nw - width) // 2
            top = (nh - height) // 2
            rgb = rgb.crop((left, top, left + width, top + height))
        else:
            scale = min(width / src_w, height / src_h)
            nw = max(round(src_w * scale), 1)
            nh = max(round(src_h * scale), 1)
            rgb = rgb.resize((nw, nh), Image.LANCZOS)
            canvas = Image.new("RGBA", (width, height), background + (255,))
            canvas.paste(rgb, ((width - nw) // 2, (height - nh) // 2), rgb)
            rgb = canvas
        if fmt.upper() == "JPEG":
            bg = Image.new("RGB", rgb.size, background)
            bg.paste(rgb, mask=rgb.split()[-1])
            bg.save(dst, "JPEG", quality=quality)
        else:
            rgb.save(dst, fmt)
    logger.info(
        f"[ImageNormalizer] {os.path.basename(src)} -> {width}x{height} "
        f"({strategy}), {os.path.getsize(dst)} bytes"
    )
    return dst


async def normalize_image_async(
    src: str, width: int, height: int, dst: Optional[str] = None,
    strategy: str = PAD, fmt: str = _DEFAULT_FORMAT,
    quality: int = _DEFAULT_QUALITY, background: Tuple[int, int, int] = (255, 255, 255),
) -> str:
    """normalize_image 的异步版本（内部 asyncio.to_thread，不阻塞事件循环）。"""
    return await asyncio.to_thread(
        normalize_image, src, width, height, dst, strategy, fmt, quality, background
    )


def normalize_reference_path(
    ref: str, width: int, height: int, dst: Optional[str] = None,
    strategy: str = PAD, fmt: str = _DEFAULT_FORMAT, quality: int = _DEFAULT_QUALITY,
) -> str:
    """归一化参考图路径的安全封装：非本地文件（URL/data:）或不存在文件原样透传。

    与 normalize_image 的区别：此函数不抛异常，归一化失败时返回原路径，
    保证任何环节接入不会因图片异常而中断流水线。
    """
    if not ref or ref.startswith(("http://", "https://", "data:")):
        return ref
    if not os.path.exists(ref):
        return ref
    try:
        return normalize_image(
            src=ref, width=width, height=height, dst=dst,
            strategy=strategy, fmt=fmt, quality=quality,
        )
    except (OSError, ValueError) as e:
        logger.warning(f"[ImageNormalizer] normalize failed for {ref} ({e}); using original")
        return ref
