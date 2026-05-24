#!/usr/bin/env python3
"""MASt3R-SLAM ROS2 node — bridge between web backend and MASt3R inference.

Usage:
  python3 mast3r_node.py [--serve]

Protocol (stdin/stdout JSON):
  Input:  {"type":"frame","image_base64":"...","timestamp":123.4,"width":640,"height":480}
  Output: {"type":"cloud","points":[[x,y,z,r,g,b],...],"num_points":30000,"num_keyframes":4,"fps":0.6}
  Output: {"type":"status","frames_processed":5,"num_keyframes":4,"total_points":90000,"fps":0.6}
  Input:  {"type":"stop"}
"""

import sys
import json
import os
import subprocess
import threading
import queue

# ── ROS2 imports ──
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, PointCloud2, PointField
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import Header
import cv2
import numpy as np
import struct


class Mast3rBridgeNode(Node):
    """ROS2 node that bridges web requests to MASt3R-SLAM inference."""

    def __init__(self):
        super().__init__('mast3r_slam_bridge')
        self.get_logger().info('MASt3R-SLAM bridge starting...')

        # Publishers
        self.cloud_pub = self.create_publisher(PointCloud2, '/slam/cloud', 10)
        self.pose_pub = self.create_publisher(PoseStamped, '/slam/pose', 10)
        self.status_pub = self.create_publisher(Image, '/slam/status', 10)  # placeholder

        # Inference subprocess (Python 3.11 with CUDA)
        self.infer_proc = None
        self.infer_queue = queue.Queue()
        self.infer_thread = None

        # State
        self.frames_processed = 0
        self.num_keyframes = 0
        self.total_points = 0
        self.current_fps = 0.0
        self.running = True

        # Start inference process
        self._start_inference()

        # Start reader thread
        self.infer_thread = threading.Thread(target=self._read_inference, daemon=True)
        self.infer_thread.start()

        self.get_logger().info('MASt3R-SLAM bridge ready')

    def _python(self):
        """Get the slam3r conda Python 3.11 path."""
        candidates = [
            "/root/miniconda3/envs/slam3r/bin/python3.11",
            "/root/miniconda3/envs/slam3r/bin/python",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return "python3.11"

    def _start_inference(self):
        """Launch MASt3R inference subprocess (Python 3.11)."""
        script = os.path.join(os.path.dirname(__file__), "mast3r_infer_standalone.py")
        if not os.path.isfile(script):
            self.get_logger().error(f"inference script not found: {script}")
            return

        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = "4"
        env["PYTHONUNBUFFERED"] = "1"

        self.infer_proc = subprocess.Popen(
            [self._python(), script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self.get_logger().info(f"Inference subprocess started (PID {self.infer_proc.pid})")

        # Start stderr reader thread for logging
        def _read_stderr():
            for line in self.infer_proc.stderr:
                if line.strip():
                    self.get_logger().info(f"[infer] {line.strip()}")
        threading.Thread(target=_read_stderr, daemon=True).start()

    def _read_inference(self):
        """Read stdout from inference subprocess."""
        for line in self.infer_proc.stdout:
            try:
                msg = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "cloud":
                points = msg.get("points", [])
                self.frames_processed = msg.get("frames_processed", self.frames_processed)
                self.num_keyframes = msg.get("num_keyframes", self.num_keyframes)
                self.total_points = msg.get("total_points", self.total_points)
                self.current_fps = msg.get("fps", self.current_fps)

                # Publish point cloud
                self._publish_cloud(points)

                # Publish status
                self.get_logger().info(
                    f"Cloud: {len(points)} pts, {self.frames_processed} frames, "
                    f"{self.num_keyframes} KF, {self.total_points} total, {self.current_fps:.1f} FPS"
                )

                # Send to web via queue
                self.infer_queue.put(msg)

            elif msg_type == "status":
                self.frames_processed = msg.get("frames_processed", self.frames_processed)
                self.num_keyframes = msg.get("num_keyframes", self.num_keyframes)
                self.total_points = msg.get("total_points", self.total_points)
                self.current_fps = msg.get("fps", self.current_fps)
                self.infer_queue.put(msg)

            elif msg_type == "error":
                self.get_logger().error(f"Inference error: {msg.get('message', '')}")
                self.infer_queue.put(msg)

    def send_frame(self, image_b64, timestamp, width=640, height=480):
        """Send a frame to the inference subprocess for processing."""
        if self.infer_proc and self.infer_proc.poll() is None:
            msg = json.dumps({
                "type": "frame",
                "image_base64": image_b64,
                "timestamp": timestamp,
                "width": width,
                "height": height,
            })
            try:
                self.infer_proc.stdin.write(msg + "\n")
                self.infer_proc.stdin.flush()
            except BrokenPipeError:
                self.get_logger().error("Inference subprocess pipe broken")
                self._restart_inference()

    def get_result(self, timeout=5.0):
        """Get next result from inference queue. Returns None if timeout."""
        try:
            return self.infer_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        """Stop inference subprocess."""
        self.running = False
        if self.infer_proc and self.infer_proc.poll() is None:
            try:
                self.infer_proc.stdin.write(json.dumps({"type": "stop"}) + "\n")
                self.infer_proc.stdin.flush()
            except Exception:
                pass
            self.infer_proc.wait(timeout=5)
        self.get_logger().info("MASt3R-SLAM bridge stopped")

    def _restart_inference(self):
        self.get_logger().info("Restarting inference subprocess...")
        self._start_inference()
        if self.infer_thread:
            self.infer_thread = threading.Thread(target=self._read_inference, daemon=True)
            self.infer_thread.start()

    def _publish_cloud(self, points):
        """Publish point cloud as PointCloud2."""
        if not points:
            return

        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = "map"

        fields = [
            PointField(name='x', offset=0, datatype=PointField.FLOAT32, count=1),
            PointField(name='y', offset=4, datatype=PointField.FLOAT32, count=1),
            PointField(name='z', offset=8, datatype=PointField.FLOAT32, count=1),
            PointField(name='rgb', offset=12, datatype=PointField.UINT32, count=1),
        ]

        n = len(points)
        data = bytearray()
        for p in points:
            data.extend(struct.pack('<fff', p[0], p[1], p[2]))
            r, g, b = int(p[3]), int(p[4]), int(p[5])
            rgb = struct.pack('<I', (r << 16) | (g << 8) | b)
            data.extend(rgb)

        cloud = PointCloud2()
        cloud.header = header
        cloud.height = 1
        cloud.width = n
        cloud.fields = fields
        cloud.is_bigendian = False
        cloud.point_step = 16
        cloud.row_step = 16 * n
        cloud.is_dense = True
        cloud.data = bytes(data)

        self.cloud_pub.publish(cloud)


def main():
    """Run as standalone ROS2 node with stdin/stdout protocol."""
    rclpy.init()
    node = Mast3rBridgeNode()

    # Read stdin and forward frames to inference
    def _read_stdin():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "frame":
                node.send_frame(
                    msg.get("image_base64", ""),
                    msg.get("timestamp", 0.0),
                    msg.get("width", 640),
                    msg.get("height", 480),
                )
            elif msg.get("type") == "get_result":
                result = node.get_result(timeout=10.0)
                if result:
                    print(json.dumps(result), flush=True)
            elif msg.get("type") == "stop":
                break

    threading.Thread(target=_read_stdin, daemon=True).start()
    rclpy.spin(node)
    node.stop()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
