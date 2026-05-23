"""Enhanced SLAM service for Web backend — supports file-based reconstruction."""

import json
import os
import subprocess
import sys
import uuid
import shutil
from pathlib import Path

from backend.config import settings

# Add project root for SLAM module imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # web/../../ → see_world/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# In-memory job store (replace with DB for production)
_jobs: dict[str, dict] = {}

RECONSTRUCT_DIR = Path(__file__).resolve().parent.parent.parent / "reconstructions"
ORB_SLAM3_DIR = Path("/root/autodl-fs/projects/see_world/SLAM/ORB_SLAM3")
ROS2_WS_DIR = Path("/root/ros2_ws")


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
            # file_id is the UUID portion of filename (format: {ts}_{uuid8}_{name})
            parts = f.name.split("_", 2)
            if len(parts) >= 2 and parts[1] == file_id:
                file_type = "image" if subdir == "images" else "video"
                return f, file_type
            # Also match against the full file_id if it wasn't split
            if file_id in f.name and not file_id.startswith("."):
                file_type = "image" if subdir == "images" else "video"
                return f, file_type
    return None


def _extract_frames(video_path: Path, output_dir: Path, frame_skip: int = 10,
                    target_size: tuple[int, int] = (640, 480)) -> int:
    """Extract frames, resizing to target_size with aspect-ratio-preserving letterbox.

    Creates:
        output_dir/frames/rgb/          — extracted frame images
        output_dir/frames/rgb.txt        — TUM-format timestamp index
    Returns frame count.
    """
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0

    t_w, t_h = target_size
    count = 0
    saved = 0
    base_dir = output_dir / "frames"
    rgb_dir = base_dir / "rgb"
    rgb_dir.mkdir(parents=True, exist_ok=True)
    entries = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if count % frame_skip == 0:
            h, w = frame.shape[:2]
            # Resize with letterbox to target size (preserve aspect ratio)
            if (w, h) != (t_w, t_h):
                scale = min(t_w / w, t_h / h)
                new_w, new_h = int(w * scale), int(h * scale)
                resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                # Letterbox (add black bars)
                frame = cv2.copyMakeBorder(
                    resized, 0, t_h - new_h, 0, t_w - new_w,
                    cv2.BORDER_CONSTANT, value=(0, 0, 0)
                )
            timestamp = count / fps
            fname = f"frame_{saved:06d}.png"
            cv2.imwrite(str(rgb_dir / fname), frame)
            entries.append(f"{timestamp:.6f} rgb/{fname}\n")
            saved += 1
        count += 1

    cap.release()

    with open(base_dir / "rgb.txt", "w") as f:
        f.write("# color images\n")
        f.write(f"# extracted from {video_path.name}\n")
        f.write("# timestamp filename\n")
        for entry in entries:
            f.write(entry)

    return saved


def _scale_calibration_yaml(orig_yaml: Path, orig_size: tuple[int, int],
                            new_size: tuple[int, int], output_yaml: Path) -> str:
    """Scale camera intrinsics from original resolution to new resolution.

    Returns path to the scaled YAML.
    """
    import cv2
    fs = cv2.FileStorage(str(orig_yaml), cv2.FILE_STORAGE_READ)
    calib = {}
    for key in ("Camera.fx", "Camera.fy", "Camera.cx", "Camera.cy",
                "Camera.k1", "Camera.k2", "Camera.p1", "Camera.p2"):
        node = fs.getNode(key)
        calib[key] = node.real() if not node.empty() else 0.0
    fs.release()

    orig_w, orig_h = orig_size
    new_w, new_h = new_size
    sx = new_w / orig_w
    sy = new_h / orig_h

    content = f"""%YAML:1.0

# Camera calibration - scaled from {orig_w}x{orig_h} to {new_w}x{new_h}
Camera.type: "PinHole"
Camera.width: {new_w}
Camera.height: {new_h}
Camera.fx: {calib['Camera.fx'] * sx:.7f}
Camera.fy: {calib['Camera.fy'] * sy:.7f}
Camera.cx: {calib['Camera.cx'] * sx:.7f}
Camera.cy: {calib['Camera.cy'] * sy:.7f}
Camera.k1: {calib['Camera.k1']:.8f}
Camera.k2: {calib['Camera.k2']:.8f}
Camera.p1: {calib['Camera.p1']:.8f}
Camera.p2: {calib['Camera.p2']:.8f}
Camera.fps: 30.0
Camera.RGB: 1
ORBextractor.nFeatures: 1200
ORBextractor.scaleFactor: 1.2
ORBextractor.nLevels: 8
ORBextractor.iniThFAST: 20
ORBextractor.minThFAST: 7
Viewer.KeyFrameSize: 0.05
Viewer.KeyFrameLineWidth: 1.0
Viewer.GraphLineWidth: 0.9
Viewer.PointSize: 2.0
Viewer.CameraSize: 0.08
Viewer.CameraLineWidth: 3.0
Viewer.ViewpointX: 0.0
Viewer.ViewpointY: -0.7
Viewer.ViewpointZ: -1.8
Viewer.ViewpointF: 500.0
"""
    output_yaml.parent.mkdir(parents=True, exist_ok=True)
    output_yaml.write_text(content)
    return str(output_yaml)


