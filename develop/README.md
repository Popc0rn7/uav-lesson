# 开发路线：从上游复现到 RoboPi

这份文档面向接续开发者：无论拿到的是只在作者机器上运行过的算法仓库，还是已经跑通的 Docker demo，都可以沿着下面四步，定位代码、建立可对照基线，再逐层替换环境。以本仓库 SUPER 的实际演进为例；具体运行命令由各后端文档维护，历史失败不需要重新经历一遍。

## 先理解四步之间换了什么

| 步骤 | PC 仿真与飞控 | 算力侧 | 本步要学会什么 | 进入下一步的依据 |
| --- | --- | --- | --- | --- |
| 1. 上游复现 | 上游示例或其原环境 | 上游算法与依赖 | 找出实际源码、构建方式、输入输出与原机依赖 | 固定版本，最小示例可运行；知道哪些结果仅属于上游 |
| 2. 双 Docker | Docker 1：PX4＋Gazebo | Docker 2：Humble＋SUPER＋适配节点 | 将算法接到真实 PX4 SITL 控制链，分离依赖、源码与产物 | 静止链路、低速往返、降落与故障处理分别通过 |
| 3. AirSim 替换 Gazebo | 宿主机 AirSim＋Docker 1 PX4 | Docker 2：Humble＋SUPER＋AirSim 适配 | 替换传感器、时钟和动力学接入，对齐坐标与时间 | 同一低速任务重新验收，不能沿用 Gazebo 飞行证据 |
| 4. RoboPi 替换算力 Docker | 宿主机 AirSim＋单 PC Docker：PX4／Agent／时钟／原始雷达 | OpenHarmony 原生：控制／配准／地图规划／任务 | 目标 ABI 构建、跨机 DDS、部署和性能定位 | 加载、消息、静止、短程、完整任务、故障逐层验收 |

“双 Docker”指两个运行角色；AirSim 场景在宿主机运行。RoboPi 替代的是算力职责，Agent 等 PC 接入节点会重新归并到 PC Docker；算法部署到 RoboPi，PX4 始终是飞控。QGC、可视化、录像和真值评测留在 PC。

**截至 2026-10-16 的边界：** Gazebo 当前 GNSS 走廊 2 m/s XYZ 往返、AirSim 低速短程／树林往返、RoboPi 1 m/s 短程及 forest1 往返已有实测；完整 AB 长任务未通过。AirSim 当前默认是 `runtime.forest10-ab.json` 单远端目标，初学复现应显式选低速配置。八航点结果、瞬时速度峰值或 `inspect` 就绪均不能替代 AB 验收。

Stage 5 同处于“AirSim替换Gazebo”层，当前日常场景为已接受的Shipping车队包，runtime生命周期已对齐SUPER；模型/任务与场景交付边界见[Stage 5开发导航](../docs/stage5/Development.md)。其静止链路可复用本阶段证据，但不得拿SUPER/Gazebo结果替代车队完整任务验收。

## 第一步：把上游仓库变成可解释的基线

先读 [来源与接口约束](../docs/stage3/Bring-up.md) 和 [SUPER 核心维护方式](../docs/stage3/SUPER-fork.md)。Bring-up 中相邻仓库、绝对路径和复制方式是历史记录；当前源码入口是 `submodules/SUPER/`，`prepare_super.py` 只初始化／检查子模块和工作区链接，不再搬入旧源码。

接入另一个“野生仓库”时，先留下这四项，再改课程适配：

1. **来源**：remote、commit、未提交改动、许可证及外部模型／场景来源。只记 HEAD 无法复现带本地补丁的作者环境。
2. **依赖**：ROS 版本、编译器、镜像身份、系统库、消息定义、运行资源；找出写死的路径和仓库外软链接。原机 Jazzy 的 install 不作为本仓库 Humble 产物。
3. **最小示例**：确认独立规划示例依赖什么理想状态／地图，再与 PX4 动力学闭环区分。`perfect_drone_sim` 通过不代表 PX4 飞行通过。
4. **接口契约**：逐项记录 odom、cloud、goal、command 的类型、坐标系、单位、时间源、频率、QoS 和失流行为。先对齐接口再换实现。

