#!/usr/bin/env bash
# Automated setup script for ORB-SLAM3
# Usage: bash scripts/setup_orb_slam3.sh
# This script clones, patches, and builds ORB-SLAM3.
# Note: Requires OpenCV, Eigen3, Pangolin. GPU not required (monocular mode).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SLAM_DIR="$(dirname "$SCRIPT_DIR")"
cd "$SLAM_DIR"

echo "=== ORB-SLAM3 Setup ==="
echo "Working dir: $SLAM_DIR"

# Check dependencies
echo ""
echo "Checking dependencies..."
command -v cmake >/dev/null 2>&1 || { echo "ERROR: cmake not found"; exit 1; }
command -v g++ >/dev/null 2>&1 || { echo "ERROR: g++ not found"; exit 1; }

# Install Pangolin if not present
if ! dpkg -l libpangolin-dev >/dev/null 2>&1 && [ ! -d "Pangolin" ]; then
    echo ""
    echo "Building Pangolin from source..."
    git clone --depth 1 https://github.com/stevenlovegrove/Pangolin.git
    cd Pangolin
    mkdir -p build && cd build
    cmake .. -DCMAKE_BUILD_TYPE=Release
    make -j$(nproc 2>/dev/null || echo 1)
    make install
    cd "$SLAM_DIR"
    echo "Pangolin built and installed."
fi

# Clone ORB-SLAM3
if [ ! -d "ORB_SLAM3" ]; then
    echo ""
    echo "Cloning ORB-SLAM3..."
    git clone https://github.com/UZ-SLAMLab/ORB_SLAM3.git
else
    echo "ORB_SLAM3 directory already exists."
fi

cd ORB_SLAM3

# Apply OpenCV 4.x compatibility patches if needed
echo ""
echo "Checking for OpenCV 4.x compatibility..."
OPENCV_VERSION=$(pkg-config --modversion opencv4 2>/dev/null || echo "0")
if [[ "$OPENCV_VERSION" == 4.* ]]; then
    echo "OpenCV 4.x detected — applying compatibility fixes..."
    # Fix for opencv/cv.h removal in OpenCV 4
    for f in $(grep -rl "opencv/cv.h" src/ include/ Examples/ 2>/dev/null || true); do
        echo "  Patching: $f"
        sed -i 's|#include <opencv/cv.h>|#include <opencv2/core.hpp>|g' "$f"
        sed -i 's|#include <opencv/highgui.h>|#include <opencv2/highgui.hpp>|g' "$f"
    done
    # Fix for OpenCV 4+ imread/imwrite namespace
    for f in $(grep -rl "CV_LOAD_IMAGE_UNCHANGED" src/ include/ Examples/ 2>/dev/null || true); do
        sed -i 's|CV_LOAD_IMAGE_UNCHANGED|cv::IMREAD_UNCHANGED|g' "$f"
    done
    for f in $(grep -rl "CV_GRAY2RGB" src/ include/ Examples/ 2>/dev/null || true); do
        sed -i 's|CV_GRAY2RGB|cv::COLOR_GRAY2RGB|g' "$f"
    done
fi

# Build ORB-SLAM3
echo ""
echo "Building ORB-SLAM3 (this may take a while on limited CPU)..."
chmod +x build.sh
./build.sh

echo ""
echo "=== ORB-SLAM3 build complete ==="
echo "Binaries in: $SLAM_DIR/ORB_SLAM3/Examples/"
echo ""
echo "Quick test:"
echo "  cd $SLAM_DIR"
echo "  python scripts/download_dataset.py --dataset tum_small --sequence fr1_desk2"
echo "  ./ORB_SLAM3/Examples/Monocular/mono_tum \\"
echo "    ORB_SLAM3/Vocabulary/ORBvoc.txt \\"
echo "    ORB_SLAM3/Examples/Monocular/TUM1.yaml \\"
echo "    datasets/fr1_desk2"
