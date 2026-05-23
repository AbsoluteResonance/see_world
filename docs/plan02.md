# See World — Phase 02 规划文档 v1.0

> 创建日期: 2026-05-23
> 基于: Phase 01 完成状态 (plan01.md, 进度01.md, 经验01.md)
> 目标: 部署单目实时 3D 稠密重建算法，通过 ROS2 与 Web/App 通信
> 首选算法: SLAM3R (CVPR 2025 Highlight)

---

## 一、Phase 01 回顾与 Phase 02 动机

### 1.1 Phase 01 已完成的关键资产

| 资产 | 状态 | Phase 02 复用方式 |
|------|------|-------------------|
| FastAPI 后端 (`web/backend/`) | 完整运行 | 扩展 API 端点，新增 SLAM3R 路由 |
| 前端 SPA (`web/frontend/`) | 完整运行 | 新增稠密点云查看器 (已有 viewer_dense.js 可复用) |
| ROS2 架构 (`ros2_ws/`) | orb_slam3_ros 已跑通 | 参照创建 slam3r_ros 包 |
| PWA (`app/pwa/`) | 基础完成 | 扩展相机帧流式上传能力 |
| Kimi 工具 (`tools/kimi/`) | 完成 | 保持不变 |
| ORB-SLAM3 (`SLAM/ORB_SLAM3/`) | 编译+测试通过 | 作为对比基线保留 |
| VINS-MONO-ROS2 | 编译通过 | 保留备用 |
| Cloudflare Tunnel | 已配置 | 继续使用 |

### 1.2 Phase 01 的核心限制 (Phase 02 要解决)

| 限制 | Phase 01 表现 | Phase 02 目标 |
|------|--------------|---------------|
| 点云密度 | SGBM ~4 万点，稀疏 | 深度学习稠密重建，百万级点 |
| 重建质量 | 依赖 SLAM 位姿精度，SGBM 视差受限 | 端到端神经网络直接回归 3D 点 |
| GPU 利用 | 无 GPU，纯 CPU | 充分利用 CUDA GPU |
| 实时性 | 离线批处理 | 在线实时重建 + 流式输出 |
| 尺度 | 单目尺度模糊 | 神经网络学习的尺度先验 |
| ROS2 通信 | 仅 batch 模式 | 完整的 topic/service 实时通信 |

---

## 二、SLAM3R 算法分析

### 2.1 核心特点

- **论文**: "SLAM3R: Real-Time Dense Scene Reconstruction from Monocular RGB Videos" (CVPR 2025 Highlight)
- **仓库**: https://github.com/PKU-VCL-3DV/SLAM3R
- **核心思想**: 使用前馈神经网络从视频帧直接回归 3D 点云，无需显式估计相机参数
- **两个子模型**:
  - Image-to-Points (I2P): 从单帧/帧对预测 3D 点云
  - Local-to-World (L2W): 将局部点云对齐到全局坐标系
- **基础架构**: 基于 DUSt3R / Croco (Vision Transformer + 双目匹配)
- **许可证**: 待确认 (需检查 GitHub 仓库)

### 2.2 与 Phase 01 技术栈对比

| 维度 | ORB-SLAM3 (Phase 01) | SLAM3R (Phase 02) |
|------|---------------------|-------------------|
| 方法 | 经典特征点法 | 深度学习前馈网络 |
| 输出 | 稀疏轨迹 + 需要后处理稠密化 | 直接输出稠密 3D 点云 |
| 相机参数 | 需要标定 (内参) | 不需要显式标定 |
| GPU | 不需要 | 需要 CUDA GPU |
| 语言 | C++ | Python (PyTorch) |
| 实时性 | 实时 (CPU) | 实时 (GPU) |
| 尺度 | 模糊 (单目) | 有先验 (训练数据学习) |

### 2.3 系统要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.11 | conda 环境 |
| CUDA | 11.8+ | GPU 加速 |
| PyTorch | 2.5.0 | 深度学习框架 |
| TorchVision | 0.20.0 | 图像预处理 |
| XFormers | 0.0.28.post2 | 高效注意力机制 (可选但推荐) |
| Open3D | latest | 点云可视化和处理 |
| Gradio | latest | Web 界面 (已有) |
| Viser | latest | 在线增量重建可视化 |

