# -*- coding: utf-8 -*-
"""
Colored 3D point cloud generation from ORB-SLAM3 trajectory + video frames.

Uses the estimated camera poses from SLAM to triangulate image features
into a colored 3D point cloud of the scene.
"""

import struct
from pathlib import Path

import cv2
import numpy as np


# Default TUM RGB-D camera intrinsics (from TUM1.yaml used by ORB-SLAM3)
DEFAULT_K = np.array([
    [517.306, 0,       318.643],
    [0,       516.469, 255.314],
    [0,       0,       1]
], dtype=np.float64)

MAX_REPROJ_ERROR = 8.0   # pixels — discard bad triangulations
MIN_PARALLAX = 0.005     # radians — skip near-zero baseline pairs
VOXEL_SIZE = 0.02        # meters — downsampling grid for PLY output


def parse_trajectory(traj_path: str) -> list[dict]:
    """Parse TUM-format trajectory file.

    Each line: timestamp tx ty tz qx qy qz qw
    Returns list of dicts with keys: timestamp, t (3-vector), q (quaternion), R (3x3 rotation matrix)
    """
    poses = []
    with open(traj_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 8:
                continue
            ts = float(parts[0])
            t = np.array([float(parts[1]), float(parts[2]), float(parts[3])])
            qx, qy, qz, qw = float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7])
            # Quaternion to rotation matrix (TUM: camera-to-world)
            R = np.array([
                [1 - 2*(qy*qy + qz*qz),   2*(qx*qy - qw*qz),       2*(qx*qz + qw*qy)],
                [2*(qx*qy + qw*qz),       1 - 2*(qx*qx + qz*qz),   2*(qy*qz - qw*qx)],
                [2*(qx*qz - qw*qy),       2*(qy*qz + qw*qx),       1 - 2*(qx*qx + qy*qy)]
            ])
            poses.append({"timestamp": ts, "t": t, "q": (qx, qy, qz, qw), "R": R})
    return poses


def pose_to_projection(R: np.ndarray, t: np.ndarray, K: np.ndarray) -> np.ndarray:
    """Convert camera-to-world pose to 3x4 projection matrix: P = K * [R^T | -R^T * t]."""
    R_cam = R.T  # world-to-camera rotation
    t_cam = -R_cam @ t  # world-to-camera translation
    P = K @ np.hstack([R_cam, t_cam.reshape(-1, 1)])
    return P


def load_frames_list(frames_dir: str) -> list[str]:
    """Load sorted frame image paths from rgb.txt or by scanning rgb/ directory."""
    rgb_txt = Path(frames_dir) / "rgb.txt"
    frames = []

    if rgb_txt.exists():
        with open(rgb_txt) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    frames.append(str(Path(frames_dir) / parts[1]))
    else:
        rgb_dir = Path(frames_dir) / "rgb"
        if rgb_dir.exists():
            frames = sorted([str(p) for p in rgb_dir.glob("*.png")])

    return frames


def find_frame_for_timestamp(frames_dir: str, timestamp: float) -> str | None:
    """Find the nearest frame image for a given timestamp.

    Uses sequential file index when timestamps don't match (video-extracted frames).
    Falls back to timestamp matching from rgb.txt.
    """
    rgb_txt = Path(frames_dir) / "rgb.txt"
    if not rgb_txt.exists():
        return None

    timestamps = []
    files = []
    with open(rgb_txt) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                ts = float(parts[0])
            except ValueError:
                continue
            timestamps.append(ts)
            files.append(str(Path(frames_dir) / parts[1]))

    if not files:
        return None

    # Try exact timestamp match first (within 0.01s)
    best_diff = float('inf')
    best_idx = 0
    for i, ts in enumerate(timestamps):
        diff = abs(ts - timestamp)
        if diff < best_diff:
            best_diff = diff
            best_idx = i

    if best_diff < 0.1:
        return files[best_idx]

    # If timestamps don't match (different time bases), use sequential index
    # Assume keyframe i roughly corresponds to frame i * (frames_count / keyframes_count)
    # But simpler: just use the first frame for the first keyframe, etc.
    if len(files) >= len(timestamps):
        # Map keyframe index to file index proportionally
        return None  # Let caller handle with proportional matching

    return None


def match_pose_to_frames(poses: list[dict], frames_list: list[str]) -> list[tuple]:
    """Match camera poses to frame files by proportional index.

    Returns list of (pose_dict, frame_path) tuples.
    """
    n_poses = len(poses)
    n_frames = len(frames_list)
    if n_poses < 2 or n_frames < 2:
        return []

    matched = []
    for i, pose in enumerate(poses):
        # Map pose index proportionally to frame index
        frame_idx = int(i * n_frames / n_poses)
        if frame_idx >= n_frames:
            frame_idx = n_frames - 1
        matched.append((pose, frames_list[frame_idx]))

    return matched


