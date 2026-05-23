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

    def check_ready(self) -> dict:
        """Check if the SLAM system is built and ready."""
        if self.slam_type == "orb_slam3":
            exe = self._find_executable("mono_tum") or self._find_executable("mono_euroc")
            vocab_ok = Path(self.vocab_path).exists()
            return {"ready": exe is not None and vocab_ok,
                    "executable": exe or "not found",
                    "vocabulary": "found" if vocab_ok else "missing"}
        elif self.slam_type == "vins_mono":
            return {"ready": False, "note": "VINS-Mono requires ROS; check ROS workspace"}
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

        if self.slam_type == "orb_slam3":
            return self._run_orb_slam3(input_path, output_dir)
        elif self.slam_type == "vins_mono":
            return self._run_vins_mono(input_path, output_dir)
        else:
            return {"status": "error", "error": f"Unknown SLAM type: {self.slam_type}"}

    def _run_orb_slam3(self, input_path: str, output_dir: str) -> dict:
        exe = self._find_executable("mono_tum")
        if not exe:
            return {"status": "error",
                    "error": "ORB-SLAM3 not compiled. Run scripts/setup_orb_slam3.sh first.",
                    "trajectory_file": "", "pointcloud_file": ""}

        if not Path(self.vocab_path).exists():
            return {"status": "error", "error": "ORBvoc.txt not found", "trajectory_file": "", "pointcloud_file": ""}
        if not Path(self.settings_path).exists():
            return {"status": "error", "error": f"Settings YAML not found: {self.settings_path}", "trajectory_file": "", "pointcloud_file": ""}

        try:
            result = subprocess.run(
                [exe, self.vocab_path, self.settings_path, input_path],
                cwd=Path(exe).parent,
                capture_output=True, text=True, timeout=3600
            )
            traj_file = Path(output_dir) / "KeyFrameTrajectory.txt"
            # Copy if exists
            src = Path(exe).parent / "KeyFrameTrajectory.txt"
            if src.exists():
                import shutil
                shutil.copy(str(src), str(traj_file))

            return {
                "status": "completed" if result.returncode == 0 else "error",
                "trajectory_file": str(traj_file) if traj_file.exists() else "",
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
                "note": "VINS-Mono requires ROS. See scripts/setup_vins_mono.sh",
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
