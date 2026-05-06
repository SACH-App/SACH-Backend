import httpx
from fastapi import UploadFile, HTTPException, status

from app.core.config import settings
from app.core.utils import generate_file_name
from app.core.logging_config import get_logger

logger = get_logger(__name__)

BUCKET = "evidence"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


async def upload_evidence(file: UploadFile) -> dict:
    """
    Upload a file to Supabase Storage.
    Returns dict with file_url, file_name, file_type, file_size.
    """
    # Validate file type
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{file.content_type}' not allowed. Allowed: {', '.join(ALLOWED_TYPES)}"
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Validate file size
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)} MB"
        )

    # Generate unique filename
    unique_name = generate_file_name(file.filename or "upload.bin")

    # Upload to Supabase Storage
    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        "apikey": settings.SUPABASE_SERVICE_KEY,
        "Content-Type": file.content_type,
    }

    upload_url = f"{settings.SUPABASE_URL}/storage/v1/object/{BUCKET}/{unique_name}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(upload_url, headers=headers, content=content)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"Supabase upload failed: {e.response.status_code} - {e.response.text}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="File upload failed. Please try again."
            )
        except httpx.RequestError as e:
            logger.error(f"Supabase connection error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Storage service is unavailable."
            )

    # Build public URL
    public_url = f"{settings.SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{unique_name}"

    logger.info(f"File uploaded: {unique_name} ({file_size} bytes)")

    return {
        "file_url": public_url,
        "file_name": file.filename or unique_name,
        "file_type": file.content_type,
        "file_size": file_size,
    }


async def delete_evidence(file_url: str) -> bool:
    """Delete a file from Supabase Storage by its URL."""
    # Extract the file path from the URL
    prefix = f"{settings.SUPABASE_URL}/storage/v1/object/public/{BUCKET}/"
    if not file_url.startswith(prefix):
        logger.warning(f"Cannot delete file, URL doesn't match expected pattern: {file_url}")
        return False

    file_path = file_url[len(prefix):]

    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        "apikey": settings.SUPABASE_SERVICE_KEY,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(
                f"{settings.SUPABASE_URL}/storage/v1/object/{BUCKET}",
                headers=headers,
                json={"prefixes": [file_path]}
            )
            response.raise_for_status()
            logger.info(f"File deleted from storage: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file from storage: {e}")
            return False
