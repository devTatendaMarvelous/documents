"""Image processing pipeline using Pillow.

Pipeline
--------
Original Image (untouched on disk)
    → Resize (max width 1920, preserve aspect ratio)
    → Compress (quality 80)
    → Convert to WebP
    → Generate 300px WebP thumbnail
    → Save optimized + thumbnail variants
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.constants import (
    IMAGE_QUALITY,
    MAX_IMAGE_WIDTH,
    OPTIMIZED_EXTENSION,
    THUMBNAIL_EXTENSION,
    THUMBNAIL_WIDTH,
)
from app.core.logger import get_logger, log_extra

logger = get_logger("image_processor")


@dataclass(frozen=True, slots=True)
class ProcessedImageResult:
    """Paths produced by the image processing pipeline."""

    optimized_path: Path
    thumbnail_path: Path
    optimized_filename: str
    thumbnail_filename: str


class ImageProcessingError(Exception):
    """Raised when an image cannot be processed."""


def _open_image(source: Path | BytesIO) -> Image.Image:
    """Open an image and apply EXIF orientation correction."""
    try:
        image = Image.open(source)
        image = ImageOps.exif_transpose(image)
        return image
    except UnidentifiedImageError as exc:
        raise ImageProcessingError("Unable to identify image file") from exc
    except OSError as exc:
        raise ImageProcessingError(f"Failed to open image: {exc}") from exc


def _ensure_rgb(image: Image.Image) -> Image.Image:
    """
    Convert the image to a mode suitable for WebP encoding.

    Preserves alpha by converting to RGBA when needed; otherwise uses RGB.
    """
    if image.mode in ("RGB", "RGBA"):
        return image
    if image.mode in ("LA", "PA") or "transparency" in image.info:
        return image.convert("RGBA")
    return image.convert("RGB")


def _resize_max_width(image: Image.Image, max_width: int) -> Image.Image:
    """Resize so width does not exceed ``max_width``, preserving aspect ratio."""
    if image.width <= max_width:
        return image
    ratio = max_width / float(image.width)
    new_height = max(1, int(image.height * ratio))
    return image.resize((max_width, new_height), Image.Resampling.LANCZOS)


def _make_thumbnail(image: Image.Image, max_width: int) -> Image.Image:
    """Create a thumbnail with a maximum width of ``max_width``."""
    return _resize_max_width(image, max_width)


def process_image(
    source_path: Path,
    optimized_dir: Path,
    thumbnails_dir: Path,
    base_stem: str,
    *,
    max_width: int = MAX_IMAGE_WIDTH,
    quality: int = IMAGE_QUALITY,
    thumbnail_width: int = THUMBNAIL_WIDTH,
) -> ProcessedImageResult:
    """
    Process an original image into optimized and thumbnail WebP variants.

    The original file at ``source_path`` is never modified or overwritten.

    Args:
        source_path: Path to the untouched original image.
        optimized_dir: Directory for the optimized WebP file.
        thumbnails_dir: Directory for the thumbnail WebP file.
        base_stem: Filename stem (UUID without extension) shared by variants.
        max_width: Maximum width for the optimized image.
        quality: WebP compression quality (1–100).
        thumbnail_width: Maximum width for the thumbnail.

    Returns:
        ProcessedImageResult with paths and filenames of generated assets.

    Raises:
        ImageProcessingError: If processing fails at any stage.
    """
    optimized_dir.mkdir(parents=True, exist_ok=True)
    thumbnails_dir.mkdir(parents=True, exist_ok=True)

    optimized_filename = f"{base_stem}{OPTIMIZED_EXTENSION}"
    thumbnail_filename = f"{base_stem}_thumb{THUMBNAIL_EXTENSION}"
    optimized_path = optimized_dir / optimized_filename
    thumbnail_path = thumbnails_dir / thumbnail_filename

    try:
        with _open_image(source_path) as original:
            working = _ensure_rgb(original.copy())

            # Optimized pipeline: resize → compress → WebP
            optimized = _resize_max_width(working, max_width)
            optimized.save(
                optimized_path,
                format="WEBP",
                quality=quality,
                method=6,
            )

            # Thumbnail pipeline from the same working copy
            thumb = _make_thumbnail(working, thumbnail_width)
            thumb.save(
                thumbnail_path,
                format="WEBP",
                quality=quality,
                method=6,
            )

        log_extra(
            logger,
            logging.INFO,
            "Image processed successfully",
            original=str(source_path.name),
            optimized=optimized_filename,
            thumbnail=thumbnail_filename,
            optimized_size=optimized_path.stat().st_size,
            thumbnail_size=thumbnail_path.stat().st_size,
        )

        return ProcessedImageResult(
            optimized_path=optimized_path,
            thumbnail_path=thumbnail_path,
            optimized_filename=optimized_filename,
            thumbnail_filename=thumbnail_filename,
        )
    except ImageProcessingError:
        _cleanup_partial(optimized_path, thumbnail_path)
        raise
    except Exception as exc:
        _cleanup_partial(optimized_path, thumbnail_path)
        log_extra(
            logger,
            logging.ERROR,
            "Image processing failed",
            original=str(source_path.name),
            error=str(exc),
        )
        raise ImageProcessingError(f"Image processing failed: {exc}") from exc


def _cleanup_partial(*paths: Path) -> None:
    """Remove partially written output files after a processing failure."""
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
