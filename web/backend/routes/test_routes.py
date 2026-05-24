"""帧接收测试路由 (独立于 SLAM)"""
from fastapi import APIRouter, HTTPException
import time, base64, io

router = APIRouter()

@router.post("/api/test/frame")
async def test_frame(body: dict):
    """接收一帧，确认收到并返回帧信息。"""
    image_b64 = body.get("image", "")
    ts = body.get("timestamp", 0)
    if not image_b64:
        raise HTTPException(status_code=400, detail="no image")
    raw = base64.b64decode(image_b64)
    size_kb = round(len(raw) / 1024, 1)
    recv_ts = time.time()
    latency = round((recv_ts - ts) * 1000, 1) if ts > 0 else 0
    print(f"[test_frame] rcvd {size_kb}KB, latency={latency}ms")
    return {
        "code": 0,
        "data": {
            "size_kb": size_kb,
            "latency_ms": latency,
            "received": True,
            "server_ts": recv_ts,
            "frame_count": body.get("frame", 0),
        }
    }
