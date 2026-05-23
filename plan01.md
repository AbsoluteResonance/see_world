# See World — 总体规划文档 v0.2

> 创建日期: 2026-05-23
> 最后更新: 2026-05-23
> 状态: Phase 0 基本完成 — 进入 Phase 1 准备
> 本文档是 See World 项目的总体指导规划，供后续各 Agent / 执行者参考。

---

## 一、项目概述

**目标:** 构建一套完整的"手机拍摄 → 上传 → 后台建图 / 场景理解 → 渲染展示"流水线。

**核心能力链:**
```
手机拍照/录像 → 上传网站/APP → 后台多模态理解(Kimi k2.6) → 3D建图(开源SLAM) → 渲染/展示
```

**仓库根目录:** `/root/autodl-tmp/`

---

## 二、目录结构总览

```
/root/autodl-tmp/
├── tools/
│   └── kimi/                        # Kimi API 多模态调用工具
│       ├── kimi_client.py           # Kimi API 封装 (kimi-k2.6)
│       ├── requirements.txt
│       └── README.md
│
└── projects/
    └── see_world/
        ├── plan01.md                # 本文档 — 总体规划
        │
        ├── web/                     # 网站子项目
        │   ├── backend/             # 后端 (FastAPI)
        │   │   ├── main.py          # 应用入口 + 生命周期
        │   │   ├── routes/
        │   │   │   ├── upload.py    # 图片/视频上传接口
        │   │   │   └── model.py     # 模型调用接口 (Kimi 分析 + SLAM 预留)
        │   │   ├── services/
        │   │   │   ├── kimi_service.py   # 封装调用 ../tools/kimi
        │   │   │   └── slam_service.py   # SLAM 建图服务 (预留坑位)
        │   │   ├── config.py        # 全局配置 (env -> pydantic Settings)
        │   │   └── utils.py         # 文件名校验、UUID 生成等工具函数
        │   ├── frontend/            # 前端 (SPA — 纯 HTML/CSS/JS)
        │   │   ├── index.html       # 主页面
        │   │   ├── css/
        │   │   │   └── style.css    # 全局样式
        │   │   └── js/
        │   │       ├── app.js       # 主逻辑
        │   │       ├── upload.js    # 上传模块
        │   │       └── gallery.js   # 画廊/预览模块
        │   └── uploads/             # 上传文件存储目录
        │       ├── images/
        │       └── videos/
        │
        ├── SLAM/                    # 开源建图模型子项目
        │   ├── README.md            # 选型记录 & 部署指南
        │   ├── ORB_SLAM2/           # ORB-SLAM2 工作目录 (待 clone)
        │   │   └── README_deploy.md # ORB-SLAM2 部署笔记
        │   └── VINS_Mono/           # VINS-Mono 工作目录 (待 clone)
        │       └── README_deploy.md # VINS-Mono 部署笔记
        │
        └── app/                     # 移动端 APP 子项目
            ├── README.md            # APP 技术选型 & 架构说明
            └── pwa/                 # PWA 快速验证版 (优先)
                └── manifest.json
```

---

## 三、手机硬件能力调研 (已确认)

**结论: 现代智能手机标配 9 轴 IMU。**

| 传感器 | 测量量 | 手机配备? |
|--------|--------|-----------|
| 加速度计 (3轴) | 线性加速度 | ✅ 标配 |
| 陀螺仪 (3轴) | 角速度 | ✅ 标配 |
| 磁力计 (3轴) | 磁场/地磁方向 | ✅ 标配 (用于指南针) |

主流供应商: Bosch Sensortec (BMI270/323)、STMicroelectronics (LSM6DS 系列)、TDK InvenSense。

**对 SLAM 选型的影响:**
- ORB-SLAM2/3 纯单目模式 → 不需要 IMU，可直接使用
- VINS-Mono 视觉-惯性融合 → 需要 IMU，手机满足条件
- 手机 IMU 属于消费级 (消费级 MEMS)，陀螺仪漂移 >10°/h，不适合长期纯惯性导航，但配合视觉进行短期融合完全可行

---

## 四、功能模块详细规划

---