### 2.4 模型权重

| 模型 | HuggingFace 路径 | 用途 |
|------|-----------------|------|
| Image-to-Points | `siyan824/slam3r_i2p` | 从图像预测 3D 点云 |
| Local-to-World | `siyan824/slam3r_l2w` | 局部点云对齐到世界坐标 |

---

## 三、Phase 02 总体架构

```
┌──────────────────────────────────────────────────────────────┐
│                        移动端 APP                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │ 相机帧捕获   │  │ IMU 传感器    │  │ 3D 渲染 (Three.js) │   │
│  │ (实时流)    │  │ (加速度+陀螺) │  │ AR 叠加            │   │
│  └──────┬──────┘  └──────┬───────┘  └────────▲───────────┘   │
│         │                │                    │               │
│         │   WebSocket / HTTP Upload           │               │
│         ▼                ▼                    │               │
│  ┌──────────────────────────────────────────────────────┐     │
│  │                   Web 后端 (FastAPI)                   │     │
│  │  ┌──────────┐  ┌───────────┐  ┌──────────────────┐   │     │
│  │  │ 上传路由  │  │ SLAM3R 路由│  │ WebSocket 路由   │   │     │
│  │  │ (已有)   │  │ (新增)    │  │ (新增, 实时通信)  │   │     │
│  │  └──────────┘  └─────┬─────┘  └────────┬─────────┘   │     │
│  │                      │                  │              │     │
│  │              ┌───────▼──────────────────▼──────┐      │     │
│  │              │     slam3r_service.py (新增)      │      │     │
│  │              │  任务管理 / ROS2 桥接 / 流式管理  │      │     │
│  │              └───────┬─────────────────────────┘      │     │
│  └──────────────────────┼────────────────────────────────┘     │
│                         │                                      │
│              ┌──────────▼──────────┐                            │
│              │    ROS2 中间层       │                            │
│              │  ┌────────────────┐ │                            │
│              │  │ slam3r_ros     │ │  ← 新增 ROS2 包            │
│              │  │ (Python 节点)   │ │                            │
│              │  │                │ │                            │
│              │  │ Topics:        │ │                            │
│              │  │ /slam3r/image  │ │  ← 接收相机帧              │
│              │  │ /slam3r/cloud  │ │  ← 发布稠密点云            │
│              │  │ /slam3r/pose   │ │  ← 发布相机位姿            │
│              │  │                │ │                            │
│              │  │ Services:      │ │                            │
│              │  │ /slam3r/start  │ │                            │
│              │  │ /slam3r/stop   │ │                            │
│              │  │ /slam3r/reset  │ │                            │
│              │  └───────┬────────┘ │                            │
│              └──────────┼──────────┘                            │
│                         │                                      │
│              ┌──────────▼──────────┐                            │
│              │   SLAM3R 引擎        │                            │
│              │  ┌────────────────┐ │                            │
│              │  │ Image2Points   │ │  ← I2P 模型                │
│              │  │ Local2World    │ │  ← L2W 模型                │
│              │  │ Point Cloud    │ │  ← 输出稠密彩色点云        │
│              │  └────────────────┘ │                            │
│              │  GPU (CUDA) 必需    │                            │
│              └─────────────────────┘                            │
└──────────────────────────────────────────────────────────────────┘
```

### 3.1 数据流

```
相机帧 → ROS2 Topic /slam3r/image
       → slam3r_ros 节点缓存帧
       → SLAM3R I2P 模型预测局部点云
       → SLAM3R L2W 模型对齐到世界坐标
       → 发布稠密点云到 /slam3r/cloud
       → 发布相机位姿到 /slam3r/pose
       → FastAPI WebSocket → 前端 Three.js 渲染
```

### 3.2 两种运行模式

**模式 1: 离线批处理 (视频上传)**
```
上传视频 → 提取帧 → 调用 SLAM3R 离线脚本 → 生成稠密点云 PLY → 返回下载链接 + 3D 预览
```
- 对应现有 `POST /api/reconstruct/from-file/{id}` 流程
- 新增 SLAM3R 作为重建引擎选项 (与 ORB-SLAM3 并列)

