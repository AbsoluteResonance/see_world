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
        "mono_tum":              "Examples/Monocular/phone_calibration.yaml",
        "mono_kitti":            "Examples/Monocular/KITTI00-02.yaml",
        "mono_euroc":            "Examples/Monocular/EuRoC.yaml",
        "mono_tum_vi":           "Examples/Monocular/TUM-VI.yaml",
        "mono_inertial_euroc":   "Examples/Monocular-Inertial/EuRoC.yaml",
        "mono_inertial_tum_vi":  "Examples/Monocular-Inertial/TUM-VI.yaml",
    }

    def __init__(self, slam_type: str = "orb_slam3",
                 vocab_path: str = "",
                 settings_path: str = "",
                 workspace: str = ""):
        self.slam_type = slam_type
        # __file__ is at ORB_SLAM3/python/slam_runner.py → parent.parent = ORB_SLAM3/
        self.workspace = workspace or str(Path(__file__).resolve().parent.parent)
        self.vocab_path = vocab_path or self._default_vocab()
        self.settings_path = settings_path

    def _default_vocab(self) -> str:
        if self.slam_type == "orb_slam3":
            p = Path(self.workspace) / "Vocabulary" / "ORBvoc.txt"
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
        dtype = self._detect_dataset_type(input_path) if input_path else "unknown"
        dtype_map = {
            "tum":      ["mono_tum"],
            "euroc":    ["mono_inertial_euroc", "mono_euroc"],
            "kitti":    ["mono_kitti"],
            "tum_vi":   ["mono_inertial_tum_vi", "mono_tum_vi"],
        }
        candidates = dtype_map.get(dtype, self.EXE_PRIORITY)

        for name in candidates:
            exe = self._find_executable(name)
            if exe:
                return exe
        for name in self.EXE_PRIORITY:
            exe = self._find_executable(name)
            if exe:
                return exe
        return None

    def _settings_for_exe(self, exe_name: str) -> str:
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
        output_dir = output_dir or str(Path(self.workspace) / "output" / Path(input_path).name)
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        if self.slam_type in ("orb_slam3", "orb_slam3_inertial"):
            return self._run_orb_slam3(input_path, output_dir)
        elif self.slam_type == "vins_mono":
            return self._run_vins_mono(input_path, output_dir)
        else:
            return {"status": "error", "error": f"Unknown SLAM type: {self.slam_type}"}

    def _detect_dataset_type(self, input_path: str) -> str:
        p = Path(input_path)
        if not p.is_dir():
            return "unknown"
        if (p / "cam0").is_dir() or (p / "dso").is_dir():
            return "tum_vi"
        if any(f.name == "data.csv" for f in p.iterdir() if f.is_file()):
            return "tum_vi"
        if (p / "rgb.txt").exists():
            return "tum"
        if (p / "mav0").exists():
            return "euroc"
        if (p / "stereo.txt").exists() or (p / "left.txt").exists():
            return "euroc"
        if (p / "image_00").exists() or (p / "image_0").exists():
            return "kitti"
        return "unknown"

    def _run_orb_slam3(self, input_path: str, output_dir: str) -> dict:
        exe = self._pick_executable(input_path)
        if not exe:
            return {"status": "error",
                    "error": "ORB-SLAM3 not compiled. Run SLAM/ORB_SLAM3/build.sh first.",
                    "trajectory_file": "", "pointcloud_file": ""}
        exe_name = Path(exe).name

        if not Path(self.vocab_path).exists():
            return {"status": "error", "error": "ORBvoc.txt not found", "trajectory_file": "", "pointcloud_file": ""}

        if not self.settings_path:
            self.settings_path = self._settings_for_exe(exe_name)
        if not self.settings_path or not Path(self.settings_path).exists():
            return {"status": "error", "error": f"Settings YAML not found: {self.settings_path}",
                    "trajectory_file": "", "pointcloud_file": ""}

        fmt, resolved_input = self._find_single_image_dir(input_path)

        try:
            # Use workspace as CWD so trajectory saves to ORB_SLAM3/
            slam_cwd = Path(self.workspace)
            result = subprocess.run(
                [exe, self.vocab_path, self.settings_path, resolved_input],
                cwd=slam_cwd,
                capture_output=True, text=True, timeout=3600,
            )
            traj_file = Path(output_dir) / "KeyFrameTrajectory.txt"
            src = slam_cwd / "KeyFrameTrajectory.txt"
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

    def _find_single_image_dir(self, input_path: str) -> tuple:
        p = Path(input_path)
        if not p.is_dir():
            return None, input_path
        if (p / "rgb.txt").exists():
            return "tum", str(p)
        images = sorted(p.glob("*.png")) or sorted(p.glob("*.jpg")) or sorted(p.glob("*.jpeg"))
        if images:
            return "images", str(p)
        return None, str(p)

    def _run_vins_mono(self, input_path: str, output_dir: str) -> dict:
        return {"status": "not_implemented",
                "note": "VINS-Mono requires ROS. Use orb_slam3_inertial as alternative.",
                "trajectory_file": "", "pointcloud_file": ""}

    def parse_trajectory(self, file_path: str) -> list[dict]:
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
