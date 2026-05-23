# -*- coding: utf-8 -*-
"""
SLAM Python interface — wrapper for running ORB-SLAM3 / VINS-Mono from Python.
"""

import subprocess
import json
import os
from pathlib import Path
from typing import Optional


class SLAMRunner:
    """Python interface to run SLAM systems and retrieve results."""

    # Executable -> dataset hint mapping for auto-detection
    EXE_PRIORITY = [
        "mono_inertial_euroc",
        "mono_inertial_tum_vi",
        "mono_euroc",
        "mono_tum_vi",
        "mono_kitti",
        "mono_tum",
    ]
    DEFAULT_SETTINGS = {
        "mono_tum":              "ORB_SLAM3/Examples/Monocular/TUM1.yaml",
        "mono_kitti":            "ORB_SLAM3/Examples/Monocular/KITTI00-02.yaml",
        "mono_euroc":            "ORB_SLAM3/Examples/Monocular/EuRoC.yaml",
        "mono_tum_vi":           "ORB_SLAM3/Examples/Monocular/TUM-VI.yaml",
        "mono_inertial_euroc":   "ORB_SLAM3/Examples/Monocular-Inertial/EuRoC.yaml",
        "mono_inertial_tum_vi":  "ORB_SLAM3/Examples/Monocular-Inertial/TUM-VI.yaml",
    }

    def __init__(self, slam_type: str = "orb_slam3",
                 vocab_path: str = "",
                 settings_path: str = "",
                 workspace: str = ""):
        self.slam_type = slam_type
        self.workspace = workspace or str(Path(__file__).resolve().parent.parent)
        self.vocab_path = vocab_path or self._default_vocab()
        self.settings_path = settings_path

    def _default_vocab(self) -> str:
        if self.slam_type == "orb_slam3":
            p = Path(self.workspace) / "ORB_SLAM3" / "Vocabulary" / "ORBvoc.txt"
            if p.exists():
                return str(p)
        return ""

    def _find_executable(self, name: str) -> Optional[str]:
        for root, dirs, files in os.walk(Path(self.workspace)):
            for f in files:
                if f == name and os.access(os.path.join(root, f), os.X_OK):
                    return os.path.join(root, f)
        return None

    def _pick_executable(self, input_path: str = "") -> Optional[str]:
        """Auto-pick the best executable based on dataset type and available exes."""
        # Detect dataset type to narrow executable choice
        dtype = self._detect_dataset_type(input_path) if input_path else "unknown"
        candidates = self.EXE_PRIORITY  # full list as fallback

        dtype_map = {
            "tum":      ["mono_tum"],
            "euroc":    ["mono_inertial_euroc", "mono_euroc"],
            "kitti":    ["mono_kitti"],
            "tum_vi":   ["mono_inertial_tum_vi", "mono_tum_vi"],
        }
        if dtype in dtype_map:
            candidates = dtype_map[dtype]

        for name in candidates:
            exe = self._find_executable(name)
            if exe:
                return exe
        # Fallback: try any available executable
        for name in self.EXE_PRIORITY:
            exe = self._find_executable(name)
            if exe:
                return exe
        return None

    def _settings_for_exe(self, exe_name: str) -> str:
        """Return default settings path for a given executable name."""
        rel = self.DEFAULT_SETTINGS.get(exe_name, "")
        if rel:
            p = Path(self.workspace) / rel
            if p.exists():
                return str(p)
        return ""

    def check_ready(self, input_path: str = "") -> dict:
        """Check if the SLAM system is built and ready."""
        if self.slam_type == "orb_slam3":
            exe = self._pick_executable(input_path)
            vocab_ok = Path(self.vocab_path).exists()
            return {"ready": exe is not None and vocab_ok,
                    "executable": exe or "not found",
                    "vocabulary": "found" if vocab_ok else "missing"}
        elif self.slam_type in ("vins_mono", "orb_slam3_inertial"):
            if self.slam_type == "vins_mono":
                return {"ready": False, "note": "VINS-Mono requires ROS; check ROS workspace"}
            exe = self._find_executable("mono_inertial_euroc")
            vocab_ok = Path(self.vocab_path).exists()
            return {"ready": exe is not None and vocab_ok,
                    "executable": exe or "not found",
                    "vocabulary": "found" if vocab_ok else "missing"}
        return {"ready": False, "error": f"Unknown SLAM type: {self.slam_type}"}

    def run(self, input_path: str, output_dir: str = "") -> dict:
        """
        Run SLAM on input images/video.

        Args:
            input_path: Directory of images or path to video/bag file
            output_dir: Directory for results (trajectory, point cloud)

        Returns:
            dict with keys: status, trajectory_file, pointcloud_file, error
        """
        output_dir = output_dir or str(Path(self.workspace) / "output" / Path(input_path).name)
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        if self.slam_type in ("orb_slam3", "orb_slam3_inertial"):
            return self._run_orb_slam3(input_path, output_dir)
        elif self.slam_type == "vins_mono":
            return self._run_vins_mono(input_path, output_dir)
        else:
            return {"status": "error", "error": f"Unknown SLAM type: {self.slam_type}"}

    def _detect_dataset_type(self, input_path: str) -> str:
        """Detect dataset type from input path."""
        p = Path(input_path)
        if not p.is_dir():
            return "unknown"
        # TUM-VI: has dataset-specific files (cam0, cam1, imu data)
        if (p / "cam0").is_dir() or (p / "dso").is_dir():
            return "tum_vi"
        if any(f.name == "data.csv" for f in p.iterdir() if f.is_file()):
            return "tum_vi"
        # Standard TUM RGB-D: rgb.txt file with timestamped images
        if (p / "rgb.txt").exists():
            return "tum"
        # EuRoC: mav0 directory or stereo/left images
        if (p / "mav0").exists():
            return "euroc"
        if (p / "stereo.txt").exists() or (p / "left.txt").exists():
            return "euroc"
        # KITTI: image directories
        if (p / "image_00").exists() or (p / "image_0").exists():
            return "kitti"
        return "unknown"

    def _find_single_image_dir(self, input_path: str) -> tuple:
        """Try to determine if input path is a TUM-style dataset directory."""
        p = Path(input_path)
        if not p.is_dir():
            return None, input_path
        # Check for rgb.txt or rgb/ directory (TUM format)
        if (p / "rgb.txt").exists():
            return "tum", str(p)
        # Check for image files directly in the directory
        images = sorted(p.glob("*.png")) or sorted(p.glob("*.jpg")) or sorted(p.glob("*.jpeg"))
        if images:
            return "images", str(p)
        return None, str(p)

    def _run_orb_slam3(self, input_path: str, output_dir: str) -> dict:
        exe_name = ""
        exe = self._pick_executable(input_path)
        if not exe:
            return {"status": "error",
                    "error": "ORB-SLAM3 not compiled. Run SLAM/ORB_SLAM3/build.sh first.",
                    "trajectory_file": "", "pointcloud_file": ""}
        exe_name = Path(exe).name

        if not Path(self.vocab_path).exists():
            return {"status": "error", "error": "ORBvoc.txt not found", "trajectory_file": "", "pointcloud_file": ""}

        # Auto-detect settings if not explicitly set
        if not self.settings_path:
            self.settings_path = self._settings_for_exe(exe_name)
        if not self.settings_path or not Path(self.settings_path).exists():
            return {"status": "error", "error": f"Settings YAML not found: {self.settings_path}",
                    "trajectory_file": "", "pointcloud_file": ""}

        # Determine input type (dataset format)
        fmt, resolved_input = self._find_single_image_dir(input_path)

        try:
            result = subprocess.run(
                [exe, self.vocab_path, self.settings_path, resolved_input],
                cwd=Path(exe).parent,
                capture_output=True, text=True, timeout=3600,
            )
            traj_file = Path(output_dir) / "KeyFrameTrajectory.txt"
            # Copy if exists (written to CWD = exe parent dir)
            src = Path(exe).parent / "KeyFrameTrajectory.txt"
            if src.exists():
                import shutil
                shutil.copy(str(src), str(traj_file))

            traj_ok = traj_file.exists() and traj_file.stat().st_size > 0
            completed = (result.returncode == 0) or traj_ok
            return {
                "status": "completed" if completed else "error",
                "trajectory_file": str(traj_file) if traj_ok else "",
                "pointcloud_file": "",
                "stdout": result.stdout[-500:],
                "stderr": result.stderr[-500:],
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "SLAM execution timed out (1h)",
                    "trajectory_file": "", "pointcloud_file": ""}
        except Exception as e:
            return {"status": "error", "error": str(e), "trajectory_file": "", "pointcloud_file": ""}

    def _run_vins_mono(self, input_path: str, output_dir: str) -> dict:
        return {"status": "not_implemented",
                "note": "VINS-Mono requires ROS. Use orb_slam3_inertial as alternative.",
                "trajectory_file": "", "pointcloud_file": ""}

    def parse_trajectory(self, file_path: str) -> list[dict]:
        """Parse a TUM-format trajectory file into list of poses."""
        if not Path(file_path).exists():
            return []
        poses = []
        with open(file_path) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 8:
                    poses.append({
                        "timestamp": float(parts[0]),
                        "tx": float(parts[1]), "ty": float(parts[2]), "tz": float(parts[3]),
                        "qx": float(parts[4]), "qy": float(parts[5]), "qz": float(parts[6]), "qw": float(parts[7]),
                    })
        return poses
