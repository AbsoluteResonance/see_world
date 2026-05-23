"""Enhanced SLAM service for Web backend — supports file-based reconstruction."""

import json
import uuid
import shutil
from pathlib import Path

from backend.config import settings


# In-memory job store (replace with DB for production)
_jobs: dict[str, dict] = {}

RECONSTRUCT_DIR = Path(__file__).resolve().parent.parent.parent / "reconstructions"


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
                    target_size: tuple | None = (640, 480)) -> int:
    """Extract frames from video using OpenCV into TUM-format directory.

    Resizes large frames to 640x480 for ORB-SLAM3 compatibility.
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
            # Resize large frames to target size for SLAM compatibility
            if target_size and (frame.shape[1] > target_size[0] or frame.shape[0] > target_size[1]):
                frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)
            timestamp = count / fps
            fname = f"frame_{saved:06d}.png"
            cv2.imwrite(str(rgb_dir / fname), frame)
            # TUM format: timestamp filename
            entries.append(f"{timestamp:.6f} rgb/{fname}\n")
            saved += 1
        count += 1

    cap.release()

    # Write rgb.txt in TUM format (mono_tum expects exactly 3 header lines)
    with open(base_dir / "rgb.txt", "w") as f:
        f.write("# color images\n")
        f.write(f"# extracted from {video_path.name}\n")
        f.write("# timestamp filename\n")
        for entry in entries:
            f.write(entry)

    return saved


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
        if file_type == "video":
            update_job(job_id, status="extracting", progress=10)
            frames_count = _extract_frames(file_path, Path(output_dir))
            if frames_count < 10:
                update_job(job_id, status="failed",
                           error=f"Too few frames extracted ({frames_count})",
                           progress=0)
                return _jobs[job_id]
            images_dir = str(Path(output_dir) / "frames")
        else:
            # Single image — copy to frames dir for SLAM consistency
            frames_dir = Path(output_dir) / "frames"
            rgb_dir = frames_dir / "rgb"
            rgb_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(file_path), str(rgb_dir / file_path.name))
            # Write minimal rgb.txt (exactly 3 header lines)
            with open(frames_dir / "rgb.txt", "w") as f:
                f.write("# color images\n")
                f.write(f"# single image\n")
                f.write(f"0.0 rgb/{file_path.name}\n")
            images_dir = str(frames_dir)

        update_job(job_id, images_dir=images_dir, status="running", progress=20)

        # Run SLAM via Python interface
        from SLAM.ORB_SLAM3.python import SLAMRunner
        runner = SLAMRunner(slam_type="orb_slam3")
        ready = runner.check_ready(images_dir)

        if not ready["ready"]:
            update_job(job_id, status="failed",
                       error=f"SLAM not ready: {ready}", progress=0)
            return _jobs[job_id]

        update_job(job_id, progress=30)
        result = runner.run(images_dir, str(Path(output_dir) / "slam_output"))

        completed = result["status"] == "completed"
        traj_file = result.get("trajectory_file", "")

        # Generate colored point cloud from trajectory
        ply_file = ""
        if completed and traj_file and Path(traj_file).stat().st_size > 0:
            try:
                from SLAM.ORB_SLAM3.python.pointcloud import build_pointcloud
                ply_path = str(Path(output_dir) / "pointcloud.ply")
                ply_file = build_pointcloud(images_dir, traj_file, ply_path)
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
