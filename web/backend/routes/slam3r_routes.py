"""SLAM3R API routes — offline batch and online streaming endpoints."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from backend.config import settings
from backend.services import slam3r_service, ros2_bridge, vins_service, mast3r_slam_service

router = APIRouter()


def _cleanup_stream(stream_id: str):
    """Clean up both slam3r and mast3r-slam sessions."""
    stream = slam3r_service.get_stream(stream_id)
    if stream and stream.get("mode") == "mast3r-slam":
        mast3r_slam_service.destroy_session(stream_id)
    slam3r_service.stop_stream(stream_id)


# ── Health / Status ──

@router.get("/api/slam3r/status")
async def get_slam3r_status():
    """Check SLAM3R availability (GPU, models, etc.)."""
    gpu = slam3r_service.check_gpu()
    installed = slam3r_service.check_slam3r_installed()
    mast3r_avail = mast3r_slam_service.check_available()
    return {
        "code": 0,
        "message": "success",
        "data": {
            "gpu": gpu,
            "slam3r_installed": installed,
            "mast3r_slam": mast3r_avail,
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
    result = ros2_bridge.reconstruct_from_path(images_dir, output_dir)
    return {"code": 0, "message": "success", "data": result}


@router.post("/api/slam3r/reconstruct/from-file/{file_id}")
async def create_reconstruction_from_file(file_id: str):
    """Start SLAM3R reconstruction from an uploaded video file."""
    job = ros2_bridge.reconstruct_from_file(file_id)
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


# ── MASt3R-SLAM HTTP Streaming ──

@router.post("/api/slam3r/mast3r/frame")
async def mast3r_frame(body: dict):
    """Fire-and-forget: send frame, return immediately. No waiting for inference."""
    import base64
    image_b64 = body.get("image", "")
    if not image_b64:
        raise HTTPException(status_code=400, detail={"code": 400, "message": "image required"})

    # Ensure inference subprocess is running (lazy start)
    if not mast3r_slam_service._infer_ready.is_set():
        ok = mast3r_slam_service.start_inference()
        if not ok:
            raise HTTPException(status_code=500, detail={"code": 500, "message": "Inference process failed to start"})

    # Fire and forget - don't wait
    mast3r_slam_service.send_frame(image_b64, body.get("timestamp", 0.0))

    return {"code": 0, "data": {"received": True}}


@router.get("/api/slam3r/mast3r/points")
async def mast3r_points():
    """Get latest point cloud result (separate lightweight call)."""
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
    import time as _time
    _ws_log = lambda msg: print(f"[WS {_time.strftime('%H:%M:%S')}] {msg}")

    try:
        while True:
            raw = await websocket.receive_text()
            _ws_log(f"rcvd {len(raw)}B")
            msg = json.loads(raw)

            if msg.get("type") == "start":
                mode = msg.get("mode", "slam3r")
                _ws_log(f"start mode={mode}")

                if mode == "mast3r-slam":
                    # MASt3R-SLAM mode: create dedicated session
                    mast3r_session = mast3r_slam_service.create_session()
                    if mast3r_session.get("status") == "error":
                        await websocket.send_text(json.dumps({
                            "type": "error", "message": mast3r_session["message"],
                        }))
                        break
                    stream_id = mast3r_session["session_id"]
                    # Also register in slam3r_service for metadata tracking
                    stream = slam3r_service.create_stream()
                    stream["stream_id"] = stream_id
                    stream["mode"] = mode
                    stream["mast3r_session"] = stream_id
                else:
                    stream = slam3r_service.create_stream()
                    stream_id = stream["stream_id"]
                    stream["mode"] = mode

                await websocket.send_text(json.dumps({
                    "type": "stream_started",
                    "stream_id": stream_id,
                    "mode": mode,
                }))

            elif msg.get("type") == "frame" and stream_id:
                timestamp = msg.get("timestamp", 0.0)
                image_b64 = msg.get("image", "")
                import base64
                image_bytes = base64.b64decode(image_b64)

                stream = slam3r_service.get_stream(stream_id)
                if stream is None:
                    stream = {"mode": "mast3r-slam", "frames_received": 0}

                mode = stream.get("mode", "slam3r")
                vins_only = mode == "vins"

                imu_data = None
                if msg.get("acc") and msg.get("gyr"):
                    imu_data = {"acc": msg["acc"], "gyr": msg["gyr"]}
                    if msg.get("timestamp"):
                        imu_data["frame_ts"] = msg["timestamp"]
                    if msg.get("imu_ts"):
                        imu_data["imu_ts"] = msg["imu_ts"]

                if mode == "mast3r-slam":
                    # MASt3R-SLAM streaming inference
                    mast3r_session = mast3r_slam_service.get_session(stream_id)
                    if mast3r_session is None:
                        result = {"type": "error", "message": "MASt3R session not found"}
                    else:
                        _ws_log(f"calling process_frame #{stream.get('frames_received',0)+1}...")
                        result = mast3r_session.process_frame(image_bytes, timestamp)
                        _ws_log(f"process_frame done: status={result.get('status')} pts={result.get('num_points')} ms={result.get('inference_ms')}")
                elif vins_only:
                    # VINS-Mono mode: forward frame+IMU to ROS2, run SGBM dense mapping
                    stream["frames_received"] = stream.get("frames_received", 0) + 1
                    result = {
                        "type": "cloud_update",
                        "timestamp": timestamp,
                        "points": [],
                        "total_points": 0,
                        "frame_count": stream["frames_received"],
                    }
                    if imu_data:
                        vins_service.forward_frame_to_vins(image_b64, timestamp,
                                                           imu_data["acc"], imu_data["gyr"])
                        result["has_imu"] = True
                    vins_service.buffer_frame_for_sgbm(image_b64, timestamp)
                    sgbm = vins_service.try_sgbm_dense()
                    if sgbm:
                        result["points"] = sgbm["points"]
                        result["total_points"] = len(sgbm["points"])
                        result["baseline"] = sgbm["baseline"]
                else:
                    # SLAM3R mode: full inference + point cloud
                    result = slam3r_service.process_frame(stream_id, image_bytes, timestamp, imu_data)
                    if imu_data:
                        vins_service.forward_frame_to_vins(image_b64, timestamp,
                                                           imu_data["acc"], imu_data["gyr"])

                # Attach latest VINS pose if available
                vins_pose = vins_service.get_vins_pose()
                if vins_pose:
                    result["vins_pose"] = vins_pose

                _ws_log(f"sending response type={result.get('type')} len={len(result.get('points',[]))}")
                await websocket.send_text(json.dumps(result))

            elif msg.get("type") == "stop" and stream_id:
                stream = slam3r_service.get_stream(stream_id)
                if stream and stream.get("mode") == "mast3r-slam":
                    mast3r_slam_service.destroy_session(stream_id)
                slam3r_service.stop_stream(stream_id)
                await websocket.send_text(json.dumps({
                    "type": "stream_stopped",
                    "stream_id": stream_id,
                }))
                break

    except WebSocketDisconnect:
        _ws_log("disconnected")
        if stream_id:
            _cleanup_stream(stream_id)
    except Exception as e:
        _ws_log(f"error: {e}")
        if stream_id:
            _cleanup_stream(stream_id)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except RuntimeError:
            pass
