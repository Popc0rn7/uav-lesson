# 无人机实践课程 · UAV Lesson

使用一台 PC 和一块 RoboPi 算力板，逐步完成硬件连接、飞控仿真、自主飞行、多机协作和大模型语义导航实践。仓库既提供学员操作文档与代码，也将提供教师准备 RoboPi 环境的部署工具。

PC 运行 PX4 SITL + Gazebo Docker 仿真，以及 QGroundControl、GUI 和可视化工具；OpenHarmony RoboPi 通过 HDC 开发、通过以太网与 PC 通信，运行 ROS 算法和模型推理。PX4 模拟飞控，RoboPi 模拟机载算力板。

## 课程安排

| 环节 | 时长 | 实践目标 |
| --- | --- | --- |
| 熟悉硬件 | 20 min | 连接 HDC，观察 ROS 包编译部署，使用 PC GUI 与板端大模型节点聊天 |
| 飞控 + 仿真 | 40 min | 启动仿真，连接 QGroundControl，观察传感器，完成三个递增难度赛道 |
| 全栈飞行 + 应用 | 80 min | 板端自主飞行、视觉任务、多机编队与探索，按课堂时间选做 |
| 大模型结合 | 60 min | NPU 模型部署与 VQA、语义导航、Jev API 对照实验与开放任务 |

总计约 200 分钟，不含课前安装、镜像下载、交叉编译和模型适配。详细待办与验收目标见 [实施路线图](docs/roadmap.md)。给后续开发代理的约定见 [AGENTS.md](AGENTS.md)。

## 当前可运行内容

- Stage 1：ROS 常驻模型聊天链路，PC 入口位于 `stage1/`，板端文件位于 `stage1/robopi/`；上游运行产物和模型需课前获取，操作见 [Hands-on](docs/stage1/Hands-on.md)。
- Stage 2：PC PX4/Gazebo 标准机 `x500_experiment`（Orbbec Gemini 2 RGBD＋MID-360S 几何近似），QGC 操作、四图展示和排障见 [Hands-on](docs/stage2/Hands-on.md)。用户已确认展示可用，改装后的完整飞行仍待验收；历史证据见 [实测记录](docs/stage2/Validation.md)。
- Stage 3：SUPER 的 Humble Docker 竞速与 PX4/Gazebo demo，含 FAST-LIO2、200 Hz IMU 传播状态和 Gazebo/RViz 双窗口。带墙面标记的 2 m/s 走廊往返已验收；[运行步骤](docs/stage3/Hands-on.md)、[验证与边界](docs/stage3/Validation.md)、[开发交接](docs/stage3/Development.md)。Jev 文本示例保留；板端迁移、统一算法对照、目标识别/追踪和聊天 GUI 尚未完成。

## Stage 2 标准机入口

教师课前准备镜像、QGC、图形环境及 `uv sync --extra stage2`。在 **PC 仓库根目录**按 [启动步骤](docs/stage2/Hands-on.md#2-学员启动单机仿真pc)运行标准机，两个模型目录必须同时挂载。仿真就绪后，在两个终端执行：

```bash
./stage2/show_sensors.sh  # WebUI：RGB、D，http://127.0.0.1:8090
./stage2/show_rviz.sh          # 两个 RViz：雷达点云、同帧表面体素
```

主入口在 `stage2/`；`models/x500_experiment/` 负责整机组合与 RGBD，`models/mid360s/` 维护雷达参数，`configure_mid360s.py` 提供三档扫描预算。`sensor_receiver.py`/`sensor_web.py` 负责接收与网页，`rviz_cloud_bridge.py` 是雷达和深度点云共用的 ROS 处理器。深度点云为 [补充实验](docs/stage2/Hands-on.md#调参和补充实验)。近似范围与官方规格对照见 [MID-360S](docs/stage2/MID-360S.md)。

## Stage 3 文本示例

在 PC 上使用 Python 3.12+ 和 uv：

```sh
uv sync
cp .env.example .env
# 编辑 .env，填入自己的 OPENROUTER_API_KEY
uv run stage3/demo.py '这个产品太好用了！'
```

示例通过网络调用 API，并输出正面情绪概率、情感分类和满意度。需要有效 API key，调用可能产生费用。`stage3/jev.py` 的接口与默认模型以当前代码为准；本次初始化未验证线上服务。

## 后续实施顺序

先建立可重复的 PC 仿真基线与 RoboPi 开发部署流程，再打通板端控制单架仿真无人机的链路。随后加入传感器可视化、竞速赛道和排行榜，最后逐项复现自主飞行、视觉、多机与大模型任务。

课程 hands-on 文档和教师准备脚本将随实际验证补齐；路线图中的待办不代表现在已经可运行。