### 模块 1: Kimi 多模态调用工具 (`tools/kimi/`)

**定位:** 封装 Kimi API，提供 Python SDK 供网站后端和其他模块调用。当 DeepSeek (纯文本模型) 需要理解和分析图片/视频内容时，通过此工具委托给 Kimi (kimi-k2.6) 处理。

**API 信息:**
- 模型: `kimi-k2.6`
- API Key: 通过环境变量 `KIMI_API_KEY` 注入，**严禁硬编码**
- Base URL: `https://api.moonshot.cn/v1`
- 兼容: OpenAI SDK 格式 (Chat Completions)

**需实现的能力:**
| 功能 | 描述 | 优先级 |
|------|------|--------|
| 单图理解 | 传入图片路径 + prompt，返回 Kimi 的文字描述 | P0 |
| 多图理解 | 一次传入多张图片，让 Kimi 对比/综合分析 | P1 |
| 视频理解 | 上传视频文件，Kimi 逐帧或摘要理解 | P1 |
| 流式对话 | 支持 stream 模式，实时返回 | P2 |
| 图片定位/检测 | 让 Kimi 描述图中物体的位置、边界框等 | P1 |

**文件规划及实现要点:**

```
tools/kimi/
├── kimi_client.py          # 核心 SDK 类
├── cli.py                  # CLI 入口 (argparse)
├── requirements.txt        # openai, pillow, python-multipart
└── README.md
```

**kimi_client.py 实现要点:**
- 使用 `openai.OpenAI` 客户端，base_url 指向 `https://api.moonshot.cn/v1`
- API Key 从 `os.getenv("KIMI_API_KEY")` 读取，不设置默认值
- `KimiClient` 类:
  - `__init__(self, api_key=None, model="kimi-k2.6")` — 初始化 OpenAI client
  - `understand_image(image_path, prompt)` — 读取图片 → base64 → 构造 `contents` 为 `[{"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}, {"type": "text", "text": prompt}]` → 调用 `chat.completions.create` → 返回 JSON `{"content": ..., "usage": ...}`
  - `understand_images(image_paths, prompt)` — 同上，多张图片
  - `understand_video(video_path, prompt)` — 对于小于 100MB 的视频，直接传文件 URL (根据 Kimi API 文档)；大视频先提取关键帧再送图片理解
  - `chat(messages, stream=False)` — 通用对话接口
  - `describe_image(image_path)` — 快捷方法：自动 prompt = "请详细描述这张图片的内容，包括场景、物体、人物、颜色、位置关系等"
- 错误处理: API 调用失败时 raise 自定义 `KimiAPIError`，带原始错误信息

**cli.py 实现要点:**
- 使用 argparse 解析 `--image` / `--images` / `--video` / `--prompt` / `--stream`
- 打印 JSON 结果到 stdout
- 用法示例: `python cli.py --image ./photo.jpg --prompt "这张图片里有几辆车？"`

**requirements.txt:**
```
openai>=1.0.0
pillow>=10.0.0
python-multipart>=0.0.6
```

---

### 模块 2: 上传网站 (`projects/see_world/web/`)

**定位:** 对外可访问的 Web 应用，提供图片/视频上传功能，后台对接 Kimi 做初步的多模态理解，并为后续 SLAM 建图预留接口。

**技术选型:**
- **后端:** Python FastAPI (异步、性能好、自带 Swagger 文档)
- **前端:** 纯 HTML5 + CSS3 + 原生 JavaScript (轻量、零构建工具依赖、快速上线)
- **部署:** uvicorn + cloudflared tunnel (首选外网方案)
- **存储:** 本地文件系统 (后续可迁移至 OSS)

**外网访问方案 (按优先级):**
1. **cloudflared tunnel** — 免费、无需公网 IP、自动 HTTPS、无速率限制
2. **ngrok** — 简单但有速率限制 (免费版约 40 req/min)
3. **frp 内网穿透** — 需自有公网服务器，灵活但需额外资源

---

#### 2.1 后端 API 详细设计

