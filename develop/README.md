# develop：双 Docker 开发环境

开发统一采用两个运行角色：Docker 1 运行 PX4＋Gazebo，Docker 2 运行 ROS 2 Humble 和算力侧应用。进入板端阶段时，RoboPi 替代 Docker 2，Docker 1 继续提供飞控和仿真。QGC、可视化、评测与教师工具留在 PC。

两个基线镜像只提供环境。课程开发的交付单位是**模块及其组合成的实验**：实验固定场景、传感器、算法、控制、任务、资源和验收条件，镜像负责这些模块的运行依赖。Stage 是课堂组织方式，不作为算法间的依赖边界。

## 目录与复用范围

- `docker/`：通用算力镜像 Dockerfile、环境入口与离线自检。
- `profiles/`：实验模块组合、启动参数、共享资源与验收证据。
- `lesson.py`：PC 统一命令入口，目前委托 Stage 3 后端执行。
- `../stageN/`：各阶段的代码、配置、模型与启动脚本；尚未迁移到此目录。
- `../thirdparty/`：上游算法源码和本地编译产物，忽略 Git，通过挂载接入容器。

Stage 1–3 计划复用两个容器角色，按实验选择挂载和启动节点。当前只有 SUPER 走廊配置接入此入口。Stage 1 聊天可不启动仿真容器，OpenHarmony/Houmo 推理产物仍在 RoboPi；Stage 2 的传感器展示还使用原入口。基础镜像提供运行依赖，容器是运行实例，挂载把 PC 文件映射进容器；修改挂载源码不必重建镜像，修改 Dockerfile 则需重建镜像，并在确认落地后重建运行容器。

## 模块边界与已有实现

| 模块 | 职责与运行位置 | 当前代码 | 迁移到 RoboPi 的处理 |
| --- | --- | --- | --- |
| 仿真资产 | Docker 1：飞控、整机模型、雷达模型、世界 | `stage2/models/`、`stage3/generate_gazebo_corridor.py`、`stage3/px4_start.sh` | 留在 PC |
| 仿真传感器接入 | 将 Gazebo 扫描、IMU、时钟转换为算法输入；开发期在 Docker 2 | `stage3/ros_src/stage3_lidar/`、`stage3/super_imu.py`、`run_super_nodes.sh` 的 ros_gz_bridge | 板端不默认安装 Gazebo；先在 PC 接入，再通过以太网 ROS 传输；实机改用设备驱动 |
| 定位与输入适配 | Docker 2：FAST-LIO2、点云坐标转换、外参和里程计 | `prepare_lio.py`、`fast_lio_gazebo.yaml`、`lio_bridge.py`、`lio_geometry.py` | 算法及消息依赖重新构建；保持输入接口与时间语义 |
| 规划 | Docker 2：地图与轨迹生成 | SUPER 上游工作区、`super_*.yaml`、`patch_super_height.py` | 重新构建核心和依赖；GCOPTER 仍待接入统一实验 |
| 控制与监督 | Docker 2：飞行状态、轨迹约束、ENU/FLU ↔ NED/FRD、失流处理 | `super_px4.py`，当前还含任务逻辑 | 保持控制协议，重新验证消息 ABI、DDS、墙钟超时及降落 |
| 任务 | Docker 2：起飞、目标序列、返程 | 当前分散在 `super_px4.py` 与验收脚本 | 后续从控制桥提取；任务通过受约束接口提交目标 |
| 评测与可视化 | PC：真值、成功判据、故障注入、Gazebo/RViz/Web | `verify_super_*.py`、`check_*.py`、`super_gazebo_view.py`、`stage2/show_*.sh` | 留在 PC；真值不得成为板端定位或控制输入 |
| 模型应用 | 算力侧：聊天、后续视觉或语义任务 | `stage1/robopi/`、`stage3/jev.py` | Stage 1 有独立运行依赖；Jev 目前只有文本示例，尚未接入飞行 |

这是对已有实现的职责映射。当前节点尚未全部拆成独立模块，尤其控制与任务仍耦合。新增功能按此边界组织；不为了目录整齐一次性搬动全部已验收代码。

## 三层配置与交付

