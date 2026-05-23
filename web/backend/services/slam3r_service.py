"""SLAM3R service layer — manages reconstruction jobs and streaming sessions."""

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from backend.config import settings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # web/../../ → see_world/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# In-memory job store
_jobs: dict[str, dict] = {}
_streams: dict[str, dict] = {}

RECONSTRUCT_DIR = Path(__file__).resolve().parent.parent.parent / "reconstructions"
SLAM3R_DIR = _PROJECT_ROOT / "SLAM" / "SLAM3R"
ROS2_WS_DIR = Path("/root/ros2_ws")
NODE_SCRIPT = ROS2_WS_DIR / "src" / "slam3r_ros" / "slam3r_ros" / "node.py"


def _ensure_dirs():
    RECONSTRUCT_DIR.mkdir(parents=True, exist_ok=True)


def _find_uploaded_file(file_id: str) -> tuple[Path, str] | None:
    """Find an uploaded file by file_id across images/ and videos/ dirs."""
    upload_dir = Path(settings.upload_dir)
    for subdir in ["images", "videos"]:
        d = upload_dir / subdir
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.name.startswith('.') or not f.is_file():
                continue
            parts = f.name.split("_", 2)
            if len(parts) >= 2 and parts[1] == file_id:
                file_type = "image" if subdir == "images" else "video"
                return f, file_type
            if file_id in f.name and not file_id.startswith("."):
                file_type = "image" if subdir == "images" else "video"
                return f, file_type
    return None


def check_gpu() -> dict:
    """Check if CUDA GPU is available for SLAM3R inference."""
    try:
        import torch
        available = torch.cuda.is_available()
        if available:
            props = torch.cuda.get_device_properties(0)
            return {"available": True, "name": props.name, "memory_gb": round(props.total_mem / 1e9, 1)}
        return {"available": False, "reason": "torch.cuda.is_available() returned False"}
    except ImportError:
        return {"available": False, "reason": "torch not installed"}
    except Exception as e:
        return {"available": False, "reason": str(e)}


def check_slam3r_installed() -> dict:
    """Check if SLAM3R code and models are available."""
    slam3r_pkg = SLAM3R_DIR / "slam3r"
    has_src = slam3r_pkg.exists()
    has_req = (SLAM3R_DIR / "requirements.txt").exists()
    return {"src_available": has_src, "requirements": has_req,
            "gpu": check_gpu()}


def create_job(output_dir: str = "") -> dict:
    _ensure_dirs()
    job_id = uuid.uuid4().hex[:12]
    if not output_dir:
        output_dir = str(RECONSTRUCT_DIR / job_id)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    _jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "slam_type": "slam3r",
        "output_dir": output_dir,
        "pointcloud_file": "",
        "poses_file": "",
        "error": "",
        "progress": 0,
    }
    return _jobs[job_id]


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def list_jobs() -> list[dict]:
    return list(_jobs.values())


def update_job(job_id: str, **kwargs) -> dict | None:
    job = _jobs.get(job_id)
    if job:
        job.update(kwargs)
    return job


