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

课程新主线从 Stage 2 使用“PC AirSim＋PX4 仿真容器”，自主算法阶段再增加 ROS 2 Humble 算力容器，后续由 RoboPi 替代算力容器。[Stage 2 AirSim 入口与验证范围](docs/stage2/AirSim.md)记录当前适配。既有 Gazebo 模块、实验配置与迁移工具见 [开发框架](develop/README.md)；该框架尚未接入新的 Stage 2 竞速入口。在 PC 仓库根目录运行 `python3 develop/lesson.py list` 查看已接入实验，`python3 develop/lesson.py up --dry-run` 查看启动命令。

- Stage 1：ROS 常驻模型聊天链路，PC 入口位于 `stage1/`，板端源码与编译入口位于 `houmo/src/`，上传包统一装配到 `houmo/deploy/`（见 [厚摩交付](houmo/README.md)）；目标 ELF 和模型需课前准备，操作见 [Hands-on](docs/stage1/Hands-on.md)。
- Stage 2：新的 [AirSim＋单 PX4 Docker 入口](docs/stage2/AirSim.md)直接通过 MAVLink 验证起降和短程往返，Stage 2 不需要 ROS 容器；原生固定准备区与手动开赛流程已获用户验收，完整穿门竞速待验收。既有 Gazebo 标准机 `x500_experiment`、QGC 操作、四图展示和排障保留在 [Hands-on](docs/stage2/Hands-on.md)；历史证据见 [实测记录](docs/stage2/Validation.md)。
- Stage 3：SUPER＋PX4/GNSS；Gazebo 无附加标记走廊 2 m/s XYZ 往返与三窗口已验收，FAST-LIO2 保留为显式对照。当前标准主线为 AirSim，低速短程／树林往返及 RoboPi 原生 1 m/s 短程／forest1 往返已通过，完整 AB 长任务未通过；[Gazebo 操作](docs/stage3/Hands-on.md)、[Gazebo 验证](docs/stage3/Validation.md)、[AirSim 操作](stage3/super/airsim/README.md)、[板端验证](docs/stage3/RoboPi-validation.md)。统一算法对照、Stage 3 视觉接入和聊天 GUI 尚未完成。

- Stage 4：AeroVLA 外部推理 API＋Town05 AirSim＋PX4／ROS 双 Docker；任务导出、轻量 uv 环境、WebUI、传感器与动作执行入口见 [Hands-on](docs/stage4/Hands-on.md)，实际验收范围见 [Validation](docs/stage4/Validation.md)。板端模型 HTTP 服务见 [AeroVLA](houmo/src/aerovla/README.md)，本阶段与板端的联合链路仍待验收。
- Stage 5：已接受的 AirSim_Mountains Shipping 车队场景，统一 runtime 管理场景／PX4／ROS；Qwen 子任务规划验收、DINO/Jev 感知决策、黄皮卡后上方持续跟随与只读灯箱。场景地址使用根 `.env` 的 `AIRSIM_MOUNTAINS`；[操作入口](docs/stage5/Hands-on.md)、[架构与边界](docs/stage5/Agent.md)、[开发导航](docs/stage5/Development.md)、[验证记录](docs/stage5/Validation.md)。其他两种跟随、复杂遮挡恢复、多轮稳定性、绕障及实机未验收，Gazebo 结果保留为历史对照。

## Stage 2 标准机入口

新的竞速环境使用 [AirSim 入口](docs/stage2/AirSim.md)，从 `uv run stage2/airsim/race.py up` 开始；以下为保留的 Gazebo 展示流程。