在 **PC 仓库根目录**，以下只读命令用于记录本次实际版本，不连接设备、不启动仿真：

```sh
git status --short
git submodule status
git -C submodules/SUPER rev-parse HEAD
git -C submodules/SUPER status --short
```

前置条件是已获取源码。当前 SUPER 子模块使用 SSH URL，需要对应仓库访问权限；获取失败先检查权限及维护者是否已推送 gitlink 对应提交。预期是能确定实际版本及所有本地修改；缺子模块按下文准备，不用旧 `thirdparty/` 副本填补。AirSim 源码子模块不包含可直接运行的场景包；场景、镜像、SDK 和模型需分别准备。

## 第二步：双 Docker，先建立 PX4 闭环

完整操作见 [Stage 3 Hands-on](../docs/stage3/Hands-on.md)，实测见 [Gazebo Validation](../docs/stage3/Validation.md)；本页下半部保留镜像、挂载和命令说明。

读代码顺序：`super_docker.py` → `run_super_nodes.sh` → `super_lidar.py`／`super_px4.py` → `submodules/SUPER/`。先看管理器如何装配环境，再看输入输出如何接入算法；不要从优化器内部开始猜环境问题。

镜像提供运行依赖，源码与配置通过挂载传入，`thirdparty/super_gazebo_ws/` 保存本机编译产物，日志另行导出。修改 Python／配置、C++ 和 Dockerfile 分别对应重启加载、重新编译、重建镜像并创建新容器。源码目录改动后旧 CMake cache 可能仍绑定原路径，按构建流程重新生成，不能只看旧 install 是否存在。

先检查时钟、定位、实际 XYZ 点云、非空地图和控制状态，再做低速起飞／往返／降落及失流验证。历史 FAST-LIO2、有标记走廊与当前 GNSS 路线条件不同；算法对比时固定场景、定位、资源和任务，分别记录结果。

## 第三步：AirSim 替换 Gazebo，重建接入契约

操作唯一入口是 [AirSim README](../stage3/super/airsim/README.md)。先按其“独立 PX4 控制测试入口”排除飞控接入问题，再接 SUPER；第一次完整规划回归显式选择 `runtime.super.json` 低速配置，不直接执行默认 10 m/s AB。

| 要替换／核验的层 | 代码入口（相对仓库根目录） | 成功判据与易错点 |
| --- | --- | --- |
| 实例与配置 | `stage3/super/airsim/runtime.py`、`runtime.*.json` | 场景路径、settings、任务和镜像可解析；相对路径以配置目录为基准，不能原样复制 JSON 到 `/tmp` |
| PX4 接入 | `stage3/super/airsim/run_px4.sh`、`px4_start.sh` | AirSim HIL→PX4 传感器和 GNSS 连续有效；独立控制通过后再接规划 |
| 时钟 | `stage3/super/airsim/clock_bridge.py` | PX4 HIL `/clock` 与雷达采集时间同源；不能用 RPC 收包墙钟替代采集时间 |
| 感知 | `stage3/super/airsim/lidar_bridge.py` | SensorLocalFrame／FRD 经外参、采集时刻位姿变为 world ENU；只改 frame_id 不会变换点坐标 |
| 规划装配 | `stage3/super/airsim/run_nodes.sh`、`planner_config.py` | 连续 odom／配准点云与非空占据／膨胀地图，参数快照对应本轮任务 |
| 任务与控制 | `stage3/super/airsim/waypoint_task.py`、`stage3/super/super_px4.py` | 任务只发目标，控制桥执行完整 XYZ；真值只用于评测，不进入定位／控制 |

保留 SUPER 核心及其消息契约，新增后端适配，不把旧 ProjectAirSim 的外部路径、SimpleFlight 控制或瞬移/reset 脚本当作当前运行依赖。GPS 200 ms 延迟补偿和 `MC_REF_FF=1` 是当前 AirSim 配置，不自动迁入 Gazebo。

