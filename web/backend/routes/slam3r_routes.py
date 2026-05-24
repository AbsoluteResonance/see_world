"""MASt3R-SLAM routes — offline batch and online streaming."""

import json
import base64
import asyncio
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

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
