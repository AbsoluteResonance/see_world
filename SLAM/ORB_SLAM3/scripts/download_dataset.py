#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download SLAM test datasets (TUM RGB-D, EuRoC MAV).

Usage:
    python scripts/download_dataset.py --dataset tum --sequence fr1_desk
    python scripts/download_dataset.py --dataset euroc --sequence MH_05
"""

import argparse
import os
import sys
import urllib.request
import tarfile
from pathlib import Path

DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"

TUM_SEQUENCES = {
    "fr1_desk":  ("http://vision.in.tum.de/rgbd/dataset/freiburg1/rgbd_dataset_freiburg1_desk.tgz", "1.2 GB"),
    "fr1_xyz":   ("http://vision.in.tum.de/rgbd/dataset/freiburg1/rgbd_dataset_freiburg1_xyz.tgz", "0.9 GB"),
    "fr2_xyz":   ("http://vision.in.tum.de/rgbd/dataset/freiburg2/rgbd_dataset_freiburg2_xyz.tgz", "1.1 GB"),
    "fr3_walk":  ("http://vision.in.tum.de/rgbd/dataset/freiburg3/rgbd_dataset_freiburg3_walking_halfsphere.tgz", "1.5 GB"),
}

EUROC_SEQUENCES = {
    "MH_01": ("http://robotics.ethz.ch/~asl-datasets/2021.02.01-euroc-mav-dataset/Machine_Hall/MH_01_easy/MH_01_easy.zip", "4.0 GB"),
    "MH_05": ("http://robotics.ethz.ch/~asl-datasets/2021.02.01-euroc-mav-dataset/Machine_Hall/MH_05_difficult/MH_05_difficult.zip", "3.8 GB"),
    "V1_01": ("http://robotics.ethz.ch/~asl-datasets/2021.02.01-euroc-mav-dataset/Vicon_1/V1_01_easy/V1_01_easy.zip", "1.2 GB"),
}

TUM_SMALL = {
    "fr1_desk2": ("https://cvg.cit.tum.de/rgbd/dataset/freiburg1/rgbd_dataset_freiburg1_desk2.tgz", "0.9 GB"),
}


def download_file(url: str, dest: Path) -> None:
    """Download with progress display."""
    print(f"Downloading {url} ...")
    try:
        urllib.request.urlretrieve(url, dest)
        print(f"Saved to {dest}")
    except Exception as e:
        print(f"Download failed: {e}")
        if dest.exists():
            dest.unlink()
        sys.exit(1)


def extract_tar(path: Path, dest: Path) -> None:
    print(f"Extracting {path} to {dest} ...")
    with tarfile.open(path, "r:gz") as tar:
        tar.extractall(path=dest)
    print(f"Extracted to {dest}")
    path.unlink()
    print("Removed archive")


def main():
    parser = argparse.ArgumentParser(description="Download SLAM test datasets")
    parser.add_argument("--dataset", choices=["tum", "euroc", "tum_small"], default="tum_small",
                        help="Dataset to download (default: tum_small for limited disk)")
    parser.add_argument("--sequence", default="fr1_desk2",
                        help="Sequence name (default: fr1_desk2 for TUM, MH_01 for EuRoC)")
    parser.add_argument("--dir", default=str(DATASETS_DIR),
                        help=f"Download directory (default: {DATASETS_DIR})")
    args = parser.parse_args()

    dest_dir = Path(args.dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    if args.dataset == "tum" or args.dataset == "tum_small":
        sequences = TUM_SMALL if args.dataset == "tum_small" else TUM_SEQUENCES
        if args.sequence not in sequences:
            print(f"Available TUM sequences: {list(sequences.keys())}")
            sys.exit(1)
        url, size = sequences[args.sequence]
        print(f"Sequence: {args.sequence} (~{size})")
        fname = url.rstrip("/").split("/")[-1]
        archive_path = dest_dir / fname
        if archive_path.exists():
            print(f"Archive already exists: {archive_path}")
        else:
            download_file(url, archive_path)
        extract_dir = dest_dir / args.sequence
        if extract_dir.exists():
            print(f"Already extracted at {extract_dir}")
        else:
            extract_tar(archive_path, dest_dir)
        print(f"Dataset ready at: {extract_dir}")
        print(f"  images: {(extract_dir / 'rgb')}")

    elif args.dataset == "euroc":
        sequences = EUROC_SEQUENCES
        if args.sequence not in sequences:
            print(f"Available EuRoC sequences: {list(sequences.keys())}")
            sys.exit(1)
        url, size = sequences[args.sequence]
        print(f"Sequence: {args.sequence} (~{size})")
        print("Note: EuRoC dataset is large. Ensure sufficient disk space.")
        fname = url.rstrip("/").split("/")[-1]
        archive_path = dest_dir / fname
        if archive_path.exists():
            print(f"Archive already exists: {archive_path}")
        else:
            download_file(url, archive_path)
        # Extract zip
        import zipfile
        extract_dir = dest_dir / f"euroc_{args.sequence}"
        if extract_dir.exists():
            print(f"Already extracted at {extract_dir}")
        else:
            print(f"Extracting {archive_path} ...")
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(path=dest_dir)
            archive_path.unlink()
        print(f"Dataset ready at: {extract_dir}")


if __name__ == "__main__":
    main()