| 路由 | 方法 | 描述 | 优先级 |
|------|------|------|--------|
| `/api/upload/image` | POST | 上传单张图片 | P0 |
| `/api/upload/video` | POST | 上传视频 (< 200MB) | P0 |
| `/api/upload/batch` | POST | 批量上传图片 (最多 20 张) | P1 |
| `/api/analyze/:file_id` | POST | 调用 Kimi 分析图片/视频内容 | P0 |
| `/api/reconstruct` | POST | 调用 SLAM 建图 (预留接口) | P2 |
| `/api/files` | GET | 列出已上传文件 (支持分页) | P0 |
| `/api/files/:file_id` | GET | 返回文件详情 JSON | P0 |
| `/api/files/:file_id/download` | GET | 下载原文件 | P1 |
| `/api/files/:file_id/thumbnail` | GET | 返回缩略图 (图片返回压缩版，视频返回首帧) | P1 |
| `/api/health` | GET | 健康检查 | P0 |
| `/` | GET | 前端 SPA 页面 | P0 |

**通用响应格式:**
```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```
错误时 `code` 为非零 (如 40001 文件过大, 40002 格式不支持, 50001 服务内部错误)。

**文件存储规范:**
- 文件名: `{timestamp}_{uuid8}_{sanitized_original_name}`
- 存储路径: `/root/autodl-tmp/projects/see_world/web/uploads/{images|videos}/`
- 支持格式: jpg, jpeg, png, webp, mp4, mov, avi
- 大小限制: 图片 < 20MB, 视频 < 200MB

---

#### 2.2 后端文件实现要点

**config.py:**
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    kimi_api_key: str = ""
    upload_dir: str = "./uploads"
    host: str = "0.0.0.0"
    port: int = 8080
    max_image_size_mb: int = 20
    max_video_size_mb: int = 200
    kimi_model: str = "kimi-k2.6"
    tunnel_token: str = ""  # Cloudflare tunnel token (optional)

    class Config:
        env_prefix = "SEE_WORLD_"
        env_file = ".env"