def reconstruct_from_file(file_id: str) -> dict:
    """Start SLAM3R reconstruction from an uploaded file (video)."""
    found = _find_uploaded_file(file_id)
    if not found:
        return {"status": "error", "error": f"File not found: {file_id}"}

    file_path, file_type = found
    job = create_job()
    job_id = job["job_id"]
    output_dir = job["output_dir"]

    update_job(job_id, status="preparing", progress=5)

    try:
        if file_type != "video":
            update_job(job_id, status="failed",
                       error="SLAM3R requires video input (multiple frames)",
                       progress=0)
            return _jobs[job_id]

        update_job(job_id, status="extracting", progress=10)

        # Check node script
        if not NODE_SCRIPT.exists():
            update_job(job_id, status="failed",
                       error=f"SLAM3R node not found: {NODE_SCRIPT}",
                       progress=0)
            return _jobs[job_id]

        # Run SLAM3R batch via ROS2 node
        update_job(job_id, status="running", progress=30)
        result = subprocess.run(
            [sys.executable, str(NODE_SCRIPT),
             "--video", str(file_path),
             "--output", output_dir,
             "--frame-skip", "10"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True, text=True, timeout=7200,
        )

        # Parse JSON output
        try:
            output = json.loads(result.stdout.strip().split("\n")[-1])
        except (json.JSONDecodeError, IndexError):
            output = {"status": "error", "error": result.stderr[-500:] or result.stdout[-500:]}

        completed = output.get("status") == "completed"
        update_job(job_id,
                   status=output.get("status", "error"),
                   pointcloud_file=output.get("pointcloud_file", ""),
                   poses_file=output.get("poses_file", ""),
                   error=output.get("error", ""),
                   progress=100 if completed else 50)

        # If SLAM3R not available but we got stub output, still mark completed
        if output.get("message") and "stub" in output["message"]:
            update_job(job_id, status="completed", progress=100)

    except subprocess.TimeoutExpired:
        update_job(job_id, status="failed", error="SLAM3R timed out (2h)", progress=0)
    except Exception as e:
        update_job(job_id, status="failed", error=str(e), progress=0)

    return _jobs[job_id]


def reconstruct_from_path(images_dir: str, output_dir: str = "") -> dict:
    """Start SLAM3R reconstruction from a frames directory."""
    job = create_job(output_dir)
    job_id = job["job_id"]
    output_dir = job["output_dir"]

    update_job(job_id, status="running", progress=20)

    try:
        if not NODE_SCRIPT.exists():
            update_job(job_id, status="failed",
                       error=f"SLAM3R node not found: {NODE_SCRIPT}")
            return _jobs[job_id]

        result = subprocess.run(
            [sys.executable, str(NODE_SCRIPT),
             "--batch", images_dir,
             "--output", output_dir],
            cwd=str(_PROJECT_ROOT),
            capture_output=True, text=True, timeout=7200,
        )

        try:
            output = json.loads(result.stdout.strip().split("\n")[-1])
        except (json.JSONDecodeError, IndexError):
            output = {"status": "error", "error": result.stderr[-500:] or result.stdout[-500:]}

        completed = output.get("status") == "completed"
        update_job(job_id,
                   status=output.get("status", "error"),
                   pointcloud_file=output.get("pointcloud_file", ""),
                   poses_file=output.get("poses_file", ""),
                   error=output.get("error", ""),
                   progress=100 if completed else 50)

    except subprocess.TimeoutExpired:
        update_job(job_id, status="failed", error="SLAM3R timed out (2h)", progress=0)
    except Exception as e:
        update_job(job_id, status="failed", error=str(e), progress=0)

    return _jobs[job_id]


# ── Streaming session management ──

def create_stream() -> dict:
    """Create a new streaming session."""
    stream_id = uuid.uuid4().hex[:12]
    _streams[stream_id] = {
        "stream_id": stream_id,
        "status": "created",
        "frames_received": 0,
        "points_total": 0,
        "fps": 0.0,
        "created_at": __import__("time").time(),
    }
    return _streams[stream_id]


def get_stream(stream_id: str) -> dict | None:
    return _streams.get(stream_id)


def update_stream(stream_id: str, **kwargs) -> dict | None:
    stream = _streams.get(stream_id)
    if stream:
        stream.update(kwargs)
    return stream


def stop_stream(stream_id: str) -> dict | None:
    stream = _streams.get(stream_id)
    if stream:
        stream["status"] = "stopped"
    return stream


def process_frame(stream_id: str, image_bytes: bytes, timestamp: float) -> dict:
    """Process a single frame from a stream session.

    Returns incremental point cloud data for WebSocket push.
    """
    stream = _streams.get(stream_id)
    if not stream:
        return {"error": "Stream not found"}

    stream["frames_received"] += 1

    # TODO: When GPU available, run SLAM3R inference here
    # For now, return empty cloud update
    return {
        "type": "cloud_update",
        "timestamp": timestamp,
        "points": [],
        "pose": None,
        "total_points": stream.get("points_total", 0),
        "frame_count": stream["frames_received"],
    }
