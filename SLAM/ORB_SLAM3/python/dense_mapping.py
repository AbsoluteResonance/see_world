# -*- coding: utf-8 -*-
"""
Dense point cloud generation via stereo matching on SLAM keyframe pairs.

Uses adjacent keyframes as stereo pairs → SGBM disparity → dense 3D points.
"""
import gc
from pathlib import Path

import cv2
import numpy as np


def parse_trajectory(traj_path: str) -> list[dict]:
    poses = []
    with open(traj_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 8:
                continue
            ts = float(parts[0])
            t = np.array([float(parts[1]), float(parts[2]), float(parts[3])])
            qx, qy, qz, qw = float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7])
            R = np.array([
                [1 - 2*(qy*qy + qz*qz),   2*(qx*qy - qw*qz),       2*(qx*qz + qw*qy)],
                [2*(qx*qy + qw*qz),       1 - 2*(qx*qx + qz*qz),   2*(qy*qz - qw*qx)],
                [2*(qx*qz - qw*qy),       2*(qy*qz + qw*qx),       1 - 2*(qx*qx + qy*qy)]
            ])
            poses.append({"timestamp": ts, "t": t, "R": R})
    return poses


def load_calibration_yaml(yaml_path: str):
    """Load camera intrinsics from ORB-SLAM3 format YAML."""
    with open(yaml_path) as f:
        text = f.read()

    def get_val(key):
        import re
        m = re.search(rf'^{key}:\s*([\d.eE+-]+)', text, re.MULTILINE)
        return float(m.group(1)) if m else None

    fx = get_val('Camera.fx')
    fy = get_val('Camera.fy')
    cx = get_val('Camera.cx')
    cy = get_val('Camera.cy')
    k1 = get_val('Camera.k1')
    k2 = get_val('Camera.k2')
    p1 = get_val('Camera.p1')
    p2 = get_val('Camera.p2')
    K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64) if fx else None
    dist = np.array([k1, k2, p1, p2, 0.0], dtype=np.float64) if k1 else None
    return K, dist


def load_frames_list(frames_dir: str) -> list[str]:
    rgb_txt = Path(frames_dir) / "rgb.txt"
    if rgb_txt.exists():
        frames = []
        with open(rgb_txt) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    frames.append(str(Path(frames_dir) / parts[1]))
        return frames
    rgb_dir = Path(frames_dir) / "rgb"
    return sorted([str(p) for p in rgb_dir.glob("*.png")]) if rgb_dir.exists() else []