## 第四步：RoboPi 替换算力 Docker，按三层迁移

先读 [板端开发约定](../robopi/AGENTS.md)，按 [AirSim README 的 RoboPi 章节](../stage3/super/airsim/README.md#robopi-算力后端2026-10-16迁移验证中) 构建和部署；接续现场见 [RoboPi handoff](../docs/stage3/RoboPi-handoff.md)，实际成功与失败见 [RoboPi validation](../docs/stage3/RoboPi-validation.md)。设备操作前使用仓库 HDC／OpenHarmony ROS 技能；阅读代码和整理文档无需连接设备。

| 迁移层 | 要对齐的内容 | 实现入口 |
| --- | --- | --- |
| 原 image 基线 | 板端已有 ROS／RMW／消息／Python／运行库与目标 ABI；核实已有能力，复用未变的层 | `stage3/robopi.py`、`stage3/board/prepare.py` |
| Dockerfile 增量 | 区分编译工具、目标运行库和留在 PC 的 Agent／仿真接入；逐项映射依赖 | `develop/docker/Dockerfile`、`stage3/board/Dockerfile.airsim`、`stage3/board/toolchain.cmake` |
| 挂载内容 | 共享 Python／配置按单一源码打包；C++／消息交叉编译，审计 ELF 与依赖，解引用共享链接 | `stage3/board/build.py`、`stage3/super/airsim/board_backend.py`、`robopi/stage3/` |

PC 启动装配看 `run_pc_nodes.sh`，板端启动看 `robopi/stage3/launch.sh`、`ros_env.sh`、`manage.py`。Linux AArch64 与 OpenHarmony AArch64 不能仅凭架构相同复用 install；消息序列化和 Python ABI 也要实际验证。

验收顺序是：**加载／import → 双向真实消息 → 静止传感器和地图 → 低速短程 → 固定完整任务 → 对应故障处理**。每层失败就保留日志，先修这一层。HDC 在线只证明管理链路；跨机 ROS 使用独立以太网 DDS，核实实际接口、地址、路由与双向数据，PC 同机 Agent／clock 还需要 UDP 回环。地址和设备标识不复制旧机器值。

## 从已踩过的坑学习：现象 → 检查层 → 证据

| 现象 | 先检查什么／已经确认什么 | 对应记录 |
| --- | --- | --- |
| 上游在作者机器能跑，本机找不到源码或依赖 | 仓库外软链接、Jazzy／Humble 差异、未提交改动；当前使用子模块固定来源 | [Bring-up](../docs/stage3/Bring-up.md)、[SUPER-fork](../docs/stage3/SUPER-fork.md) |
| 有点云但地图错位 | 原始坐标、外参和采集时刻位姿；ROG 不会仅凭 frame_id 自动做 TF 变换 | [接口约束](../docs/stage3/Bring-up.md#4-共同接口约束)、[AirSim 接口](../stage3/super/airsim/README.md#接口时间与故障恢复) |
| 近目标可规划，远端单目标 A* 连续失败 | 曾发现裁剪目标已搜到却返回错误语义，修为 REACH_HORIZON；真实搜索回归和负对照确认，未因此通过完整 AB | [A* 问题报告](../docs/stage3/SUPER-astar-clipped-goal-report.md) |
| 板端 C++ 能加载，启用 sim time 却断言 | 曾定位到 Clock 发布器创建；按需创建发布器，仍消费 PC 外部时钟，不能用关闭 sim time 掩盖 | [板端启动修复](../docs/stage3/RoboPi-validation.md#板端启动层的实际修复) |
| 跨机话题有一部分，PC clock／vehicle 缺失 | 显式 peer 与接口白名单须覆盖同机 UDP 回环；只加远端 peer 或 SHM 没解决该次问题 | [板端启动修复](../docs/stage3/RoboPi-validation.md#板端启动层的实际修复) |
| 板端 A* 超预算 | 曾发现邻格热路径反复 getenv，缓存不变配置后同输入微基准／真实搜索改善，再实飞 forest1 通过；提速前继续 profile | [forest1 性能定位](../docs/stage3/RoboPi-validation.md#forest1-首轮失败与性能定位) |
| ping 正常但大点云出现数秒空窗 | 702 秒观测中收到的 3939 帧均完成配准，同步捕获 IP 分片重组失败；尚未确认具体诱因或修复，不归结为应用队列堆积 | [点云与 IP 分片证据](../docs/stage3/RoboPi-validation.md#点云持续观测与-ip-分片证据) |
| 日志看起来“规划用了几秒” | 区分 CPU／墙钟／仿真时间；不直接将 ROS 日志前缀对齐 sim_s，也不相减两机绝对单调时钟 | [交接排障](../docs/stage3/RoboPi-handoff.md#分析时不要重复踩坑) |
| 失败后 Land 不解除解锁，task 又占锁 | 用独立 status／land／stop 恢复入口，核实实例身份；stop 是仿真急停，不能写作降落通过 | [恢复入口](../stage3/super/airsim/README.md#失控碰撞或命令卡住时pc另一个终端) |

AB 实验的 observe／land 策略取决于显式配置，当前保留中止条件统一见 [AB 中止条件](../stage3/super/airsim/README.md#ab-仿真实验的中止条件2026-10-16-门限审计)。排障时先记录实际条件，不为制造通过改变路线、点数、预算或新增隐藏中止；实验档通过也不等于原基线通过。

## 每次交接留下什么

交给下一个开发者的最小记录包括：源码提交及未提交修改、镜像身份、场景来源／版本／许可、本次 runtime／task／settings／planner 快照、设备 ABI 与依赖、实际命令和运行位置、预期与实际结果、失败原因、run ID 及报告／节点日志／ULog／review 的位置。速度同时记配置值、实际峰值和任务段统计，任务同时记是否到终点、有无碰撞和是否 Disarmed。

源码、配置示例、构建部署脚本和中文操作说明入库；场景包、模型、编译输出、运行日志及真实密钥不入库。历史 `artifacts/` 路径是证据索引，clone 不会自动带来旧数据；需要复盘时单独取回该 run。新开发者应能从已验证基线重建，不依赖维护者旧机器的缓存。

---

下面是双 Docker 的具体布局与 Gazebo 操作入口；AirSim 和板端命令继续由上述唯一入口维护。

## 目录与复用范围

- `docker/`：Docker 2 适配版的通用算力镜像 Dockerfile、环境入口与离线自检。
- `profiles/`：实验模块组合、启动参数、共享资源与验收证据。
- `lesson.py`：PC 统一命令入口，目前委托 Stage 3 后端执行。
- `../stage3/super/`：课程启动、传感器/PX4 适配、场景、配置与验收。
- `../submodules/SUPER/`：SUPER fork，核心修改在 `feat/sim` 开发。
- `../thirdparty/`：本地编译产物，忽略 Git，通过挂载接入容器。

Stage 1-3 目前都计划基于这两个 image，通过挂载不同的文件实现功能。

## Stage 3 模块边界与挂载

以下按当前 SUPER＋PX4/GNSS、无墙面标记的 corridor 主流程说明。路径以 PC 仓库根目录为基准；挂载文件仍保存在 PC，由对应容器读取和执行。

### Docker 1：PX4 与 Gazebo

容器 `uav-stage3-sitl` 使用 PX4/Gazebo 镜像。以下挂载全部只读：

| PC 文件或目录 | 容器内位置 | 用途 |
| --- | --- | --- |
| `stage3/super/worlds/corridor.sdf` | `/opt/px4-gazebo/share/gz/worlds/corridor.sdf` | 生成的实体走廊场景 |
| `stage3/super/models/x500_super/` | `/opt/px4-gazebo/share/gz/models/x500_experiment/` | 生成的无人机模型，包含课程传感器与接触检测配置 |
| `stage3/super/models/mid360/` | `/opt/px4-gazebo/share/gz/models/mid360s/` | 生成的仿真雷达模型 |
| `stage3/super/px4_start.sh` | `/stage3-start.sh` | 启动 PX4、传感器预热和真值监测 |
| `stage3/super/` | `/lesson-stage3/` | 读取场景布局，执行 `gazebo_warmup.py` 与 `gazebo_monitor.py` |

PX4 和 Gazebo 程序来自镜像。场景、整机和雷达模型由 PC 的 `generate_gazebo_corridor.py` 在启动前生成，基础模型来自 `stage2/models/`。默认空场景则直接挂载 Stage 2 的整机和雷达模型，不挂载 corridor 世界文件。Docker 1 的日志和运行状态保存在容器中，真值仅供评测使用。

### Docker 2：SUPER 与控制适配

容器 `uav-stage3-ros` 使用 `uav-computer-ros-humble:local`。运行时有以下三个挂载，全部只读：

| PC 文件或目录 | 容器内位置 | 用途 |
| --- | --- | --- |
| 仓库根目录 | `/lesson/` | 执行 `stage3/super/run_super_nodes.sh`、控制桥和传感器适配；读取 SUPER YAML 与 DDS 配置；通过 docker exec 执行检查、飞行验收和故障注入脚本 |
| `thirdparty/super_gazebo_ws/` | `/super_ws/` | 加载已编译的 SUPER、ROG-Map、消息包与课程雷达节点 |
| `submodules/SUPER/` | `/super_ws/src/` | 使用 fork 的核心源码，覆盖工作区中的旧源码路径 |

ROS Humble、PX4 消息、XRCE Agent 和 Gazebo 桥来自镜像。运行脚本启动 Agent、时钟/IMU 桥、雷达预处理、点云坐标转换、SUPER 规划器与 `super_px4.py` 控制桥。定位使用 PX4/GNSS 估计位姿。节点日志、算法 CSV 和验收报告写入容器 `/tmp`。

编译使用同一镜像创建临时容器：`/super_ws` 挂载改为可写，`/lesson` 仍只读，并通过 `--user` 指定 PC 用户的 UID/GID。`colcon build` 在容器内执行，产物保存回 PC 的 `thirdparty/super_gazebo_ws/`。

### 留在 PC 的入口与工具

- `develop/lesson.py`、`stage3/super/super_docker.py`：组织镜像构建、容器启动、检查和清理。
- `prepare_super.py`、`generate_gazebo_corridor.py`：初始化 submodule 和生成仿真资产。
- `check_gazebo_scan.py`、`check_gazebo_contact.py`：从 PC 查询仿真真值服务，输出诊断报告。
- QGroundControl 和 `super_gazebo_view.py`：在 PC 查看飞行与地图。view 入口另外创建 Gazebo GUI、点云 RViz、地图 RViz 三个容器，通过桌面 socket 与授权文件显示窗口。
- 仓库源码、场景配置和 `thirdparty/` 编译产物：保存在 PC；容器内 `/tmp` 报告需要在删除容器前按 Hands-on 导出。

飞行验收脚本 `verify_super_*.py` 和故障注入脚本 `check_super_fault.py` 当前在 Docker 2 内执行，由 PC 入口调用。

## Stage 3 SUPER 开发流程

SUPER 的脚本、配置、ROS 包和测试集中在 `stage3/super/`。核心源码来自 `submodules/SUPER/`，算法编译产物保存在 `thirdparty/super_gazebo_ws/`，分别挂载供容器使用。

- Docker 1：运行 PX4 与 Gazebo。
- Docker 2：运行 SUPER、ROG-Map、定位及控制适配节点。
- 编译：在 Docker 2 镜像创建的临时容器内执行，使用 PC 用户的 UID/GID；产物保存在 PC 工作区。
- 运行：工作区只读，日志和验收报告写入容器 `/tmp`。修改算法后重新编译；修改 Dockerfile 后重新构建镜像。

### 准备算力镜像

在 **PC 仓库根目录**执行，需要 Docker 权限和可访问的软件源：

```sh
docker build --network host \
  --build-arg http_proxy --build-arg https_proxy \
  -t uav-computer-ros-humble:local develop/docker
docker run --rm --network none uav-computer-ros-humble:local \
  python3 /opt/uav/check_runtime.py
```

成功判据：构建退出码 0，自检输出 `passed=true`。内存不足时添加 `--build-arg BUILD_JOBS=1`。自检只检查镜像依赖，完整启动和飞行需另行验证。

### SUPER 主入口

在 **PC 仓库根目录**执行。前置条件、上游源码准备和 GPU 要求见 [Stage 3 Hands-on](../docs/stage3/Hands-on.md)。新用户使用 `git clone --recurse-submodules` 获取课程和固定版本的 SUPER fork，或在已有 clone 中执行 `git submodule update --init submodules/SUPER`。prepare 只初始化并检查 submodule，build 在 Docker 内编译；不再下载额外 SUPER 副本或应用补丁。核心开发在 submodule 的 `feat/sim`，课程根仓库记录验证过的 commit。

```sh
python3 stage3/super/super_docker.py prepare
python3 stage3/super/super_docker.py build
python3 stage3/super/super_docker.py up --scene corridor
python3 stage3/super/super_docker.py inspect
python3 stage3/super/super_docker.py view
```

默认走廊使用 SUPER＋PX4/GNSS 定位、无附加墙面标记、2 m/s，展示 Gazebo、点云 RViz 和 ROG 地图 RViz 三个窗口。`inspect` 的成功判据为 `ready=true`；就绪后按 Hands-on 执行 verify，验收完整往返与降落。启动失败时保留容器和日志，先检查 inspect 与节点日志，不通过关闭健康检查绕过错误。

```sh
# 执行飞行验收
python3 stage3/super/super_docker.py verify
# 确认落地且 Disarmed 后清理
python3 stage3/super/super_docker.py down
```

build 会构建算力镜像和 SUPER 包，内存紧张时加 `--build-jobs 1`。新镜像不会自动更新已有容器；确认落地后 down/up 创建新实例。

### develop 配置入口

`develop/lesson.py` 委托 `stage3/super/super_docker.py` 执行，默认配置为 [super-gnss-corridor.json](profiles/super-gnss-corridor.json)，与 SUPER 主入口统一使用 PX4/GNSS 定位、无附加墙面标记、2 m/s 走廊。

在 **PC 仓库根目录**查看配置与命令，无需启动 Docker：

```sh
python3 develop/lesson.py list
python3 develop/lesson.py plan
python3 develop/lesson.py up --dry-run
```

实际运行时可使用同一入口的 prepare、build、up、inspect、scan、view、verify 和 down。`up` 采用配置文件参数；inspect、verify、fault 检查运行容器的实际配置。故障注入按 Hands-on 单独执行。

Stage 3 的资源固定为 ROS 域 10、Gazebo 分区 `uav-stage3`、Agent UDP 8888、真值 HTTP 8096；同一 PC 同时只运行一组实例。容器已存在时先 inspect，确认落地后再 down，不从另一工作区关闭当前实验。

详细操作与排障见 [Hands-on](../docs/stage3/Hands-on.md)，实测和未验收项见 [Validation](../docs/stage3/Validation.md)，开发边界见 [Development](../docs/stage3/Development.md)。

## RoboPi 开发入口

板端交付物统一维护在 [`robopi/`](../robopi/)，迁移流程与逐层验收遵循 [`robopi/AGENTS.md`](../robopi/AGENTS.md)。Stage 1 部署入口为 `stage1/deploy.py`；Stage 3 已有原生板端交付与短程实测，完整 AB 任务仍未验收，Stage 5 尚未上板。仓库 `skills/` 同步维护 HDC、OpenHarmony ROS、Houmo 与 Wi-Fi 的 Codex skills。

当前迁移以 AirSim＋PX4＋ROS/SUPER（GNSS、无 LIO）为标准，Gazebo 章节保留既有流程。AirSim 板端模式复用统一 runtime，PC 单容器运行仿真接入、RoboPi 原生运行算力节点；准备、无显示测试及验证边界统一见 [AirSim README](../stage3/super/airsim/README.md#robopi-算力后端2026-10-16迁移验证中)。