**模式 2: 在线实时重建 (相机流)**
```
手机相机帧 → WebSocket → ROS2 /slam3r/image → SLAM3R 实时推理 → ROS2 /slam3r/cloud → WebSocket → 前端增量渲染
```
- 全新能力，Phase 01 没有
- 核心挑战: 延迟、帧率、GPU 推理速度

---

## 四、实施步骤

### Step 0: 环境准备 (GPU 服务器)

**目标**: 在新的 GPU 服务器上准备好 CUDA 环境和基础依赖。

| 子任务 | 详细操作 | 验证标准 |
|--------|---------|---------|
| 0.1 确认 GPU 环境 | `nvidia-smi` 确认 GPU 型号、显存、CUDA 版本 | CUDA >= 11.8, 显存 >= 8GB |
| 0.2 安装 Miniconda | 下载安装 Miniconda3, 创建 `slam3r` conda 环境 (Python 3.11) | `conda activate slam3r` 成功 |
| 0.3 安装 PyTorch | `pip install torch==2.5.0 torchvision==0.20.0 --index-url https://download.pytorch.org/whl/cu118` | `python -c "import torch; print(torch.cuda.is_available())"` → True |
| 0.4 克隆 SLAM3R | `git clone https://github.com/PKU-VCL-3DV/SLAM3R.git` 到 `SLAM/SLAM3R/` | 仓库完整 clone |
| 0.5 安装依赖 | `pip install -r requirements.txt && pip install -r requirements_optional.txt` | 无报错 |
| 0.6 编译 CUDA 算子 | 编译 RoPE CUDA kernel (`slam3r/pos_embed/curope/`) | 编译成功 |
| 0.7 安装 XFormers | `pip install xformers==0.0.28.post2` | import 成功 |
| 0.8 下载模型权重 | 运行 Python 代码从 HuggingFace 下载 I2P + L2W 权重 | 权重文件存在于 HF cache |
| 0.9 测试 Demo | 下载 Replica 示例场景，运行 `bash scripts/demo_replica.sh` | 成功生成稠密点云结果 |

**关键注意事项**:
- 新 GPU 服务器的项目目录建议与 Phase 01 保持一致: `/autodl-fs/data/projects/see_world/`
- 先将 Phase 01 代码 git clone 到新服务器，然后在 `SLAM/` 下新增 `SLAM3R/`
- Conda 环境名建议为 `slam3r`，与 SLAM3R 官方文档保持一致
- XFormers 安装可能因 CUDA 版本不同而失败，如失败可跳过 (性能下降但功能不受影响)

---

### Step 1: 克隆项目代码到 GPU 服务器

**目标**: 在新 GPU 服务器上建立完整的项目目录结构。

```bash
# 1. Clone Phase 01 仓库
cd /autodl-fs/data/projects
git clone <see_world_repo_url> see_world
cd see_world

# 2. 目录结构 (在 Phase 01 基础上新增)
mkdir -p SLAM/SLAM3R          # SLAM3R 源码 (git clone 到这里)
mkdir -p ros2_ws/src/slam3r_ros  # 新增 ROS2 包
mkdir -p web/backend/services   # 已有，新增 slam3r_service.py
mkdir -p web/backend/routes     # 已有，新增 slam3r_routes.py
```

**目录变更预览**:
```
see_world/
├── docs/
│   ├── plan01.md               # Phase 01 规划 (只读参考)
│   ├── 进度01.md                # Phase 01 进度 (只读参考)
│   ├── 经验01.md                # Phase 01 经验 (只读参考)
│   └── plan02.md               # 本文档 — Phase 02 规划
├── web/                        # 不变，仅扩展
│   └── backend/
│       ├── routes/
│       │   └── slam3r_routes.py    # 新增: SLAM3R API 端点
│       └── services/
│           └── slam3r_service.py   # 新增: SLAM3R 服务层
├── SLAM/
│   ├── ORB_SLAM3/              # 保留 (Phase 01 基线)
│   ├── VINS_Mono/              # 保留
│   └── SLAM3R/                 # 新增: SLAM3R 源码 (git clone)
├── ros2_ws/
│   └── src/
│       ├── orb_slam3_ros/      # 保留 (Phase 01)
│       └── slam3r_ros/         # 新增: SLAM3R ROS2 节点
└── app/                        # 扩展 PWA 实时流能力
```