def triangulate_pair(img1: np.ndarray, img2: np.ndarray,
                     P1: np.ndarray, P2: np.ndarray,
                     K: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Extract features, match, triangulate, return points (Nx3) and colors (Nx3)."""
    # Detect features (use ORB with more features, or SIFT if available)
    try:
        # Try SIFT first for better matching
        sift = cv2.SIFT_create(nfeatures=3000)
        kp1, des1 = sift.detectAndCompute(img1, None)
        kp2, des2 = sift.detectAndCompute(img2, None)
        norm = cv2.NORM_L2
    except Exception:
        orb = cv2.ORB_create(nfeatures=3000)
        kp1, des1 = orb.detectAndCompute(img1, None)
        kp2, des2 = orb.detectAndCompute(img2, None)
        norm = cv2.NORM_HAMMING

    if des1 is None or des2 is None or len(kp1) < 10 or len(kp2) < 10:
        return np.empty((0, 3)), np.empty((0, 3))

    # Match with FLANN-based matcher for SIFT, BF for ORB
    if norm == cv2.NORM_L2:
        # FLANN for SIFT
        FLANN_INDEX_KDTREE = 1
        index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
        search_params = dict(checks=50)
        matcher = cv2.FlannBasedMatcher(index_params, search_params)
    else:
        matcher = cv2.BFMatcher(norm)

    matches = matcher.knnMatch(des1, des2, k=2)

    # Ratio test (Lowe's)
    good_matches = []
    for m_pair in matches:
        if len(m_pair) >= 2:
            m, n = m_pair
            if m.distance < 0.75 * n.distance:
                good_matches.append(m)

    if len(good_matches) < 8:
        return np.empty((0, 3)), np.empty((0, 3))

    # Get matching point coordinates
    pts1 = np.float32([kp1[m.queryIdx].pt for m in good_matches]).T  # 2xN
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good_matches]).T  # 2xN

    # Triangulate
    pts4d = cv2.triangulatePoints(P1, P2, pts1, pts2)
    pts3d = (pts4d[:3] / pts4d[3]).T  # Nx3

    # Filter by reprojection error
    # Project back to both cameras
    pts_h = np.hstack([pts3d, np.ones((pts3d.shape[0], 1))])
    proj1 = (P1 @ pts_h.T).T
    proj1 = proj1[:, :2] / proj1[:, 2:3]
    proj2 = (P2 @ pts_h.T).T
    proj2 = proj2[:, :2] / proj2[:, 2:3]

    err1 = np.sqrt(np.sum((proj1 - pts1.T)**2, axis=1))
    err2 = np.sqrt(np.sum((proj2 - pts2.T)**2, axis=1))
    valid = (err1 < MAX_REPROJ_ERROR) & (err2 < MAX_REPROJ_ERROR)

    pts3d = pts3d[valid]
    good_idx = np.where(valid)[0]

    # Get colors from source image
    colors = np.zeros((len(pts3d), 3), dtype=np.uint8)
    for i, idx in enumerate(good_idx):
        pt = kp1[good_matches[idx].queryIdx].pt
        u, v = int(round(pt[0])), int(round(pt[1]))
        if 0 <= u < img1.shape[1] and 0 <= v < img1.shape[0]:
            b, g, r = img1[v, u]
            colors[i] = [r, g, b]

    # Filter points behind camera (negative depth)
    valid_z = pts3d[:, 2] > 0
    pts3d = pts3d[valid_z]
    colors = colors[valid_z]

    return pts3d, colors


def voxel_downsample(points: np.ndarray, colors: np.ndarray,
                     voxel_size: float) -> tuple[np.ndarray, np.ndarray]:
    """Simple voxel grid downsampling."""
    if len(points) == 0:
        return points, colors

    voxel_indices = np.floor(points / voxel_size).astype(np.int32)
    # Use a dictionary to average points in each voxel
    voxel_dict = {}
    for i in range(len(points)):
        key = tuple(voxel_indices[i])
        if key not in voxel_dict:
            voxel_dict[key] = ([], [])
        voxel_dict[key][0].append(points[i])
        voxel_dict[key][1].append(colors[i])

    n = len(voxel_dict)
    down_points = np.zeros((n, 3), dtype=np.float32)
    down_colors = np.zeros((n, 3), dtype=np.uint8)
    for i, key in enumerate(voxel_dict):
        pts_list, col_list = voxel_dict[key]
        down_points[i] = np.mean(pts_list, axis=0)
        down_colors[i] = np.mean(col_list, axis=0).astype(np.uint8)

    return down_points, down_colors


def write_ply(filepath: str, points: np.ndarray, colors: np.ndarray):
    """Write colored PLY file (ASCII format)."""
    n = len(points)
    with open(filepath, 'w') as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write(f"element vertex {n}\n")
        f.write("property float x\n")
        f.write("property float y\n")
        f.write("property float z\n")
        f.write("property uchar red\n")
        f.write("property uchar green\n")
        f.write("property uchar blue\n")
        f.write("end_header\n")
        for i in range(n):
            x, y, z = points[i]
            r, g, b = colors[i]
            f.write(f"{x:.6f} {y:.6f} {z:.6f} {int(r)} {int(g)} {int(b)}\n")


def load_calibration_yaml(yaml_path: str) -> np.ndarray:
    """Load camera intrinsics from ORB-SLAM3 format YAML."""
    import re
    with open(yaml_path) as f:
        text = f.read()
    def get_val(key):
        m = re.search(rf'^{key}:\s*([\d.eE+-]+)', text, re.MULTILINE)
        return float(m.group(1)) if m else None
    fx = get_val('Camera.fx')
    fy = get_val('Camera.fy')
    cx = get_val('Camera.cx')
    cy = get_val('Camera.cy')
    if all(v is not None for v in [fx, fy, cx, cy]):
        return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
    return DEFAULT_K.copy()


def build_pointcloud(frames_dir: str, trajectory_file: str,
                     output_ply: str, K: np.ndarray | None = None) -> str:
    """Generate a colored PLY point cloud from SLAM trajectory + frames.

    Args:
        frames_dir: Directory containing rgb.txt and rgb/ subfolder
        trajectory_file: TUM-format trajectory file
        output_ply: Path for output PLY file
        K: Camera intrinsic matrix (3x3). Defaults to TUM1.yaml values.

    Returns:
        Path to output PLY file (or empty string on failure)
    """
    # Parse trajectory
    poses = parse_trajectory(trajectory_file)
    if len(poses) < 2:
        print(f"[pointcloud] Need at least 2 poses, got {len(poses)}")
        return ""

    print(f"[pointcloud] Loaded {len(poses)} camera poses")

    # Load frame list and match proportionally
    frames_list = load_frames_list(frames_dir)
    if len(frames_list) < 2:
        print(f"[pointcloud] Not enough frames: {len(frames_list)}")
        return ""

    matched = match_pose_to_frames(poses, frames_list)
    print(f"[pointcloud] Matched {len(matched)} pose-frame pairs")

    # Auto-detect image dimensions from first frame
    first_img = cv2.imread(matched[0][1])
    if first_img is None:
        print("[pointcloud] Cannot read first frame")
        return ""
    h, w = first_img.shape[:2]

    # Use default K if provided, otherwise estimate from image dimensions
    if K is None:
        K = DEFAULT_K.copy()
        # Scale intrinsics to match actual image size relative to default (640x480)
        scale_x = w / 640.0
        scale_y = h / 480.0
        K[0, 0] *= scale_x   # fx
        K[1, 1] *= scale_y   # fy
        K[0, 2] *= scale_x   # cx
        K[1, 2] *= scale_y   # cy

    print(f"[pointcloud] Image size: {w}x{h}, K diag: [{K[0,0]:.1f}, {K[1,1]:.1f}]")

    all_points = []
    all_colors = []

    # Use every pair (i, i+2) for larger baseline = better triangulation
    pair_gap = 2
    for i in range(0, len(matched) - pair_gap):
        pose1, img_path1 = matched[i]
        pose2, img_path2 = matched[i + pair_gap]

        # Compute baseline (parallax)
        baseline = np.linalg.norm(pose2["t"] - pose1["t"])
        if baseline < MIN_PARALLAX:
            continue

        img1 = cv2.imread(img_path1)
        img2 = cv2.imread(img_path2)
        if img1 is None or img2 is None:
            continue

        # Compute projection matrices
        P1 = pose_to_projection(pose1["R"], pose1["t"], K)
        P2 = pose_to_projection(pose2["R"], pose2["t"], K)

        # Triangulate
        pts3d, colors = triangulate_pair(img1, img2, P1, P2, K)
        if len(pts3d) > 0:
            all_points.append(pts3d)
            all_colors.append(colors)

        if (i + 1) % 10 == 0:
            print(f"[pointcloud] Processed {i+1}/{len(matched)-1} pose pairs")

    if not all_points:
        print("[pointcloud] No 3D points generated")
        return ""

    # Aggregate
    all_points = np.vstack(all_points)
    all_colors = np.vstack(all_colors)
    print(f"[pointcloud] Raw triangulated points: {len(all_points)}")

    # Downsample
    if VOXEL_SIZE > 0 and len(all_points) > 10000:
        all_points, all_colors = voxel_downsample(all_points, all_colors, VOXEL_SIZE)
        print(f"[pointcloud] After voxel downsample: {len(all_points)}")

    # Remove statistical outliers (simple z-score filter on cluster size)
    if len(all_points) > 100:
        mean_pt = np.mean(all_points, axis=0)
        dists = np.linalg.norm(all_points - mean_pt, axis=1)
        std = np.std(dists)
        mask = dists < (std * 5)  # remove extreme outliers
        all_points = all_points[mask]
        all_colors = all_colors[mask]

    # Write PLY
    write_ply(output_ply, all_points, all_colors)
    print(f"[pointcloud] Saved {len(all_points)} colored points to {output_ply}")
    return output_ply
