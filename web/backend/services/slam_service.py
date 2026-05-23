"""Enhanced SLAM service for Web backend."""

import json
import uuid
from pathlib import Path


# In-memory job store (replace with DB for production)
_jobs: dict[str, dict] = {}

RECONSTRUCT_DIR = Path(__file__).resolve().parent.parent.parent / "reconstructions"


def _ensure_dirs():
    RECONSTRUCT_DIR.mkdir(parents=True, exist_ok=True)


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


def run_slam(job_id: str) -> dict:
    """Run SLAM reconstruction for a given job.

    In production this would run in a background thread/process.
    For now, check if ORB-SLAM3 is available and run it.
    """
    job = _jobs.get(job_id)
    if not job:
        return {"status": "error", "error": "Job not found"}

    update_job(job_id, status="running", progress=10)

    try:
        from SLAM.python_interface import SLAMRunner

        runner = SLAMRunner(slam_type="orb_slam3")
        ready = runner.check_ready()

        if not ready["ready"]:
            update_job(job_id, status="failed", error=f"SLAM not ready: {ready}", progress=0)
            return _jobs[job_id]

        settings_yaml = str(Path(job["images_dir"]).parent / "calibration.yaml")
        if not Path(settings_yaml).exists():
            # Try default TUM config
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
