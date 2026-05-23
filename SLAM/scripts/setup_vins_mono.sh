#!/usr/bin/env bash
# Automated setup script for VINS-Mono
# Usage: bash scripts/setup_vins_mono.sh
# Note: VINS-Mono requires ROS (Robot Operating System).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SLAM_DIR="$(dirname "$SCRIPT_DIR")"
cd "$SLAM_DIR"

echo "=== VINS-Mono Setup ==="
echo "Working dir: $SLAM_DIR"
echo ""
echo "NOTE: VINS-Mono requires a full ROS installation."
echo "If ROS is not installed, install it first:"
echo "  https://wiki.ros.org/noetic/Installation/Ubuntu"
echo ""

# Check for ROS
if [ -z "$ROS_DISTRO" ]; then
    echo "WARNING: ROS not detected in current environment."
    echo "Setup will still clone the repo but compilation requires ROS."
    INSTALL_ROS=true
else
    echo "ROS $ROS_DISTRO detected."
    INSTALL_ROS=false
fi

# Install Ceres Solver if not present
if ! dpkg -l libceres-dev >/dev/null 2>&1; then
    echo ""
    echo "Installing Ceres Solver..."
    apt-get update -qq
    apt-get install -y -qq libceres-dev 2>/dev/null || {
        echo "Building Ceres from source..."
        git clone --depth 1 https://github.com/ceres-solver/ceres-solver.git
        cd ceres-solver
        mkdir -p build && cd build
        cmake .. -DCMAKE_BUILD_TYPE=Release
        make -j$(nproc 2>/dev/null || echo 1)
        make install
        cd "$SLAM_DIR"
    }
fi

# Clone VINS-Mono
if [ ! -d "VINS_Mono" ]; then
    echo ""
    echo "Cloning VINS-Mono..."
    git clone https://github.com/HKUST-Aerial-Robotics/VINS-Mono.git VINS_Mono
else
    echo "VINS-Mono directory already exists."
fi

if [ "$INSTALL_ROS" = true ]; then
    echo ""
    echo "=== Setup incomplete ==="
    echo "VINS-Mono source code is downloaded. To compile:"
    echo "1. Install ROS Noetic: https://wiki.ros.org/noetic/Installation/Ubuntu"
    echo "2. Create a catkin workspace:"
    echo "     mkdir -p ~/catkin_ws/src"
    echo "     ln -s $SLAM_DIR/VINS_Mono ~/catkin_ws/src/"
    echo "3. Build:"
    echo "     cd ~/catkin_ws"
    echo "     catkin_make"
    echo "4. Source and run:"
    echo "     source devel/setup.bash"
    echo "     roslaunch vins_estimator euroc.launch"
    echo ""
    echo "Test with EuRoC dataset:"
    echo "     python scripts/download_dataset.py --dataset euroc --sequence MH_05"
    echo "     rosbag play datasets/euroc_MH_05/MH_05_difficult.bag"
else
    echo ""
    echo "=== Setup complete ==="
    echo "VINS-Mono is ready to build in a ROS workspace."
fi
