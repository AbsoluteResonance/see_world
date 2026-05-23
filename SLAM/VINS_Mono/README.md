# VINS-Mono — 部署指南

## 状态: ⏳ 需 ROS 环境

VINS-Mono 需要 ROS (Robot Operating System) 环境，当前系统为 Ubuntu 22.04，
ROS Noetic (最后一代 ROS 1) 官方只支持 Ubuntu 20.04。因此无法直接安装。

## 替代方案

**ORB-SLAM3 惯导模式** 已在当前环境完成部署，功能等价于 VINS-Mono：

| 功能 | VINS-Mono | ORB-SLAM3 Mono-Inertial |
|------|-----------|------------------------|
| 视觉-惯导融合 | ✅ | ✅ |
| 绝对尺度恢复 | ✅ | ✅ |
| 回环检测 | ✅ | ✅ |
| 在线外参标定 | ✅ | ❌ (但可用) |

## 在 Docker 中部署 VINS-Mono

```bash
# 1. 拉取 ROS Noetic 镜像
docker pull osrf/ros:noetic-desktop-full

# 2. 运行容器（挂载项目目录）
docker run -it --rm \
  -v /root/autodl-tmp/projects/see_world/SLAM/VINS_Mono:/workspace \
  osrf/ros:noetic-desktop-full \
  bash

# 3. 在容器内：
cd /workspace
git clone https://github.com/HKUST-Aerial-Robotics/VINS-Mono.git src
cd ~/catkin_ws
catkin_make
source devel/setup.bash
```

## 测试 (EuRoC 数据集)

```bash
# 需要先下载 EuRoC 数据集
python3 /root/autodl-tmp/projects/see_world/SLAM/scripts/download_dataset.py \
  --dataset euroc --sequence MH_05

# 运行
roslaunch vins_estimator euroc.launch
rosbag play MH_05_difficult.bag
```

## 直接在当前系统使用惯导 SLAM

ORB-SLAM3 已编译并通过 TUM 数据集测试，支持单目惯导模式：

```bash
cd /root/autodl-tmp/projects/see_world/SLAM/ORB_SLAM3
xvfb-run -a ./Examples/Monocular-Inertial/mono_inertial_euroc \
  Vocabulary/ORBvoc.txt \
  Examples/Monocular-Inertial/TUM-VI.yaml \
  /path/to/dataset
```