def _run_orb_slam3_ros(images_dir: str, settings_yaml: str,
                        output_dir: Path) -> dict:
    """Run ORB-SLAM3 via orb_slam3_ros batch mode (ROS2 bridge).

    Calls the Python node directly — no rclpy needed in server process.
    Returns dict with status/trajectory_file/error.
    """
    node_script = str(ROS2_WS_DIR / "src" / "orb_slam3_ros" / "orb_slam3_ros" / "node.py")
    if not Path(node_script).exists():
        return {"status": "error", "error": f"ROS2 node not found: {node_script}"}

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [sys.executable, node_script,
             "--batch", images_dir,
             "--settings", settings_yaml,
             "--output", str(output_dir)],
            cwd=str(ORB_SLAM3_DIR),
            capture_output=True, text=True, timeout=3600,
        )

        traj_dst = output_dir / "KeyFrameTrajectory.txt"
        ok = traj_dst.exists() and traj_dst.stat().st_size > 0

        if ok:
            return {"status": "completed", "trajectory_file": str(traj_dst),
                    "stdout": result.stdout, "stderr": result.stderr}

        err = result.stderr or result.stdout or ""
        if "Segmentation fault" in err:
            err = "SLAM crashed (segfault) — check calibration"
        return {"status": "error", "error": err[:300].strip() or f"Exit {result.returncode}",
                "trajectory_file": str(traj_dst) if traj_dst.exists() else ""}

    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "SLAM timed out (1h)"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def create_job(images_dir: str, output_dir: str = "") -> dict:
    """Create a reconstruction job and return its ID."""
    _ensure_dirs()
    job_id = uuid.uuid4().hex[:12]

    if not output_dir:
        output_dir = str(RECONSTRUCT_DIR / job_id)

    _jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "images_dir": images_dir,
        "output_dir": output_dir,
        "slam_type": "orb_slam3",
        "trajectory_file": "",
        "pointcloud_file": "",
        "dense_pointcloud_file": "",
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
    """Start reconstruction from an uploaded file (video or image)."""
    found = _find_uploaded_file(file_id)
    if not found:
        return {"status": "error", "error": f"File not found: {file_id}"}

    file_path, file_type = found

    # Create job
    job = create_job(str(file_path.parent))
    job_id = job["job_id"]
    output_dir = job["output_dir"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    update_job(job_id, status="preparing", progress=5)

    try:
        frame_size = None
        if file_type == "video":
            update_job(job_id, status="extracting", progress=10)
            frames_count = _extract_frames(file_path, Path(output_dir))
            if frames_count < 10:
                update_job(job_id, status="failed",
                           error=f"Too few frames extracted ({frames_count})",
                           progress=0)
                return _jobs[job_id]
            images_dir = str(Path(output_dir) / "frames")
            # Detect frame dimensions from first extracted frame
            import cv2
            first_frame = sorted(Path(images_dir).glob("rgb/frame_*.png"))
            if first_frame:
                img = cv2.imread(str(first_frame[0]))
                if img is not None:
                    frame_size = (img.shape[1], img.shape[0])  # (w, h)
        else:
            # Single image — copy to frames dir for SLAM consistency
            frames_dir = Path(output_dir) / "frames"
            rgb_dir = frames_dir / "rgb"
            rgb_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(file_path), str(rgb_dir / file_path.name))
            with open(frames_dir / "rgb.txt", "w") as f:
                f.write("# color images\n")
                f.write(f"# single image\n")
                f.write(f"0.0 rgb/{file_path.name}\n")
            images_dir = str(frames_dir)
            # Detect frame size from original image
            import cv2
            img = cv2.imread(str(file_path))
            if img is not None:
                frame_size = (img.shape[1], img.shape[0])

        update_job(job_id, images_dir=images_dir, status="running", progress=20)

        # Generate scaled calibration YAML matching 640x480
        calib_src = Path(ORB_SLAM3_DIR) / "Examples" / "Monocular" / "phone_calibration.yaml"
        scaled_yaml = str(Path(output_dir) / "calibration_scaled.yaml")
        if calib_src.exists():
            with open(calib_src) as f:
                calib_text = f.read()
            import re
            def g(k): m = re.search(rf'^{k}:\s*([\d.eE+-]+)', calib_text, re.MULTILINE); return float(m.group(1)) if m else None
            cw, ch = int(g('Camera.width') or 3072), int(g('Camera.height') or 4096)
            scaled_yaml = _scale_calibration_yaml(calib_src, (cw, ch), (640, 480), Path(scaled_yaml))

        update_job(job_id, progress=30)

        # Run SLAM via ROS2 orb_slam3_ros node (batch mode)
        slam_output_dir = Path(output_dir) / "slam_output"
        slam_output_dir.mkdir(parents=True, exist_ok=True)
        result = _run_orb_slam3_ros(images_dir, scaled_yaml, slam_output_dir)

        completed = result["status"] == "completed"
        traj_file = result.get("trajectory_file", "")

        # Generate colored point cloud from trajectory
        ply_file = ""
        scaled_yaml_path = str(Path(output_dir) / "calibration_scaled.yaml")
        if completed and traj_file and Path(traj_file).stat().st_size > 0:
            try:
                from SLAM.ORB_SLAM3.python.pointcloud import build_pointcloud
                ply_path = str(Path(output_dir) / "pointcloud.ply")
                ply_file = build_pointcloud(
                    images_dir, traj_file, ply_path,
                    calibration_yaml=scaled_yaml_path if Path(scaled_yaml_path).exists() else None
                )
            except Exception as e:
                print(f"[slam] Point cloud generation failed: {e}")

        update_job(job_id,
                   status=result["status"],
                   trajectory_file=traj_file,
                   pointcloud_file=ply_file,
                   error=result.get("error", ""),
                   progress=100 if completed else 50)

    except Exception as e:
        update_job(job_id, status="failed", error=str(e), progress=0)

    return _jobs[job_id]