**关键原则**:
- **不删除 Phase 01 的任何代码或目录** — ORB-SLAM3、VINS-Mono、orb_slam3_ros 全部保留
- **不修改 Phase 01 已有的 API 端点签名** — 新增端点走新路由
- **不修改现有的前端页面布局** — 新增功能以独立按钮/选项形式呈现
- **不在项目根目录或 web/ 目录下创建 SLAM3R 相关文件** — 所有 SLAM3R 源码放 `SLAM/SLAM3R/`

---

### Step 2: SLAM3R 核心部署与验证

**目标**: 在 GPU 服务器上跑通 SLAM3R 的所有模式，确认功能正常。

#### 2.1 离线重建验证

| 子任务 | 详细操作 | 验证标准 |
|--------|---------|---------|
| 2.1.1 Replica 数据集测试 | 下载 Replica 示例场景，运行 demo | 生成稠密点云，目视检查质量 |
| 2.1.2 自采数据测试 | 用 Phase 01 已上传的手机视频测试 | 确认对手机拍摄数据有效 |
| 2.1.3 输出格式确认 | 检查 SLAM3R 输出的点云格式 (PLY/NPZ)、坐标系、颜色 | 明确输出规格 |

#### 2.2 在线重建验证

| 子任务 | 详细操作 | 验证标准 |
|--------|---------|---------|
| 2.2.1 Gradio 在线界面 | 运行 `python app.py --online` | Viser 窗口显示增量重建 |
| 2.2.2 确认在线模式 API | 阅读 SLAM3R 在线模式代码，理解帧输入/点云输出接口 | 明确编程接口 |

#### 2.3 性能基准测试

| 指标 | 目标 | 测试方法 |
|------|------|---------|
| 单帧推理时间 | < 100ms (I2P) | 计时 Image2Points 前向传播 |
| 全局对齐时间 | < 50ms (L2W) | 计时 Local2World 前向传播 |
| 总吞吐 | >= 5 FPS | 端到端处理一段视频计时 |
| GPU 显存占用 | < 8GB | nvidia-smi 监控峰值 |

---

### Step 3: ROS2 节点开发 (slam3r_ros)

**目标**: 创建 ROS2 Python 包，将 SLAM3R 封装为标准的 ROS2 节点。

**参照**: `ros2_ws/src/orb_slam3_ros/` 的结构和模式。

#### 3.1 包结构

```
ros2_ws/src/slam3r_ros/
├── package.xml                  # ROS2 包描述
├── setup.py                     # Python 包安装
├── setup.cfg
├── resource/
│   └── slam3r_ros               # marker file
└── slam3r_ros/
    ├── __init__.py
    └── node.py                   # SLAM3R ROS2 节点主文件
```

#### 3.2 节点功能设计

**订阅的 Topics**:
| Topic | 消息类型 | 说明 |
|-------|---------|------|
| `/slam3r/image` | `sensor_msgs/Image` | 输入相机帧 (BGR8) |
| `/slam3r/calib` | `sensor_msgs/CameraInfo` | 相机内参 (可选，SLAM3R 不需要但保留接口) |

**发布的 Topics**:
| Topic | 消息类型 | 说明 |
|-------|---------|------|
| `/slam3r/cloud` | `sensor_msgs/PointCloud2` | 稠密 3D 点云 (世界坐标) |
| `/slam3r/cloud_local` | `sensor_msgs/PointCloud2` | 局部 3D 点云 (当前帧坐标) |
| `/slam3r/pose` | `geometry_msgs/PoseStamped` | 当前相机位姿估计 |
| `/slam3r/status` | `std_msgs/String` | 状态信息 (tracking/lost/init) |

**Services**:
| Service | 类型 | 说明 |
|---------|------|------|
| `/slam3r/start` | `std_srvs/Trigger` | 启动/重启重建 |
| `/slam3r/stop` | `std_srvs/Trigger` | 停止重建 |
| `/slam3r/save` | `std_srvs/Trigger` | 保存当前点云到文件 |
| `/slam3r/reset` | `std_srvs/Empty` | 重置系统状态 |

