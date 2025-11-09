"""Storage API for handling file uploads and downloads with local storage.

This module provides endpoints for uploading and downloading files when using
local filesystem storage instead of cloud storage (S3, GCS, Azure).
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, status
from fastapi.responses import FileResponse
from pathlib import Path
from src.config import settings
from src.storage.object_storage import LocalStorageService

router = APIRouter(prefix="/storage", tags=["storage"])


def get_local_storage() -> LocalStorageService:
    """Get local storage service instance."""
    if settings.storage_provider != "local":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Local storage endpoints are only available when storage_provider is 'local'"
        )
    return LocalStorageService(base_path=settings.storage_local_path)


@router.put("/upload/{key:path}")
async def upload_file(key: str, file: UploadFile = File(...)):
    """
    Upload a file to local storage.

    This endpoint is used by devices to upload photos when using local storage.
    It mimics the behavior of pre-signed S3 URLs.

    Args:
        key: Storage key (path) for the file
        file: File to upload

    Returns:
        Success message with the storage key
    """
    storage = get_local_storage()

    # Read file content
    content = await file.read()

    # Save to storage
    url = storage.save_file_content(key, content)

    return {
        "status": "success",
        "message": "File uploaded successfully",
        "key": key,
        "url": url
    }


@router.get("/files/{key:path}")
async def download_file(key: str):
    """
    Download a file from local storage.

    This endpoint serves files stored in local filesystem storage.

    Args:
        key: Storage key (path) for the file

    Returns:
        The requested file
    """
    storage = get_local_storage()

    file_path = storage._get_file_path(key)

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    # Try to get metadata for content type
    try:
        metadata = storage.get_file_metadata(key)
        media_type = metadata.get("content_type", "application/octet-stream")
    except:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name
    )


@router.get("/download/{key:path}")
async def download_file_alias(key: str):
    """
    Alternative download endpoint (alias for /files/).

    This provides compatibility with pre-signed download URLs.
    """
    return await download_file(key)
