"""Upload endpoints for documents and images."""

from __future__ import annotations

import logging
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.constants import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    DOCUMENT_MIME_TYPES,
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
    prefix="/upload",
    tags=["Upload"],
    dependencies=[Depends(verify_api_key)],
)

logger = get_logger("upload")


class DocumentUploadResponse(BaseModel):
    """Response returned after a successful document upload."""

    success: bool = True
    filename: str
    original_name: str
    size: int
    mime_type: str
    url: str


class ImageUploadResponse(BaseModel):
    """Response returned after a successful image upload and processing."""

    success: bool = True
    original: str
    optimized: str
    thumbnail: str
    url: str
    optimized_url: str
    thumbnail_url: str


@router.post(
    "/document",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document",
    description=(
        "Accepts PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, TXT, CSV, or ZIP. "
        "Stores the file under ``storage/documents/`` with a UUID filename."
    ),
)
async def upload_document(
    file: UploadFile = File(..., description="Document file to upload"),
    settings: Settings = Depends(get_settings),
) -> DocumentUploadResponse:
    """Receive and store a document file on the local filesystem."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "Bad Request",
                "message": "Filename is required",
            },
        )

    validate_extension(file.filename, ALLOWED_DOCUMENT_EXTENSIONS)
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

    stored_name = generate_uuid_filename(file.filename)
    destination: Path = settings.documents_dir / stored_name

    try:
        async with aiofiles.open(destination, "wb") as out:
            await out.write(content)
    except OSError as exc:
        log_extra(
            logger,
            logging.ERROR,
            "Document upload failed to write",
            original=file.filename,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "Internal Server Error",
                "message": "Failed to store uploaded document",
            },
        ) from exc

    extension = get_extension(file.filename)
    mime_type = DOCUMENT_MIME_TYPES.get(extension, get_mime_type(stored_name))

    log_extra(
        logger,
        logging.INFO,
        "Document uploaded",
        original=file.filename,
        stored=stored_name,
        size=len(content),
        mime_type=mime_type,
    )

    return DocumentUploadResponse(
        success=True,
        filename=stored_name,
        original_name=file.filename,
        size=len(content),
        mime_type=mime_type,
        url=f"/files/{stored_name}",
    )


@router.post(
    "/image",
    response_model=ImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and process an image",
    description=(
        "Accepts JPG, JPEG, PNG, or WebP. Stores the original under "
        "``storage/images/``, then generates optimized and thumbnail WebP "
        "variants. The original file is never overwritten."
    ),
)
async def upload_image(
    file: UploadFile = File(..., description="Image file to upload"),
    settings: Settings = Depends(get_settings),
) -> ImageUploadResponse:
    """Receive an image, store the original, and generate processed variants."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "Bad Request",
                "message": "Filename is required",
            },
        )

    validate_extension(file.filename, ALLOWED_IMAGE_EXTENSIONS)
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

    stored_name = generate_uuid_filename(file.filename)
    original_path: Path = settings.images_dir / stored_name

    try:
        async with aiofiles.open(original_path, "wb") as out:
            await out.write(content)
    except OSError as exc:
        log_extra(
            logger,
            logging.ERROR,
            "Image upload failed to write original",
            original=file.filename,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "Internal Server Error",
                "message": "Failed to store uploaded image",
            },
        ) from exc

    base_stem = Path(stored_name).stem

    try:
        result = process_image(
            source_path=original_path,
            optimized_dir=settings.optimized_dir,
            thumbnails_dir=settings.thumbnails_dir,
            base_stem=base_stem,
        )
    except ImageProcessingError as exc:
        # Remove the original if processing fails so we do not leave orphans
        try:
            if original_path.exists():
                original_path.unlink()
        except OSError:
            pass

        log_extra(
            logger,
            logging.ERROR,
            "Image processing failure during upload",
            original=file.filename,
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

    log_extra(
        logger,
        logging.INFO,
        "Image uploaded and processed",
        original=file.filename,
        stored=stored_name,
        optimized=result.optimized_filename,
        thumbnail=result.thumbnail_filename,
        size=len(content),
    )

    return ImageUploadResponse(
        success=True,
        original=stored_name,
        optimized=result.optimized_filename,
        thumbnail=result.thumbnail_filename,
        url=f"/files/{stored_name}",
        optimized_url=f"/optimized/{result.optimized_filename}",
        thumbnail_url=f"/thumbnails/{result.thumbnail_filename}",
    )
