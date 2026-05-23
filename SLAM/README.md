# SLAM Module — Deployment & Integration

## Status: ✅ ORB-SLAM3 Deployed

| System | Type | IMU Required? | Status |
|--------|------|--------------|--------|
| [ORB-SLAM3](https://github.com/UZ-SLAMLab/ORB_SLAM3) | Visual + Inertial (Monocular/Stereo/RGB-D) | Optional | ✅ Compiled & tested |
| [VINS-Mono](https://github.com/HKUST-Aerial-Robotics/VINS-Mono) | Visual-Inertial | **Required** | ⏳ Needs ROS Noetic (Ubuntu 20.04 / Docker) |

## Directory Structure

```
SLAM/
├── datasets/              # Test datasets (TUM fr1_xyz: 428MB, 798 frames)
├── outputs/               # SLAM output trajectories & point clouds
├── camera_calibration/    # Calibration tools & configs
├── python_interface/      # Python wrappers for SLAM
├── scripts/               # Setup & data scripts
├── ORB_SLAM3/             # ORB-SLAM3 source (compiled ✅)
│   ├── Vocabulary/        # ORBvoc.txt (139MB)
│   └── Examples/          # 11 example executables
└── VINS_Mono/             # VINS-Mono docs (no ROS on 22.04)
```

## Benchmark (TUM fr1_xyz)

| Metric | Value |
|--------|-------|
| Image sequence | 798 frames (640×480) |
| Keyframes generated | 32-39 |
| Median tracking time | 34 ms/frame |
| Mean tracking time | 36 ms/frame (≈28 FPS) |
| Map points | ~424 |
| Vocab load time | ~15s (139MB) |

## Python Interface

```python
from python_interface import SLAMRunner

# Auto-detect dataset type and pick the right executable
runner = SLAMRunner(slam_type="orb_slam3")
result = runner.run("/path/to/tum_dataset")
print(f"Trajectory: {result['trajectory_file']}")

# Parse trajectory
poses = runner.parse_trajectory(result['trajectory_file'])
for pose in poses:
    print(f"t={pose['timestamp']} pos=({pose['tx']:.3f}, {pose['ty']:.3f}, {pose['tz']:.3f})")
```

## Web API Integration

SLAM reconstruction is exposed via:
- `POST /api/reconstruct` — Start a reconstruction job
- `GET /api/reconstruct/{job_id}` — Query job status
- `GET /api/reconstruct/{job_id}/pointcloud` — Download point cloud PLY (TBD)
- `GET /api/reconstruct/{job_id}/trajectory` — Download trajectory (TUM format)

## Dataset Preparation

### TUM RGB-D Dataset
```bash
python scripts/download_dataset.py --dataset tum --sequence fr1_desk
```

### EuRoC MAV Dataset
```bash
python scripts/download_dataset.py --dataset euroc --sequence MH_05
```

## Camera Calibration

```bash
python camera_calibration/calibrate.py --images /path/to/checkerboard --output config.yaml
```