**参数**:
| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `model_path_i2p` | `siyan824/slam3r_i2p` | I2P 模型路径或 HF ID |
| `model_path_l2w` | `siyan824/slam3r_l2w` | L2W 模型路径或 HF ID |
| `buffer_size` | `50` | 帧缓冲大小 |
| `keyframe_interval` | `5` | 关键帧间隔 |
| `device` | `cuda` | 推理设备 |
| `output_dir` | `./slam3r_output` | 点云保存目录 |

#### 3.3 node.py 实现要点

```
Slam3RNode (rclpy.node.Node)
├── __init__
│   ├── 加载 I2P + L2W 模型
│   ├── 初始化 CUDA 推理
│   ├── 创建 publishers (cloud, pose, status)
│   ├── 创建 subscribers (image, calib)
│   ├── 创建 services (start, stop, save, reset)
│   └── 初始化帧缓冲和状态机
│
├── image_callback(msg)
│   ├── sensor_msgs/Image → numpy (HWC, BGR)
│   ├── 加入帧缓冲
│   └── 如果达到关键帧间隔 → 触发推理
│
├── process_keyframes()
│   ├── 从缓冲取最近 N 帧
│   ├── 调用 I2P 模型 → 局部点云
│   ├── 调用 L2W 模型 → 世界坐标对齐
│   ├── 发布 /slam3r/cloud (PointCloud2)
│   └── 发布 /slam3r/pose (PoseStamped)
│
├── start_callback()  → 重置状态, 开始接受帧
├── stop_callback()   → 停止推理, 保存当前结果
├── save_callback()   → 导出点云 PLY 文件
└── reset_callback()  → 清空缓冲, 重置模型状态
```

#### 3.4 与 orb_slam3_ros 的对比

| 维度 | orb_slam3_ros | slam3r_ros |
|------|---------------|------------|
| 语言 | Python (调用 C++ exe) | Python (直接调用 PyTorch) |
| 运行方式 | subprocess 批处理 | 进程内推理 |
| 实时性 | 无实时 (batch only) | 在线实时 |
| GPU | 不需要 | 必需 |
| 输出 | 稀疏轨迹 txt | 稠密点云 PointCloud2 |
| 相机标定 | 必需 | 不需要 |

---

### Step 4: Web 后端扩展

**目标**: 在 FastAPI 后端中集成 SLAM3R，提供 HTTP API 和 WebSocket 端点。

#### 4.1 新增服务层: `web/backend/services/slam3r_service.py`

```
class Slam3RService:
    """
    管理 SLAM3R 的生命周期和任务队列。

    两种工作模式:
    1. batch: 上传视频 → 离线重建 → 返回 PLY
    2. stream: WebSocket 帧流 → 实时重建 → 流式推送点云
    """

    __init__():
        - 检查 SLAM3R 可用性 (模型是否加载成功)
        - 初始化任务队列 (内存 dict)

    reconstruct_from_file(file_id) -> job:
        """离线批处理: 视频文件 → 提取帧 → SLAM3R 推理 → PLY"""
        - 参照 slam_service.reconstruct_from_file
        - 调用 SLAM3R 离线脚本而非 orb_slam3_ros

    start_stream() -> stream_id:
        """开启实时流会话"""
        - 启动 slam3r_ros 节点 (如未运行)
        - 返回 stream_id

    process_frame(stream_id, image_bytes) -> cloud_data:
        """处理单帧图像 → 返回增量点云"""
        - 通过 ROS2 topic 发送帧
        - 等待 /slam3r/cloud 返回

    stop_stream(stream_id):
        """停止流会话"""
```

#### 4.2 新增路由: `web/backend/routes/slam3r_routes.py`

