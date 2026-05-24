"""MASt3R-SLAM routes — offline batch and online streaming."""

import io
import json
import base64
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from backend.services import mast3r_slam_service

router = APIRouter()


@router.get("/api/slam3r/status")
async def get_slam3r_status():
    """Check availability."""
    avail = mast3r_slam_service.check_available()
    return {"code": 0, "message": "success", "data": {
        "mast3r_slam": avail,
        "ready": avail.get("available", False),
    }}


@router.post("/api/slam3r/mast3r/frame")
async def mast3r_frame(body: dict):
    """Fire-and-forget frame submission."""
    image_b64 = body.get("image", "")
    if not image_b64:
        raise HTTPException(status_code=400, detail="no image")
    if not mast3r_slam_service._infer_ready.is_set():
        ok = mast3r_slam_service.start_inference()
        if not ok:
            raise HTTPException(status_code=500, detail="inference start failed")
    mast3r_slam_service.send_frame(image_b64, body.get("timestamp", 0.0), max_points=body.get("max_points", 500))
    save_flag = body.get("save", False)
    print(f"[route] save={save_flag} type={type(save_flag).__name__}")
    if save_flag:
        try:
            ts = str(body.get("timestamp", "0"))
            with open(f"/tmp/mast3r_frame_{ts}.jpg", "wb") as f:
                f.write(base64.b64decode(image_b64))
            print(f"[route] saved frame {ts}")
        except Exception as e:
            print(f"[route] save frame failed: {e}")
    return {"code": 0, "data": {"received": True}}


@router.get("/api/slam3r/mast3r/points")
async def mast3r_points():
    """Get latest point cloud result."""
    r = mast3r_slam_service.get_result()
    if not r:
        return {"code": 0, "data": {"type": "no_data", "points": []}}
    return {"code": 0, "data": {
        "type": "cloud",
        "points": r.get("points", []),
        "num_points": r.get("num_points", 0),
        "frames_processed": r.get("frames_processed", 0),
        "total_points": r.get("total_points", 0),
    }}


# ── Batch offline reconstruction ──


@router.post("/api/slam3r/reconstruct")
async def start_reconstruction(body: dict):
    """Start offline batch reconstruction from an uploaded video."""
    file_id = body.get("file_id", "")
    if not file_id:
        raise HTTPException(status_code=400, detail={"code": 400, "message": "file_id required"})

    found = None
    from backend.config import settings
    video_dir = Path(settings.upload_dir) / "videos"
    if video_dir.exists():
        for f in video_dir.iterdir():
            if f.name.startswith('.') or not f.is_file():
                continue
            if file_id in f.name:
                found = f
                break

    if not found:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Video file not found"})

    job = mast3r_slam_service.create_batch_job(str(found))
    mast3r_slam_service.start_batch_job(job["job_id"])

    return {"code": 0, "message": "success", "data": {"job_id": job["job_id"]}}


@router.get("/api/slam3r/reconstruct/{job_id}")
async def get_reconstruction_status(job_id: str):
    """Poll reconstruction job status."""
    job = mast3r_slam_service.get_batch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Job not found"})
    return {"code": 0, "message": "success", "data": {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job.get("progress", 0),
        "progress_message": job.get("progress_message", ""),
        "ply_path": job.get("ply_path", ""),
        "num_points": job.get("num_points", 0),
        "screenshots": job.get("screenshots", []),
        "error": job.get("error", ""),
    }}


@router.get("/api/slam3r/reconstruct/{job_id}/pointcloud")
async def download_pointcloud(job_id: str):
    """Download the PLY point cloud file."""
    job = mast3r_slam_service.get_batch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Job not found"})
    if not job.get("ply_path") or not Path(job["ply_path"]).exists():
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Point cloud not found"})
    return FileResponse(
        str(job["ply_path"]),
        media_type="application/octet-stream",
        filename=f"recon_{job_id}.ply",
    )


@router.get("/api/slam3r/reconstruct/{job_id}/screenshots")
async def download_screenshots(job_id: str):
    """Download screenshots as a zip file."""
    job = mast3r_slam_service.get_batch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Job not found"})
    screenshot_dir = Path(job["output_dir"]) / "screenshots"
    if not screenshot_dir.exists():
        raise HTTPException(status_code=404, detail={"code": 404, "message": "No screenshots found"})

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for png_file in sorted(screenshot_dir.glob("*.png")):
            zf.write(png_file, png_file.name)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=recon_{job_id}_screenshots.zip"},
    )
