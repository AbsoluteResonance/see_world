"""Camera calibration API — upload checkerboard photos, get camera intrinsics."""

import uuid
import shutil
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from backend.config import settings

router = APIRouter()

CALIB_DIR = Path(settings.upload_dir) / "calibration"
CALIB_DIR.mkdir(parents=True, exist_ok=True)

# In-memory calibration session
_calib_session = {
    "images": [],         # list of file paths with detected corners
    "image_size": None,   # (w, h) from first image
    "pattern_size": (9, 6),
    "square_size": 0.025,  # meters
    "result": None,       # calibration result dict
}


@router.get("/api/calibrate/status")
async def get_calibration_status():
    """Get current calibration session status."""
    return {
        "code": 0,
        "message": "success",
        "data": {
            "image_count": len(_calib_session["images"]),
            "image_size": _calib_session["image_size"],
            "pattern_size": list(_calib_session["pattern_size"]),
            "has_result": _calib_session["result"] is not None,
        },
    }


@router.post("/api/calibrate/upload")
async def upload_calibration_image(
    file: UploadFile = File(...),
    pattern_width: int = Form(9),
    pattern_height: int = Form(6),
    square_size: float = Form(0.025),
):
    """Upload a checkerboard image for calibration."""
    if not file.filename:
        raise HTTPException(status_code=400, detail={"code": 40001, "message": "No file provided"})

    ext = Path(file.filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png"}:
        raise HTTPException(status_code=400, detail={"code": 40002, "message": "Only JPG/PNG supported"})

    content = await file.read()
    img_array = np.frombuffer(content, np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail={"code": 40001, "message": "Failed to decode image"})

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]
    pattern_size = (pattern_width, pattern_height)

    # Detect checkerboard corners
    ret, corners = cv2.findChessboardCorners(gray, pattern_size, None)
    if not ret:
        return {
            "code": 0,
            "message": "success",
            "data": {"detected": False, "corners": 0, "reason": "No checkerboard found"},
        }

    # Refine corners
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    corners2 = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)

    # Save image and update session
    fname = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    dest = CALIB_DIR / fname
    cv2.imwrite(str(dest), img)

    # Update session
    _calib_session["images"].append({
        "path": str(dest),
        "corners": corners2.tolist(),
        "size": (w, h),
    })
    _calib_session["pattern_size"] = pattern_size
    _calib_session["square_size"] = square_size
    if _calib_session["image_size"] is None:
        _calib_session["image_size"] = (w, h)
    _calib_session["result"] = None  # invalidate old result

    return {
        "code": 0,
        "message": "success",
        "data": {
            "detected": True,
            "corners": len(corners2),
            "image_count": len(_calib_session["images"]),
            "image_size": (w, h),
        },
    }


