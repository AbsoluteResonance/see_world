#!/usr/bin/env python3
"""MASt3R-SLAM batch reconstruction — offline video → PLY + screenshots.

Protocol (stdin/stdout JSON):
  Input:  {"type":"start","video_path":"...","output_dir":"...",
           "max_frames":200,"frame_skip":5,"conf_threshold":1.5,"img_size":512}
  Output: {"type":"progress","stage":"extracting|inference|saving|screenshots",
           "current":N,"total":M,"message":"..."}
  Output: {"type":"result","ply_path":"...","num_points":N,"num_frames":N,
           "screenshots":["front.png","back.png","left.png","right.png"]}
  Output: {"type":"error","message":"..."}
  Output: {"type":"done"}
"""

import sys
import json
import os
import time
import io
from pathlib import Path

os.environ["OMP_NUM_THREADS"] = "4"

import numpy as np
import cv2
from PIL import Image

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
    "../../../../SLAM/MASt3R-SLAM"))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from mast3r_slam.config import load_config, set_global_config
from mast3r_slam.mast3r_utils import load_mast3r, mast3r_inference_mono
from mast3r_slam.frame import create_frame
from mast3r_slam.tracker import FrameTracker
import lietorch


# ── Helpers ──

def _out(msg):
    print(json.dumps(msg), flush=True)


def _log(msg):
    print(f"[mast3r_batch] {msg}", file=sys.stderr, flush=True)


class KeyframeList:
    def __init__(self):
        self._frames = []
    def last_keyframe(self):
        return self._frames[-1] if self._frames else None
    def __getitem__(self, idx):
        return self._frames[idx]
    def __setitem__(self, idx, frame):
        self._frames[idx] = frame
    def __len__(self):
        return len(self._frames)
    def append(self, frame):
        self._frames.append(frame)


# ── Reconstructor ──

