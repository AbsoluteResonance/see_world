"""SLAM3R API routes — offline batch and online streaming endpoints."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from backend.config import settings
from backend.services import slam3r_service

router = APIRouter()


# ── Health / Status ──

@router.get("/api/slam3r/status")
async def get_slam3r_status():
    """Check SLAM3R availability (GPU, models, etc.)."""
    gpu = slam3r_service.check_gpu()
    installed = slam3r_service.check_slam3r_installed()
    return {
        "code": 0,
        "message": "success",
        "data": {
            "gpu": gpu,
            "slam3r_installed": installed,
            "ready": gpu.get("available", False) and installed.get("src_available", False),
        },
    }


# ── Offline Batch Reconstruction ──

@router.post("/api/slam3r/reconstruct")
async def create_reconstruction(body: dict):
    """Start SLAM3R reconstruction from a frames directory.

    Request:
    {
        "images_dir": "/path/to/frames",
        "output_dir": "/path/to/output" (optional)
    }
    """
    images_dir = body.get("images_dir", "")
    if not images_dir:
        raise HTTPException(status_code=400, detail={"code": 40001, "message": "images_dir is required"})
    if not Path(images_dir).exists():
        raise HTTPException(status_code=400, detail={"code": 40001, "message": f"images_dir not found: {images_dir}"})

    output_dir = body.get("output_dir", "")
    result = slam3r_service.reconstruct_from_path(images_dir, output_dir)
    return {"code": 0, "message": "success", "data": result}


@router.post("/api/slam3r/reconstruct/from-file/{file_id}")
async def create_reconstruction_from_file(file_id: str):
    """Start SLAM3R reconstruction from an uploaded video file."""
    job = slam3r_service.reconstruct_from_file(file_id)
    if job.get("status") in ("error", "failed"):
        err_msg = job.get("error", "Unknown error") or "Unknown error"
        raise HTTPException(status_code=400, detail={"code": 40001, "message": err_msg})
    return {"code": 0, "message": "success", "data": job}


@router.get("/api/slam3r/reconstruct/{job_id}")
async def get_reconstruction_status(job_id: str):
    """Get SLAM3R reconstruction job status."""
    job = slam3r_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Job not found"})
    return {"code": 0, "message": "success", "data": job}


@router.get("/api/slam3r/reconstruct/{job_id}/pointcloud")
async def download_pointcloud(job_id: str):
    """Download SLAM3R dense point cloud PLY file."""
    job = slam3r_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Job not found"})
    if not job.get("pointcloud_file") or not Path(job["pointcloud_file"]).exists():
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Point cloud not available"})
    return FileResponse(job["pointcloud_file"])


@router.get("/api/slam3r/reconstruct/{job_id}/poses")
async def download_poses(job_id: str):
    """Download SLAM3R camera poses JSON."""
    job = slam3r_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Job not found"})
    if not job.get("poses_file") or not Path(job["poses_file"]).exists():
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Poses not available"})
    return FileResponse(job["poses_file"])


@router.get("/api/slam3r/reconstruct")
async def list_reconstructions():
    """List all SLAM3R reconstruction jobs."""
    jobs = slam3r_service.list_jobs()
    return {"code": 0, "message": "success", "data": jobs}


# ── Online Streaming ──

@router.post("/api/slam3r/stream/start")
async def start_stream():
    """Start a real-time SLAM3R streaming session."""
    stream = slam3r_service.create_stream()
    return {"code": 0, "message": "success", "data": stream}


@router.get("/api/slam3r/stream/{stream_id}/status")
async def get_stream_status(stream_id: str):
    """Get streaming session status."""
    stream = slam3r_service.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Stream not found"})
    return {"code": 0, "message": "success", "data": stream}


@router.post("/api/slam3r/stream/{stream_id}/stop")
async def stop_stream(stream_id: str):
    """Stop a streaming session."""
    stream = slam3r_service.stop_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Stream not found"})
    return {"code": 0, "message": "success", "data": stream}


@router.websocket("/ws/slam3r/stream")
async def websocket_stream(websocket: WebSocket):
    """WebSocket endpoint for real-time frame streaming.

    Client sends:
    {
        "type": "frame",
        "stream_id": "abc123",
        "timestamp": 1716480000.123,
        "image": "<base64 jpeg>",
        "resolution": {"width": 640, "height": 480}
    }

    Server responds:
    {
        "type": "cloud_update",
        "timestamp": 1716480000.456,
        "points": [[x,y,z,r,g,b], ...],
        "pose": [tx, ty, tz, qx, qy, qz, qw],
        "total_points": 1234567,
        "frame_count": 42
    }
    """
    await websocket.accept()
    stream_id = None

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "start":
                # Create a new stream session
                stream = slam3r_service.create_stream()
                stream_id = stream["stream_id"]
                await websocket.send_text(json.dumps({
                    "type": "stream_started",
                    "stream_id": stream_id,
                }))

            elif msg.get("type") == "frame" and stream_id:
                timestamp = msg.get("timestamp", 0.0)
                image_b64 = msg.get("image", "")
                import base64
                image_bytes = base64.b64decode(image_b64)

                result = slam3r_service.process_frame(stream_id, image_bytes, timestamp)
                await websocket.send_text(json.dumps(result))

            elif msg.get("type") == "stop" and stream_id:
                slam3r_service.stop_stream(stream_id)
                await websocket.send_text(json.dumps({
                    "type": "stream_stopped",
                    "stream_id": stream_id,
                }))
                break

    except WebSocketDisconnect:
        if stream_id:
            slam3r_service.stop_stream(stream_id)
    except Exception as e:
        if stream_id:
            slam3r_service.stop_stream(stream_id)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except RuntimeError:
            pass
