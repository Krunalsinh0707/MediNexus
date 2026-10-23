import os
import re
import uuid
from typing import Mapping, Set

from fastapi import HTTPException, UploadFile, status

ALLOWED_EXTENSIONS: Set[str] = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

MAGIC_NUMBERS = {
    b"%PDF-": ".pdf",
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
}

ALLOWED_MIME_TYPES: Mapping[str, Set[str]] = {
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
}

def sanitize_original_filename(filename: str) -> str:
    """Return a display-safe basename without accepting a filesystem path."""
    clean_original = os.path.basename(filename or "unnamed_report")
    return re.sub(r"[^\w\.\-\s]", "_", clean_original)[:255]


def sanitize_filename(filename: str, prefix: str = "report_") -> str:
    """
    Return an opaque storage filename while preserving an allowed extension.
    """
    clean_original = sanitize_original_filename(filename)

    ext = os.path.splitext(clean_original)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".bin"

    safe_prefix = re.sub(r"[^A-Za-z0-9_-]", "_", prefix)[:64]
    return f"{safe_prefix}{uuid.uuid4().hex}{ext}"

async def validate_uploaded_file(
    file: UploadFile,
    max_size_bytes: int = MAX_FILE_SIZE_BYTES,
    allowed_exts: Set[str] = ALLOWED_EXTENSIONS
) -> bytes:
    """
    Validate extension, MIME type, size, and magic bytes, then return content.

    Invalid files raise an HTTP error and are never written by this helper.
    """
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename cannot be empty")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{ext}' is not permitted. Allowed extensions: {', '.join(sorted(allowed_exts))}",
        )

    allowed_mimes = ALLOWED_MIME_TYPES.get(ext, set())
    if file.content_type not in allowed_mimes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"MIME type '{file.content_type or 'unknown'}' is not permitted for {ext} files",
        )

    # Read leading bytes for signature check & size check
    content = await file.read(max_size_bytes + 1)
    if not content:
        await file.seek(0)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    if len(content) > max_size_bytes:
        await file.seek(0)
        limit_mb = max_size_bytes / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File size exceeds maximum limit of {limit_mb:g}MB",
        )

    # Signature validation
    if ext == ".pdf":
        if not content.startswith(b"%PDF-"):
            await file.seek(0)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File format mismatch: Content is not a valid PDF document")
    elif ext == ".png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            await file.seek(0)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File format mismatch: Content is not a valid PNG image")
    elif ext in (".jpg", ".jpeg"):
        if not content.startswith(b"\xff\xd8\xff"):
            await file.seek(0)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File format mismatch: Content is not a valid JPEG image")

    # Reset file pointer to beginning for subsequent reads
    await file.seek(0)
    return content
