# SLAM Module — Deployment & Integration

## Status: ✅ ORB-SLAM3 Deployed

| System | Type | IMU Required? | Status |
|--------|------|--------------|--------|
| [ORB-SLAM3](https://github.com/UZ-SLAMLab/ORB_SLAM3) | Visual + Inertial | Optional | ✅ Deployed |
| [VINS-Mono](https://github.com/HKUST-Aerial-Robotics/VINS-Mono) | Visual-Inertial | **Required** | ⏳ Needs ROS (Ubuntu 20.04/Docker) |

## Directory Structure

```
SLAM/
├── datasets/              # Test datasets (TUM fr1_xyz)
├── ORB_SLAM3/             # ORB-SLAM3 source (compiled)
│   ├── Vocabulary/        # ORBvoc.txt (139MB)
│   ├── Examples/          # 11 example executables
│   ├── python/            # Python wrapper (SLAMRunner, pointcloud)
│   ├── tools/calibration/ # Camera calibration tool
│   └── scripts/           # Dataset download scripts
└── VINS_Mono/             # VINS-Mono docs
```

## Python Interface

```python
from SLAM.ORB_SLAM3.python import SLAMRunner

runner = SLAMRunner(slam_type="orb_slam3")
result = runner.run("/path/to/tum_dataset")
print(f"Trajectory: {result['trajectory_file']}")

# Generate colored point cloud
from SLAM.ORB_SLAM3.python.pointcloud import build_pointcloud
build_pointcloud(frames_dir, trajectory_file, "output.ply")
```

## Web API Integration

- `POST /api/reconstruct/from-file/{file_id}` — Start from uploaded video
- `GET /api/reconstruct/{job_id}` — Query job status
- `GET /api/reconstruct/{job_id}/trajectory` — Download TUM trajectory
- `GET /api/reconstruct/{job_id}/pointcloud` — Download colored PLY