教师课前准备镜像、QGC、图形环境及 `uv sync --extra stage2`。在 **PC 仓库根目录**按 [启动步骤](docs/stage2/Hands-on.md#2-学员启动单机仿真pc)运行标准机，两个模型目录必须同时挂载。仿真就绪后，在两个终端执行：

```bash
./stage2/show_sensors.sh  # WebUI：RGB、D，http://127.0.0.1:8090
./stage2/show_rviz.sh          # 两个 RViz：雷达点云、同帧表面体素
```

主入口在 `stage2/`；`models/x500_experiment/` 负责整机组合与 RGBD，`models/mid360s/` 维护雷达参数，`configure_mid360s.py` 提供三档扫描预算。`sensor_receiver.py`/`sensor_web.py` 负责接收与网页，`rviz_cloud_bridge.py` 是雷达和深度点云共用的 ROS 处理器。深度点云为 [补充实验](docs/stage2/Hands-on.md#调参和补充实验)。近似范围与官方规格对照见 [MID-360S](docs/stage2/MID-360S.md)。

## 后续实施顺序

先建立可重复的 PC 仿真基线与 RoboPi 开发部署流程，再打通板端控制单架仿真无人机的链路。随后加入传感器可视化、竞速赛道和排行榜，最后逐项复现自主飞行、视觉、多机与大模型任务。

课程 hands-on 文档和教师准备脚本将随实际验证补齐；路线图中的待办不代表现在已经可运行。

板端开发与交付统一见 [robopi/AGENTS.md](robopi/AGENTS.md)，实际板端文件放在 `robopi/stageN/`；仓库 `skills/` 维护配套 Codex skills。Stage 1 新布局已完成部署回归，Stage 3 的板端短程链路已验证，完整 AB 任务仍待验收。

当前 Stage 3 标准主线为 AirSim＋PX4＋ROS＋SUPER（GNSS、无 LIO）；Docker 2 板端迁移入口及 NoDisplay 验证流程见 [AirSim README](stage3/super/airsim/README.md#robopi-算力后端2026-10-16迁移验证中)。已验证范围与换机接续见 [RoboPi 迁移交接](docs/stage3/RoboPi-handoff.md)。

## PC AirSim 场景路径

在 PC 仓库根目录首次配置（已有 `.env` 时只补充变量，保留已有密钥）：

```sh
cp -n .env.example .env
```

编辑 `.env.example` 中列出的配置，再按本机环境填写 `.env`：

- `AIRSIM_NH`（SUPER）、`AIRSIM_TOWN05`（AeroVLA）、`AIRSIM_RACE`（竞速）直接指向 Linux ELF，保留完整场景包资源，布局为 `<包根>/<项目>/Binaries/Linux/<ELF>`。Stage 2–4 的 settings 仍由各阶段独立准备；Stage 5 保留已接受场景包内的 settings。
- `AEROVLA_API_URL`、`DINO_DETECT_URL` 是完整服务端点；`QWEN_BASE_URL` 是 OpenAI 兼容服务基址，配套 `QWEN_MODEL`。示例值不代表服务已启动。
- Jev 使用 `JEV_BACKEND=typesafe|vllm`、`JEV_BASE_URL`、`JEV_MODEL` 和 `JEV_API_KEY`；vLLM System 1 另需模型头与校准 JSON，见 [Stage 5 操作说明](docs/stage5/Hands-on.md#jev-决策-clientpc)。RGB/depth 固定来自本机 8189 端口，不再提供两个环境变量。

入口自动读取根 `.env`，无需 `source`。优先级为 shell > 根 `.env`；显式客户端参数仍优先。Stage 5 不再读取旧 `stage5/.env`。路径支持 `~`，相对路径以仓库根目录为基准。缺失或空的 AirSim 路径会明确报出变量名。

SUPER/Town05 的 runtime 用 `binary_env` 选择变量，自动推导包根目录；自定义 JSON 仍支持原 `scene_dir` + `binary`。race 的显式 `--scene`、prepare 的 `--source` 仍接收包根目录并优先于环境配置。竞速关卡沿用 level 选择，共用 ADRL 包。更改路径后在下次启动生效，已运行实例使用原快照。

文件不存在时检查 ELF 路径及完整包资源。配置解析不代表启动或飞行验收；操作见 [SUPER AirSim](stage3/super/airsim/README.md)、[AeroVLA](docs/stage4/Hands-on.md) 和 [race](docs/stage2/AirSim.md)。
