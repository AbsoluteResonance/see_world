"""MASt3R-SLAM service — inference via standalone subprocess (stdin/stdout JSON)."""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_MAST3R_SLAM_DIR = _PROJECT_ROOT / "SLAM" / "MASt3R-SLAM"
_INFER_SCRIPT = (_PROJECT_ROOT / "ros2_ws" / "src" / "slam3r_ros" /
                  "slam3r_ros" / "mast3r_infer_standalone.py")
_SLAM3R_PYTHON = "/root/miniconda3/envs/slam3r/bin/python3.11"

_infer_proc: Optional[subprocess.Popen] = None
_infer_results: list = []
_infer_lock = threading.Lock()
_infer_ready = threading.Event()


def start_inference() -> bool:
    """Start the MASt3R inference subprocess (Python 3.11)."""
    global _infer_proc
    if _infer_proc and _infer_proc.poll() is None:
        return True
    try:
        env = os.environ.copy()
        _infer_proc = subprocess.Popen(
            [_SLAM3R_PYTHON, str(_INFER_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, bufsize=1,
            env=env,
        )

        # Thread: read stderr (inference logs)
        def _read_stderr():
            for line in _infer_proc.stderr:
                line = line.strip()
                if line:
                    print(f"[infer] {line}")
        threading.Thread(target=_read_stderr, daemon=True).start()

        # Thread: read stdout (JSON results)
        def _read_stdout():
            for line in _infer_proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    with _infer_lock:
                        _infer_results.append(msg)
                        if len(_infer_results) > 10:
                            _infer_results.pop(0)
                except json.JSONDecodeError:
                    pass
        threading.Thread(target=_read_stdout, daemon=True).start()

        # Wait for ready signal
        for _ in range(120):
            if _infer_proc.poll() is not None:
                break
            # Check if it printed something on stderr (model loaded)
            time.sleep(0.5)
            if _infer_results:
                break

        alive = _infer_proc.poll() is None
        if alive:
            _infer_ready.set()
            print(f"[mast3r_service] Inference subprocess started (PID {_infer_proc.pid})")
        else:
            print(f"[mast3r_service] Inference subprocess exited: {_infer_proc.returncode}")
        return alive
    except Exception as e:
        print(f"[mast3r_service] Failed to start inference: {e}")
        return False


def send_frame(image_b64: str, timestamp: float, max_points: int = 500):
    """Send a frame to the inference subprocess."""
    global _infer_proc
    _infer_ready.wait(timeout=120)
    if _infer_proc and _infer_proc.poll() is None:
        msg = json.dumps({"type": "frame", "image_base64": image_b64, "timestamp": timestamp, "max_points": max_points})
        try:
            _infer_proc.stdin.write(msg + "\n")
            _infer_proc.stdin.flush()
        except BrokenPipeError:
            print("[mast3r_service] Broken pipe, restarting...")
            start_inference()


def get_result() -> Optional[dict]:
    """Get the latest inference result."""
    with _infer_lock:
        if _infer_results:
            return _infer_results[-1]
    return None


def stop_inference():
    """Stop the inference subprocess."""
    global _infer_proc
    if _infer_proc and _infer_proc.poll() is None:
        try:
            _infer_proc.stdin.write(json.dumps({"type": "stop"}) + "\n")
            _infer_proc.stdin.flush()
        except Exception:
            pass
        try:
            _infer_proc.wait(timeout=5)
        except Exception:
            _infer_proc.kill()
        _infer_proc = None
        print("[mast3r_service] Inference stopped")


def check_available() -> dict:
    """Check if MASt3R-SLAM is available."""
    try:
        import torch
        gpu_ok = torch.cuda.is_available()
        proc_ok = _infer_proc is not None and _infer_proc.poll() is None
        return {"available": gpu_ok and proc_ok,
                "gpu": torch.cuda.get_device_name(0) if gpu_ok else None,
                "running": proc_ok}
    except Exception as e:
        return {"available": False, "error": str(e)}


# Session management (kept for compatibility with routes)
_sessions = {}

def create_session() -> dict:
    session_id = f"mast3r_{int(time.time())}"
    ok = start_inference()
    _sessions[session_id] = {"session_id": session_id, "status": "running" if ok else "error"}
    return _sessions[session_id]

def get_session(session_id: str) -> Optional[dict]:
    return _sessions.get(session_id)

def destroy_session(session_id: str):
    _sessions.pop(session_id, None)
    stop_inference()


# ── Batch offline reconstruction ──

import uuid

_BATCH_SCRIPT = (_PROJECT_ROOT / "ros2_ws" / "src" / "slam3r_ros" /
                  "slam3r_ros" / "mast3r_batch_standalone.py")
_RECONSTRUCTIONS_DIR = Path(__file__).resolve().parent.parent.parent / "reconstructions"
_batch_jobs: dict[str, dict] = {}


def create_batch_job(video_path: str) -> dict:
    """Create a batch reconstruction job from a video file."""
    job_id = uuid.uuid4().hex[:12]
    output_dir = _RECONSTRUCTIONS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    job = {
        "job_id": job_id,
        "status": "pending",
        "video_path": str(video_path),
        "output_dir": str(output_dir),
        "ply_path": "",
        "num_points": 0,
        "num_frames": 0,
        "screenshots": [],
        "progress": 0,
        "progress_message": "",
        "error": "",
    }
    _batch_jobs[job_id] = job
    return job


def start_batch_job(job_id: str) -> bool:
    """Launch the batch reconstruction subprocess."""
    job = _batch_jobs.get(job_id)
    if not job:
        return False

    job["status"] = "extracting"

    config = {
        "type": "start",
        "video_path": job["video_path"],
        "output_dir": job["output_dir"],
        "max_frames": 200,
        "frame_skip": 10,
        "max_points_per_frame": 1000,
        "conf_threshold": 1.5,
        "img_size": 512,
    }

    try:
        proc = subprocess.Popen(
            [_SLAM3R_PYTHON, str(_BATCH_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        proc.stdin.write(json.dumps(config) + "\n")
        proc.stdin.flush()

        def _monitor():
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = msg.get("type", "")
                if t == "progress":
                    job["progress"] = msg.get("current", 0)
                    total = msg.get("total", 1)
                    if total > 0:
                        job["progress"] = int(msg.get("current", 0) / total * 100)
                    job["progress_message"] = msg.get("message", "")
                elif t == "result":
                    job["ply_path"] = msg.get("ply_path", "")
                    job["num_points"] = msg.get("num_points", 0)
                    job["num_frames"] = msg.get("num_frames", 0)
                    job["screenshots"] = msg.get("screenshots", [])
                elif t == "error":
                    job["status"] = "failed"
                    job["error"] = msg.get("message", "")
                elif t == "done":
                    if job["status"] != "failed":
                        job["status"] = "completed"
            # Process ended
            if job["status"] not in ("completed", "failed"):
                job["status"] = "failed"
                job["error"] = job.get("error") or "Process exited unexpectedly"

        threading.Thread(target=_monitor, daemon=True).start()

        def _read_stderr():
            for line in proc.stderr:
                line = line.strip()
                if line:
                    print(f"[batch:{job_id}] {line}")

        threading.Thread(target=_read_stderr, daemon=True).start()

        job["proc"] = proc
        return True
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        return False


def get_batch_job(job_id: str) -> dict | None:
    return _batch_jobs.get(job_id)
