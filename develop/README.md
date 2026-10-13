# develop：双 Docker 开发环境

开发统一采用两个运行角色：Docker 1 运行 PX4＋Gazebo，Docker 2 运行 ROS 2 Humble 和算力侧应用。
进入板端阶段时，RoboPi 替代 Docker 2，Docker 1 继续提供飞控和仿真。
QGC、可视化、评测与教师工具留在 PC。

两个基线镜像只提供环境。使用时的镜像边界是：镜像负责模块的运行依赖，文件挂载、脚本运行、环境变量不持久到镜像。

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