```
POST   /api/slam3r/reconstruct          # 开始 SLAM3R 离线重建 (从路径)
POST   /api/slam3r/reconstruct/from-file/{file_id}  # 开始 SLAM3R 离线重建 (从已上传文件)
GET    /api/slam3r/reconstruct/{job_id}             # 查询重建任务状态
GET    /api/slam3r/reconstruct/{job_id}/pointcloud  # 下载稠密点云 PLY

WS     /ws/slam3r/stream                 # WebSocket: 实时帧流 → 实时点云推送
POST   /api/slam3r/stream/start          # 开始实时流会话 (返回 stream_id)
POST   /api/slam3r/stream/{id}/frame     # 上传单帧 (备选方案，WebSocket 优先)
GET    /api/slam3r/stream/{id}/status    # 查询流状态
POST   /api/slam3r/stream/{id}/stop      # 停止流
```

**路由注册**: 在 `web/backend/main.py` 中新增:
```python
from backend.routes import slam3r_routes
app.include_router(slam3r_routes.router)
```

#### 4.3 API 设计原则

- **与 Phase 01 API 共存不冲突**: 所有 SLAM3R 端点前缀为 `/api/slam3r/`，现有 `/api/reconstruct/` 保持不变 (走 ORB-SLAM3)
- **统一响应格式**: 继续使用 `{"code": 0, "message": "success", "data": {...}}`
- **错误码扩展**:
  - `50004`: SLAM3R 模型未加载
  - `50005`: GPU 不可用
  - `50006`: SLAM3R 推理失败

---

### Step 5: Web 前端扩展

**目标**: 前端支持 SLAM3R 稠密点云查看和实时流预览。

#### 5.1 已有可复用组件

- `viewer_dense.js` — Three.js 稠密点云查看器 (Phase 01 已实现，支持彩色 PLY)
- `upload.js` — 拖拽上传模块
- `gallery.js` — 文件画廊

#### 5.2 新增/修改

| 文件 | 修改内容 |
|------|---------|
| `index.html` | 新增 "SLAM3R 稠密重建" 按钮 + 实时流面板 |
| `js/viewer_dense.js` | 升级: 支持增量添加点 (实时流场景)，支持更大点云 (LOD) |
| `js/slam3r.js` (新增) | SLAM3R 前端逻辑: 调用 API、WebSocket 连接、进度管理 |

#### 5.3 前端交互流程

**离线模式**:
```
用户选择已上传视频 → 点击 "SLAM3R 重建" → 显示进度条
→ 完成后 → 点击 "查看点云" → viewer_dense.js 渲染
```

**在线模式 (新功能)**:
```
用户点击 "实时重建" → 请求相机权限 → WebSocket 连接后端
→ 每 N 帧发送一帧 → 后端返回增量点云 → viewer_dense.js 增量更新
→ 显示 FPS、点数、延迟等状态
```

---

### Step 6: PWA/移动端扩展

**目标**: 移动端支持相机帧流式上传，为实时重建提供前端数据源。

#### 6.1 修改 `app/pwa/camera.js`

- 新增: 定时捕获 canvas 帧 → JPEG 压缩 → WebSocket 发送
- 新增: 帧率控制 (可配置发送间隔，如每 3 帧发 1 帧)
- 新增: 分辨率控制 (发送低分辨率到后端，前端显示原分辨率)

#### 6.2 WebSocket 帧协议

```json
{
  "type": "frame",
  "stream_id": "abc123",
  "timestamp": 1716480000.123,
  "image": "<base64 jpeg>",
  "resolution": {"width": 640, "height": 480}
}
```

服务端响应:
```json
{
  "type": "cloud_update",
  "timestamp": 1716480000.456,
  "points": [[x,y,z,r,g,b], ...],  // 增量点云
  "pose": [tx, ty, tz, qx, qy, qz, qw],  // 相机位姿
  "total_points": 1234567
}
```

---

### Step 7: 集成测试

**目标**: 验证全链路 "手机拍摄 → WebSocket → ROS2 → SLAM3R → 前端渲染"。

| 测试用例 | 输入 | 期望输出 |
|---------|------|---------|
| TC-01 | 上传一段手机视频 (离线) | 返回稠密点云 PLY, 前端正常渲染 |
| TC-02 | WebSocket 发送模拟帧序列 | 实时返回增量点云, 前端增量更新 |
| TC-03 | 发送低纹理帧 (白墙) | SLAM3R 状态变为 lost, 不崩溃 |
| TC-04 | 发送快速旋转帧序列 | 跟踪恢复, 不崩溃 |
| TC-05 | 并发两个重建任务 | 一个排队等待, 一个运行 |

