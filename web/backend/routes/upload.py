from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.config import settings
from backend.utils import (
    is_allowed_ext,
    is_image_ext,
    make_storage_filename,
)

router = APIRouter()

VIDEO_DIR = Path(settings.upload_dir) / "videos"
MAX_VIDEO_BYTES = settings.max_video_size_mb * 1024 * 1024


async def save_upload(file: UploadFile, dest_dir: Path, max_bytes: int) -> dict:
    """Save uploaded file by streaming to disk (memory-efficient)."""
    if not file.filename or not is_allowed_ext(file.filename):
        raise HTTPException(status_code=400, detail={"code": 40002, "message": "Unsupported file format"})

    fname = make_storage_filename(file.filename)
    dest = dest_dir / fname

    total = 0
    with open(dest, "wb") as f:
        while chunk := await file.read(64 * 1024):
            total += len(chunk)
            if total > max_bytes:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail={
                    "code": 40003,
                    "message": f"File too large (max {max_bytes // (1024*1024)}MB)"
                })
            f.write(chunk)

    return {
        "file_id": fname.split("_")[1] if len(fname.split("_")) > 1 else fname,
        "filename": fname,
        "original_name": file.filename,
        "size": total,
        "url": f"/uploads/videos/{fname}",
        "type": "video",
    }


@router.post("/api/upload/video")
async def upload_video(file: UploadFile = File(...),
                       auto_reconstruct: bool = Form(False)):
    result = await save_upload(file, VIDEO_DIR, MAX_VIDEO_BYTES)
    response = {"code": 0, "message": "success", "data": result}

    if auto_reconstruct:
        try:
            from backend.services import mast3r_slam_service
            job = mast3r_slam_service.create_batch_job(
                str(VIDEO_DIR / result["filename"]))
            mast3r_slam_service.start_batch_job(job["job_id"])
            response["data"]["reconstruction_job_id"] = job["job_id"]
        except Exception as e:
            print(f"[upload] auto-reconstruct failed: {e}")
            response["data"]["reconstruction_error"] = str(e)

    return response


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
        if len(content) > MAX_VIDEO_BYTES:
            results.append({"original_name": f.filename, "status": "skipped", "reason": "file too large"})
            continue
        fname = make_storage_filename(f.filename)
        (VIDEO_DIR / fname).write_bytes(content)
        results.append({"original_name": f.filename, "status": "uploaded", "filename": fname})

    return {"code": 0, "message": "success", "data": results}


@router.get("/api/files")
async def list_files(page: int = 1, size: int = 20):
    all_files = []
    if VIDEO_DIR.exists():
        for f in sorted(VIDEO_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.name.startswith('.'):
                continue
            all_files.append({
                "file_id": f.name.split("_")[1] if len(f.name.split("_")) > 1 else f.name,
                "filename": f.name,
                "size": f.stat().st_size,
                "url": f"/uploads/videos/{f.name}",
                "type": "video",
                "created": f.stat().st_mtime,
            })

    total = len(all_files)
    start = (page - 1) * size
    items = all_files[start:start + size]
    return {"code": 0, "message": "success", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/api/files/{file_id}")
async def get_file(file_id: str):
    for subdir in [VIDEO_DIR]:
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
                        "type": "video",
                    },
                }
    raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})


@router.get("/api/files/{file_id}/download")
async def download_file(file_id: str):
    from fastapi.responses import FileResponse
    for subdir in [VIDEO_DIR]:
        if not subdir.exists():
            continue
        for f in subdir.iterdir():
            if file_id in f.name:
                return FileResponse(str(f))
    raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})


@router.get("/api/files/{file_id}/thumbnail")
async def get_thumbnail(file_id: str):
    import io
    from fastapi.responses import Response

    cache_dir = Path(settings.upload_dir) / ".cache" / "thumbs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{file_id}.jpg"
    if cached.exists():
        return Response(content=cached.read_bytes(), media_type="image/jpeg")

    for subdir in [VIDEO_DIR]:
        if not subdir.exists():
            continue
        for f in subdir.iterdir():
            if f.name.startswith('.') or not f.is_file():
                continue
            if file_id not in f.name:
                continue
            try:
                import cv2
                cap = cv2.VideoCapture(str(f))
                ret, frame = cap.read()
                cap.release()
                if not ret:
                    raise RuntimeError("Cannot read video frame")
                from PIL import Image
                import numpy as np
                img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

                img.thumbnail((300, 300))
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                data = buf.getvalue()
                cached.write_bytes(data)
                return Response(content=data, media_type="image/jpeg")
            except Exception as e:
                raise HTTPException(status_code=400, detail={"code": 40001, "message": f"Thumbnail failed: {e}"})

    raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})


def _find_file(file_id: str) -> Path | None:
    """Find an uploaded file by file_id. Returns path or None."""
    for subdir in [VIDEO_DIR]:
        if not subdir.exists():
            continue
        for f in subdir.iterdir():
            if f.name.startswith('.') or not f.is_file():
                continue
            if file_id in f.name:
                return f
    return None


@router.put("/api/files/{file_id}/rename")
async def rename_file(file_id: str, body: dict):
    """Rename an uploaded file."""
    fpath = _find_file(file_id)
    if not fpath:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})

    new_name = (body.get("new_name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail={"code": 40001, "message": "new_name is required"})

    # Keep original extension
    orig_ext = fpath.suffix
    stem = new_name.rsplit(".", 1)[0] if "." in new_name else new_name
    new_path = fpath.with_stem(stem)
    if new_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".avi"}:
        new_path = new_path.with_suffix(orig_ext)

    # Avoid collision
    if new_path.exists() and new_path != fpath:
        raise HTTPException(status_code=400, detail={"code": 40001, "message": "Target name already exists"})

    fpath.rename(new_path)

    # Remove cached thumbnail
    cache_dir = Path(settings.upload_dir) / ".cache" / "thumbs"
    thumb = cache_dir / f"{file_id}.jpg"
    if thumb.exists():
        thumb.unlink()

    return {"code": 0, "message": "success", "data": {"filename": new_path.name}}


@router.delete("/api/files/{file_id}")
async def delete_file(file_id: str):
    """Delete an uploaded file."""
    fpath = _find_file(file_id)
    if not fpath:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})

    fpath.unlink()

    # Remove cached thumbnail
    cache_dir = Path(settings.upload_dir) / ".cache" / "thumbs"
    thumb = cache_dir / f"{file_id}.jpg"
    if thumb.exists():
        thumb.unlink()

    return {"code": 0, "message": "success", "data": {"deleted": file_id}}
