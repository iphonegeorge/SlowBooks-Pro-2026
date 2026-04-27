# ============================================================================
# File Uploads — company logo and other file uploads
# Feature 15: Infrastructure D (UploadFile pattern, static/uploads/)
# ============================================================================

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.models.users import User
from app.models.settings import Settings

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

UPLOAD_DIR = Path(__file__).parent.parent / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf"}
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "application/pdf"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("/logo")
async def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Validate MIME type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Only PNG, JPEG, GIF, or PDF files are allowed")

    # Validate extension
    ext = ""
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File extension '.{ext}' is not allowed")

    # Read and validate file size
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 5 MB size limit")

    # Sanitize filename — always use a fixed name to prevent path traversal
    filename = f"company_logo.{ext}"
    filepath = (UPLOAD_DIR / filename).resolve()

    # Verify resolved path is within upload directory
    if not filepath.is_relative_to(UPLOAD_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")

    with open(filepath, "wb") as f:
        f.write(contents)

    # Save path to settings
    logo_path = f"/static/uploads/{filename}"
    row = db.query(Settings).filter(Settings.key == "company_logo_path").first()
    if row:
        row.value = logo_path
    else:
        db.add(Settings(key="company_logo_path", value=logo_path))
    db.commit()

    return {"path": logo_path, "message": "Logo uploaded successfully"}
