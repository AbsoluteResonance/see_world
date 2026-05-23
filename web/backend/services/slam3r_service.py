"""SLAM3R service layer — manages reconstruction jobs and streaming sessions."""

import base64
import io
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from backend.config import settings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # web/../../ → see_world/
for p in [str(_PROJECT_ROOT), str(_PROJECT_ROOT / "SLAM" / "SLAM3R")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# In-memory job store
_jobs: dict[str, dict] = {}
_streams: dict[str, dict] = {}

RECONSTRUCT_DIR = Path(__file__).resolve().parent.parent.parent / "reconstructions"
SLAM3R_DIR = _PROJECT_ROOT / "SLAM" / "SLAM3R"
ROS2_WS_DIR = Path("/root/ros2_ws")
NODE_SCRIPT = ROS2_WS_DIR / "src" / "slam3r_ros" / "slam3r_ros" / "node.py"

# ── Shared SLAM3R model singleton (lazy loaded) ──
_shared_i2p_model = None
_shared_l2w_model = None
_shared_device = None


def _load_models() -> bool:
    """Load SLAM3R models once, reuse across streams."""
    global _shared_i2p_model, _shared_l2w_model, _shared_device
    if _shared_i2p_model is not None:
        return True
    try:
        import torch
        from slam3r.models import Image2PointsModel, Local2WorldModel
        if not torch.cuda.is_available():
            return False
        # Set HF cache to data disk
        hf_cache = settings.slam3r_hf_cache or "/autodl-fs/data/projects/see_world/.hf_cache"
        os.environ.setdefault("HF_HOME", hf_cache)
        _shared_device = "cuda"
        print("[slam3r_service] Loading I2P model...")
        _shared_i2p_model = Image2PointsModel.from_pretrained(settings.slam3r_model_i2p)
        _shared_i2p_model.to(_shared_device)
        _shared_i2p_model.eval()
        print("[slam3r_service] Loading L2W model...")
        _shared_l2w_model = Local2WorldModel.from_pretrained(settings.slam3r_model_l2w)
        _shared_l2w_model.to(_shared_device)
        _shared_l2w_model.eval()
        print("[slam3r_service] SLAM3R models loaded successfully")
        return True
    except Exception as e:
        print(f"[slam3r_service] Failed to load SLAM3R models: {e}")
        return False


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
    models_loaded = _shared_i2p_model is not None
    return {"src_available": has_src, "requirements": has_req,
            "models_loaded": models_loaded,
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


def _extract_frames_from_video(video_path: Path, output_dir: str,
                                frame_skip: int = 10,
                                target_size: tuple = (224, 224)) -> str:
    """Extract frames from video, returns path to frames directory."""
    import cv2
    import numpy as np

    frames_dir = Path(output_dir) / "input_frames"
    rgb_dir = frames_dir / "rgb"
    rgb_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    count = 0
    saved = 0
    entries = []
    t_w, t_h = target_size

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if count % frame_skip == 0:
            h, w = frame.shape[:2]
            scale = min(t_w / w, t_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
            resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            frame_rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            # Pad to target
            padded = np.zeros((t_h, t_w, 3), dtype=np.uint8)
            padded[:new_h, :new_w] = frame_rgb
            timestamp = count / fps
            fname = f"frame_{saved:06d}.png"
            cv2.imwrite(str(rgb_dir / fname), cv2.cvtColor(padded, cv2.COLOR_RGB2BGR))
            entries.append(f"{timestamp:.6f} rgb/{fname}\n")
            saved += 1
        count += 1
    cap.release()

    with open(frames_dir / "rgb.txt", "w") as f:
        f.write("# color images\n")
        f.write(f"# extracted from {video_path.name}\n")
        f.write("# timestamp filename\n")
        f.writelines(entries)

    print(f"[slam3r_service] Extracted {saved} frames from {video_path.name}")
    return str(frames_dir)


def _direct_reconstruct_from_video(video_path: Path, output_dir: str) -> dict:
    """Run SLAM3R directly via Python API (no ROS2 subprocess)."""
    import torch
    output_path = Path(output_dir)

    # Extract frames
    frames_dir = _extract_frames_from_video(video_path, output_dir, frame_skip=10)
    if not frames_dir:
        return {"status": "error", "error": "Frame extraction failed"}

    # Use offline pipeline
    from slam3r.pipeline.recon_offline_pipeline import scene_recon_pipeline_offline
    from slam3r.datasets.wild_seq import Seq_Data

    device = _shared_device or "cuda"
    dataset = Seq_Data(img_dir=frames_dir, img_size=224, to_tensor=True,
                       silent=True, sample_freq=1, start_idx=0,
                       num_views=-1, start_freq=1)
    if hasattr(dataset, "set_epoch"):
        dataset.set_epoch(0)

    import argparse
    args = argparse.Namespace(
        win_r=3, num_scene_frame=10, initial_winsize=5,
        conf_thres_l2w=12, conf_thres_i2p=1.5,
        num_points_save=2000000, keyframe_stride=3,
        norm_input=False, save_frequency=3, save_each_frame=True,
        retrieve_freq=1, update_buffer_intv=1, buffer_size=100,
        buffer_strategy='reservoir', save_online=False,
        save_preds=False, save_for_eval=False, save_all_views=False,
        perframe=1, device=device,
        keyframe_adapt_min=1, keyframe_adapt_max=20,
        keyframe_adapt_stride=1,
    )

    print(f"[slam3r_service] Running offline reconstruction: {frames_dir}")
    scene_recon_pipeline_offline(
        _shared_i2p_model, _shared_l2w_model, dataset, args, str(output_path))

    # Find output PLY
    ply_files = list(output_path.glob("*_recon.ply"))
    ply_path = str(ply_files[0]) if ply_files else ""
    frames_processed = len(dataset[0]) if hasattr(dataset, '__getitem__') else 0

    print(f"[slam3r_service] Reconstruction complete: {ply_path}")
    return {"status": "completed" if ply_path else "error",
            "pointcloud_file": ply_path,
            "poses_file": "",
            "frames_processed": frames_processed}
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

        # Try direct inference first (uses shared models, faster)
        if _shared_i2p_model is not None or _load_models():
            update_job(job_id, status="running", progress=30)
            try:
                result = _direct_reconstruct_from_video(file_path, output_dir)
                completed = result.get("status") == "completed"
                update_job(job_id,
                           status=result.get("status", "error"),
                           pointcloud_file=result.get("pointcloud_file", ""),
                           poses_file=result.get("poses_file", ""),
                           error=result.get("error", ""),
                           progress=100 if completed else 50)
                return _jobs[job_id]
            except Exception as e:
                print(f"[slam3r_service] Direct inference failed, falling back to ROS2 node: {e}")

        # Fallback: Run SLAM3R batch via ROS2 node subprocess
        if not NODE_SCRIPT.exists():
            update_job(job_id, status="failed",
                       error=f"SLAM3R node not found: {NODE_SCRIPT}",
                       progress=0)
            return _jobs[job_id]

        update_job(job_id, status="running", progress=30)
        result = subprocess.run(
            [sys.executable, str(NODE_SCRIPT),
             "--video", str(file_path),
             "--output", output_dir,
             "--frame-skip", "10"],
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
        # Try direct inference first
        if _shared_i2p_model is not None or _load_models():
            try:
                import torch
                from slam3r.pipeline.recon_offline_pipeline import scene_recon_pipeline_offline
                from slam3r.datasets.wild_seq import Seq_Data

                device = _shared_device or "cuda"
                dataset = Seq_Data(img_dir=images_dir, img_size=224, to_tensor=True,
                                   silent=True, sample_freq=1, start_idx=0,
                                   num_views=-1, start_freq=1)

                import argparse
                args = argparse.Namespace(
                    win_r=3, num_scene_frame=10, initial_winsize=5,
                    conf_thres_l2w=12, conf_thres_i2p=1.5,
                    num_points_save=2000000, keyframe_stride=3,
                    norm_input=False, save_frequency=3, save_each_frame=True,
                    retrieve_freq=1, update_buffer_intv=1, buffer_size=100,
                    buffer_strategy='reservoir', save_online=False,
                    save_preds=False, save_for_eval=False, save_all_views=False,
                    perframe=1, device=device,
                    keyframe_adapt_min=1, keyframe_adapt_max=20, keyframe_adapt_stride=1,
                )

                output_path = Path(output_dir)
                scene_recon_pipeline_offline(
                    _shared_i2p_model, _shared_l2w_model, dataset, args, str(output_path))

                ply_files = list(output_path.glob("*_recon.ply"))
                ply_path = str(ply_files[0]) if ply_files else ""
                completed = bool(ply_path)

                update_job(job_id, status="completed" if completed else "error",
                           pointcloud_file=ply_path, poses_file="",
                           progress=100 if completed else 50)
                return _jobs[job_id]
            except Exception as e:
                print(f"[slam3r_service] Direct inference failed: {e}")

        # Fallback: ROS2 node subprocess
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
    Uses real SLAM3R inference when models are loaded, otherwise stub.
    """
    stream = _streams.get(stream_id)
    if not stream:
        return {"error": "Stream not found"}

    stream["frames_received"] += 1
    n = stream["frames_received"]

    # Try to load models on first frame if not already loaded
    use_real = (_shared_i2p_model is not None) or _load_models()

    if use_real:
        try:
            return _real_process_frame(stream_id, image_bytes, timestamp, n)
        except Exception as e:
            print(f"[slam3r_service] Real inference failed, falling back to stub: {e}")

    return _stub_process_frame(stream, n, timestamp)


def _real_process_frame(stream_id: str, image_bytes: bytes, timestamp: float, n: int) -> dict:
    """Run actual SLAM3R inference on a frame."""
    import torch
    import numpy as np
    from PIL import Image
    from slam3r.utils.recon_utils import i2p_inference_batch

    stream = _streams[stream_id]

    # Decode JPEG bytes → RGB tensor (224x224 as required by SLAM3R)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_resized = img.resize((224, 224), Image.LANCZOS)
    img_tensor = torch.from_numpy(np.array(img_resized)).float().permute(2, 0, 1) / 255.0
    true_shape = torch.tensor([[224, 224]], dtype=torch.float32)

    view = {
        'img': img_tensor.unsqueeze(0).to(_shared_device),
        'true_shape': true_shape.to(_shared_device),
        'label': str(n),
    }

    # Buffer the view
    buf = stream.setdefault('_frame_buffer', [])
    buf.append(view)
    if len(buf) > 10:
        buf.pop(0)

    # Only run inference every 3 frames, or when we have enough
    if n < 3 or n % 3 != 0:
        return {
            "type": "cloud_update",
            "timestamp": timestamp,
            "points": [],
            "pose": None,
            "total_points": stream.get("points_total", 0),
            "frame_count": n,
        }

    # Run I2P inference on buffered frames
    with torch.no_grad():
        output = i2p_inference_batch([buf], _shared_i2p_model, ref_id=0,
                                     tocpu=True, unsqueeze=False)
    preds = output['preds']

    # Extract point cloud from reference view
    pts3d = preds[0]['pts3d'].cpu().numpy()  # (1, 224, 224, 3)
    conf = preds[0]['conf'].cpu().numpy()      # (1, 224, 224)

    # Filter by confidence
    valid = (conf[0] > 1.5).reshape(-1)
    h, w = pts3d.shape[1:3]
    pts_flat = pts3d[0].reshape(-1, 3)

    # Filter out zero points (invalid)
    valid = valid & (np.linalg.norm(pts_flat, axis=1) > 0.01)

    valid_pts = pts_flat[valid]

    # Get colors from the input image
    colors = np.array(img_resized).reshape(-1, 3)
    valid_colors = colors[valid]

    # Downsample for bandwidth
    if len(valid_pts) > 3000:
        idx = np.random.choice(len(valid_pts), 3000, replace=False)
        valid_pts = valid_pts[idx]
        valid_colors = valid_colors[idx]

    # Build point list
    points = []
    for i in range(len(valid_pts)):
        points.append([
            round(float(valid_pts[i, 0]), 4),
            round(float(valid_pts[i, 1]), 4),
            round(float(valid_pts[i, 2]), 4),
            int(valid_colors[i, 0]),
            int(valid_colors[i, 1]),
            int(valid_colors[i, 2]),
        ])

    stream["points_total"] += len(points)

    # Stub pose
    pose = [math.sin(n * 0.02) * 0.5, 0.0, math.cos(n * 0.02) * 0.5,
            0.0, 0.0, 0.0, 1.0]

    return {
        "type": "cloud_update",
        "timestamp": timestamp,
        "points": points,
        "pose": pose,
        "total_points": stream.get("points_total", 0),
        "frame_count": n,
    }


def _stub_process_frame(stream, n: int, timestamp: float) -> dict:
    """Generate stub spiral point cloud for testing without GPU."""
    random.seed(n)
    num_points = min(20 + n // 2, 80)
    points = []
    base_angle = n * 0.3
    for i in range(num_points):
        angle = base_angle + i * 0.5
        radius = 0.5 + random.random() * 1.5
        x = math.cos(angle) * radius * 0.5
        z = math.sin(angle) * radius * 0.5
        y = random.random() * 2.0 - 0.5
        r = int((math.sin(angle) * 0.5 + 0.5) * 255)
        g = int((math.cos(angle) * 0.5 + 0.5) * 255)
        b = int((math.sin(base_angle) * 0.5 + 0.5) * 255)
        points.append([round(x, 4), round(y, 4), round(z, 4), r, g, b])

    stream["points_total"] += len(points)

    now = time.time()
    prev_ts = stream.get("_last_timestamp", now)
    stream["_last_timestamp"] = now
    if n > 1 and now - prev_ts > 0:
        fps = 1.0 / (now - prev_ts)
        stream["fps"] = stream.get("fps", fps) * 0.7 + fps * 0.3

    pose = [
        math.sin(n * 0.02) * 1.0, 0.0, math.cos(n * 0.02) * 1.0,
        0.0, 0.0, 0.0, 1.0,
    ]

    return {
        "type": "cloud_update",
        "timestamp": timestamp,
        "points": points,
        "pose": pose,
        "total_points": stream.get("points_total", 0),
        "frame_count": n,
    }
