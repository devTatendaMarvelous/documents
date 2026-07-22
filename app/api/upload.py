"""Unified upload endpoint for documents and images."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.constants import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_UPLOAD_EXTENSIONS,
    DOCUMENT_MIME_TYPES,
    IMAGE_MIME_TYPES,
)
from app.core.image_processor import ImageProcessingError, process_image
from app.core.logger import get_logger, log_extra
from app.core.security import verify_api_key
from app.utils.helpers import (
    generate_uuid_filename,
    get_extension,
    get_mime_type,
    read_upload_limited,
    validate_extension,
)

router = APIRouter(
    tags=["Upload"],
    dependencies=[Depends(verify_api_key)],
)

logger = get_logger("upload")


class UploadResponse(BaseModel):
    """Unified response for any successful upload."""

    success: bool = True
    type: Literal["document", "image"]
    filename: str
    original_name: str
    size: int
    mime_type: str
    url: str
    optimized: str | None = None
    thumbnail: str | None = None
    optimized_url: str | None = None
    thumbnail_url: str | None = None


def _require_filename(upload: UploadFile) -> str:
    if not upload.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "Bad Request",
                "message": "Filename is required",
            },
        )
    return upload.filename


async def _write_bytes(destination: Path, content: bytes, *, label: str) -> None:
    try:
        async with aiofiles.open(destination, "wb") as out:
            await out.write(content)
    except OSError as exc:
        log_extra(
            logger,
            logging.ERROR,
            f"{label} upload failed to write",
            path=str(destination),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "Internal Server Error",
                "message": f"Failed to store uploaded {label}",
            },
        ) from exc


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document or image",
    description=(
        "Single upload endpoint for all supported types. "
        "Documents (PDF, Office, TXT, CSV, ZIP) are stored as-is. "
        "Images (JPG, JPEG, PNG, WebP) are stored as originals and also "
        "processed into optimized + thumbnail WebP variants. "
        "All downloads use ``GET /files/{filename}``."
    ),
)
async def upload_file(
    file: UploadFile = File(..., description="Document or image to upload"),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    """Accept any allowed file type and route it to the correct storage path."""
    original_name = _require_filename(file)
    extension = validate_extension(original_name, ALLOWED_UPLOAD_EXTENSIONS)
    content = await read_upload_limited(file, settings.max_upload_size_bytes)

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "Bad Request",
                "message": "Uploaded file is empty",
            },
        )

    if extension in ALLOWED_IMAGE_EXTENSIONS:
        return await _store_image(original_name, content, settings)

    return await _store_document(original_name, content, settings, extension)


async def _store_document(
    original_name: str,
    content: bytes,
    settings: Settings,
    extension: str,
) -> UploadResponse:
    stored_name = generate_uuid_filename(original_name)
    destination = settings.documents_dir / stored_name
    await _write_bytes(destination, content, label="document")

    mime_type = DOCUMENT_MIME_TYPES.get(extension, get_mime_type(stored_name))

    log_extra(
        logger,
        logging.INFO,
        "Document uploaded",
        original=original_name,
        stored=stored_name,
        size=len(content),
        mime_type=mime_type,
    )

    return UploadResponse(
        success=True,
        type="document",
        filename=stored_name,
        original_name=original_name,
        size=len(content),
        mime_type=mime_type,
        url=f"/files/{stored_name}",
    )


async def _store_image(
    original_name: str,
    content: bytes,
    settings: Settings,
) -> UploadResponse:
    stored_name = generate_uuid_filename(original_name)
    original_path = settings.images_dir / stored_name
    await _write_bytes(original_path, content, label="image")

    try:
        result = process_image(
            source_path=original_path,
            optimized_dir=settings.optimized_dir,
            thumbnails_dir=settings.thumbnails_dir,
            base_stem=Path(stored_name).stem,
        )
    except ImageProcessingError as exc:
        try:
            if original_path.exists():
                original_path.unlink()
        except OSError:
            pass

        log_extra(
            logger,
            logging.ERROR,
            "Image processing failure during upload",
            original=original_name,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "Bad Request",
                "message": str(exc),
            },
        ) from exc

    mime_type = IMAGE_MIME_TYPES.get(
        get_extension(original_name),
        get_mime_type(stored_name),
    )

    log_extra(
        logger,
        logging.INFO,
        "Image uploaded and processed",
        original=original_name,
        stored=stored_name,
        optimized=result.optimized_filename,
        thumbnail=result.thumbnail_filename,
        size=len(content),
    )

    return UploadResponse(
        success=True,
        type="image",
        filename=stored_name,
        original_name=original_name,
        size=len(content),
        mime_type=mime_type,
        url=f"/files/{stored_name}",
        optimized=result.optimized_filename,
        thumbnail=result.thumbnail_filename,
        optimized_url=f"/files/{result.optimized_filename}",
        thumbnail_url=f"/files/{result.thumbnail_filename}",
    )
