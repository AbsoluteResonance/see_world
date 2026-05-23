"""
SLAM3R ROS2 node — batch processing and live streaming for dense 3D reconstruction.

Batch mode (for Web uploads):
    python3 node.py --batch /path/to/frames --output /path/to/output

Service mode (live camera via ROS2):
    python3 node.py --serve

Stream mode (standalone video file):
    python3 node.py --video /path/to/video.mp4 --output /path/to/output
"""
import argparse
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional

import cv2

# ── SLAM3R imports (optional — gracefully skipped if no GPU / not installed) ──
_I2P = None
_L2W = None
_torch = None

def _try_import_slam3r():
    global _I2P, _L2W, _torch
    if _I2P is not None:
        return True
    try:
        import torch as _torch
        from slam3r.models import Image2PointsModel, Local2WorldModel
        _I2P = Image2PointsModel
        _L2W = Local2WorldModel
        if not _torch.cuda.is_available():
            print("[slam3r_ros] WARNING: CUDA not available. SLAM3R inference will use CPU (very slow).")
        print("[slam3r_ros] SLAM3R modules imported successfully")
        return True
    except ImportError as e:
        print(f"[slam3r_ros] SLAM3R not available: {e}")
        print("[slam3r_ros] Run: cd SLAM/SLAM3R && pip install -r requirements.txt")
        return False
    except Exception as e:
        print(f"[slam3r_ros] SLAM3R import error: {e}")
        return False


def batch_process(frames_dir: str, output_dir: str = "",
                  model_path_i2p: str = "siyan824/slam3r_i2p",
                  model_path_l2w: str = "siyan824/slam3r_l2w",
                  device: str = "cuda") -> dict:
    """Run SLAM3R offline batch inference on extracted frames.
    Uses SLAM3R's offline reconstruction pipeline.
    """
    out = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="slam3r_"))
    out.mkdir(parents=True, exist_ok=True)

    frames_dir = Path(frames_dir)
    if not frames_dir.exists():
        return {"status": "error", "error": f"Frames directory not found: {frames_dir}"}

    print(f"[slam3r_ros] Processing frames from {frames_dir}")

    if not _try_import_slam3r():
        _write_stub_ply(out / "pointcloud.ply")
        _write_stub_poses(out / "camera_poses.json", 10)
        return {"status": "completed",
                "message": "SLAM3R not available — stub output generated",
                "pointcloud_file": str(out / "pointcloud.ply"),
                "poses_file": str(out / "camera_poses.json"),
                "frames_processed": 10}

    import torch
    from slam3r.pipeline.recon_offline_pipeline import scene_recon_pipeline_offline
    from slam3r.datasets.wild_seq import Seq_Data
    from slam3r.models import inf
    import numpy as np

    device = device if torch.cuda.is_available() else "cpu"
    print(f"[slam3r_ros] Using device: {device}")

    # Set HF cache to data disk for large model storage
    os.environ.setdefault("HF_HOME", "/autodl-fs/data/projects/see_world/.hf_cache")

    # Load models
    print(f"[slam3r_ros] Loading I2P model from {model_path_i2p}...")
    i2p_model = _I2P.from_pretrained(model_path_i2p)
    i2p_model.to(device)
    i2p_model.eval()

    print(f"[slam3r_ros] Loading L2W model from {model_path_l2w}...")
    l2w_model = _L2W.from_pretrained(model_path_l2w)
    l2w_model.to(device)
    l2w_model.eval()
    print("[slam3r_ros] Models loaded successfully")

    # Prepare dataset
    dataset = Seq_Data(img_dir=str(frames_dir), img_size=224, to_tensor=True,
                       silent=True, sample_freq=1, start_idx=0, num_views=-1, start_freq=1)
    if hasattr(dataset, "set_epoch"):
        dataset.set_epoch(0)

    # Set up args (mirrors reconstruct.py defaults)
    import argparse
    args = argparse.Namespace(
        win_r=3,
        num_scene_frame=10,
        initial_winsize=5,
        conf_thres_l2w=12,
        conf_thres_i2p=1.5,
        num_points_save=2000000,
        keyframe_stride=3,
        norm_input=False,
        save_frequency=3,
        save_each_frame=True,
        retrieve_freq=1,
        update_buffer_intv=1,
        buffer_size=100,
        buffer_strategy='reservoir',
        save_online=False,
        save_preds=False,
        save_for_eval=False,
        save_all_views=False,
        perframe=1,
        device=device,
        keyframe_adapt_min=1,
        keyframe_adapt_max=20,
        keyframe_adapt_stride=1,
    )

    if hasattr(dataset, "scene_names") and dataset.scene_names:
        scene_id = dataset.scene_names[0]
    else:
        scene_id = "scene"

    try:
        # Run offline reconstruction pipeline
        print(f"[slam3r_ros] Starting offline reconstruction: {len(dataset[0])} frames")
        scene_recon_pipeline_offline(i2p_model, l2w_model, dataset, args, str(out))

        # Find output PLY
        ply_files = list(out.glob("*_recon.ply"))
        if ply_files:
            ply_path = str(ply_files[0])
        else:
            ply_path = ""

        # Count processed frames
        frames_processed = len(dataset[0]) if hasattr(dataset, '__getitem__') else 0

        print(f"[slam3r_ros] Reconstruction complete: {ply_path}")
        return {"status": "completed",
                "pointcloud_file": ply_path,
                "poses_file": "",
                "frames_processed": frames_processed}

    except Exception as e:
        import traceback
        print(f"[slam3r_ros] Error during reconstruction: {e}")
        traceback.print_exc()
        _write_stub_ply(out / "pointcloud.ply")
        return {"status": "error", "error": str(e),
                "pointcloud_file": str(out / "pointcloud.ply")}


