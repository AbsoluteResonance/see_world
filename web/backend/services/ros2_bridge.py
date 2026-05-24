"""
ROS2 Bridge — unified SLAM communication layer.

Supports two modes (configurable via SEE_WORLD_SLAM_BRIDGE_MODE):
  - "direct" (default): Call Python APIs directly for lowest latency.
  - "ros2": Communicate via ROS2 topics/services — swap SLAM models
            without changing web backend code.

Unified SLAM Interface (ROS2 topics/services under /slam/ namespace):
  Topics:
    /slam/image        sensor_msgs/Image          — input camera frame
    /slam/cloud        sensor_msgs/PointCloud2     — dense point cloud
    /slam/pose         geometry_msgs/PoseStamped   — camera pose
    /slam/status       std_msgs/String             — status (init/tracking/lost)
  Services:
    /slam/start        std_srvs/Trigger            — start reconstruction
    /slam/stop         std_srvs/Trigger            — stop
    /slam/save         std_srvs/Trigger            — save current point cloud
    /slam/reconstruct  std_srvs/Trigger            — offline batch reconstruction

To use ROS2 mode:
  1. export SEE_WORLD_SLAM_BRIDGE_MODE=ros2
  2. Start the SLAM node: python3 slam3r_ros/node.py --serve
  3. Start the web server as usual

To swap models: replace the ROS2 node (same interface, different backend).
"""
import json
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Optional

from backend.config import settings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SLAM3R_NODE = (_PROJECT_ROOT / "ros2_ws" / "src" / "slam3r_ros" /
                "slam3r_ros" / "node.py")
_ROS2_WS = Path(settings.ros2_workspace)


def get_mode() -> str:
    return settings.slam_bridge_mode


# ── Direct mode (default) ──

def _direct_reconstruct_from_file(file_id: str) -> dict:
    from backend.services import slam3r_service
    return slam3r_service.reconstruct_from_file(file_id)


def _direct_reconstruct_from_path(images_dir: str, output_dir: str = "") -> dict:
    from backend.services import slam3r_service
    return slam3r_service.reconstruct_from_path(images_dir, output_dir)


def _direct_process_frame(stream_id: str, image_bytes: bytes, timestamp: float) -> dict:
    from backend.services import slam3r_service
    return slam3r_service.process_frame(stream_id, image_bytes, timestamp)


def _direct_get_job(job_id: str) -> Optional[dict]:
    from backend.services import slam3r_service
    return slam3r_service.get_job(job_id)


def _direct_list_jobs() -> list[dict]:
    from backend.services import slam3r_service
    return slam3r_service.list_jobs()


# ── ROS2 mode ──

def _ros2_service_call(service_name: str, srv_type: str = "std_srvs/srv/Trigger",
                        request: str = "{}") -> dict:
    """Call a ROS2 service via CLI and parse the JSON response."""
    source_cmd = (f". {_ROS2_WS}/install/setup.bash 2>/dev/null || "
                  f". {_ROS2_WS}/devel/setup.bash 2>/dev/null || true")
    full_cmd = f"bash -c '{source_cmd} && ros2 service call {service_name} {srv_type} \"{request}\" --output json 2>&1'"
    try:
        result = subprocess.run(
            ["bash", "-c", full_cmd],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"status": "error", "error": result.stderr[:500]}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "ROS2 service timed out"}
    except json.JSONDecodeError:
        return {"status": "error", "error": f"Invalid ROS2 response: {result.stdout[:200]}"}