settings = Settings()
```

**main.py 实现要点:**
- 创建 FastAPI app，挂载 CORS 中间件 (允许所有来源，开发阶段)
- 挂载静态文件服务 `/uploads` → `uploads/` 目录
- 挂载前端静态文件 `/static` → `frontend/` 目录
- `@app.on_event("startup")` — 创建 uploads 子目录、验证 Kimi API Key 可用性
- 引入 routes/upload.py 和 routes/model.py 的路由

**routes/upload.py 实现要点:**
- `POST /api/upload/image` — 接收 `UploadFile`，校验扩展名和大小 → 保存到 `uploads/images/` → 返回 `{"file_id": ..., "filename": ..., "size": ..., "url": ...}`
- `POST /api/upload/video` — 同上，目标路径 `uploads/videos/`
- `POST /api/upload/batch` — 接收 `List[UploadFile]`，并发保存，返回成功/失败统计
- `GET /api/files` — 扫描 uploads 目录，列出所有文件，支持 `?page=1&size=20`
- `GET /api/files/{file_id}` — 查找 uuid 匹配的文件，返回文件信息 JSON
- `GET /api/files/{file_id}/download` — FileResponse 返回原文件流
- `GET /api/files/{file_id}/thumbnail` — 图片: Pillow 压缩到 300px 宽；视频: 暂返回占位图

**routes/model.py 实现要点:**
- `POST /api/analyze/{file_id}` — 读取文件 → 根据类型(image/video)调用 `KimiService.analyze(file_path, prompt)` → 返回分析结果 JSON
  - 请求体: `{"prompt": "请描述这张图片", "model": "kimi-k2.6"}`
  - 响应: `{"content": "Kimi 分析结果文本...", "model": "kimi-k2.6", "tokens": {"input": 1234, "output": 567}}`
- `POST /api/reconstruct` — 预留接口，直接返回 `{"code": 0, "message": "SLAM 模型尚未部署", "data": null}`

**services/kimi_service.py 实现要点:**
- 封装 `from tools.kimi.kimi_client import KimiClient`
- `KimiService.analyze(file_path, prompt, model="kimi-k2.6")` — 判断是图片还是视频 → 调用对应的 KimiClient 方法 → 返回统一格式 result dict
- `KimiService.analyze_batch(file_paths, prompt)` — 多文件批量分析
- 添加结果缓存: `{file_id}_{prompt_hash}.json` 存于 `uploads/.cache/`

**services/slam_service.py 实现要点:**
- 纯占位: 所有方法返回 `{"status": "not_implemented"}` 
- 预留接口: `reconstruct(images_dir, output_dir)`, `get_pose()`, `get_pointcloud()`
- 供 Phase 2 填充

---

#### 2.3 前端实现要点

**页面结构 (index.html):**
```
┌──────────────────────────────────────┐
│  See World                           │
│  上传 & 场景理解                       │
├──────────────────────────────────────┤
│  ┌────────────────────────────────┐  │
│  │   拖拽或点击上传                  │  │
│  │   📷 图片 / 🎬 视频              │  │
│  │   支持批量上传 (最多20张)         │  │
│  └────────────────────────────────┘  │
│  [上传进度条]                         │
├──────────────────────────────────────┤
│  已上传文件画廊                       │
│  ┌───┐ ┌───┐ ┌───┐ ┌───┐           │
│  │   │ │   │ │   │ │   │           │
│  │ 📷 │ │ 📷 │ │ 🎬 │ │ 📷 │           │
│  │   │ │   │ │   │ │   │           │
│  └───┘ └───┘ └───┘ └───┘           │
│  点击文件 → 查看详情 / AI 分析         │
├──────────────────────────────────────┤
│  ┌────────────────────────────────┐  │
│  │  🤖 Kimi 分析结果               │  │
│  │  [分析文本...]                  │  │
│  └────────────────────────────────┘  │
│  [🔧 建图] [预留]                    │
└──────────────────────────────────────┘
```

**关键交互逻辑 (app.js):**
1. **拖拽上传:** 监听 dragenter/dragover/drop 事件，高亮上传区
2. **上传进度:** 使用 `XMLHttpRequest.upload.onprogress` 显示百分比
3. **画廊刷新:** 上传成功后调用 `GET /api/files` 刷新画廊
4. **AI 分析:** 点击画廊中的文件 → 弹出 prompt 输入框 (默认 "请描述这张图片") → 调用 `POST /api/analyze/{file_id}` → 展示结果
5. **建图按钮:** 点击 → 弹出 "SLAM 模型尚未部署" 提示
6. **响应式:** CSS Grid 布局，移动端单列、桌面多列

---

### 模块 3: 开源建图模型 (`projects/see_world/SLAM/`)

**定位:** 部署两个经典的 SLAM 系统: ORB-SLAM2 (纯视觉单目) 和 VINS-Mono (视觉-惯性单目)，为后续手机建图提供后端引擎。

**前提确认 (基于调研):**
- ✅ ORB-SLAM2 支持纯单目视觉模式，无需 IMU
- ✅ VINS-Mono 需要 IMU 数据，手机标配 9 轴 IMU → 满足条件
- ✅ 两个系统均为 C++ 实现，均依赖 ROS (Robot Operating System)

---

#### 3.1 ORB-SLAM2

**仓库:** https://github.com/raulmur/ORB_SLAM2
**许可证:** GPLv3
**作者:** Raul Mur-Artal, Juan D. Tardós (Universidad de Zaragoza)
**论文:** "ORB-SLAM2: an Open-Source SLAM System for Monocular, Stereo and RGB-D Cameras", IEEE T-RO, 2017

**核心特点:**
- 纯视觉特征点法 SLAM (基于 ORB 特征)
- 支持三种模式: Monocular / Stereo / RGB-D
- 实时重定位 + 回环检测 + 全局 BA
- 尺度模糊是单目模式的固有局限 (无法恢复绝对尺度)

**依赖项:**
| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| OpenCV | ≥ 2.4.3 | 图像处理 + ORB 特征提取 |
| Eigen3 | ≥ 3.1.0 | 线性代数 |
| Pangolin | latest | 可视化 / GUI |
| DBoW2 | 内置 (Thirdparty/) | 词袋模型 (回环检测) |
| g2o | 内置 (Thirdparty/) | 图优化 |
| ROS | Hydro+ (可选) | ROS 节点支持 |

**部署规划:**

1. **获取源码:**
   ```bash
   cd /root/autodl-tmp/projects/see_world/SLAM/ORB_SLAM2
   git clone https://github.com/raulmur/ORB_SLAM2.git src
   ```

2. **编译步骤 (标准流程):**
   ```bash
   cd src
   chmod +x build.sh
   ./build.sh
   ```
   build.sh 会自动编译 Thirdparty (DBoW2 + g2o) 和 ORB-SLAM2 本体。

3. **单目测试 (TUM 数据集):**
   ```bash
   ./Examples/Monocular/mono_tum \
     Vocabulary/ORBvoc.txt \
     Examples/Monocular/TUM1.yaml \
     /path/to/TUM/sequence
   ```

4. **输出:**
   - 相机轨迹 (KeyFrameTrajectory.txt)
   - 稀疏 3D 地图点
   - 实时 Pangolin 可视化窗口

**关键注意事项:**
- ORBvoc.txt 约 40MB，需要单独下载
- 单目模式需要良好的初始化 (平移 + 一定旋转)
- 纯旋转运动会导致初始化失败
- 建议使用 ORB-SLAM3 (https://github.com/UZ-SLAMLab/ORB_SLAM3) 作为替代，功能更全且支持纯单目

**ORB_SLAM2/README_deploy.md 应记录:**
- 上述部署步骤的详细执行结果
- 遇到的编译/运行问题和解决方案
- 测试数据集的表现数据
- 相机标定参数 .yaml 的准备方法

---

#### 3.2 VINS-Mono

**仓库:** https://github.com/HKUST-Aerial-Robotics/VINS-Mono
**许可证:** GPLv3
**作者:** Tong Qin, Peiliang Li, Shaojie Shen (HKUST Aerial Robotics Group)
**论文:** "VINS-Mono: A Robust and Versatile Monocular Visual-Inertial State Estimator", IEEE T-RO, 2018

**核心特点:**
- 紧耦合、基于滑窗优化的视觉-惯性里程计 (VIO)
- 自动初始化 (无需已知初始姿态)
- 在线外参标定 (相机-IMU)
- 失效检测与恢复
- 回环检测 + 4 自由度位姿图优化
- 地图保存/加载/合并

**为什么选 VINS-Mono:**
- 业界最广泛使用的开源 VIO 系统
- 手机 IMU 可以满足其传感器要求
- 有配套移动端实现: VINS-Mobile (iOS, 已归档但代码可参考)
- 有升级版 VINS-Fusion (支持多传感器)

**依赖项:**
| 依赖 | 说明 |
|------|------|
| ROS | Kinetic/Melodic (Ubuntu 16.04/18.04) 或 Noetic (20.04) |
| Ceres Solver | 非线性优化后端 |
| OpenCV | 图像处理 |
| Eigen3 | 线性代数 |

**部署规划:**

1. **获取源码:**
   ```bash
   cd /root/autodl-tmp/projects/see_world/SLAM/VINS_Mono
   git clone https://github.com/HKUST-Aerial-Robotics/VINS-Mono.git src
   ```

2. **编译 (ROS workspace):**
   ```bash
   mkdir -p ~/catkin_ws/src
   ln -s /root/autodl-tmp/projects/see_world/SLAM/VINS_Mono/src ~/catkin_ws/src/
   cd ~/catkin_ws
   catkin_make
   source devel/setup.bash
   ```

3. **单目+IMU 测试 (EuRoC 数据集):**
   ```bash
   roslaunch vins_estimator euroc.launch
   roslaunch vins_estimator vins_rviz.launch
   rosbag play MH_05_difficult.bag
   ```

4. **输出:**
   - 相机位姿 (6-DOF, 带绝对尺度！)
   - 稀疏/半稠密点云
   - IMU 偏置估计
   - 实时 Rviz 可视化

**关键注意事项:**
- VINS-Mono **必须有 IMU 才能运行**，不支持纯视觉模式
- 相比 ORB-SLAM2 纯视觉，VINS-Mono 可以恢复绝对尺度 (由 IMU 提供)
- 手机 IMU 需要与相机进行标定 (camera-IMU extrinsic calibration)
- VINS-Mobile 仓库 (https://github.com/HKUST-Aerial-Robotics/VINS-Mobile) 是 iOS 原生实现，但已于 2017 年停止更新，只能作为算法参考

**与 APP 模块的关系:**
- 最终 APP 的实时建图能力可以参考 VINS-Mono 的算法流程
- 但需要针对移动端重新实现 (用 ARKit/ARCore 的 VIO 替代，或者自研轻量 VIO)
- 先在服务器端跑通 VINS-Mono，验证算法可行性

**VINS_Mono/README_deploy.md 应记录:**
- 详细的 ROS 环境配置
- 编译过程和依赖安装
- EuRoC 测试数据集运行结果
- 相机-IMU 标定流程
- 手机 IMU 数据格式转换方法

---

#### 3.3 SLAM 模块 FAQ (基于调研)

**Q: 手机有没有 IMU？**
A: 有。现代手机标配 9 轴 IMU (加速度计 + 陀螺仪 + 磁力计)。供应商: Bosch (BMI270/323)、ST (LSM6DS)、InvenSense (ICM-4/6 系列)。消费级 MEMS 精度，陀螺漂移 >10°/h，但配合视觉融合足够使用。

**Q: ORB-SLAM2 vs ORB-SLAM3 选哪个？**
A: ORB-SLAM3 是 ORB-SLAM2 的直接升级，功能更全 (视觉+惯导+多地图)。建议优先考虑 ORB-SLAM3，但 ORB-SLAM2 作为经典基线仍有部署价值。

**Q: 没有 IMU 能不能跑 VINS-Mono？**
A: 不能。VINS-Mono 是视觉-惯性系统，IMU 数据是必须输入。为没有 IMU 的场景，请使用 ORB-SLAM2/3 的纯视觉模式。

**Q: VINS-Mobile 还能用吗？**
A: 不能直接用于现代 iOS。最后一次更新是 2017 年，依赖 Xcode 8 + iOS 10。只建议参考其算法实现，实际 APP 建议用 ARKit (iOS) / ARCore (Android) 或自研轻量 VIO。

---

### 模块 4: 移动端 APP (`projects/see_world/app/`)

**定位:** 将 Web 能力打包为手机 APP，扩展原生能力 (相机、GPS、实时渲染)。

**核心需求:**
- 调用手机摄像头，实时取景
- 拍照/录像上传至后端服务器
- 实时获取相机 6-DOF 位姿 (依赖 SLAM 模块)
- 获取 GPS 位置信息
- 将 3D 重建结果实时渲染叠加到相机画面 (AR 效果)
- 跨平台 (至少支持 Android，最好同时支持 iOS)

**技术选型对比:**
| 方案 | 相机/GPS | 3D AR 渲染 | 热更新 | 包体积 | 评估 |
|------|----------|------------|--------|--------|------|
| PWA | 有限 (`getUserMedia`) | WebXR (实验性) | ✅ 天然 | 极轻 | 快速验证首选 |
| React Native + Expo | 良好 (expo-camera) | 一般 (Three.js) | ✅ OTA | 中 | 常规 APP 首选 |
| Flutter | 良好 (camera plugin) | 弱 (需桥接) | ❌ 需发版 | 中 | 跨平台但 3D 弱 |
| Native (Kotlin/Swift) | 最佳 | ARKit/ARCore 最强 | ❌ | 大 | 最终方案 |
| Unity | 优秀 | 最强 3D 引擎 | ❌ | 大 | 游戏/3D heavy APP |

**推荐三阶段路线:**
```
Phase A: PWA 快速原型
  → 验证上传流程、Kimi 分析、后端连通性
  → 移动端浏览器即可使用，无需安装
  → 局限性: 相机调用受限、无法做 AR 渲染