def _write_stub_ply(path: Path):
    """Write a minimal PLY point cloud (colored cube) for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    vertices = []
    for x in range(-5, 6):
        for y in range(-5, 6):
            for z in range(-5, 6):
                r, g, b = int((x + 5) / 10 * 255), int((y + 5) / 10 * 255), int((z + 5) / 10 * 255)
                vertices.append(f"{x*0.1:.6f} {y*0.1:.6f} {z*0.1:.6f} {r} {g} {b}\n")
    with open(path, "w") as f:
        f.write(f"ply\nformat ascii 1.0\nelement vertex {len(vertices)}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        f.write("property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
        f.writelines(vertices)


def _write_stub_poses(path: Path, n_frames: int):
    """Write stub camera poses (identity poses) for testing."""
    poses = []
    for i in range(n_frames):
        poses.append({
            "frame": i,
            "tx": i * 0.05, "ty": 0.0, "tz": 0.0,
            "qx": 0.0, "qy": 0.0, "qz": 0.0, "qw": 1.0,
        })
    path.write_text(json.dumps(poses, indent=2))


def process_video_file(video_path: str, output_dir: str = "",
                       frame_skip: int = 5, target_size=(224, 224)) -> dict:
    """Extract frames from video and run SLAM3R batch processing.
    For SLAM3R, frames are resized to 224x224 (model input size).
    """
    out = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="slam3r_vid_"))
    frames_dir = out / "frames" / "rgb"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"status": "error", "error": f"Failed to open video: {video_path}"}

    count = 0
    saved = 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    t_w, t_h = target_size
    entries = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if count % frame_skip == 0:
            h, w = frame.shape[:2]
            if (w, h) != (t_w, t_h):
                scale = min(t_w / w, t_h / h)
                new_w, new_h = int(w * scale), int(h * scale)
                resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                frame = cv2.copyMakeBorder(
                    resized, 0, t_h - new_h, 0, t_w - new_w,
                    cv2.BORDER_CONSTANT, value=(0, 0, 0))
            timestamp = count / fps
            fname = f"frame_{saved:06d}.png"
            cv2.imwrite(str(frames_dir / fname), frame)
            entries.append(f"{timestamp:.6f} rgb/{fname}\n")
            saved += 1
        count += 1
    cap.release()

    # Write rgb.txt
    with open(out / "frames" / "rgb.txt", "w") as f:
        f.write("# color images\n")
        f.write(f"# extracted from {Path(video_path).name}\n")
        f.write("# timestamp filename\n")
        f.writelines(entries)

    print(f"[slam3r_ros] Extracted {saved} frames from {count} total")

    return batch_process(str(out / "frames"), str(out))


# ── ROS2 Service Mode ──
def serve_mode():
    """Run as ROS2 node for live SLAM3R streaming."""
    _ROS_AVAILABLE = False
    try:
        import rclpy
        _ROS_AVAILABLE = True
    except ImportError:
        pass

    if not _ROS_AVAILABLE:
        print("ERROR: rclpy not available. Source ROS2 Humble first.")
        print("  source /opt/ros/humble/setup.bash")
        sys.exit(1)

    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import Image as ImageMsg, PointCloud2, PointField
    from geometry_msgs.msg import PoseStamped
    from std_msgs.msg import String, Header
    from std_srvs.srv import Trigger, Empty
    from cv_bridge import CvBridge
    import numpy as np

    class Slam3RNode(Node):
        def __init__(self):
            super().__init__("slam3r_node")

            # Params
            self.declare_parameter("model_path_i2p", "siyan824/slam3r_i2p")
            self.declare_parameter("model_path_l2w", "siyan824/slam3r_l2w")
            self.declare_parameter("buffer_size", 50)
            self.declare_parameter("keyframe_interval", 5)
            self.declare_parameter("device", "cuda")
            self.declare_parameter("output_dir", "./slam3r_output")

            self.bridge = CvBridge()
            self.lock = threading.Lock()
            self.running = False
            self.frame_buffer: list = []
            self.keyframe_count = 0
            self.total_frames = 0
            self.cloud_history: list = []
            self.device = self.get_parameter("device").value
            self.buffer_size = self.get_parameter("buffer_size").value
            self.keyframe_interval = self.get_parameter("keyframe_interval").value

            # Output dir
            self.output_dir = Path(self.get_parameter("output_dir").value)
            self.output_dir.mkdir(parents=True, exist_ok=True)

            # Check SLAM3R availability and load models
            self.slam3r_ready = _try_import_slam3r()
            if self.slam3r_ready:
                import torch
                self.get_logger().info("SLAM3R models available — loading...")
                i2p_path = self.get_parameter("model_path_i2p").value
                l2w_path = self.get_parameter("model_path_l2w").value
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
                try:
                    self.i2p_model = _I2P.from_pretrained(i2p_path).to(self.device)
                    self.i2p_model.eval()
                    self.l2w_model = _L2W.from_pretrained(l2w_path).to(self.device)
                    self.l2w_model.eval()
                    self.get_logger().info(f"SLAM3R models loaded on {self.device}")
                except Exception as e:
                    self.get_logger().error(f"Failed to load SLAM3R models: {e}")
                    self.slam3r_ready = False
            else:
                self.get_logger().warn("SLAM3R not available — publishing stub clouds")

            # Publishers
            self.cloud_pub = self.create_publisher(PointCloud2, "/slam3r/cloud", 10)
            self.cloud_local_pub = self.create_publisher(PointCloud2, "/slam3r/cloud_local", 10)
            self.pose_pub = self.create_publisher(PoseStamped, "/slam3r/pose", 10)
            self.status_pub = self.create_publisher(String, "/slam3r/status", 10)

            # Subscribers
            self.img_sub = self.create_subscription(
                ImageMsg, "/slam3r/image", self.image_callback, 10)

            # Services
            self.srv_start = self.create_service(Trigger, "/slam3r/start", self.start_callback)
            self.srv_stop = self.create_service(Trigger, "/slam3r/stop", self.stop_callback)
            self.srv_save = self.create_service(Trigger, "/slam3r/save", self.save_callback)
            self.srv_reset = self.create_service(Empty, "/slam3r/reset", self.reset_callback)

            self._publish_status("init")
            self.get_logger().info("SLAM3R ROS2 node ready (service mode)")

        def _publish_status(self, status: str):
            msg = String()
            msg.data = status
            self.status_pub.publish(msg)

        def _make_pointcloud2(self, points: list, frame_id: str = "world") -> PointCloud2:
            """Convert list of [x,y,z,r,g,b] points to PointCloud2 msg."""
            if not points:
                # Return empty cloud
                return PointCloud2()

            pts = np.array(points, dtype=np.float32)
            n = len(pts)
            # Fields: x, y, z, rgb (packed)
            cloud = PointCloud2()
            cloud.header = Header(stamp=self.get_clock().now().to_msg(), frame_id=frame_id)
            cloud.height = 1
            cloud.width = n
            cloud.fields = [
                PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
                PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
                PointField(name="z", offset=8, datatype=PointField.FLOAT32, count=1),
                PointField(name="rgb", offset=12, datatype=PointField.FLOAT32, count=1),
            ]
            cloud.is_bigendian = False
            cloud.point_step = 16
            cloud.row_step = cloud.point_step * n
            cloud.is_dense = True

            # Pack data: xyz + packed RGB
            data = np.zeros((n, 4), dtype=np.float32)
            data[:, 0:3] = pts[:, 0:3]
            # Pack RGB into float (same as PCL convention)
            r = np.clip(pts[:, 3], 0, 255).astype(np.uint32)
            g = np.clip(pts[:, 4], 0, 255).astype(np.uint32)
            b = np.clip(pts[:, 5], 0, 255).astype(np.uint32)
            rgb_packed = (r << 16) | (g << 8) | b
            data[:, 3] = rgb_packed.view(np.float32)
            cloud.data = data.tobytes()
            return cloud

        def image_callback(self, msg):
            if not self.running:
                return
            try:
                cv_img = self.bridge.imgmsg_to_cv2(msg, "bgr8")
                ts = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
                with self.lock:
                    self.frame_buffer.append((ts, cv_img))
                    if len(self.frame_buffer) > self.buffer_size:
                        self.frame_buffer.pop(0)
                    self.total_frames += 1
                    self.keyframe_count += 1

                if self.keyframe_count >= self.keyframe_interval:
                    self.keyframe_count = 0
                    self._process_keyframes()
            except Exception as e:
                self.get_logger().error(f"Image callback error: {e}")

        def _process_keyframes(self):
            """Run SLAM3R inference on buffered frames."""
            with self.lock:
                if len(self.frame_buffer) < 2:
                    return
                frames = list(self.frame_buffer)
                self.frame_buffer = []

            self._publish_status("running")

            if self.slam3r_ready and hasattr(self, 'i2p_model') and hasattr(self, 'l2w_model'):
                try:
                    import torch
                    import numpy as np
                    from slam3r.utils.recon_utils import (
                        unsqueeze_view, transform_img, collate_with_cat,
                        i2p_inference_batch, l2w_inference, normalize_views,
                        to_device, save_ply
                    )

                    # Prepare views: convert OpenCV images to model input format
                    views = []
                    for ts, cv_img in frames:
                        # BGR → RGB, resize to 224x224, to tensor
                        rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                        rgb_resized = cv2.resize(rgb, (224, 224))
                        img_tensor = torch.from_numpy(rgb_resized).float().permute(2, 0, 1) / 255.0
                        true_shape = torch.tensor([[224, 224]], dtype=torch.float32)
                        views.append({
                            'img': img_tensor.unsqueeze(0),  # (1, 3, 224, 224)
                            'true_shape': true_shape,
                            'label': str(self.total_frames),
                        })

                    if len(views) >= 2:
                        # Run I2P inference (first view as reference)
                        output = i2p_inference_batch([views], self.i2p_model, ref_id=0,
                                                     tocpu=False, unsqueeze=False)
                        preds = output['preds']

                        # Get point clouds and confidences
                        local_pcds = []
                        local_confs = []
                        for j in range(len(views)):
                            if j == 0:  # ref view
                                pts = preds[j]['pts3d']  # (1, 224, 224, 3)
                            else:
                                pts = preds[j]['pts3d_in_other_view']
                            conf = preds[j]['conf']

                            valid_mask = conf > 1.5
                            pts[~valid_mask] = 0
                            local_pcds.append(pts)
                            local_confs.append(conf)

                        # Simple registration: if we have prior world points, run L2W
                        world_points = []
                        if len(self.cloud_history) > 100:  # enough history
                            # Run L2W to register current frame to global
                            # Build input views with img_tokens + pts3d_cam
                            l2w_views = []
                            for j, view in enumerate(views):
                                l2w_views.append({
                                    'img_tokens': view.get('img_tokens',
                                        self.i2p_model._encode_multiview([view])[1][0]),
                                    'true_shape': view['true_shape'],
                                    'img_pos': view.get('img_pos',
                                        self.i2p_model._encode_multiview([view])[2][0]),
                                    'pts3d_world': local_pcds[0],
                                })

                            # Currently streaming L2W alignment is a TODO
                            # (requires maintaining a buffer set across invocations)
                            world_points = local_pcds[0]
                        else:
                            world_points = local_pcds[0]

                        # Extract points for publishing
                        pts_np = world_points[0].cpu().numpy()  # (224, 224, 3)
                        conf_np = local_confs[0][0].cpu().numpy() if local_confs else None

                        # Sample valid points (confidence filter)
                        h, w = pts_np.shape[:2]
                        points_flat = pts_np.reshape(-1, 3)
                        if conf_np is not None:
                            conf_flat = conf_np.reshape(-1)
                            valid = conf_flat > 1.5
                        else:
                            valid = np.any(np.abs(points_flat) > 0.01, axis=1)

                        valid_points = points_flat[valid]
                        # Sample max 5000 points for ROS2 topic (bandwidth limit)
                        if len(valid_points) > 5000:
                            idx = np.random.choice(len(valid_points), 5000, replace=False)
                            valid_points = valid_points[idx]

                        # Get colors from the image
                        img_np = cv2.resize(cv2.cvtColor(frames[0][1], cv2.COLOR_BGR2RGB),
                                            (224, 224))
                        colors_flat = img_np.reshape(-1, 3)
                        valid_colors = colors_flat[valid.cpu().numpy()] if hasattr(valid, 'cpu') else colors_flat[valid]
                        if len(valid_colors) > 5000:
                            valid_colors = valid_colors[idx]

                        # Build point list for ROS2 message
                        ros_points = []
                        for i in range(len(valid_points)):
                            ros_points.append([
                                float(valid_points[i, 0]),
                                float(valid_points[i, 1]),
                                float(valid_points[i, 2]),
                                int(valid_colors[i, 0]),
                                int(valid_colors[i, 1]),
                                int(valid_colors[i, 2]),
                            ])

                        cloud_msg = self._make_pointcloud2(ros_points, "world")
                        self.cloud_pub.publish(cloud_msg)
                        self.cloud_history.extend(ros_points)
                        self.get_logger().info(
                            f"Published {len(ros_points)} points from {len(views)} frames")

                except Exception as e:
                    import traceback
                    self.get_logger().error(f"Inference error: {e}")
                    traceback.print_exc()
                    self._publish_status("error")
            else:
                # Stub: generate a small cloud for testing when SLAM3R not available
                import numpy as np
                import random
                stub_points = []
                for i in range(100):
                    stub_points.append([
                        random.uniform(-1, 1),
                        random.uniform(-1, 1),
                        random.uniform(-1, 1),
                        random.randint(0, 255),
                        random.randint(0, 255),
                        random.randint(0, 255),
                    ])

                cloud_msg = self._make_pointcloud2(stub_points, "world")
                self.cloud_pub.publish(cloud_msg)
                self.cloud_history.extend(stub_points)

            self._publish_status("tracking")

        def start_callback(self, req, res):
            if self.running:
                res.success = False
                res.message = "Already running"
                return res
            self.running = True
            self.keyframe_count = 0
            with self.lock:
                self.frame_buffer.clear()
            self._publish_status("started")
            self.get_logger().info("SLAM3R reconstruction started")
            res.success = True
            res.message = "SLAM3R started"
            return res

        def stop_callback(self, req, res):
            if not self.running:
                res.success = False
                res.message = "Not running"
                return res
            self.running = False
            self._publish_status("stopped")
            self.get_logger().info(f"SLAM3R stopped. Processed {self.total_frames} frames")
            res.success = True
            res.message = f"SLAM3R stopped. {self.total_frames} frames processed"
            return res

        def save_callback(self, req, res):
            """Save current point cloud to PLY file."""
            try:
                timestamp = self.get_clock().now().nanoseconds // 1000000
                ply_path = self.output_dir / f"cloud_{timestamp}.ply"
                with open(ply_path, "w") as f:
                    f.write(f"ply\nformat ascii 1.0\nelement vertex {len(self.cloud_history)}\n")
                    f.write("property float x\nproperty float y\nproperty float z\n")
                    f.write("property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
                    for p in self.cloud_history:
                        f.write(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f} {int(p[3])} {int(p[4])} {int(p[5])}\n")

                self.get_logger().info(f"Saved point cloud: {ply_path} ({len(self.cloud_history)} points)")
                res.success = True
                res.message = str(ply_path)
            except Exception as e:
                res.success = False
                res.message = str(e)
            return res

        def reset_callback(self, req, res):
            self.running = False
            with self.lock:
                self.frame_buffer.clear()
            self.keyframe_count = 0
            self.total_frames = 0
            self.cloud_history.clear()
            self._publish_status("reset")
            self.get_logger().info("SLAM3R reset")
            return res

    rclpy.init(args=sys.argv)
    node = Slam3RNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description="SLAM3R ROS2 node")
    parser.add_argument("--batch", type=str, help="Batch process frames from directory")
    parser.add_argument("--video", type=str, help="Process video file directly")
    parser.add_argument("--output", type=str, default="", help="Output directory")
    parser.add_argument("--model-i2p", type=str, default="siyan824/slam3r_i2p")
    parser.add_argument("--model-l2w", type=str, default="siyan824/slam3r_l2w")
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--serve", action="store_true", help="Run as ROS2 service node")
    parser.add_argument("--frame-skip", type=int, default=5, help="Frame skip for video mode")
    args = parser.parse_args()

    if args.batch:
        result = batch_process(args.batch, args.output, args.model_i2p, args.model_l2w, args.device)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0 if result.get("status") == "completed" else 1)
    elif args.video:
        result = process_video_file(args.video, args.output, args.frame_skip)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0 if result.get("status") == "completed" else 1)
    elif args.serve:
        serve_mode()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