class Mast3rBatchReconstructor:
    def __init__(self, device="cuda"):
        self.device = device
        self.model = None
        self.tracker = None
        self.keyframes = KeyframeList()
        self.frame_count = 0
        self.last_T_WC = None

    def init_model(self):
        _log("Loading MASt3R model...")
        ckpt = os.path.join(_PROJECT_ROOT, "checkpoints",
            "MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth")
        self.model = load_mast3r(ckpt, device=self.device)
        load_config(os.path.join(_PROJECT_ROOT, "config", "base.yaml"))
        set_global_config({"single_thread": True, "use_calib": False})
        self.tracker = FrameTracker(self.model, self.keyframes, self.device)
        _log("Model loaded")

    def extract_frames(self, video_path, max_frames=200, frame_skip=5,
                       target_size=(640, 480)):
        """Extract frames from video, return list of numpy arrays [0,1] RGB."""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {video_path}")

        total_in = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        _log(f"Video: {total_in} frames @ {fps:.1f} fps")

        frames = []
        count = 0
        while len(frames) < max_frames:
            ret, img_bgr = cap.read()
            if not ret:
                break
            if count % frame_skip != 0:
                count += 1
                continue
            count += 1

            # Letterbox resize
            h, w = img_bgr.shape[:2]
            target_w, target_h = target_size
            scale = min(target_w / w, target_h / h)
            nw, nh = int(w * scale), int(h * scale)
            resized = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_AREA)
            canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
            y_off = (target_h - nh) // 2
            x_off = (target_w - nw) // 2
            canvas[y_off:y_off + nh, x_off:x_off + nw] = resized

            # BGR → RGB, normalize to [0,1]
            img_rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            frames.append(img_rgb)

        cap.release()
        _log(f"Extracted {len(frames)} frames (skip={frame_skip})")
        return frames

    def process_frames(self, frames):
        """Run MASt3R on all frames, accumulate keyframes."""
        _log(f"Processing {len(frames)} frames...")
        for i, img_np in enumerate(frames):
            if self.frame_count == 0:
                T_WC = lietorch.Sim3.Identity(1, device=self.device)
            else:
                T_WC = self.last_T_WC

            frame = create_frame(self.frame_count, img_np, T_WC,
                                 img_size=512, device=self.device)

            if self.frame_count == 0:
                X, C = mast3r_inference_mono(self.model, frame)
                frame.update_pointmap(X, C)
                self.keyframes.append(frame)
            else:
                add_new_kf, _, try_reloc = self.tracker.track(frame)
                force_kf = (self.frame_count % 3 == 0)
                if (add_new_kf or force_kf) and len(self.keyframes) < 200:
                    self.keyframes.append(frame)

            self.last_T_WC = frame.T_WC
            self.frame_count += 1

            _out({
                "type": "progress",
                "stage": "inference",
                "current": i + 1,
                "total": len(frames),
                "message": f"处理帧 {i + 1}/{len(frames)} "
                           f"(关键帧: {len(self.keyframes)})",
            })

        _log(f"Inference done: {self.frame_count} frames, "
             f"{len(self.keyframes)} keyframes")

    def save_ply(self, output_path, conf_threshold=1.5):
        """Save accumulated point cloud as PLY with colors."""
        import plyfile
        _log(f"Saving PLY to {output_path} (conf_threshold={conf_threshold})")

        pointclouds = []
        colors = []
        for kf in self.keyframes:
            if kf.X_canon is None:
                continue
            pW = kf.T_WC.act(kf.X_canon).cpu().numpy().reshape(-1, 3)
            color = (kf.uimg.cpu().numpy() * 255).astype(np.uint8).reshape(-1, 3)
            valid = kf.get_average_conf().cpu().numpy().reshape(-1) > conf_threshold
            # Flip Y → Y-up
            pW_valid = pW[valid].copy()
            pW_valid[:, 1] = -pW_valid[:, 1]
            pointclouds.append(pW_valid)
            colors.append(color[valid])

        if not pointclouds:
            raise RuntimeError("No valid point clouds to save")

        points = np.concatenate(pointclouds, axis=0)
        cols = np.concatenate(colors, axis=0)
        _log(f"Total points: {len(points)}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        # Write PLY via plyfile
        dtype = [
            ("x", "f4"), ("y", "f4"), ("z", "f4"),
            ("red", "u1"), ("green", "u1"), ("blue", "u1"),
        ]
        arr = np.empty(len(points), dtype=dtype)
        arr["x"] = points[:, 0]
        arr["y"] = points[:, 1]
        arr["z"] = points[:, 2]
        arr["red"] = cols[:, 0]
        arr["green"] = cols[:, 1]
        arr["blue"] = cols[:, 2]
        plyfile.PlyData([plyfile.PlyElement.describe(arr, "vertex")],
                        text=False).write(output_path)
        _log("PLY saved")
        return len(points)

    def generate_screenshots(self, ply_path, output_dir, img_size=(800, 600)):
        """Render 4 screenshots using matplotlib (headless-safe)."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d import Axes3D
        _log("Generating screenshots...")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Read PLY points
        import open3d as o3d
        pcd = o3d.io.read_point_cloud(ply_path)
        pts = np.asarray(pcd.points)
        cols = np.asarray(pcd.colors)
        _log(f"  Point cloud: {len(pts)} points")

        if len(pts) == 0:
            _log("  WARNING: empty point cloud, no screenshots")
            return []

        bounds_min = pts.min(axis=0)
        bounds_max = pts.max(axis=0)
        center = (bounds_min + bounds_max) / 2
        extent = bounds_max - bounds_min
        max_dim = max(extent) or 1.0
        dist = max_dim * 2.0

        views = {
            "front": (center + np.array([0, 0, dist]), center),
            "back":  (center + np.array([0, 0, -dist]), center),
            "left":  (center + np.array([-dist, 0, 0]), center),
            "right": (center + np.array([dist, 0, 0]), center),
        }

        filenames = []
        for name, (eye, lookat) in views.items():
            fig = plt.figure(figsize=(img_size[0]/100, img_size[1]/100), dpi=100)
            ax = fig.add_subplot(111, projection="3d")
            ax.set_facecolor("#1a1a2e")
            fig.patch.set_facecolor("#1a1a2e")
            ax.grid(False)
            ax.axis("off")

            # Scatter with colors
            # Subsample if too many points for rendering speed
            if len(pts) > 50000:
                idx = np.random.choice(len(pts), 50000, replace=False)
                sp = pts[idx]
                sc = cols[idx]
            else:
                sp = pts
                sc = cols
            ax.scatter(sp[:, 0], sp[:, 1], sp[:, 2], c=sc, s=1, alpha=0.8)

            # Set equal aspect and view
            ax.set_xlim(bounds_min[0], bounds_max[0])
            ax.set_ylim(bounds_min[1], bounds_max[1])
            ax.set_zlim(bounds_min[2], bounds_max[2])
            ax.view_init(elev=0, azim=self._view_azimuth(name))

            fname = f"{name}.png"
            fig.savefig(str(output_dir / fname), dpi=100,
                        facecolor="#1a1a2e", bbox_inches="tight", pad_inches=0)
            plt.close(fig)
            filenames.append(fname)
            _log(f"  Screenshot: {fname}")

        return filenames

    @staticmethod
    def _view_azimuth(name):
        return {"front": 0, "back": 180, "left": 90, "right": -90}.get(name, 0)


# ── Main ──

def main():
    line = sys.stdin.readline()
    if not line:
        return
    try:
        msg = json.loads(line.strip())
    except json.JSONDecodeError as e:
        _out({"type": "error", "message": f"Invalid JSON: {e}"})
        _out({"type": "done"})
        return

    if msg.get("type") != "start":
        _out({"type": "error", "message": "Expected type=start"})
        _out({"type": "done"})
        return

    video_path = msg["video_path"]
    output_dir = Path(msg["output_dir"])
    max_frames = msg.get("max_frames", 200)
    frame_skip = msg.get("frame_skip", 5)
    conf_threshold = msg.get("conf_threshold", 1.5)
    img_size = msg.get("img_size", 512)
    max_points = msg.get("max_points_per_frame", 1000)

    try:
        # 1. Extract
        _out({"type": "progress", "stage": "extracting", "current": 0, "total": 1,
              "message": "提取视频帧…"})
        recon = Mast3rBatchReconstructor()
        recon.init_model()

        frames = recon.extract_frames(video_path, max_frames=max_frames,
                                       frame_skip=frame_skip)
        _out({"type": "progress", "stage": "extracting", "current": 1, "total": 1,
              "message": f"已提取 {len(frames)} 帧"})

        if len(frames) < 5:
            raise RuntimeError(f"Too few frames extracted: {len(frames)} (need ≥5)")

        # 2. Inference
        recon.process_frames(frames)

        # 3. Save PLY
        _out({"type": "progress", "stage": "saving", "current": 0, "total": 1,
              "message": "保存点云…"})
        output_dir.mkdir(parents=True, exist_ok=True)
        ply_path = str(output_dir / "pointcloud.ply")
        num_points = recon.save_ply(ply_path, conf_threshold=conf_threshold)
        _out({"type": "progress", "stage": "saving", "current": 1, "total": 1,
              "message": f"点云保存完成 ({num_points} 点)"})

        # 4. Screenshots
        _out({"type": "progress", "stage": "screenshots", "current": 0, "total": 1,
              "message": "生成截图…"})
        screenshot_dir = output_dir / "screenshots"
        screenshots = recon.generate_screenshots(ply_path, screenshot_dir)
        _out({"type": "progress", "stage": "screenshots", "current": 1, "total": 1,
              "message": f"截图完成 ({len(screenshots)} 张)"})

        # 5. Result
        _out({
            "type": "result",
            "ply_path": ply_path,
            "num_points": num_points,
            "num_frames": len(frames),
            "screenshots": screenshots,
        })
        _out({"type": "done"})
        _log("Batch reconstruction complete")

    except Exception as e:
        import traceback
        _log(f"Error: {e}\n{traceback.format_exc()}")
        _out({"type": "error", "message": str(e)})
        _out({"type": "done"})


if __name__ == "__main__":
    main()