def generate_dense_pointcloud(job_id: str) -> dict:
    """Run dense point cloud generation on a completed SLAM job."""
    job = get_job(job_id)
    if not job:
        return {"status": "error", "error": "Job not found"}

    traj_file = job.get("trajectory_file", "")
    images_dir = job.get("images_dir", "")
    output_dir = job.get("output_dir", "")

    if not traj_file or not Path(traj_file).exists():
        return {"status": "error", "error": "Trajectory file not available. Run SLAM first."}

    scaled_yaml = str(Path(output_dir) / "calibration_scaled.yaml")
    if not Path(scaled_yaml).exists():
        return {"status": "error", "error": "Calibration YAML not found."}

    update_job(job_id, status="dense", progress=50)
    try:
        from SLAM.ORB_SLAM3.python.dense_mapping import build_dense_pointcloud
        output_ply = str(Path(output_dir) / "dense_pointcloud.ply")
        result = build_dense_pointcloud(images_dir, traj_file, scaled_yaml, output_ply)
        if result:
            update_job(job_id, dense_pointcloud_file=result, progress=100)
            return {"status": "completed", "dense_pointcloud_file": result}
        else:
            update_job(job_id, status="completed", error="Dense mapping returned no points")
            return {"status": "completed", "dense_pointcloud_file": ""}
    except Exception as e:
        update_job(job_id, status="error", error=str(e))
        return {"status": "error", "error": str(e)}


def run_slam(job_id: str) -> dict:
    """Run SLAM reconstruction for a given job (legacy path-based API)."""
    job = _jobs.get(job_id)
    if not job:
        return {"status": "error", "error": "Job not found"}

    update_job(job_id, status="running", progress=10)

    try:
        from SLAM.ORB_SLAM3.python import SLAMRunner

        runner = SLAMRunner(slam_type="orb_slam3")
        ready = runner.check_ready(job["images_dir"])

        if not ready["ready"]:
            update_job(job_id, status="failed", error=f"SLAM not ready: {ready}", progress=0)
            return _jobs[job_id]

        settings_yaml = str(Path(job["images_dir"]).parent / "calibration.yaml")
        if not Path(settings_yaml).exists():
            settings_yaml = str(Path(runner.workspace) / "ORB_SLAM3" / "Examples" / "Monocular" / "TUM1.yaml")

        runner.settings_path = settings_yaml
        result = runner.run(job["images_dir"], job["output_dir"])
        update_job(job_id,
                   status=result["status"],
                   trajectory_file=result.get("trajectory_file", ""),
                   pointcloud_file=result.get("pointcloud_file", ""),
                   error=result.get("error", ""),
                   progress=100 if result["status"] == "completed" else 50)
    except ImportError as e:
        update_job(job_id, status="failed", error=f"SLAM module not available: {e}", progress=0)
    except Exception as e:
        update_job(job_id, status="failed", error=str(e), progress=0)

    return _jobs[job_id]