@router.post("/api/calibrate/run")
async def run_calibration(body: dict = None):
    """Run calibration on all uploaded images."""
    images = _calib_session["images"]
    if len(images) < 3:
        raise HTTPException(status_code=400, detail={
            "code": 40001,
            "message": f"Need at least 3 images with checkerboard, got {len(images)}"
        })

    pattern_size = _calib_session["pattern_size"]
    square_size = _calib_session["square_size"]

    # Build object and image points
    objp = np.zeros((pattern_size[0] * pattern_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pattern_size[0], 0:pattern_size[1]].T.reshape(-1, 2) * square_size

    objpoints = []
    imgpoints = []
    first_size = None

    for entry in images:
        img = cv2.imread(entry["path"])
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if first_size is None:
            first_size = gray.shape[::-1]
        ret, corners = cv2.findChessboardCorners(gray, pattern_size, None)
        if ret:
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners2 = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            objpoints.append(objp)
            imgpoints.append(corners2)

    if len(objpoints) < 3:
        raise HTTPException(status_code=400, detail={
            "code": 40001,
            "message": f"Only {len(objpoints)} valid images after re-detection"
        })

    # Run calibration
    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
        objpoints, imgpoints, first_size, None, None
    )
    h = first_size[1]
    w = first_size[0]

    # Build result
    fx, fy = mtx[0, 0], mtx[1, 1]
    cx, cy = mtx[0, 2], mtx[1, 2]
    k1 = dist[0, 0] if dist.size > 0 else 0.0
    k2 = dist[0, 1] if dist.size > 1 else 0.0
    p1 = dist[0, 2] if dist.size > 2 else 0.0
    p2 = dist[0, 3] if dist.size > 3 else 0.0

    result = {
        "reprojection_error": round(float(ret), 6),
        "image_size": {"width": w, "height": h},
        "camera_matrix": {
            "fx": round(float(fx), 4),
            "fy": round(float(fy), 4),
            "cx": round(float(cx), 4),
            "cy": round(float(cy), 4),
        },
        "distortion": {
            "k1": round(float(k1), 6),
            "k2": round(float(k2), 6),
            "p1": round(float(p1), 6),
            "p2": round(float(p2), 6),
        },
        "images_used": len(objpoints),
    }

    _calib_session["result"] = result

    return {"code": 0, "message": "success", "data": result}


@router.get("/api/calibrate/result")
async def get_calibration_result():
    """Get the calibration result as JSON."""
    if not _calib_session["result"]:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "No calibration result yet"})
    return {"code": 0, "message": "success", "data": _calib_session["result"]}


@router.get("/api/calibrate/result/yaml")
async def download_calibration_yaml(target_width: int = 0, target_height: int = 0):
    """Download calibration result as ORB-SLAM3 YAML.

    Query params:
        target_width, target_height: optionally scale intrinsics to a target image size
                                     (e.g., ?target_width=640&target_height=480 for SLAM resize)
    """
    if not _calib_session["result"]:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "No calibration result yet"})

    r = _calib_session["result"]
    w = r["image_size"]["width"]
    h = r["image_size"]["height"]
    cm = r["camera_matrix"]
    d = r["distortion"]
    error = r["reprojection_error"]

    # Scale intrinsics to target size if requested
    fx, fy = cm['fx'], cm['fy']
    cx, cy = cm['cx'], cm['cy']
    out_w, out_h = w, h
    if target_width > 0 and target_height > 0:
        scale_x = target_width / w
        scale_y = target_height / h
        fx *= scale_x
        fy *= scale_y
        cx *= scale_x
        cy *= scale_y
        out_w, out_h = target_width, target_height

    yaml = f"""%YAML:1.0

# Camera calibration - Auto generated by See World
# Reprojection error: {error}
# Images used: {r['images_used']}
# Original image size: {w}x{h}
{f'# Scaled to: {out_w}x{out_h} (for ORB-SLAM3)' if target_width > 0 else ''}

Camera.type: "PinHole"

Camera.width: {out_w}
Camera.height: {out_h}

Camera.fx: {fx:.8f}
Camera.fy: {fy:.8f}
Camera.cx: {cx:.8f}
Camera.cy: {cy:.8f}

Camera.k1: {d['k1']:.8f}
Camera.k2: {d['k2']:.8f}
Camera.p1: {d['p1']:.8f}
Camera.p2: {d['p2']:.8f}

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

    return Response(content=yaml, media_type="text/plain",
                    headers={"Content-Disposition": f"attachment; filename=calibration_{out_w}x{out_h}.yaml"})


@router.delete("/api/calibrate/reset")
async def reset_calibration():
    """Clear all calibration data."""
    _calib_session["images"].clear()
    _calib_session["image_size"] = None
    _calib_session["result"] = None
    # Clean uploaded files
    shutil.rmtree(str(CALIB_DIR), ignore_errors=True)
    CALIB_DIR.mkdir(parents=True, exist_ok=True)
    return {"code": 0, "message": "success", "data": {"reset": True}}