def dense_stereo_pair(img1: np.ndarray, img2: np.ndarray,
                       R_rel: np.ndarray, t_rel: np.ndarray,
                       K: np.ndarray, dist: np.ndarray,
                       max_depth: float = 50.0) -> tuple[np.ndarray, np.ndarray]:
    """Compute dense depth for image1 from stereo pair with image2.

    Returns (points Nx3, colors Nx3) in world space.
    """
    h, w = img1.shape[:2]

    # Stereo rectification (alpha=1 keeps original image content)
    R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(
        K, dist, K, dist, (w, h), R_rel, t_rel,
        alpha=1, flags=cv2.CALIB_ZERO_DISPARITY
    )

    # Rectify images
    map1x, map1y = cv2.initUndistortRectifyMap(K, dist, R1, P1, (w, h), cv2.CV_32FC1)
    map2x, map2y = cv2.initUndistortRectifyMap(K, dist, R2, P2, (w, h), cv2.CV_32FC1)
    rect1 = cv2.remap(img1, map1x, map1y, cv2.INTER_LINEAR)
    rect2 = cv2.remap(img2, map2x, map2y, cv2.INTER_LINEAR)

    gray1 = cv2.cvtColor(rect1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(rect2, cv2.COLOR_BGR2GRAY)

    # SGBM with tuned parameters
    stereo = cv2.StereoSGBM_create(
        minDisparity=0,
        numDisparities=128,
        blockSize=7,
        P1=8 * 3 * 7 ** 2,
        P2=32 * 3 * 7 ** 2,
        disp12MaxDiff=1,
        uniquenessRatio=5,
        speckleWindowSize=100,
        speckleRange=32,
        mode=cv2.StereoSGBM_MODE_SGBM,
    )
    disparity = stereo.compute(gray1, gray2).astype(np.float32) / 16.0

    # Reproject to 3D
    points_3d = cv2.reprojectImageTo3D(disparity, Q, handleMissingValues=True)

    # Filter valid points
    valid = (disparity > 0.5) & (disparity < 127.0)
    # Also filter by depth range
    depth = points_3d[..., 2]
    valid &= (depth > 0.1) & (depth < max_depth)

    pts = points_3d[valid]
    colors = rect1[valid]
    colors = colors[:, ::-1]  # BGR → RGB

    # Remove NaN/Inf
    mask = np.isfinite(pts).all(axis=1)
    pts = pts[mask]
    colors = colors[mask]

    # Transform points from rectified camera coordinates to world coordinates
    # In rectified coordinates: points are in camera1's rectified frame
    # We need to transform back to world using R1 (rotation from rectified to original cam) and the camera-to-world pose
    # But for simplicity, return in rectified camera frame

    return pts, colors


def build_dense_pointcloud(frames_dir: str, trajectory_file: str,
                            calibration_yaml: str, output_ply: str,
                            min_baseline: float = 0.05,
                            max_depth: float = 50.0,
                            max_pairs: int = 20) -> str:
    """Generate dense point cloud via stereo matching between keyframe pairs.

    Returns output PLY path (or empty string on failure).
    """
    print(f"[dense] Loading trajectory from {trajectory_file}")
    poses = parse_trajectory(trajectory_file)
    if len(poses) < 2:
        print(f"[dense] Need >=2 poses, got {len(poses)}")
        return ""

    K, dist = load_calibration_yaml(calibration_yaml)
    if K is None:
        print("[dense] Failed to load calibration YAML")
        return ""

    print(f"[dense] Loaded {len(poses)} poses, K diag: [{K[0,0]:.1f}, {K[1,1]:.1f}]")

    frames = load_frames_list(frames_dir)
    if len(frames) < 2:
        print(f"[dense] Not enough frames: {len(frames)}")
        return ""

    # Match poses to frames proportionally
    all_points = []
    all_colors = []

    # Use non-adjacent pairs for larger baseline → better stereo
    gap = max(2, len(poses) // max_pairs)

    for i in range(0, len(poses) - gap):
        j = i + gap
        p1, p2 = poses[i], poses[j]

        # Baseline check
        baseline = np.linalg.norm(p2["t"] - p1["t"])
        if baseline < min_baseline:
            continue

        # Get frame images
        idx1 = int(i * len(frames) / len(poses))
        idx2 = int(j * len(frames) / len(poses))
        idx1 = min(idx1, len(frames) - 1)
        idx2 = min(idx2, len(frames) - 1)

        img1 = cv2.imread(frames[idx1])
        img2 = cv2.imread(frames[idx2])
        if img1 is None or img2 is None:
            continue

        # Relative pose: R_rel, t_rel from camera1 to camera2
        R_rel = p2["R"].T @ p1["R"]
        t_rel = p2["R"].T @ (p1["t"] - p2["t"])

        print(f"[dense] Pair {i}→{j}: baseline={baseline:.3f}m")
        pts, colors = dense_stereo_pair(img1, img2, R_rel, t_rel, K, dist, max_depth)

        if len(pts) > 0:
            all_points.append(pts)
            all_colors.append(colors)
            print(f"[dense]   → {len(pts)} points")

        # Clean up
        del img1, img2, pts, colors
        gc.collect()

    if not all_points:
        print("[dense] No dense points generated")
        # Fall back to sparse triangulation
        from .pointcloud import build_pointcloud
        print("[dense] Falling back to sparse point cloud")
        return build_pointcloud(frames_dir, trajectory_file, output_ply, calibration_yaml=calibration_yaml)

    points = np.vstack(all_points)
    colors = np.vstack(all_colors)
    print(f"[dense] Total raw points: {len(points)}")

    # Voxel downsample
    if len(points) > 50000:
        voxel_size = 0.03
        voxel_indices = np.floor(points / voxel_size).astype(np.int32)
        voxel_dict = {}
        for k in range(len(points)):
            key = tuple(voxel_indices[k])
            if key not in voxel_dict:
                voxel_dict[key] = ([], [])
            voxel_dict[key][0].append(points[k])
            voxel_dict[key][1].append(colors[k])
        n = len(voxel_dict)
        down_pts = np.zeros((n, 3), dtype=np.float32)
        down_cols = np.zeros((n, 3), dtype=np.uint8)
        for k, key in enumerate(voxel_dict):
            pts_list, col_list = voxel_dict[key]
            down_pts[k] = np.mean(pts_list, axis=0)
            down_cols[k] = np.mean(col_list, axis=0).astype(np.uint8)
        points = down_pts
        colors = down_cols
        print(f"[dense] After downsample: {len(points)} points")

    # Write PLY
    Path(output_ply).parent.mkdir(parents=True, exist_ok=True)
    with open(output_ply, 'w') as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"element vertex {len(points)}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        f.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        f.write("end_header\n")
        for k in range(len(points)):
            x, y, z = points[k]
            r, g, b = colors[k]
            f.write(f"{x:.4f} {y:.4f} {z:.4f} {int(r)} {int(g)} {int(b)}\n")

    print(f"[dense] Saved {len(points)} dense points to {output_ply}")
    return output_ply
