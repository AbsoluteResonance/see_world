#!/usr/bin/env python3
"""
Multi-threaded directory copy with progress bar.
Usage:
    python3 tools/copy_progress.py /source/dir /dest/dir [--workers 8]
"""

import os
import sys
import shutil
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm


def copy_file(src: str, dst: str) -> tuple[str, int]:
    """Copy a single file, return (path, size)."""
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        size = os.path.getsize(src)
        return (src, size)
    except Exception as e:
        return (f"{src}: {e}", 0)


def collect_files(root: str) -> list[tuple[str, str, int]]:
    """Walk directory and collect all (src_path, dst_path, size)."""
    items = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        for f in filenames:
            src = os.path.join(dirpath, f)
            try:
                sz = os.path.getsize(src)
            except OSError:
                sz = 0
            items.append((src, rel, f, sz))

        for d in dirnames:
            src = os.path.join(dirpath, d)
            # also collect symlinks to dirs
            if os.path.islink(src):
                items.append((src, rel, d, 0))
    return items


def main():
    parser = argparse.ArgumentParser(description="Multi-threaded copy with progress")
    parser.add_argument("src", help="Source directory")
    parser.add_argument("dst", help="Destination directory")
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel threads")
    args = parser.parse_args()

    src_root = Path(args.src).resolve()
    dst_root = Path(args.dst).resolve()

    if not src_root.exists():
        print(f"Error: source {src_root} does not exist")
        sys.exit(1)

    print(f"Scanning {src_root} ...")
    all_items = list(src_root.rglob("*"))
    # separate dirs, symlinks, and files
    dirs = sorted(p for p in all_items if p.is_dir() and not p.is_symlink())
    symlinks = sorted(p for p in all_items if p.is_symlink())
    files = sorted(p for p in all_items if p.is_file())

    # total size for progress
    total_bytes = sum(f.stat(follow_symlinks=False).st_size for f in files if f.exists())
    file_count = len(files)
    print(f"  {len(dirs)} directories, {file_count} files, {total_bytes / 1e9:.1f} GB")

    # create destination dirs first
    print("Creating directories ...")
    for d in dirs:
        rel = d.relative_to(src_root)
        (dst_root / rel).mkdir(parents=True, exist_ok=True)
    dst_root.mkdir(parents=True, exist_ok=True)

    # copy symlinks
    for link in symlinks:
        rel = link.relative_to(src_root)
        target = os.readlink(link)
        dst_link = dst_root / rel
        dst_link.parent.mkdir(parents=True, exist_ok=True)
        if dst_link.exists() or os.path.islink(dst_link):
            dst_link.unlink()
        os.symlink(target, dst_link)

    print(f"Copying {file_count} files with {args.workers} threads ...")
    copied_bytes = 0

    with tqdm(total=total_bytes, unit="B", unit_scale=True, unit_divisor=1024,
              desc="Copying") as pbar:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {}
            for f in files:
                rel = f.relative_to(src_root)
                dst = str(dst_root / rel)
                futures[pool.submit(copy_file, str(f), dst)] = (str(f), dst)

            for fut in as_completed(futures):
                src_path, sz = fut.result()
                copied_bytes += sz
                pbar.update(sz)
                pbar.set_postfix(file=os.path.basename(src_path), refresh=False)

    print(f"\nDone. Copied {copied_bytes / 1e9:.1f} GB in {file_count} files")
    print(f"Run: ln -s {dst_root} {src_root}.bak && mv {src_root} {src_root}.bak")
    print(f"  Or manually switch: mv {src_root} {src_root}.bak && ln -s {dst_root} {src_root}")


if __name__ == "__main__":
    main()
