# VINS-Mono — 部署指南

## 状态: ⏳ 需 ROS 1 (Noetic) 环境

**VINS-Mono 需要 ROS 1 (Noetic)，不是 ROS 2。**
不能与 Ubuntu 22.04 上可安装的 ROS 2 Humble 混用。

## 为什么在当前系统无法安装

| 需求 | 当前环境 | 问题 |
|------|---------|------|
| ROS 1 Noetic | Ubuntu 22.04 (Jammy) | Noetic 只支持 Ubuntu 20.04 (Focal) |
| libboost 1.71 | 已安装 1.74 | 版本不兼容 |
| libconsole-bridge 0.4 | 已安装 1.0 | 版本不兼容 |
| ROS 2 Humble | 可安装 | **VINS-Mono 不用 ROS 2** |

## 部署方案

### 方案 1: Docker (推荐)

```bash
docker pull osrf/ros:noetic-desktop-full
docker run -it --rm \
  -v /root/autodl-tmp/projects/see_world/SLAM/VINS_Mono:/workspace \
  osrf/ros:noetic-desktop-full \
  bash

# 在容器内：
cd /workspace
git clone https://github.com/HKUST-Aerial-Robotics/VINS-Mono.git src
cd ~/catkin_ws
catkin_make
source devel/setup.bash
```

### 方案 2: Ubuntu 20.04 物理机/虚拟机

直接在 Ubuntu 20.04 上安装 ROS Noetic。

## 测试 (EuRoC 数据集)

```bash
python3 /root/autodl-tmp/projects/see_world/SLAM/ORB_SLAM3/scripts/download_dataset.py \
  --dataset euroc --sequence MH_05

roslaunch vins_estimator euroc.launch
rosbag play MH_05_difficult.bag
```