def _ros2_is_node_running() -> bool:
    """Check if a SLAM ROS2 node is running."""
    try:
        result = subprocess.run(
            ["bash", "-c", "ros2 node list 2>/dev/null | grep -q slam"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _ros2_reconstruct_from_file(file_id: str) -> dict:
    """Trigger reconstruction via ROS2 service."""
    from backend.services import slam3r_service
    # In ROS2 mode, we still create the job locally but trigger SLAM via ROS2
    job = slam3r_service.create_job()
    job_id = job["job_id"]

    # Find the file
    found = slam3r_service._find_uploaded_file(file_id)
    if not found:
        return {"status": "error", "error": f"File not found: {file_id}"}

    if not _ros2_is_node_running():
        slam3r_service.update_job(job_id, status="failed",
                                  error="SLAM ROS2 node not running. Start with: python3 slam3r_ros/node.py --serve")
        return slam3r_service.get_job(job_id)

    # Call /slam/reconstruct service
    resp = _ros2_service_call("/slam/reconstruct", "std_srvs/srv/Trigger")
    if resp.get("status") == "error":
        slam3r_service.update_job(job_id, status="failed",
                                  error=resp.get("error", "ROS2 service failed"))
        return slam3r_service.get_job(job_id)

    # ROS2 node runs reconstruction; poll for completion
    slam3r_service.update_job(job_id, status="running", progress=30)
    return slam3r_service.get_job(job_id)


def _ros2_reconstruct_from_path(images_dir: str, output_dir: str = "") -> dict:
    """Trigger reconstruction from a frames directory via ROS2."""
    from backend.services import slam3r_service
    job = slam3r_service.create_job(output_dir)
    if not _ros2_is_node_running():
        slam3r_service.update_job(job["job_id"], status="failed",
                                  error="SLAM ROS2 node not running")
        return slam3r_service.get_job(job["job_id"])
    slam3r_service.update_job(job["job_id"], status="running", progress=30)
    return slam3r_service.get_job(job["job_id"])


# ── Public API — dispatches to direct or ROS2 based on config ──

def reconstruct_from_file(file_id: str) -> dict:
    if settings.slam_bridge_mode == "ros2":
        return _ros2_reconstruct_from_file(file_id)
    return _direct_reconstruct_from_file(file_id)


def reconstruct_from_path(images_dir: str, output_dir: str = "") -> dict:
    if settings.slam_bridge_mode == "ros2":
        return _ros2_reconstruct_from_path(images_dir, output_dir)
    return _direct_reconstruct_from_path(images_dir, output_dir)


def process_frame(stream_id: str, image_bytes: bytes, timestamp: float) -> dict:
    return _direct_process_frame(stream_id, image_bytes, timestamp)
    # Note: real-time streaming always uses direct mode for latency reasons.
    # For ROS2-based streaming, run the ROS2 node directly and subscribe to /slam/cloud.


def get_job(job_id: str) -> Optional[dict]:
    from backend.services import slam3r_service
    return slam3r_service.get_job(job_id)


def list_jobs() -> list[dict]:
    from backend.services import slam3r_service
    return slam3r_service.list_jobs()


def create_stream() -> dict:
    from backend.services import slam3r_service
    return slam3r_service.create_stream()


def stop_stream(stream_id: str) -> Optional[dict]:
    from backend.services import slam3r_service
    return slam3r_service.stop_stream(stream_id)


def get_stream(stream_id: str) -> Optional[dict]:
    from backend.services import slam3r_service
    return slam3r_service.get_stream(stream_id)


def check_gpu() -> dict:
    from backend.services import slam3r_service
    return slam3r_service.check_gpu()


def check_slam3r_installed() -> dict:
    from backend.services import slam3r_service
    return slam3r_service.check_slam3r_installed()


# ── MASt3R-SLAM ROS2 Bridge ──

_MAST3R_NODE = str(_PROJECT_ROOT / "ros2_ws" / "src" / "slam3r_ros" /
                   "slam3r_ros" / "mast3r_node.py")
_MAST3R_PYTHON = "/usr/bin/python3.10"  # ROS2 Python
_mast3r_proc: Optional[subprocess.Popen] = None
_mast3r_thread: Optional[threading.Thread] = None
_mast3r_results: list = []


def start_mast3r_bridge() -> bool:
    """Start MASt3R-SLAM ROS2 bridge subprocess (Python 3.10)."""
    global _mast3r_proc, _mast3r_thread

    if _mast3r_proc and _mast3r_proc.poll() is None:
        return True

    try:
        import threading

        env = os.environ.copy()
        # Strip conda from PATH for ROS2 compatibility
        env["PATH"] = "/usr/bin:/bin:" + env.get("PATH", "")
        for key in list(env.keys()):
            if "conda" in key.lower():
                env.pop(key, None)

        _mast3r_proc = subprocess.Popen(
            [_MAST3R_PYTHON, _MAST3R_NODE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, bufsize=1,
            env=env,
        )

        def _read_stdout():
            for line in _mast3r_proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if msg.get("type") in ("cloud", "status", "error"):
                        _mast3r_results.append(msg)
                        if len(_mast3r_results) > 10:
                            _mast3r_results.pop(0)
                except json.JSONDecodeError:
                    pass

        _mast3r_thread = threading.Thread(target=_read_stdout, daemon=True)
        _mast3r_thread.start()
        print(f"[ros2_bridge] MASt3R bridge started (PID {_mast3r_proc.pid})")
        return True
    except Exception as e:
        print(f"[ros2_bridge] MASt3R bridge start failed: {e}")
        return False


def mast3r_send_frame(image_b64: str, timestamp: float):
    """Send a frame to the MASt3R bridge subprocess."""
    global _mast3r_proc
    if _mast3r_proc is None or _mast3r_proc.poll() is not None:
        return
    item = {"type": "frame", "image_base64": image_b64, "timestamp": timestamp,
            "width": 640, "height": 480}
    try:
        _mast3r_proc.stdin.write(json.dumps(item) + "\n")
        _mast3r_proc.stdin.flush()
    except Exception:
        pass


def mast3r_get_latest_result() -> Optional[dict]:
    """Get the latest MASt3R inference result."""
    if _mast3r_results:
        return _mast3r_results[-1]
    return None


def stop_mast3r_bridge():
    """Stop the MASt3R bridge subprocess."""
    global _mast3r_proc
    if _mast3r_proc and _mast3r_proc.poll() is None:
        try:
            _mast3r_proc.stdin.write(json.dumps({"type": "stop"}) + "\n")
            _mast3r_proc.stdin.flush()
        except Exception:
            pass
        _mast3r_proc.wait(timeout=5)
        _mast3r_proc = None
        print("[ros2_bridge] MASt3R bridge stopped")