---

## 五、目录变更总览

```
see_world/
├── docs/
│   └── plan02.md                         # 新增: 本文档
│
├── SLAM/
│   └── SLAM3R/                            # 新增: SLAM3R 源码 (git clone)
│       ├── slam3r/                        # 核心模型代码
│       ├── scripts/                       # 官方脚本
│       ├── app.py                         # Gradio 界面
│       └── requirements.txt               # 依赖
│
├── ros2_ws/
│   └── src/
│       └── slam3r_ros/                    # 新增: ROS2 节点
│           ├── package.xml
│           ├── setup.py
│           ├── setup.cfg
│           └── slam3r_ros/
│               ├── __init__.py
│               └── node.py
│
├── web/
│   ├── backend/
│   │   ├── main.py                        # 修改: 注册 slam3r_routes
│   │   ├── routes/
│   │   │   └── slam3r_routes.py           # 新增: SLAM3R API
│   │   └── services/
│   │       └── slam3r_service.py          # 新增: SLAM3R 服务层
│   └── frontend/
│       ├── index.html                     # 修改: 新增 SLAM3R 按钮
│       └── js/
│           ├── viewer_dense.js            # 修改: 支持增量更新
│           └── slam3r.js                  # 新增: SLAM3R 前端逻辑
│
└── app/
    └── pwa/
        └── camera.js                      # 修改: 新增 WebSocket 帧流
```

**不修改的文件** (以 Phase 01 为准):
- `web/backend/config.py` — 配置项已足够
- `web/backend/routes/upload.py` — 上传逻辑不变
- `web/backend/routes/model.py` — Kimi 分析不变
- `web/backend/services/kimi_service.py` — Kimi 服务不变
- `web/frontend/js/upload.js` — 上传 UI 不变
- `web/frontend/js/gallery.js` — 画廊不变
- `tools/kimi/` — 全部不变

---

## 六、执行顺序与依赖

```
Step 0: 环境准备 ────── (必须先做, 在新 GPU 服务器上)
  │
  ▼
Step 1: 克隆代码 ────── (依赖 Step 0)
  │
  ▼
Step 2: SLAM3R 部署 ─── (依赖 Step 1, 验证算法可行性)
  │
  ├──────────────────────────────┐
  ▼                              ▼
Step 3: ROS2 节点 ────   Step 5: 前端扩展
  │                              │
  ▼                              │
Step 4: Web 后端 ──────┬─────────┘
  │                    │
  ▼                    ▼
Step 6: PWA 扩展 ─── Step 7: 集成测试
```

Step 2 是核心验证点: 如果 SLAM3R 在 GPU 环境上无法正常运行或效果不达预期，需要重新评估算法方案。

---

## 七、风险与备份方案

| 风险 | 概率 | 影响 | 缓解措施 | 备份方案 |
|------|------|------|---------|---------|
| SLAM3R 推理速度不达实时 | 中 | 高 | 降低分辨率、增大关键帧间隔、使用 FP16 | 降级为"准实时"模式 (1-2 FPS) |
| GPU 显存不足 | 中 | 高 | 使用更小的模型变体、降低点云密度 | 换用更大显存 GPU |
| SLAM3R 对手机数据效果差 | 中 | 中 | 先用 Replica 测试，确认是数据问题还是模型问题 | 评估 DUSt3R + 后处理方案 |
| XFormers 编译失败 | 低 | 低 | 跳过 XFormers，使用原生 attention | 性能下降但不影响功能 |
| ROS2 通信延迟过高 | 低 | 中 | 减小消息体积 (降采样点云)、使用 ZeroMQ 替代 | 直接用 Python API 绕过 ROS2 |
| CUDA 版本不兼容 | 低 | 中 | 严格按照 SLAM3R 要求的 CUDA 11.8 | 使用 Docker 容器固定环境 |

### 备份算法方案 (如果 SLAM3R 不满足需求)

