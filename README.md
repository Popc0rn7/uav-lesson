# 无人机实践课程 · UAV Lesson

使用一台 PC 和一块 RoboPi 算力板，逐步完成硬件连接、飞控仿真、自主飞行、多机协作和大模型语义导航实践。仓库既提供学员操作文档与代码，也将提供教师准备 RoboPi 环境的部署工具。

PC 运行 PX4 SITL 与 Gazebo／AirSim 仿真，以及 QGroundControl、GUI 和可视化工具；OpenHarmony RoboPi 通过 HDC 开发、通过以太网与 PC 通信，运行 ROS 算法和模型推理。PX4 模拟飞控，RoboPi 模拟机载算力板。

## 课程安排

| 环节 | 时长 | 实践目标 |
| --- | --- | --- |
| 熟悉硬件 | 20 min | 连接 HDC，观察 ROS 包编译部署，使用 PC GUI 与板端大模型节点聊天 |
| 飞控 + 仿真 | 40 min | 启动仿真，连接 QGroundControl，观察传感器，完成三个递增难度赛道 |
| 全栈飞行 + 应用 | 80 min | 板端自主飞行、视觉任务、多机编队与探索，按课堂时间选做 |
| 大模型结合 | 60 min | NPU 模型部署与 VQA、语义导航、Jev API 对照实验与开放任务 |

总计约 200 分钟，不含课前安装、镜像下载、交叉编译和模型适配。详细待办与验收目标见 [实施路线图](docs/roadmap.md)。给后续开发代理的约定见 [AGENTS.md](AGENTS.md)。

## 当前可运行内容

接续开发先读 [开发路线：上游复现 → 双 Docker → AirSim → RoboPi](develop/README.md)，了解每步替换的层、代码入口、验收条件和已知陷阱。Gazebo 双 Docker 配置入口如下；当前 AirSim 与板端操作入口见文末。在 PC 仓库根目录运行 `python3 develop/lesson.py list` 查看已接入实验，`python3 develop/lesson.py up --dry-run` 查看启动命令。

- Stage 1：ROS 常驻模型聊天链路，PC 入口位于 `stage1/`，板端文件位于 `robopi/stage1/`；上游运行产物和模型需课前获取，操作见 [Hands-on](docs/stage1/Hands-on.md)。
- Stage 2：PC PX4/Gazebo 标准机 `x500_experiment`（Orbbec Gemini 2 RGBD＋MID-360S 几何近似），QGC 操作、四图展示和排障见 [Hands-on](docs/stage2/Hands-on.md)。用户已确认展示可用，改装后的完整飞行仍待验收；相机配置实测见 [配置验证](docs/stage2/Hands-on.md#相机配置验证2026-10-10)。
- Stage 3：SUPER＋PX4/GNSS；Gazebo 无附加标记走廊 2 m/s XYZ 往返与三窗口已验收，FAST-LIO2 保留为显式对照。当前标准主线为 AirSim，低速短程／树林往返及 RoboPi 原生 1 m/s 短程／forest1 往返已通过，完整 AB 长任务未通过；[Gazebo 操作](docs/stage3/Hands-on.md)、[Gazebo 验证](docs/stage3/Validation.md)、[AirSim 操作](stage3/super/airsim/README.md)、[板端验证](docs/stage3/RoboPi-validation.md)。统一算法对照、Stage 3 视觉接入和聊天 GUI 尚未完成。

- Stage 4：AeroVLA 外部推理 API＋Town05 AirSim＋PX4／ROS 双 Docker；任务导出、轻量 uv 环境、WebUI、传感器与动作执行入口见 [Hands-on](docs/stage4/Hands-on.md)，实际验收范围见 [Validation](docs/stage4/Validation.md)。模型服务留在旧仓库，上板后续实现。
- Stage 5：Qwen分阶段规划与验收、Jev执行、红车RGBD跟随及只读任务灯箱；[架构与关键问题](docs/stage5/Agent.md)、[运行步骤](docs/stage5/Hands-on.md)、[验证记录](docs/stage5/Validation.md)。当前仅为指定街区的PC仿真demo，未验证通用目标、复杂绕障或实机。

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

板端开发与交付统一见 [robopi/AGENTS.md](robopi/AGENTS.md)，实际板端文件放在 `robopi/stageN/`；仓库 `skills/` 维护配套 Codex skills。Stage 1 新布局已完成部署回归，Stage 3 的板端短程链路已验证，完整 AB 任务仍待验收。

当前 Stage 3 标准主线为 AirSim＋PX4＋ROS＋SUPER（GNSS、无 LIO）；Docker 2 板端迁移入口及 NoDisplay 验证流程见 [AirSim README](stage3/super/airsim/README.md#robopi-算力后端2026-10-16迁移验证中)。已验证范围与换机接续见 [RoboPi 迁移交接](docs/stage3/RoboPi-handoff.md)。
