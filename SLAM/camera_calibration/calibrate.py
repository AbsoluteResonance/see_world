#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Camera calibration tool using OpenCV.
Generates YAML config for ORB-SLAM3 / VINS-Mono.

Usage:
    python camera_calibration/calibrate.py --width 640 --height 480 \
        --images /path/to/checkerboard/images --output config/my_cam.yaml
"""

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np


def calibrate(image_dir: str, pattern_size: tuple = (9, 6), square_size: float = 0.025,
              output: str = "calibration.yaml"):
    """Calibrate camera using checkerboard images."""
    images = sorted(Path(image_dir).glob("*"))
    image_paths = [str(p) for p in images if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]

    if not image_paths:
        print(f"No images found in {image_dir}")
        return

    print(f"Found {len(image_paths)} calibration images")

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    objp = np.zeros((pattern_size[0] * pattern_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pattern_size[0], 0:pattern_size[1]].T.reshape(-1, 2) * square_size

    objpoints = []
    imgpoints = []
    gray = None

    for fname in image_paths:
        img = cv2.imread(fname)
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, pattern_size, None)

        if ret:
            objpoints.append(objp)
            corners2 = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            imgpoints.append(corners2)
            cv2.drawChessboardCorners(img, pattern_size, corners2, ret)
            cv2.imshow("Calibration", img)
            cv2.waitKey(100)

    cv2.destroyAllWindows()

    if not objpoints:
        print("No checkerboard corners found in any image")
        return

    print(f"Using {len(objpoints)} valid images for calibration")

    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
        objpoints, imgpoints, gray.shape[::-1], None, None
    )

    print(f"\nReprojection error: {ret:.6f}")
    print(f"Camera matrix:\n{mtx}")
    print(f"Distortion coefficients:\n{dist}")

    h, w = gray.shape[:2]
    fx = mtx[0, 0]
    fy = mtx[1, 1]
    cx = mtx[0, 2]
    cy = mtx[1, 2]
    k1 = dist[0, 0] if dist.size > 0 else 0.0
    k2 = dist[0, 1] if dist.size > 1 else 0.0
    p1 = dist[0, 2] if dist.size > 2 else 0.0
    p2 = dist[0, 3] if dist.size > 3 else 0.0

    # ORB-SLAM3 YAML format
    yaml_content = f"""%YAML:1.0

# Camera calibration - Auto generated
# Reprojection error: {ret:.6f}

Camera.type: "PinHole"

Camera.width: {w}
Camera.height: {h}

Camera.fx: {fx:.8f}
Camera.fy: {fy:.8f}
Camera.cx: {cx:.8f}
Camera.cy: {cy:.8f}

Camera.k1: {k1:.8f}
Camera.k2: {k2:.8f}
Camera.p1: {p1:.8f}
Camera.p2: {p2:.8f}

# Camera frames per second
Camera.fps: 30.0

# Color order (0: BGR, 1: RGB)
Camera.RGB: 1

# ORB Extractor
ORBextractor.nFeatures: 1200
ORBextractor.scaleFactor: 1.2
ORBextractor.nLevels: 8
ORBextractor.iniThFAST: 20
ORBextractor.minThFAST: 7

# Viewer
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

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(yaml_content)
    print(f"\nCalibration saved to: {output}")


def main():
    parser = argparse.ArgumentParser(description="Camera calibration tool")
    parser.add_argument("--images", required=True, help="Directory of checkerboard images")
    parser.add_argument("--width", type=int, default=9, help="Checkerboard inner corners per row (default: 9)")
    parser.add_argument("--height", type=int, default=6, help="Checkerboard inner corners per column (default: 6)")
    parser.add_argument("--square-size", type=float, default=0.025, help="Checkerboard square size in meters (default: 0.025)")
    parser.add_argument("--output", default="calibration.yaml", help="Output YAML file path")
    args = parser.parse_args()

    calibrate(args.images, (args.width, args.height), args.square_size, args.output)


if __name__ == "__main__":
    main()
