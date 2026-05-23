"""
ROS2 SLAM bridge — orchestrates the orb_slam3_ros ROS2 node from the Web backend.

Architecture:
  FastAPI → ros_slam_service → ROS2 orb_slam3_node → mono_tum
                                ↓
  Publishes images → /slam/image
  Calls → /slam/run → SLAM processes → publishes /slam/trajectory
"""
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from backend.config import settings

ORB_SLAM3_DIR = Path("/root/autodl-tmp/projects/see_world/SLAM/ORB_SLAM3")
VOCAB_PATH = ORB_SLAM3_DIR / "Vocabulary" / "ORBvoc.txt"
EXE_PATH = ORB_SLAM3_DIR / "Examples" / "Monocular" / "mono_tum"


class RosSlamService:
    """Manages communication between Web backend and ROS2 SLAM node."""

    def __init__(self):
        self._proc = None
        self._running = False

    @property
    def available(self) -> bool:
        """Check if ROS2 orb_slam3 node is running."""
        return self._running and self._proc is not None and self._proc.poll() is None

    def start(self, settings_yaml: str = "") -> str:
        """Launch the ROS2 orb_slam3 node as a subprocess."""
        if self.available:
            return "Already running"

        if not EXE_PATH.exists():
            return f"ORB-SLAM3 executable not found: {EXE_PATH}"
        if not VOCAB_PATH.exists():
            return f"Vocabulary not found: {VOCAB_PATH}"

        yaml_path = settings_yaml or str(ORB_SLAM3_DIR / "Examples" / "Monocular" / "phone_calibration.yaml")

        env = os.environ.copy()
        env["SEE_WORLD_SLAM_DIR"] = str(ORB_SLAM3_DIR)

        self._proc = subprocess.Popen(
            [str(EXE_PATH), str(VOCAB_PATH), yaml_path, "/dev/null"],
            cwd=str(ORB_SLAM3_DIR),
            env=env,
        )
        self._running = True

    def stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc.wait(timeout=5)
            self._proc = None
        self._running = False


# Singleton
ros_slam = RosSlamService()