Phase B: React Native / Flutter 完整 APP  
  → 下载安装，调用原生相机 + GPS
  → 上传→分析→展示 完整闭环
  → 预留 AR 渲染能力接口

Phase C: 原生 AR 渲染层
  → 对接 SLAM 模型的实时位姿输出
  → ARKit/ARCore 原生 3D 渲染叠加
  → 最终完整体验
```

**PWA 实现要点 (Phase A — 优先启动):**
- `app/pwa/manifest.json` — PWA 配置 (name: "See World", display: standalone, icons 等)
- 复用 Web 前端，增加 Service Worker 离线缓存
- `navigator.mediaDevices.getUserMedia({video: true})` 打开相机
- `navigator.geolocation.watchPosition()` 获取 GPS
- PWA 的 Camera API 无法获取每一帧的原始像素数据做实时 SLAM — 这是 PWA 的根本局限

**React Native APP 实现要点 (Phase B — 后续启动):**
- 使用 `react-native-vision-camera` 获取高帧率相机流
- 使用 `react-native-sensors` 读取 IMU 数据 (加速度计+陀螺仪)
- 使用 `@react-native-community/geolocation` 获取 GPS
- 相机帧上传到后端，后端跑 SLAM → 返回位姿 → 前端 Three.js 渲染

---

## 五、实施路线图

```
Phase 0: 基础搭建 ✅ (2026-05-23 完成)
├── ✅ 创建目录结构
├── ✅ 撰写 plan01.md
├── ✅ 实现 Kimi 多模态调用工具 (tools/kimi/)
│   ├── ✅ kimi_client.py — KimiClient SDK
│   ├── ✅ cli.py — 命令行工具
│   └── ✅ requirements.txt
│
├── ✅ 实现上传网站 v0.1 (projects/see_world/web/)
│   ├── ✅ backend/main.py + config.py + utils.py
│   ├── ✅ backend/routes/upload.py (上传 + 文件管理)
│   ├── ✅ backend/routes/model.py (分析接口 + SLAM 预留)
│   ├── ✅ backend/services/kimi_service.py (对接 Kimi)
│   ├── ✅ backend/services/slam_service.py (占位)
│   ├── ✅ frontend/ (HTML + CSS + JS)
│   ├── ✅ uvicorn 启动 (已测试: health ✅, upload ✅, files ✅, thumbnail ✅, analyze ✅)
│   └── ⬜ cloudflared 外网访问 (可选，需要 token 时启用)
│
└── ✅ 更新 plan01.md checkbox

