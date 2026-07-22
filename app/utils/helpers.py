"""Reusable filesystem and validation helpers."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.constants import ALL_MIME_TYPES, DEFAULT_MIME_TYPE


_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def generate_uuid_filename(original_name: str) -> str:
    """
    Generate a UUID-based filename while preserving the original extension.

    Example::

        invoice.pdf → 5fbfa1ab-fac8-44d2-b5ba-0d02b51eeb89.pdf
    """
    extension = Path(original_name).suffix.lower()
    return f"{uuid.uuid4()}{extension}"


def get_extension(filename: str) -> str:
    """Return the lowercase file extension including the leading dot."""
    return Path(filename).suffix.lower()


def get_mime_type(filename: str) -> str:
    """Resolve a MIME type from the filename extension."""
    return ALL_MIME_TYPES.get(get_extension(filename), DEFAULT_MIME_TYPE)


def sanitize_filename(filename: str) -> str:
    """
    Validate a path segment used in URL parameters.

    Rejects path traversal attempts and unexpected characters.
    """
    name = Path(filename).name  # strips any directory components
    if not name or name in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "Bad Request",
                "message": "Invalid filename",
            },
        )
    if not _SAFE_FILENAME_RE.match(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "Bad Request",
                "message": "Filename contains invalid characters",
            },
        )
    return name


def validate_extension(filename: str, allowed: frozenset[str]) -> str:
    """
    Ensure the file extension is in the allowed set.

    Returns the normalized extension on success.
    """
    extension = get_extension(filename)
    if extension not in allowed:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "success": False,
                "error": "Unsupported Media Type",
                "message": (
                    f"File type '{extension or '(none)'}' is not allowed. "
                    f"Allowed: {', '.join(sorted(allowed))}"
                ),
            },
        )
    return extension


async def read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    """
    Read an uploaded file into memory, enforcing a maximum size.

    Raises HTTP 413 if the payload exceeds ``max_bytes``.
    """
    chunks: list[bytes] = []
    total = 0
    chunk_size = 1024 * 1024  # 1 MiB

    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "success": False,
                    "error": "Payload Too Large",
                    "message": f"Upload exceeds maximum allowed size of {max_bytes} bytes",
                },
            )
        chunks.append(chunk)

    return b"".join(chunks)


def resolve_in_directories(filename: str, *directories: Path) -> Path | None:
    """
    Locate ``filename`` in the first directory where it exists.

    Returns ``None`` when the file is not found in any directory.
    """
    safe_name = sanitize_filename(filename)
    for directory in directories:
        candidate = directory / safe_name
        if candidate.is_file():
            return candidate
    return None


def stem_from_filename(filename: str) -> str:
    """Return the stem (UUID portion) of a stored filename."""
    return Path(filename).stem


def related_variant_names(filename: str) -> tuple[str, str]:
    """
    Derive optimized and thumbnail WebP filenames from an original image name.

    Both variants share the UUID stem of the original.
    """
    stem = stem_from_filename(sanitize_filename(filename))
    return f"{stem}.webp", f"{stem}.webp"
