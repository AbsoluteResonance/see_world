import os
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.config import settings
from backend.utils import (
    is_allowed_ext,
    is_image_ext,
    make_storage_filename,
)

router = APIRouter()

IMAGE_DIR = Path(settings.upload_dir) / "images"
VIDEO_DIR = Path(settings.upload_dir) / "videos"
MAX_IMAGE_BYTES = settings.max_image_size_mb * 1024 * 1024
MAX_VIDEO_BYTES = settings.max_video_size_mb * 1024 * 1024


async def save_upload(file: UploadFile, dest_dir: Path, max_bytes: int) -> dict:
    """Save uploaded file by streaming to disk (memory-efficient)."""
    if not file.filename or not is_allowed_ext(file.filename):
        raise HTTPException(status_code=400, detail={"code": 40002, "message": "Unsupported file format"})

    fname = make_storage_filename(file.filename)
    dest = dest_dir / fname

    total = 0
    with open(dest, "wb") as f:
        while chunk := await file.read(64 * 1024):  # 64KB chunks
            total += len(chunk)
            if total > max_bytes:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail={
                    "code": 40003,
                    "message": f"File too large (max {max_bytes // (1024*1024)}MB)"
                })
            f.write(chunk)

    subdir = dest_dir.name  # "images" or "videos"
    return {
        "file_id": fname.split("_")[1] if len(fname.split("_")) > 1 else fname,
        "filename": fname,
        "original_name": file.filename,
        "size": total,
        "url": f"/uploads/{subdir}/{fname}",
        "type": "image" if dest_dir == IMAGE_DIR else "video",
    }


@router.post("/api/upload/image")
async def upload_image(file: UploadFile = File(...)):
    result = await save_upload(file, IMAGE_DIR, MAX_IMAGE_BYTES)
    return {"code": 0, "message": "success", "data": result}


@router.post("/api/upload/video")
async def upload_video(file: UploadFile = File(...)):
    result = await save_upload(file, VIDEO_DIR, MAX_VIDEO_BYTES)
    return {"code": 0, "message": "success", "data": result}


@router.post("/api/upload/batch")
async def upload_batch(files: list[UploadFile] = File(...)):
    if len(files) > 20:
        raise HTTPException(status_code=400, detail={"code": 40001, "message": "Max 20 files per batch"})

    results = []
    for f in files:
        if not f.filename or not is_allowed_ext(f.filename):
            results.append({"original_name": f.filename, "status": "skipped", "reason": "unsupported format"})
            continue
        content = await f.read()
        max_bytes = MAX_VIDEO_BYTES if not is_image_ext(f.filename) else MAX_IMAGE_BYTES
        if len(content) > max_bytes:
            results.append({"original_name": f.filename, "status": "skipped", "reason": "file too large"})
            continue
        fname = make_storage_filename(f.filename)
        dest = IMAGE_DIR if is_image_ext(f.filename) else VIDEO_DIR
        (dest / fname).write_bytes(content)
        results.append({"original_name": f.filename, "status": "uploaded", "filename": fname})

    return {"code": 0, "message": "success", "data": results}


@router.get("/api/files")
async def list_files(page: int = 1, size: int = 20):
    all_files = []
    for subdir, ftype in [(IMAGE_DIR, "image"), (VIDEO_DIR, "video")]:
        if subdir.exists():
            for f in sorted(subdir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if f.name.startswith('.'):
                    continue  # skip hidden files (.gitkeep)
                all_files.append({
                    "file_id": f.name.split("_")[1] if len(f.name.split("_")) > 1 else f.name,
                    "filename": f.name,
                    "size": f.stat().st_size,
                    "url": f"/uploads/{subdir.name}/{f.name}",
                    "type": ftype,
                    "created": f.stat().st_mtime,
                })

    total = len(all_files)
    start = (page - 1) * size
    items = all_files[start:start + size]
    return {"code": 0, "message": "success", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/api/files/{file_id}")
async def get_file(file_id: str):
    for subdir in [IMAGE_DIR, VIDEO_DIR]:
        if not subdir.exists():
            continue
        for f in subdir.iterdir():
            if file_id in f.name:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "file_id": file_id,
                        "filename": f.name,
                        "size": f.stat().st_size,
                        "url": f"/uploads/{subdir.name}/{f.name}",
                        "type": "image" if subdir == IMAGE_DIR else "video",
                    },
                }
    raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})


@router.get("/api/files/{file_id}/download")
async def download_file(file_id: str):
    from fastapi.responses import FileResponse
    for subdir in [IMAGE_DIR, VIDEO_DIR]:
        if not subdir.exists():
            continue
        for f in subdir.iterdir():
            if file_id in f.name:
                return FileResponse(str(f))
    raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})


@router.get("/api/files/{file_id}/thumbnail")
async def get_thumbnail(file_id: str):
    for subdir in [IMAGE_DIR]:
        if not subdir.exists():
            continue
        for f in subdir.iterdir():
            if file_id in f.name:
                try:
                    from PIL import Image
                    import io
                    from fastapi.responses import Response
                    img = Image.open(f)
                    img.thumbnail((300, 300))
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG")
                    return Response(content=buf.getvalue(), media_type="image/jpeg")
                except Exception:
                    raise HTTPException(status_code=400, detail={"code": 40001, "message": "Failed to generate thumbnail"})

    raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})