1. **环境**：Docker 1 的 PX4/Gazebo 镜像；Docker 2 的 Humble 基础环境、模块依赖和开发工具。固定镜像摘要、架构、上游版本和补丁，课前完成下载与构建。
2. **模块**：声明输入输出消息、坐标系、单位、QoS、时间源、依赖、参数、启动方式、停止方式和异常行为。只有算法模块不应直接依赖 Gazebo 或 HDC；这些依赖放到适配或部署层。
3. **实验配置**：组合模块并固定场景、传感器、速度、资源和证据。一次实验使用一种算力后端；切到 RoboPi 时替换启动/部署与传感器传输适配，不把 Linux install 目录复制上板。

当前首个配置为 [super-lio-corridor.json](profiles/super-lio-corridor.json)，选取已验收的带墙面标记、2 m/s FAST-LIO2＋SUPER 走廊。配置是现有后端的组合入口，目前只能选择已接入组合，不能任意交换 planner 或并行启动多套。资源仍固定为 ROS 域 10、Gazebo 分区 `uav-stage3`、UDP 8888、HTTP 8096；同一 PC 由一组持有运行权。

## 当前可运行入口（PC 仓库根目录）

只查看配置与启动命令无需 Docker，也不会调用付费 API：

```sh
python3 develop/lesson.py list
python3 develop/lesson.py plan
python3 develop/lesson.py up --dry-run
```

成功判据：退出码 0，显示模块组合、固定资源以及 `super_docker.py up` 的完整参数。未知配置或缺失故障类型会以非零退出码停止。

教师按现有 [Stage 3 准备与运行步骤](../docs/stage3/Hands-on.md)准备上游源码、镜像、构建产物与 GPU。以下入口委托原后端执行，前置条件、飞行判据和排障继续以该文档为准：

```sh
python3 develop/lesson.py prepare
python3 develop/lesson.py build
python3 develop/lesson.py lio-build
python3 develop/lesson.py up
python3 develop/lesson.py inspect
python3 develop/lesson.py scan
python3 develop/lesson.py view
python3 develop/lesson.py verify
# verify 会执行飞行；fault 会注入故障，按现有 Hands-on 单独操作。
# 确认已落地且 Disarmed 后：
python3 develop/lesson.py down
```

内存紧张时，构建入口支持 `build --build-jobs 1` 与 `lio-build --build-jobs 1`。通用镜像独立构建和离线自检见 [教师准备](../docs/stage3/Hands-on.md#教师准备pc)。

`up` 使用所选实验配置；`inspect`、`verify`、`fault` 读取已运行容器的实际配置，由原后端检查。`plan` 描述拟启动实验，不证明当前容器匹配它。容器已存在时入口拒绝覆盖；先 inspect，按原流程落地再 down。构建失败保留输出，不自动拉取其他版本或改用备用算法。

## 下一步按依赖顺序收敛

| 顺序 | 具体工作 | 完成判据 |
| --- | --- | --- |
| 1 | 已将快照构建替换为 `develop/docker/Dockerfile`：直接构建 `uav-computer-ros-humble:local`，源码挂载编译；验证状态见 Stage 3 Validation | 镜像和算法编译检查之外，仍需相同实验重新飞行与故障验收 |
| 2 | 从 `run_super_nodes.sh` 提取传感器接入、定位、规划、控制的独立启动单元；从控制桥提取任务编排 | 原配置行为一致；可单独诊断模块，异常退出仍可被监督器发现 |
| 3 | 定义共用算法接口并接入 GCOPTER；配置校验拒绝不兼容组合 | 两种 planner 共用输入/控制，固定同一场景、初始状态和预算完成对照 |
| 4 | 为以太网传输增加 PC 传感器接入模式，构建 OpenHarmony 目标产物，显式设备部署 | Docker 2 停止后，RoboPi 控制同一架仿真机完成起飞、悬停、降落与失联处理 |
| 5 | 参数化容器、域、分区、所有端口及命名空间，再接入视觉、多机、模型任务 | 完整运行隔离及各实验独立证据，不能仅靠修改容器名宣称隔离 |

板端迁移还需核实 SDK/toolchain、消息版本、Python ABI、目标库及网络条件；本次没有进行板端部署。当前仓库仍依赖本地上游算法源码及其补丁，基础镜像不能单独复现全部成果。实测状态以各阶段 Validation 为准，本框架入口的静态验证不扩大历史验收范围。
