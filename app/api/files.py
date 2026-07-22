"""File retrieval and deletion endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.logger import get_logger, log_extra
from app.core.security import verify_api_key
from app.utils.helpers import (
    get_mime_type,
    related_variant_names,
    resolve_in_directories,
    sanitize_filename,
)

router = APIRouter(tags=["Files"], dependencies=[Depends(verify_api_key)])

logger = get_logger("files")


class DeleteResponse(BaseModel):
    """Response returned after a delete operation."""

    success: bool = True
    message: str
    deleted: list[str] = Field(default_factory=list)


def _not_found(filename: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "success": False,
            "error": "Not Found",
            "message": f"File '{filename}' was not found",
        },
    )


@router.get(
    "/files/{filename}",
    summary="Retrieve a document or original image",
    description=(
        "Serves a file from ``storage/documents/`` or ``storage/images/`` "
        "with the correct MIME type. Documents and images share this path "
        "because originals live in separate storage directories."
    ),
    responses={404: {"description": "File not found"}},
)
async def get_file(
    filename: str,
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve an original document or image by stored filename."""
    safe_name = sanitize_filename(filename)
    path = resolve_in_directories(
        safe_name,
        settings.documents_dir,
        settings.images_dir,
    )
    if path is None:
        raise _not_found(safe_name)

    mime_type = get_mime_type(safe_name)
    log_extra(
        logger,
        logging.INFO,
        "File downloaded",
        filename=safe_name,
        mime_type=mime_type,
        location=str(path.parent.name),
    )
    return FileResponse(
        path=path,
        media_type=mime_type,
        filename=safe_name,
    )


@router.get(
    "/optimized/{filename}",
    summary="Retrieve an optimized image",
    description=(
        "Serves a processed WebP image from ``storage/optimized/``. "
        "Also available via the StaticFiles mount at ``/optimized/``."
    ),
    responses={404: {"description": "File not found"}},
)
async def get_optimized(
    filename: str,
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve an optimized WebP image variant with download logging."""
    safe_name = sanitize_filename(filename)
    path = settings.optimized_dir / safe_name
    if not path.is_file():
        raise _not_found(safe_name)

    log_extra(
        logger,
        logging.INFO,
        "Optimized image downloaded",
        filename=safe_name,
    )
    return FileResponse(
        path=path,
        media_type="image/webp",
        filename=safe_name,
    )


@router.get(
    "/thumbnails/{filename}",
    summary="Retrieve a thumbnail image",
    description=(
        "Serves a thumbnail WebP image from ``storage/thumbnails/``. "
        "Also available via the StaticFiles mount at ``/thumbnails/``."
    ),
    responses={404: {"description": "File not found"}},
)
async def get_thumbnail(
    filename: str,
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve a thumbnail WebP image variant with download logging."""
    safe_name = sanitize_filename(filename)
    path = settings.thumbnails_dir / safe_name
    if not path.is_file():
        raise _not_found(safe_name)

    log_extra(
        logger,
        logging.INFO,
        "Thumbnail downloaded",
        filename=safe_name,
    )
    return FileResponse(
        path=path,
        media_type="image/webp",
        filename=safe_name,
    )


@router.delete(
    "/files/{filename}",
    response_model=DeleteResponse,
    summary="Delete a file and its variants",
    description=(
        "Deletes the original file from documents or images storage, and "
        "removes matching optimized and thumbnail variants when present."
    ),
)
async def delete_file(
    filename: str,
    settings: Settings = Depends(get_settings),
) -> DeleteResponse:
    """Delete an original file plus any related optimized/thumbnail assets."""
    safe_name = sanitize_filename(filename)
    deleted: list[str] = []

    original = resolve_in_directories(
        safe_name,
        settings.documents_dir,
        settings.images_dir,
    )

    optimized_name, thumbnail_name = related_variant_names(safe_name)
    candidates: list[tuple[str, Path]] = [
        (f"optimized/{optimized_name}", settings.optimized_dir / optimized_name),
        (f"thumbnails/{thumbnail_name}", settings.thumbnails_dir / thumbnail_name),
    ]

    if original is not None:
        try:
            original.unlink()
            deleted.append(str(original.name))
        except OSError as exc:
            log_extra(
                logger,
                logging.ERROR,
                "Failed to delete original file",
                filename=safe_name,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "success": False,
                    "error": "Internal Server Error",
                    "message": "Failed to delete file",
                },
            ) from exc

    for name, path in candidates:
        if path.is_file():
            try:
                path.unlink()
                deleted.append(name)
            except OSError as exc:
                log_extra(
                    logger,
                    logging.ERROR,
                    "Failed to delete variant file",
                    filename=name,
                    error=str(exc),
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "success": False,
                        "error": "Internal Server Error",
                        "message": f"Failed to delete variant '{name}'",
                    },
                ) from exc

    if not deleted:
        raise _not_found(safe_name)

    log_extra(
        logger,
        logging.INFO,
        "File deleted",
        filename=safe_name,
        deleted=",".join(deleted),
    )

    return DeleteResponse(
        success=True,
        message=f"Deleted {len(deleted)} file(s)",
        deleted=deleted,
    )
