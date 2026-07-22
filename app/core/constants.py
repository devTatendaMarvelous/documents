"""Application-wide constants for allowed file types, MIME maps, and image limits."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Document uploads
# ---------------------------------------------------------------------------

ALLOWED_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".txt",
        ".csv",
        ".zip",
    }
)

DOCUMENT_MIME_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".zip": "application/zip",
}

# ---------------------------------------------------------------------------
# Image uploads
# ---------------------------------------------------------------------------

ALLOWED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }
)

IMAGE_MIME_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

# ---------------------------------------------------------------------------
# Image processing defaults
# ---------------------------------------------------------------------------

MAX_IMAGE_WIDTH: int = 1920
IMAGE_QUALITY: int = 80
THUMBNAIL_WIDTH: int = 300
OPTIMIZED_EXTENSION: str = ".webp"
THUMBNAIL_EXTENSION: str = ".webp"

# ---------------------------------------------------------------------------
# Combined lookup for serving files
# ---------------------------------------------------------------------------

ALL_MIME_TYPES: dict[str, str] = {
    **DOCUMENT_MIME_TYPES,
    **IMAGE_MIME_TYPES,
    OPTIMIZED_EXTENSION: "image/webp",
}

ALLOWED_UPLOAD_EXTENSIONS: frozenset[str] = (
    ALLOWED_DOCUMENT_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS
)

DEFAULT_MIME_TYPE: str = "application/octet-stream"

# Shared secret required in the X-API-Key header (all endpoints except /health)
API_KEY: str = "microfindev263"
