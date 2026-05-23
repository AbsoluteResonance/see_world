# SLAM Module — Deployment & Integration

## Overview

This module integrates two open-source SLAM systems for 3D reconstruction from monocular images/video.

| System | Type | IMU Required? | Scale |
|--------|------|--------------|-------|
| [ORB-SLAM3](https://github.com/UZ-SLAMLab/ORB_SLAM3) | Visual (Monocular/Stereo/RGB-D) + Inertial | Optional | Unknown (monocular) |
| [VINS-Mono](https://github.com/HKUST-Aerial-Robotics/VINS-Mono) | Visual-Inertial | **Required** | Metric |

## Directory Structure

```
SLAM/
├── datasets/              # Test datasets (TUM, EuRoC)
├── camera_calibration/    # Calibration tools & configs
├── python_interface/      # Python wrappers for SLAM
├── scripts/               # Setup & data scripts
├── ORB_SLAM3/             # ORB-SLAM3 source (after setup)
└── VINS_Mono/             # VINS-Mono source (after setup)
```

## Dataset Preparation

### TUM RGB-D Dataset (ORB-SLAM3 monocular test)
http://vision.in.tum.de/data/datasets/rgbd-dataset/download

```bash
python scripts/download_dataset.py --dataset tum --sequence fr1_desk
```

### EuRoC MAV Dataset (VINS-Mono test)
https://projects.asl.ethz.ch/datasets/doku.php?id=kmavvisualinertialdatasets

```bash
python scripts/download_dataset.py --dataset euroc --sequence MH_05
```

## Camera Calibration

Prepare a `calibration.yaml` for your phone/device:

```bash
python camera_calibration/calibrate.py --images /path/to/checkerboard/images --output config/my_phone.yaml
```

## Usage via Python Interface

```python
from python_interface import SLAMRunner

# Run ORB-SLAM3 on a video/images
runner = SLAMRunner(slam_type="orb_slam3", vocab_path="path/to/ORBvoc.txt", settings_path="path/to/calib.yaml")
result = runner.run(input_path="/path/to/images")
print(f"Trajectory: {result['trajectory_file']}")
print(f"Point cloud: {result['pointcloud_file']}")
```

## Web API Integration

SLAM reconstruction is exposed via:
- `POST /api/reconstruct` — Start a reconstruction job
- `GET /api/reconstruct/{job_id}` — Query job status
- `GET /api/reconstruct/{job_id}/pointcloud` — Download point cloud PLY
- `GET /api/reconstruct/{job_id}/trajectory` — Download trajectory
