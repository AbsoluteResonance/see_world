#!/usr/bin/env python3
"""MASt3R-SLAM inference subprocess — runs in Python 3.11 (slam3r env).

Protocol (stdin/stdout JSON):
  Input:  {"type":"frame","image_base64":"...","timestamp":123.4,"width":640,"height":480}
  Output: {"type":"cloud","points":[[x,y,z,r,g,b],...],"num_points":30000,...}
  Output: {"type":"status","frames_processed":5,...}
  Output: {"type":"error","message":"..."}
  Input:  {"type":"stop"}
"""

import sys
import json
import base64
import io
import time
import os

os.environ["OMP_NUM_THREADS"] = "4"

import numpy as np
from PIL import Image

# Add MASt3R-SLAM to path
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
    "../../../../SLAM/MASt3R-SLAM"))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from mast3r_slam.config import load_config, set_global_config
from mast3r_slam.mast3r_utils import load_mast3r, mast3r_inference_mono
from mast3r_slam.frame import create_frame
from mast3r_slam.tracker import FrameTracker
import lietorch


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


class Mast3rInference:
    """MASt3R-SLAM inference engine, runs in a subprocess."""

    def __init__(self):
        self.device = "cuda"
        self.model = None
        self.tracker = None
        self.keyframes = KeyframeList()
        self.frame_count = 0
        self.last_T_WC = None
        self.total_points = 0
        self.num_keyframes = 0
        self.smoothed_fps = 0.0

    def init(self):
        self._log("Loading MASt3R model...")
        ckpt = os.path.join(_PROJECT_ROOT, "checkpoints",
            "MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth")
        self.model = load_mast3r(ckpt, device=self.device)
        load_config(os.path.join(_PROJECT_ROOT, "config", "base.yaml"))
        set_global_config({"single_thread": True, "use_calib": False})
        self.tracker = FrameTracker(self.model, self.keyframes, self.device)
        self._log(f"Model loaded, device={self.device}")

    def process_frame(self, image_bytes, timestamp, max_points=500):
        start = time.time()
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_np = np.array(img).astype(np.float32) / 255.0

        if self.frame_count == 0:
            T_WC = lietorch.Sim3.Identity(1, device=self.device)
        else:
            T_WC = self.last_T_WC

        frame = create_frame(self.frame_count, img_np, T_WC, img_size=512, device=self.device)

        if self.frame_count == 0:
            X, C = mast3r_inference_mono(self.model, frame)
            frame.update_pointmap(X, C)
            self.keyframes.append(frame)
            status = "init"
        else:
            add_new_kf, _, try_reloc = self.tracker.track(frame)
            # Force new keyframe every 3 frames for fresh colors
            force_kf = (self.frame_count % 3 == 0)
            if (add_new_kf or force_kf) and len(self.keyframes) < 200:
                self.keyframes.append(frame)
            status = "reloc" if try_reloc else "tracking"

        self.last_T_WC = frame.T_WC
        self.frame_count += 1

        # Extract point cloud from ALL keyframes (accumulated)
        points = []
        pts_per_kf = max(int(max_points) // max(len(self.keyframes), 1), 50)
        for kidx in range(len(self.keyframes)):
            kf = self.keyframes[kidx]
            if kf.X_canon is None:
                continue
            pW = kf.T_WC.act(kf.X_canon).cpu().numpy().reshape(-1, 3)
            colors = (kf.uimg.cpu().numpy() * 255).astype(np.uint8).reshape(-1, 3)
            valid = kf.get_average_conf().cpu().numpy().reshape(-1) > 0.0
            pW = pW[valid]
            colors = colors[valid]
            if len(pW) > pts_per_kf:
                idx = np.random.choice(len(pW), pts_per_kf, replace=False)
                pW = pW[idx]
                colors = colors[idx]
            for i in range(len(pW)):
                points.append([
                    round(float(pW[i, 0]), 4),
                    round(-float(pW[i, 1]), 4),  # Y-down → Y-up
                    round(float(pW[i, 2]), 4),
                    int(colors[i, 0]), int(colors[i, 1]), int(colors[i, 2]),
                ])
        self.total_points = sum(len(kf.X_canon) for kf in self.keyframes if kf.X_canon is not None)
        self.num_keyframes = len(self.keyframes)

        elapsed = time.time() - start
        fps = 1.0 / elapsed if elapsed > 0 else 0
        self.smoothed_fps = self.smoothed_fps * 0.9 + fps * 0.1

        return {
            "type": "cloud",
            "points": points,
            "num_points": len(points),
            "frames_processed": self.frame_count,
            "num_keyframes": self.num_keyframes,
            "total_points": self.total_points,
            "fps": round(self.smoothed_fps, 1),
            "inference_ms": round(elapsed * 1000),
            "status": status,
            "timestamp": timestamp,
        }

    def _log(self, msg):
        print(f"[mast3r_infer] {msg}", file=sys.stderr, flush=True)


def main():
    infer = Mast3rInference()
    infer.init()
    infer._log("Ready")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        if msg.get("type") == "frame":
            try:
                image_b64 = msg.get("image_base64", "")
                timestamp = msg.get("timestamp", 0.0)
                max_points = msg.get("max_points", 500)
                image_bytes = base64.b64decode(image_b64)
                result = infer.process_frame(image_bytes, timestamp, max_points=max_points)
                print(json.dumps(result), flush=True)
            except Exception as e:
                import traceback
                error_msg = f"{e}\n{traceback.format_exc()}"
                infer._log(error_msg)
                print(json.dumps({"type": "error", "message": str(e)}), flush=True)

        elif msg.get("type") == "stop":
            break

    infer._log("Stopped")


if __name__ == "__main__":
    main()