| 方案 | 优势 | 劣势 |
|------|------|------|
| **DUSt3R + 后处理** | SLAM3R 的底层基础, 支持双目/单目, 社区活跃 | 需要额外开发时序融合逻辑 |
| **Spann3R** | 基于 DUSt3R, 增量重建, 实时性好 | 需要训练或使用预训练权重 |
| **Depth Anything v2 + 三角化** | 单目深度估计成熟, 鲁棒性好 | 需要相机位姿 (ORB-SLAM3 提供) |
| **3D Gaussian Splatting** | 渲染质量最高, 可实时 | 训练慢, 在线模式复杂 |
| **保留 ORB-SLAM3 + 升级稠密** | 已有基础, 风险最小 | 质量受限于 SGBM, 不如深度学习方法 |

---

## 八、Agent 执行指南

当其他 Agent 读取本文档并执行 Phase 02 时，必须遵守以下规则:

1. **先检查环境** — 运行 `nvidia-smi` 确认 GPU 可用，确认 CUDA 版本
2. **严格按 Step 顺序执行** — Step 0 → Step 1 → Step 2 → ... → Step 7，不可跳跃
3. **Step 2 是关键门禁** — 如果 SLAM3R Demo 跑不通，暂停执行并报告，不要继续后续步骤
4. **增量修改，不推倒重来** — Phase 01 的代码和目录结构全部保留，仅在现有基础上扩展
5. **不修改已有 API 签名** — 新增端点走新路由前缀 `/api/slam3r/`
6. **所有新文件放在规划目录内** — SLAM3R 源码 → `SLAM/SLAM3R/`；ROS2 节点 → `ros2_ws/src/slam3r_ros/`；后端服务 → `web/backend/services/slam3r_service.py`
7. **每完成一个 Step，更新进度02.md (待创建)**
8. **遇到问题先查阅 经验01.md** — 可能有类似的坑 (如 f-string YAML 转义、导入路径等)
9. **GPU 环境不同于 Phase 01 的 CPU 环境** — 重新安装所有依赖，不要假设已有包可用
10. **所有 API Key 和密钥走环境变量** — 延续 Phase 01 惯例

---

## 九、成功标准

| 指标 | Phase 01 (基线) | Phase 02 目标 |
|------|----------------|---------------|
| 点云密度 | ~4 万点 (SGBM) | >50 万点 (SLAM3R) |
| 重建模式 | 仅离线批处理 | 离线 + 在线实时 |
| 推理速度 | 不适用 (CPU) | >= 5 FPS (GPU) |
| 相机标定 | 必需 (棋盘格) | 不需要 |
| 与前端通信 | HTTP 轮询 | WebSocket 实时推送 |
| ROS2 节点 | 1 个 (batch) | 2 个 (batch + stream) |
| 3D 前端渲染 | 静态点云文件 | 增量动态点云 |

---

## 十、附录

### A. 关键资源链接

| 名称 | URL |
|------|-----|
| SLAM3R 仓库 | https://github.com/PKU-VCL-3DV/SLAM3R |
| SLAM3R 论文 | https://arxiv.org/abs/2412.09401 |
| I2P 模型权重 | https://huggingface.co/siyan824/slam3r_i2p |
| L2W 模型权重 | https://huggingface.co/siyan824/slam3r_l2w |
| DUSt3R 仓库 | https://github.com/naver/dust3r |
| Replica 数据集 | https://cvg-data.inf.ethz.ch/nice-slam/data/Replica.zip |
| XFormers | https://github.com/facebookresearch/xformers |

### B. 环境变量 (新增)

```bash
# Phase 02 新增
SLAM3R_MODEL_PATH=siyan824/slam3r_i2p     # I2P 模型 (HF ID 或本地路径)
SLAM3R_L2W_MODEL_PATH=siyan824/slam3r_l2w  # L2W 模型
SLAM3R_DEVICE=cuda                          # 推理设备
SLAM3R_OUTPUT_DIR=./output/slam3r           # 结果输出目录
```

### C. 变更日志

| 日期 | 变更内容 | 作者 |
|------|----------|------|
| 2026-05-23 | v1.0 初始版本: Phase 02 总体规划, 基于 Phase 01 完成状态 + SLAM3R 调研 | Claude (DeepSeek) |
