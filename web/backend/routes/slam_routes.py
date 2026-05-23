"""SLAM reconstruction API routes."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.config import settings
from backend.services import slam_service

router = APIRouter()


@router.post("/api/reconstruct")
async def create_reconstruction(body: dict):
    """Start a new reconstruction job.

    Request body:
    {
        "images_dir": "/path/to/images",
        "output_dir": "/path/to/output"  (optional)
    }
    """
    images_dir = body.get("images_dir", "")
    if not images_dir:
        raise HTTPException(status_code=400, detail={"code": 40001, "message": "images_dir is required"})

    if not Path(images_dir).exists():
        raise HTTPException(status_code=400, detail={"code": 40001, "message": f"images_dir not found: {images_dir}"})

    output_dir = body.get("output_dir", "")
    job = slam_service.create_job(images_dir, output_dir)

    # Run in foreground for now (async/background in production)
    result = slam_service.run_slam(job["job_id"])

    return {"code": 0, "message": "success", "data": result}


@router.post("/api/reconstruct/from-file/{file_id}")
async def create_reconstruction_from_file(file_id: str):
    """Start a reconstruction job from an uploaded file (video or image).

    The file must have been uploaded via /api/upload/image or /api/upload/video.
    Videos are automatically split into frames before running SLAM.
    """
    job = slam_service.reconstruct_from_file(file_id)
    if job.get("status") in ("error", "failed"):
        err_msg = job.get("error", "Unknown error") or "Unknown error"
        raise HTTPException(status_code=400, detail={"code": 40001, "message": err_msg})
    return {"code": 0, "message": "success", "data": job}


@router.get("/api/reconstruct/{job_id}")
async def get_reconstruction_status(job_id: str):
    """Get reconstruction job status."""
    job = slam_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Job not found"})
    return {"code": 0, "message": "success", "data": job}


@router.get("/api/reconstruct/{job_id}/trajectory")
async def download_trajectory(job_id: str):
    """Download trajectory file for a completed job."""
    job = slam_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Job not found"})
    if not job.get("trajectory_file") or not Path(job["trajectory_file"]).exists():
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Trajectory file not available"})
    return FileResponse(job["trajectory_file"])


@router.get("/api/reconstruct/{job_id}/pointcloud")
async def download_pointcloud(job_id: str):
    """Download sparse point cloud PLY file for a completed job."""
    job = slam_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Job not found"})
    if not job.get("pointcloud_file") or not Path(job["pointcloud_file"]).exists():
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Point cloud file not available"})
    return FileResponse(job["pointcloud_file"])


@router.post("/api/reconstruct/{job_id}/dense")
async def generate_dense_pointcloud(job_id: str):
    """Run dense point cloud reconstruction for a completed SLAM job."""
    job = slam_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Job not found"})
    result = slam_service.generate_dense_pointcloud(job_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail={"code": 40001, "message": result.get("error", "Unknown error")})
    return {"code": 0, "message": "success", "data": result}


@router.get("/api/reconstruct/{job_id}/dense-pointcloud")
async def download_dense_pointcloud(job_id: str):
    """Download dense point cloud PLY file."""
    job = slam_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Job not found"})
    if not job.get("dense_pointcloud_file") or not Path(job["dense_pointcloud_file"]).exists():
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Dense point cloud not available. Run POST /api/reconstruct/{id}/dense first."})
    return FileResponse(job["dense_pointcloud_file"])


@router.get("/api/reconstruct")
async def list_reconstructions():
    """List all reconstruction jobs."""
    jobs = slam_service.list_jobs()
    return {"code": 0, "message": "success", "data": jobs}
