"""File download and deletion endpoints."""

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


def _all_storage_dirs(settings: Settings) -> tuple[Path, ...]:
    """Search order for the unified download endpoint."""
    return (
        settings.documents_dir,
        settings.images_dir,
        settings.optimized_dir,
        settings.thumbnails_dir,
    )


@router.get(
    "/files/{filename}",
    summary="Download a file",
    description=(
        "Single download endpoint for every stored asset: documents, original "
        "images, optimized WebP variants, and thumbnails."
    ),
    responses={404: {"description": "File not found"}},
)
async def get_file(
    filename: str,
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve any stored file by UUID filename."""
    safe_name = sanitize_filename(filename)
    path = resolve_in_directories(safe_name, *_all_storage_dirs(settings))
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


@router.delete(
    "/files/{filename}",
    response_model=DeleteResponse,
    summary="Delete a file and its variants",
    description=(
        "Deletes the requested file. When the target is an original image "
        "(or any of its variants), matching optimized and thumbnail files "
        "are removed as well."
    ),
)
async def delete_file(
    filename: str,
    settings: Settings = Depends(get_settings),
) -> DeleteResponse:
    """Delete a file plus related optimized/thumbnail assets when present."""
    safe_name = sanitize_filename(filename)
    deleted: list[str] = []

    # Delete the exact requested file from any storage directory
    direct = resolve_in_directories(safe_name, *_all_storage_dirs(settings))
    if direct is not None:
        try:
            direct.unlink()
            deleted.append(str(direct.name))
        except OSError as exc:
            log_extra(
                logger,
                logging.ERROR,
                "Failed to delete file",
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

    # Also clean related image variants (idempotent if already removed)
    optimized_name, thumbnail_name = related_variant_names(safe_name)
    for name, path in (
        (optimized_name, settings.optimized_dir / optimized_name),
        (thumbnail_name, settings.thumbnails_dir / thumbnail_name),
        # Original may still exist under images/ if a variant was deleted first
    ):
        if name == safe_name:
            continue
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

    # If caller deleted a variant, also remove the original image when present
    stem = Path(safe_name).stem
    if stem.endswith("_thumb"):
        stem = stem[: -len("_thumb")]
    for image_path in settings.images_dir.glob(f"{stem}.*"):
        if image_path.is_file() and image_path.name not in deleted:
            try:
                image_path.unlink()
                deleted.append(image_path.name)
            except OSError as exc:
                log_extra(
                    logger,
                    logging.ERROR,
                    "Failed to delete original image",
                    filename=image_path.name,
                    error=str(exc),
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "success": False,
                        "error": "Internal Server Error",
                        "message": "Failed to delete original image",
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