Phase 1: 核心闭环 ✅
├── ✅ 网站对接 Kimi，实现"上传→分析→展示"完整闭环 (2026-05-23)
├── ⬜ 外网可访问确认 (cloudflared tunnel)
├── ✅ SLAM 模型部署:
│   ├── ✅ ORB-SLAM3 编译 + 测试 (TUM fr1_xyz: 798帧, 36ms/帧)
│   ├── ✅ Python 接口 (slam_runner.py) — 自动数据集检测
│   ├── ✅ Web API 全链路集成 (reconstruct/job/trajectory)
│   └── ⬜ VINS-Mono (需 ROS Noetic 环境, Ubuntu 22.04 不兼容)

Phase 2: 3D 能力
├── ⬜ 网站增加建图接口 (上传多图 → SLAM 后端 → 返回结果)
├── ⬜ 3D 点云结果预览 (WebGL / Three.js)
├── ⬜ 多图/视频 → 3D 场景管线打通
└── ⬜ 手机拍摄数据集成测试

Phase 3: 移动化
├── ⬜ PWA 原型: 相机 + 上传 + 查看
├── ⬜ React Native / Flutter APP 开发
│   ├── ⬜ 原生相机 + GPS + IMU 权限
│   ├── ⬜ 实时上传帧 → 后端建图
│   └── ⬜ 位姿结果回传 → AR 渲染
└── ⬜ 完整移动端闭环测试
```

---

## 六、跨模块约定

### 6.1 文件命名规范
- 上传文件: `{timestamp}_{uuid8}_{sanitized_original_name}`
- Kimi 分析缓存: `{file_id}_{prompt_md5hash}.json`
- SLAM 输出: `{session_id}/trajectory.txt`, `{session_id}/pointcloud.ply`

### 6.2 API 通信格式
统一 JSON:
```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```
错误码: `0` 成功; `40001` 参数错误; `40002` 文件格式不支持; `40003` 文件过大; `50001` 服务内部错误; `50002` Kimi API 调用失败; `50003` SLAM 模型错误

### 6.3 环境变量
所有密钥/配置统一走环境变量:
```bash
KIMI_API_KEY=sk-xxxxx                 # Kimi API Key (必需)
SEE_WORLD_UPLOAD_DIR=./uploads        # 上传目录
SEE_WORLD_HOST=0.0.0.0                # 监听地址
SEE_WORLD_PORT=8080                   # 服务端口
SEE_WORLD_TUNNEL_TOKEN=xxx            # Cloudflare Tunnel Token
SEE_WORLD_MAX_IMAGE_SIZE_MB=20        # 图片大小上限
SEE_WORLD_MAX_VIDEO_SIZE_MB=200       # 视频大小上限
SEE_WORLD_KIMI_MODEL=kimi-k2.6        # Kimi 模型版本
```

### 6.4 技术栈统一
- Python >= 3.10
- FastAPI + uvicorn + python-multipart
- openai SDK (兼容 Kimi API)
- 前端: 零框架 (HTML5 + CSS3 + Vanilla JS)
- C++ 模块: CMake + OpenCV + Eigen3 + ROS
- 外网: cloudflared tunnel

---

## 七、Agent 执行指南

当其他 Agent 读取本文档时，应:

1. **先检查当前状态** — 对照第五节的路线图 checkbox，确认各模块的实际进度
2. **按优先级执行** — Phase 0 → Phase 1 → Phase 2 → Phase 3，模块内部按 P0 → P1 → P2 排序
3. **模块之间解耦** — Kimi 工具可独立开发测试，网站可先用 mock 数据跑通流程，SLAM 可独立编译测试
4. **所有代码放在对应模块目录下** — 不要污染上级目录
5. **每完成一个子任务，更新本文档中对应项的 checkbox (⬜ → ✅)**
6. **遇到需要多模态理解图片/视频时**，不自行处理，而是调用 Module 1 的 Kimi 工具
7. **先读对应模块的 README** — 如果存在 README_deploy.md 或 README.md，先阅读再动手
8. **所有 API Key 从环境变量读取**，严禁在代码中硬编码

---

## 八、附录

### A. 关键 URL 和仓库

| 名称 | URL | 说明 |
|------|-----|------|
| Kimi API 文档 | https://platform.moonshot.cn/docs | Kimi API 参考 |
| Kimi API Base URL | https://api.moonshot.cn/v1 | OpenAI 兼容 |
| ORB-SLAM2 主仓库 | https://github.com/raulmur/ORB_SLAM2 | 经典纯视觉 SLAM |
| ORB-SLAM3 主仓库 | https://github.com/UZ-SLAMLab/ORB_SLAM3 | 升级版 (推荐) |
| VINS-Mono 主仓库 | https://github.com/HKUST-Aerial-Robotics/VINS-Mono | 视觉-惯性 SLAM |
| VINS-Mobile (iOS) | https://github.com/HKUST-Aerial-Robotics/VINS-Mobile | 移动端参考 (已归档) |
| VINS-Fusion | https://github.com/HKUST-Aerial-Robotics/VINS-Fusion | 多传感器 VINS |

### B. 变更日志
| 日期 | 变更内容 | 作者 |
|------|----------|------|
| 2026-05-23 | v0.1 初始版本: 目录结构 + 四模块概述 | Claude (DeepSeek) |
| 2026-05-23 | v0.2 大幅更新: 手机 IMU 调研；SLAM 模块细化 (ORB-SLAM2 + VINS-Mono 详细部署规划)；Kimi 模块细化 (类设计+代码要点)；Web 模块细化 (API+前后端实现要点)；APP 模块细化 (三阶段路线)；FAQ；错误码 | Claude (DeepSeek) |
| 2026-05-23 | v0.3 Phase 0 实现: Kimi 模块代码完成 + Web 后端全套 API + 前端 SPA + 服务部署测试通过 | Claude Code |
