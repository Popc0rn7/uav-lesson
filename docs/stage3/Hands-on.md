# Stage 3：SUPER Humble 仿真 demo

Stage 3 提供两个入口：perfect_drone_sim 用于算法竞速演示，Gazebo 实体 corridor 用于实际传感器扫描、PX4 动力学与 Gazebo＋双 RViz 展示。各入口的已通过范围见 Validation。

PX4/Gazebo 入口在 PC 运行两个 Docker：ROS 2 Humble 内运行 SUPER、ROG-Map、雷达坐标适配和 PX4 Offboard 桥；另一个容器运行 PX4/Gazebo 与 Stage 2 标准机 `x500_experiment`。不需要 ProjectAirSim、MAVROS 或原机 Jazzy。当前为单机、静态场景、低速实验，板端迁移另行进行。

## 教师准备（PC）

本机复用已验收的 `gcopter-humble` 容器作为 Humble 依赖基线，要求其 `/workspace/ros2_ws/install/` 包含匹配当前 PX4 的 `px4_msgs` 和 Micro XRCE-DDS Agent。准备脚本将容器层保存为本地镜像并把 install 复制到专用运行镜像；不修改原容器、不使用其运行节点。这个流程依赖教师已有环境，尚不是新 PC 从官方基础镜像重建全部依赖的流程。

前置条件：Docker 可访问；`thirdparty/SUPER` 指向搬入的 ROS 2 源码；PC 有 `/dev/dri/renderD128`；已有 Stage 2 PX4/Gazebo 镜像。本机 Docker 需要已授权的执行权限，下面的命令在有 Docker 权限的 PC 终端运行。

```sh
python3 stage3/super_docker.py prepare
python3 stage3/super_docker.py build
```

`prepare` 将源码复制到 Git 忽略的 `thirdparty/super_gazebo_ws/src/SUPER`，保留已有 ROS 2 修改，排除旧 build/install/log，并修正 SUPER 入口强制关闭仿真时间的行为。目标已存在时拒绝覆盖，已有准备好的副本直接执行 build。原 `../SUPER` 及旧 AirSim 链接保持原样。

`build` 创建 `uav-stage3-ros:local`，仅新增 `libdw-dev` 依赖，复制既有控制消息/Agent，构建 `mars_quadrotor_msgs`、`rog_map`、`super_planner`。不构建 MAVROS、AirSim 适配器或 perfect_drone_sim。编译限制两路并发。成功判据：三个包构建完成、退出码 0；下载/镜像构建/源码编译属于课前准备，不提交产物或日志。

本次实际基础环境、版本及验收结果见 [Validation](Validation.md)。镜像快照仍依赖原开发容器的手工准备，apt 软件源未快照锁定；教师需保存专用镜像及其摘要，换 PC/镜像重新验收。源码 commit 不覆盖用户未提交修改，分发前应保存实际源码补丁与版本。

## 启动和数据检查（PC）

先确认没有其它 PX4/Agent 占用 UDP 8888 或同名容器。命令仅管理 `uav-stage3-ros`、`uav-stage3-sitl`，不会停止其它课程进程：

```sh
python3 stage3/super_docker.py up
python3 stage3/super_docker.py inspect
```

使用 Stage 2 的两个只读模型挂载，默认 Gazebo `default` 空场景、无 GUI、GPU 无界面渲染；雷达参数仍来自 `stage2/models/mid360s/model.sdf`。PX4/SUPER 共同使用仿真时钟、ROS 域 10；Gazebo 分区为 `uav-stage3`。启动不解锁。DDS 使用 Fast DDS，`ROS_LOCALHOST_ONLY=0`，当前只验收同一 PC 的 host 网络，没有上板或跨机验收。

`inspect` 最多等待 60 秒，确认数据链和飞控预检就绪后独立采样 8 秒，输出 PX4 状态/里程计、原始点云、变换点云、时钟和控制状态。成功判据：ready=true、所有消息计数非零，`px4_status.preflight=true`，状态为 idle/disarmed，雷达与世界点云时间递增。它不发飞行命令；仅话题存在不能代替连续数据检查。

## 飞行验收（PC → ROS Docker）

前置条件：上述检查通过。下面命令**会让本任务的仿真飞机起飞**，依次验收 2 m 悬停、SUPER 规划到局部 ENU `(2,0,2)` m、到点稳定和降落：

```sh
python3 stage3/super_docker.py verify
```

预期依次输出起飞悬停通过、SUPER 到点通过，最终 JSON 的 `passed=true`，并确认 `landing_disarmed`。到点判据为误差小于 0.3 m、速度小于 0.3 m/s、持续 2 秒；本次是空场景闭环，不代表密林或碰撞专项通过。失败也请求降落，若未确认 Disarmed 不自动删除容器。

## 接口与传感器边界

| 接口 | 含义 |
| --- | --- |
| `/mid360s/scan/points` | Gazebo 原始 PointCloud2，`mid360s_sensor`，传感器局部 XYZ |
| `/lidar_slam/odom` | PX4 估计里程计转换为 ENU/FLU，frame=`world`；名称沿用 SUPER，并非运行 LiDAR SLAM |
| `/cloud_registered` | 实际变换后的 world XYZ+intensity，采样时刻保留，0.1 m 降采样 |
| `/planning/pos_cmd` | SUPER PositionCommand，世界 ENU 位置/速度/加速度 |
| `/stage3/uav1/command` | String `takeoff` / `land`，显式飞行请求 |
| `/stage3/uav1/goal` | PoseStamped，frame=`world`，米；仅稳定悬停且雷达新鲜时接受 |
| `/stage3/uav1/status` | idle、prestream、takeoff、hover、planning、track、land 及原因 |

这里的 `world` 是 PX4 局部 ENU，不保证等于 Gazebo 全球原点。雷达按照最近 50 ms 内的 PX4 位姿和 Stage 2 外参实际旋转平移 XYZ：base→传感器原点 `(0,0,0.135)` m。无匹配位姿时丢弃，不只替换 frame_id。有效距离 0.6–39.9 m，去除非有限点；ROG-Map 开启射线更新，未知区域保留未知语义，仍需专项验证规划器未知区策略。

沿用课程 **MID-360S 规则 GPU 扫描近似**，当前 512×16、10 Hz。它不是 Livox 不重复扫描、真实驱动或逐点运动补偿；同款传感器路线不能直接等同于真实 MID-360 算法验收。定位来自 PX4，尚未接入 LiDAR-inertial odometry。

规划最高速度 2 m/s、加速度 4 m/s²，机体规划半径 0.6 m；控制桥拒绝超出 XY ±10 m、Z 0.2–5 m、速度 3 m/s、加速度 6 m/s²以及过期/非有限命令。固定起飞高度 2 m、保持初始机头方向。流失/时钟停更/估计重置请求降落，PX4 Offboard 失联降落作为兜底。尚未进行所有故障注入验收。

## 停止、重置和排障（PC）

确认降落并 Disarmed 后：

```sh
python3 stage3/super_docker.py down
# 重新启动时所有仿真状态重新开始，源码/构建产物保留。
python3 stage3/super_docker.py up
```

down 对仍解锁或无法确认状态的飞机报错，保留现场。删除前保存需要的容器日志到仓库外；节点日志在 ROS 容器 `/tmp/stage3-node-logs/`，验收 JSON 在 `/tmp/stage3-super-flight.json`。

| 现象 | 恢复 |
| --- | --- |
| Docker socket 权限拒绝 | 使用教师已授权的 Docker 会话，不修改系统 socket 权限 |
| build 缺 Agent/消息包 | 检查原 `gcopter-humble` 安装前缀；不能用另一固件版本的消息替代 |
| 模型加载失败 | 检查标准机和独立 mid360s 两个挂载都存在 |
| 气压计尚未就绪 | 检查 SITL `/tmp/stage3-barometer-warmup.log` 和 inspect；启动探针使用 FluidPressure，不能以关闭健康检查解决 |
| 无 PX4 ROS 数据 | 核对域 10、Agent 8888、Fast DDS 与 localhost 设置；重启本任务节点清除旧域会话 |
| 点云存在但 world 无数据 | 检查 frame、位姿到达、时间匹配；不要扩大同步门限掩盖问题 |
| SUPER 无规划/起飞超时 | 保存 planner/px4 日志及 inspect JSON，检查飞控预检、地图和当前状态 |
| 仿真慢或点云超时 | 核实 GPU render 节点和容器映射；软件渲染未作为飞行基线验收 |
| 同名容器已存在 | inspect 现有实例；确认落地后 down，再 up，不覆盖活动实例 |

## SUPER 自带 corridor 竞速（PC，perfect_drone_sim）

先用这个入口展示 SUPER 的规划和避障。它以 `perfect_drone_sim` 替代 PX4/Gazebo，直接跟踪规划位置指令；不会连接或解锁 PX4。场景来自搬入的 SUPER：6 m 宽、100 m 长、4 m 高侧墙，包含中心线立柱和低矮灌木。默认中等难度、速度上限 10 m/s，初始世界坐标 `(0,-50,1.5)` m，依次前往 `(0,50,1.5)` 和返回起点。

教师在 PC 先完成前文 `prepare` 和核心 `build`，再准备渲染镜像及仿真包：

```sh
python3 stage3/super_race.py build
```

此步骤安装 GLFW/GLEW、Xvfb 和 Mesa，构建 `marsim_render`、`perfect_drone_sim` 与 SUPER 核心；不依赖 MAVROS 或旧 ProjectAirSim。当前复用已有本机 Humble 基础镜像。运行使用 Xvfb + Mesa 软件渲染，不需要宿主桌面授权。

学员在 PC 启动、验收：

```sh
python3 stage3/super_race.py up
python3 stage3/super_race.py verify
```

容器为 `uav-stage3-race`，ROS 域 **13**、Fast DDS、host 网络；与 PX4 demo 的域 10 隔离。使用系统时间，不能给这个模拟器强行开启 `use_sim_time`。`up` 启动模拟器和规划器，等待目标；`verify` 收到至少 100 帧运行时雷达点云和里程计、加载模拟器同一份 PCD 净空参考后，执行往返。每段要求误差 <0.3 m、速度 <0.5 m/s、稳定 1 秒；每段超时 120 秒。点云净空门限 0.2 m，与该竞速配置的机器人半径一致；该检查不等于物理碰撞检测。

结果在 Docker 内 `/tmp/super-race/result.json` 和 `trajectory.csv`，成功判据为退出码 0、`passed=true`、两段完成。教师可在 PC 导出临时记录：

```sh
docker cp uav-stage3-race:/tmp/super-race /tmp/stage3-race-evidence
```

验收只适用于初始状态。再次运行前重置本任务容器：

```sh
python3 stage3/super_race.py down
python3 stage3/super_race.py up
python3 stage3/super_race.py verify
```

故障诊断（PC）：`python3 stage3/super_race.py logs`。没有点云时检查 `sim.log` 的 GLFW/OpenGL/PCD 错误；没有规划检查 `planner.log`、目标订阅及域 13。容器名称冲突时先保存日志，再 `down/up`。验收失败不会把本轮写成通过，结果中保留错误和轨迹；模拟器不负责物理碰撞响应，失败后重置再试。

观看飞行（PC 图形桌面终端，无需在宿主安装 ROS）：

```sh
python3 stage3/super_race.py view
```

这个命令在独立 `uav-stage3-race-view` 容器打开 RViz，使用当前桌面的 DISPLAY/XAUTHORITY 和只读 X11 挂载，不修改 xhost 访问列表。独立容器使用域 13 的 UDP DDS 配置，避免 Docker 共享内存隔离导致发现话题却收不到数据。默认跟随 `perfect_drone`，显示点云、飞机模型和 `/path` 实际飞行轨迹。滚轮缩放、左键拖动旋转；按 H 显示/隐藏侧面板，Views 中有 `Corridor overview` 全景视角。

保持窗口打开，在另一个 PC 终端重置并执行飞行；这会自动完成往返，无需点击目标：

```sh
python3 stage3/super_race.py down
python3 stage3/super_race.py up
python3 stage3/super_race.py verify
```

预期先等待约 10–15 秒积累点云，然后飞到另一端并返回，停稳，终端输出 passed=true。RViz 的 2D Goal Pose 已配置为 `/planning/click_goal`，可在自动验收结束后手动选目标；自动验收期间不要额外点击目标。已有窗口时无需重复 view；关闭及再次打开使用：

```sh
python3 stage3/super_race.py view-close
python3 stage3/super_race.py view
```

若无窗口，检查 PC 桌面 DISPLAY/XAUTHORITY 和 `docker logs uav-stage3-race-view`；SSH 无桌面会被启动预检拒绝。有网格而无点云时检查域 13、race 容器和 UDP DDS 配置是否加载；全局点云可能错过启动发布，保持 RViz 打开再 down/up 仿真。关闭 RViz 容器不停止模拟器，down 仿真不关闭 RViz。

该配置为通用 360° 雷达（`lidar_type: 2`），并非真实 MID-360 驱动或不重复扫描验收。10 m/s 是规划上限，实际速度见结果；15/20/25 m/s、多难度统计、真实动力学、板端均另行验收。原始上游 benchmark 的无射线投射地图策略予以保留，本 demo 不用于证明未知区域安全性。

课程规划配置为 `stage3/super_race.yaml`，从上游 medium/10 m/s quiet 配置派生：地图垂直范围 6→10 m、虚拟天花板 5→6 m；避免膨胀与机器人半径裁剪使搜索种子处在走廊边界外。场景没有实体顶棚，允许三维绕障；不能将完成任务等同于全程水平侧绕立柱。实际高度范围在结果中记录。

## Gazebo 实体走廊与三窗口（PC）

此入口将中等 corridor 的墙、18 根立柱和 9 个灌木实体化；地面、障碍均有碰撞几何。走廊长 100 m、净宽 6 m，侧墙高 4 m；立柱半径 0.1 m、高 2.5 m，灌木用半径 0.5 m、高 0.35 m 的圆柱近似。坐标为 ENU，原场景 y∈[-50,50] 平移为 [0,100]。原 `perfect_drone_sim` 入口继续保留。

前置条件：先完成上文教师准备与核心构建，PC 有 Docker 权限、GPU renderD128 和图形桌面。新 C++ 预处理包也由 `build` 构建；依赖 Gazebo transport 13 / msgs 10，工作空间含匹配当前 PX4 的消息包。首次准备属于教师流程。

PC，在仓库根目录执行：

```bash
python3 stage3/super_docker.py build
python3 stage3/super_docker.py up --scene corridor --speed 2
python3 stage3/super_docker.py inspect
python3 stage3/super_docker.py view
python3 stage3/super_docker.py scan
python3 stage3/super_docker.py verify
```

预期打开三个窗口：Gazebo 显示实体飞机和赛道；点云 RViz 保留之前按高度着色的实时雷达回波、飞机和路径；地图 RViz 显示青色 ROG 占据体素（0.2 m）、淡橙色安全膨胀区域、飞机和路径。两个 RViz 各自跟随飞机。ROG-Map 本身就是体素占据地图：内部还区分空闲与未知区域；`/rog_map/occ` 只输出被判为占据的体素中心，`/rog_map/inf_occ` 输出规划用膨胀体素中心。RViz 将这些中心画成方块或淡色点；两个话题来自同一地图，不是两套独立建图算法。实时回波 `/cloud_registered` 每帧更新，已观察到的障碍在 ROG 局部地图中积累；地图随飞机滑动，只保留附近区域。两个 RViz 左边缘的箭头都可展开 Displays 面板；点云窗口使用 `stage3/super_gazebo_cloud.rviz`，只订阅 `/cloud_registered`；地图窗口使用 `stage3/super_gazebo_map.rviz`，只订阅 `/rog_map/occ` 和 `/rog_map/inf_occ`。这使“当前扫描”和“已积累地图”不会叠在同一画面。`view` 只连接已有世界；三个显示容器会由 `view-close` 一并关闭。需要有效的 DISPLAY 与 XAUTHORITY；不修改宿主 xhost 权限。

PC：`up`、`inspect` 显示 ready=true 且世界点云持续到达后，可检查地图确实发布（`view` 开启时也会订阅地图）：

```bash
docker exec uav-stage3-ros bash -lc 'source /opt/ros/humble/setup.bash; timeout 10 ros2 topic echo /rog_map/occ sensor_msgs/msg/PointCloud2 --once --field width --no-daemon'
docker exec uav-stage3-ros bash -lc 'source /opt/ros/humble/setup.bash; timeout 10 ros2 topic echo /rog_map/inf_occ sensor_msgs/msg/PointCloud2 --once --field width --no-daemon'
```

两条命令都应输出大于零的点数并在 10 秒内退出。若世界点云有数据但地图为空，先检查 `/tmp/stage3-node-logs/planner.log` 中 ROG 的点云/位姿超时提示，以及 RViz 的 Fixed Frame 是否为 `world`；不要用延长 RViz 点云保留时间冒充地图积累。

默认 PX4/GNSS 定位模式中的 `--lidar mid360` 为 MID-360 视场与标称点率近似：水平 360°、垂直 −7°～52°、30 Hz 点云、标称 20 万角度采样/秒、最大距离 70 m。参数依据 [Livox 官方规格](https://www.livoxtech.com/cn/mid-360/specs)。现在以 900×148 的 GPU 角度栅格查询 Gazebo 实体回波，再按 SUPER/MARSIM 的 MID_360 轨迹公式随仿真时间选择方向。该栅格是内部查询载体，不能把其 133,200 射线/帧当作输出点数。角度重复会合并，空回波、距离与体素过滤也会减少输出点；没有逐点真实采样时间、运动畸变、反射率相关量程或实机噪声模型，不能称为 MID-360 实机复现。`--lidar super360` 保留旧的 178° GENERAL_360 高密度对照；`--lidar mid360s` 使用 Stage 2 的 512×16 / 40 m 近似，尚未重新验收。不同传感器配置必须分别验证，不能混用证据。

两档课程配置使用 10 m 规划前视、6 m 滚动距离、1.0 m 走廊机器人半径与 1.2 m 栅格膨胀，加速度规划上限均为 2 m/s²；射线空闲更新概率 `p_miss=0.4`，用于更快清除往返时定位偏差留下的占据残影。PX4 水平位置增益 `MPC_XY_P=1.2`。2/5 m/s 均为规划速度上限，实际速度在验收结果中记录。两档除速度上限外使用相同参数。这些是本实体赛道的仿真参数，原竞速配置不变。源码头部声明 LGPL-3.0-or-later，而部分 package.xml 声明 BSD，发布课程镜像前需核实上游许可证差异；当前通过本地源码工作副本准备运行产物。

此 PX4 1.18 基线已将 GPS 延迟参数迁移为 `SENS_GPS0_DELAY` / `SENS_GPS1_DELAY`，见 [官方版本说明](https://docs.px4.io/v1.18/en/releases/1.18)。Gazebo GNSS 使用当前仿真采样，课程容器显式设两者为 0 ms；默认 110 ms 会使测量时间戳偏移，在高速飞行时影响点云配准。换 PX4 版本时先核实参数及实际 `vehicle_gps_position.timestamp_sample`，不能套用已移除的 `EKF2_GPS_DELAY`，也不能将此无延迟设置直接用于真实 GNSS。

默认 `--localization px4` 模式使用 PX4 原生气压高度：`EKF2_BARO_CTRL=1`、`EKF2_HGT_REF=0`、`EKF2_EV_CTRL=0`、`EKF2_GPS_CTRL=5`（水平 GNSS 与速度），不启动雷达地面拟合或注入视觉高度。正装雷达最向下仅 −7°，不能提供原先依赖的近地平面观测。控制桥仍检查 PX4 本地高度、位置、速度健康以及点云/里程计/时钟新鲜度；只是该模式不等待不存在的雷达高度消息。PX4 定位仍来自 SITL 传感器融合，尚未接入真正的 LIO。高度融合设置依据 [PX4 EKF 文档](https://docs.px4.io/v1.18/en/advanced_config/tuning_the_ecl_ekf)。

PC 可独立运行高度拟合几何检查：`docker exec -w /lesson/stage3 uav-stage3-ros python3 -m unittest discover -s tests -v`。它不替代真实扫描与飞行验收。

默认 PX4/GNSS 数据链为 Gazebo GPU 实体扫描 → Gazebo transport C++ 距离过滤/10 cm 体素 → ROS 雷达帧 → PX4 估计姿态与安装外参转换 → `/cloud_registered` → ROG-Map/SUPER → PX4 Offboard。规划器没有读取 PCD 或 Gazebo 真值。旧 `--lidar super360` 平坦走廊模式增加雷达地面平面拟合：48 次确定性 RANSAC、最多 1200 点的候选样本、2.5 cm 内点门限，要求地面占候选点至少 45%，再以 SVD 精化。安装偏移修正后得到机体离地高度，通过 `/fmu/in/vehicle_visual_odometry` 的 NED Z 交给 PX4；不融合该消息的 XY、速度或姿态。设置 `EKF2_EV_CTRL=2`、`EKF2_HGT_REF=3`、`EKF2_EVP_NOISE=0.05`、`EKF2_GPS_P_NOISE=0.05`、`EKF2_BARO_CTRL=0`，GNSS 继续提供水平定位与速度。接口配置依据 [PX4 EKF 文档](https://docs.px4.io/v1.18/en/advanced_config/tuning_the_ecl_ekf)。这仅是平坦地面的高度辅助，不是完整 LIO；坡地、台阶、地面被遮挡及实际 MID-360 扫描均需另行验证。高度拟合失败或超过 0.5 s 未更新时请求降落，参数不能直接当作板端基线。`world` 为课程 ENU，`base_link` 为机体 FLU，`mid360s_sensor` 的 base 外参 z=0.135 m；PX4 输入输出为 NED/FRD。里程计以 PX4 sample 时间戳发布；雷达保留 Gazebo 时间戳，姿态配对误差最多 50 ms。里程计 twist 沿用 SUPER 接口的世界坐标速度约定。

`verify` 等待控制状态 `idle: local_ready` 与点云，然后等待估计器静止收敛，起飞到 1.95 m，飞到 `(0,100,1.95)` 并返回 `(0,0,1.95)`，最后降落并解除解锁。每端所选定位输出与 Gazebo 真值位置误差均 <0.3 m、速度均 <0.3 m/s 连续 2 s；Gazebo 实际机体高度必须为 1.3–2.2 m，中心到实体边界净空至少 0.35 m，无障碍接触。参考指令还有范围、速度、加速度与新鲜度检查；数据或规划超时请求降落。真值 HTTP 8096 仅供验收。1.95 m 是课程为本走廊选择的固定飞行层，不是 PX4 的能力限制；PX4 Offboard 接口支持三维位置、速度、加速度。该实体赛道的立柱和侧墙在飞行层具有相同水平截面，当前控制桥执行 SUPER 的 XY 位置/速度/加速度，并独立保持 1.95 m 高度（Z 速度与加速度参考为零）；原始规划指令仍校验范围、动态限制和新鲜度。此投影仅适用于本赛道，不能直接用于有悬空障碍或分层通道的场景。RViz 的 SUPER/备用轨迹是规划辅助轨迹，橙色实际路径反映真实水平飞行；最终执行参考另发布在 `/stage3/uav1/reference`。

通过条件为 JSON 中 `passed=true`，不能仅凭看到飞机运动认定通过。ROS Docker 中结果为 `/tmp/stage3-corridor/result-2.json`，逐帧记录为 `trajectory-2.csv`；PC 扫描结果为 `/tmp/stage3-gazebo-scan.json`。扫描检查持续 60 s，要求达到启动配置标称扫描率的 90%（FAST-LIO 查询载体 ≥54 Hz；PX4 MID-360 对照 ≥27 Hz；旧对照 ≥9 Hz）、平均实时率 ≥0.8、最大帧间隔 ≤0.5 s。检查期间不要重启仿真。

默认 PX4/GNSS 2 m/s 验收完成后，在 PC 冷启动已验证的 5 m/s 配置（FAST-LIO 5 档尚未验收）：

```bash
python3 stage3/super_docker.py down
python3 stage3/super_docker.py up --scene corridor --speed 5 --localization px4
python3 stage3/super_docker.py inspect
python3 stage3/super_docker.py view
python3 stage3/super_docker.py verify
```

`down` 要求 PX4 已解除解锁，并清理本任务两个显示容器；冷启动新世界后重新执行 `view`，避免 Gazebo GUI 保留旧实体而画面不刷新。未确认落地时保留容器。可在 ROS Docker 请求降落：

```bash
# PC：命令通过 docker exec 在 ROS Docker 执行
docker exec -e ROS_LOCALHOST_ONLY=0 uav-stage3-ros bash -lc 'source /opt/ros/humble/setup.bash; ros2 topic pub --once /stage3/uav1/command std_msgs/msg/String "{data: land}"'
```

故障检查各用新的冷启动 2 m/s 实例：`fault --case lidar`、`--case planner`、`--case clock`。工具在起飞进入跟踪后暂停本任务雷达/规划进程或仿真时钟，要求 3 s 内请求降落。FAST-LIO 的 lidar 案例保持雷达停止直到落地解除解锁，并检查传播里程计停止输出，用于验证无外部定位数据时的气压降落后备；结束后才恢复雷达进程。其他案例恢复进程或时钟后等待解除解锁。结果在 ROS Docker 的 `/tmp/stage3-corridor/fault-*.json`。`contact-check` 只能在解除解锁时执行，会在侧墙内生成临时碰撞探针，要求接触传感器收到事件，随后删除探针；之后必须冷启动，避免接触记录污染飞行验收。

若失败试飞碰撞后倒在地面，PX4 可能无法确认落地，`down` 会继续拒绝删除。保留失败报告，用 Gazebo 与真值监测确认本任务虚拟飞机已经倒地静止；教师可在 PC 对这个 SITL 容器执行 `docker exec uav-stage3-sitl /opt/px4-gazebo/bin/px4-commander disarm -f` 后再 `down`。这是已发生的仿真碰撞恢复步骤，不计为自动降落通过，也不用于实体无人机。

PC 关闭画面：`python3 stage3/super_docker.py view-close`。若窗口空白，检查同一 Gazebo 分区、ROS 域 10、仿真时钟和 GUI 日志；若实际高度超限、地图不更新或规划超时，先保留报告并降落，再定位坐标/估计器/数据链问题。当前实际通过范围以 [Validation](Validation.md) 为准。

局部就绪检查包括 PX4 的姿态、角速度、局部高度、位置、速度有效性和关键故障标志，以及数据/高度新鲜度。外部高度参考时，全局高度可能无效，当前 Auto Loiter 的 preflight 字段不作为局部 Offboard 的唯一前置条件；进入 Offboard 后，解锁命令仍由 PX4 Commander 检查，未设置强制解锁或关闭解锁检查。

仿真服务由 `px4_start.sh` 显式启动一个 Gazebo server，PX4 使用 standalone 连接；避免启动前的时钟订阅被 PX4 误判为已有世界。启动预热订阅气压计、GNSS 和磁力计，确认数据产生；若缺磁力计/航向导致 inspect 未就绪，保留启动日志，未起飞时 down 后冷启动，不能绕过健康检查。ROS 将 `/world/corridor/clock`（空场景为 `/world/default/clock`）桥接并重映射到 `/clock`。ROS 与 RViz 使用显式 UDP DDS，发送/接收缓冲各 4 MiB，配置依据 [Fast DDS 2.6 传输文档](https://fast-dds.docs.eprosima.com/en/2.6.x/fastdds/xml_configuration/transports.html)；当前 PC 的内核缓冲上限为 4 MiB，没有修改宿主 sysctl。航向保持起飞时方向，返程可沿机身后方飞行；雷达水平 360° 扫描覆盖返程方向。

### 自体回波过滤

走廊 C++ 点云预处理默认启用 `self_filter=true`，按 X500 的保守机体包络剔除回波：base_link FLU 中 x/y 为 ±0.34 m、z 为 -0.235～0.12 m，雷达外参 z=0.135 m。该包络是仿真机型专用近似，更换机型或雷达安装位置必须重新核实。过滤不会恢复遮挡区域，也不会将未知区域标为自由空间；Gazebo 中的机体仍参与雷达遮挡。

PC：确认落地后用现有 `down` 流程关闭实例，再执行 `python3 stage3/super_docker.py up --scene corridor --speed 2 --self-filter off` 可关闭这层过滤；省略开关或指定 `on` 则开启。原有 0.6 m 近距离过滤始终保留，因此 `off` 不代表原始点云包含机体回波。Docker 中 `/tmp/stage3-node-logs/prefilter.log` 每 5 秒记录包络内剔除数，计数发生在距离过滤之前。

场景与速度只需在 `up` 时选择，`inspect`、`verify`、`fault` 自动读取运行容器配置；显式传入不一致参数会报错，不会改变运行配置。`verify` 首先等待数据链（最多 60 秒），再等待 EKF 静止对齐 30 秒，然后发送起飞指令；终端逐步显示当前阶段，等待期间飞机不会起飞。

### 雷达安装与地面盲区

Stage 3 走廊默认把雷达 link 安装高度从 base_link 上方 0.10 m 提高到 **0.30 m**；扫描原点另有 0.035 m，因此算法外参为 **0.335 m**。增加半径 0.01 m 的实体支架，保留机身、旋翼、支架和雷达外壳的真实遮挡。使用生成的 `stage3/models/x500_super`，不改 Stage 2 的机型；Gazebo GUI 读取 server 的实际模型挂载。点云转换、自体过滤和地面高度估计从运行配置读取同一外参。此前文中的 0.135 m 为原安装位置，现可作对比基线；空场景仍使用 Stage 2 原模型。

PC：落地后 `down`，然后执行 `python3 stage3/super_docker.py up --scene corridor --speed 2` 使用抬高版本。要比较原高度，启动时加 `--lidar-mount-z 0.10`；允许 0.10～0.60 m，但除 0.10 / 0.30 m 外尚未飞行验收。继续执行 `inspect`、`view`、`verify`，不需要重复这些参数。安装高度变更必须重启世界，不可只修改算法外参。

单帧实时点云仍会存在机体遮挡；抬高只缩小盲区，没有补点或把未知区域当作自由空间。累积地图的覆盖效果还取决于飞机移动和地图更新。仿真支架质量/惯量为课程近似，实机须重新核实刚性、重心和安装外参，不直接套用。

Gazebo Docker 的 `check_lidar_occlusion.py` 只做评测：在 1.85～2.05 m 定点悬停、倾角小于 10° 时，将原始扫描中小于 0.65 m 的近机体射线投影到平地，估计飞机下方半径 2 m 内的遮挡面积。限定 GENERAL_360 规则扫描和附近无障碍的起点悬停；它不控制飞机，也不适用于任意场景或 MID-360 实测。原始扫描包含重复射线，回波数不是障碍数量。

Gazebo GUI 打开后脚本显式恢复该任务世界运行并检查服务确认，避免 GUI 初始化暂停物理世界；`view` 会使暂停的世界继续运行。

### 与 SUPER 实机感知方案的对齐范围（PX4 对照基线）

上游 [SUPER-Hardware BOM](https://github.com/hku-mars/SUPER-Hardware) 确认雷达为 Livox MID360；[作者实机部署说明](https://github.com/hku-mars/SUPER/issues/5) 描述 30 Hz 点云与 IMU 传播后的 200 Hz 里程计。该说明日期为 2025-04-15，本仓库采用其 30 Hz 作为当前传感器帧率基线。论文 Materials and Methods / Fig.7 则记录 FAST-LIO2 输出 50 Hz 配准点云、200 Hz 状态及飞控 IMU 200 Hz；这些来自不同公开记录，不把它们当成同一配置。论文源文件为 SUPER/misc/scirobotics.ado6187.pdf。

| 项目 | PX4 对照实现 | 对齐状态 |
|---|---|---|
| 雷达型号、视场、距离上限 | MID-360 外形近似，360° / −7°～52°，上限 70 m | 视场与上限已对齐；反射率依赖未实现 |
| 扫描轨迹 | 复用本地 SUPER 71298ec 的 marsim_render.cpp MID_360 数学轨迹；200,000 次/秒角度取样，30 Hz 分帧 | SUPER 模拟轨迹近似；非厂商实测扫描表 |
| 场景与机体回波 | 查询 Gazebo 实体碰撞场景对应的 GPU 扫描，不使用 PCD 填补观测 | 已跑通；GPU 雷达遮挡由渲染几何决定 |
| 飞控 IMU | base_link 位置、FLU、200 Hz；角速度 rad/s、加速度 m/s²，含重力 | 输出率与位置约定对齐；噪声沿用 PX4/Gazebo 近似，不是 SUPER 校准值 |
| 点云 / IMU 时间 | Gazebo 仿真时间；原始 IMU 时间戳保留 | 同一时钟已验证；点云逐点采样与去畸变未实现 |
| 位姿与配准点云 | PX4 估计姿态/位置转换到 world；当前里程计约 100 Hz | 接口已跑通；不是 FAST-LIO2 / 200 Hz IMU 传播 |
| 雷达—IMU 外参 | 飞控 IMU 与 base_link 同原点；雷达扫描原点 z=安装高度+0.035 m | 当前模型一致；SUPER 实机精确外参未获得，需标定 |
| 相机 | Orbbec Gemini 2 几何近似仍是课程扩展，不参与当前 SUPER 规划 | 不宣称来自 SUPER 基础硬件 BOM |

点云方向选择复用了 SUPER/MARSIM 的 `MID_360` 分支，保留 200 kHz 相位推进。每一帧的回波来自该帧末尾的 Gazebo 瞬时场景：方向随时间变化，但一帧内所有回波没有按各自时刻重新射线查询。因此没有输出可用于真实运动去畸变的虚假逐点时间。后续接入 FAST-LIO2 前，应实现时间分片射线观测或实机录包回放，再对齐逐点时间、外参及 IMU 原始数据。

ROS Docker：`/stage3/uav1/imu` 是计划供 LIO 使用的原始测量接口（目前仅验证输出，未接入定位），200 Hz、frame=base_link。它仅发布角速度和线加速度；`orientation_covariance[0]=-1`，避免将 Gazebo 绝对姿态送给 LIO。`/stage3/uav1/imu_raw` 是仿真桥接调试话题，不作为 LIO 输入。`inspect` 会检查 IMU 帧、加速度与姿态有效性；8 秒通常约 1600 条 IMU 和 240 帧雷达/世界点云。


## FAST-LIO2 定位链路（PC / ROS Docker）

FAST-LIO2 是显式定位对照，需要 `--localization fastlio`；这时默认开启可选墙面立体标记。`--wall-landmarks off` 保留原赛道，纯 LIO 在该对照中曾出现纵向漂移，尚未通过完整往返。教师在 `build` 后执行一次 `lio-build`：准备固定版本源码、构建 `uav-stage3-lio:local`、Livox 消息、FAST-LIO2 和时间分片雷达节点。依赖 ROS 2 Humble、PCL ROS 与 Gazebo transport 13 / msgs 10；成功判据是所有包构建完成、命令退出 0。源代码与编译产物放在忽略提交的 thirdparty 中。已有实例必须落地后 `down` 再切换定位方式。

PC 操作使用上文通用启动与验收命令。默认走廊使用 PX4/GNSS 定位且不加墙面标记；FAST-LIO 对照首次教师准备增加 `lio-build`。需要明确切换场景对照时，先确认落地并执行 down，然后使用：

```bash
# 可选标记对照：FAST-LIO 定位，先执行 lio-build
python3 stage3/super_docker.py up --scene corridor --speed 2 --localization fastlio --wall-landmarks on
# 原始几何的 LIO 退化对照；不能套用带标记的通过结果
python3 stage3/super_docker.py up --scene corridor --speed 2 --localization fastlio --wall-landmarks off
# 默认 PX4 / GNSS 定位；无需附加墙面标记
python3 stage3/super_docker.py up --scene corridor --speed 2
```

场景、速度、定位方式只在 up 设置，后续命令读取当前容器配置。默认 PX4/GNSS 使用 900×148 / 30 Hz 瞬时扫描；FAST-LIO 模式目前只支持 corridor + mid360，使用时间分片扫描。各次飞行报告记录实际定位模式，不能混用验证结果。

| 接口 | 当前用途 |
| --- | --- |
| Gazebo `/mid360s/scan/points` | 1800×64、60 Hz 实际实体射线查询载体；垂直 −7°～52°，水平 360° |
| `/stage3/lio/lidar` | 30 Hz 官方 Livox CustomMsg，XYZ 为雷达局部坐标；timebase/header 为首个分片区间起点，offset_time 为真实分片时刻相对该时刻的 ns |
| `/stage3/uav1/imu` | 200 Hz 飞控位置原始 FLU IMU，rad/s、m/s²，包含重力，无仿真绝对姿态 |
| `/stage3/lio/odom` | FAST-LIO 每次点云更新后的 camera_init / body 位姿及 body 速度，约 30 Hz |
| `/stage3/lio/odom_propagated` | 独立滤波副本在每次新 IMU 测量上预测，约 200 Hz，供控制桥与 SUPER 使用 |
| `/stage3/lio/cloud` | FAST-LIO 去畸变、配准后的 camera_init 点云，约 30 Hz |
| `/lidar_slam/odom`、`/cloud_registered` | 同一初始坐标变换后的 world 数据，供 SUPER / ROG-Map 使用；速度按现有 SUPER 接口为 world ENU |
| `/fmu/in/vehicle_visual_odometry` | LIO 转 NED / FRD 后送入 PX4，包含位置、速度、姿态和采样时间 |

LIO 与控制不读取 Gazebo 真值或预制点云。world 保留 LIO 重力方向，仅对齐初始航向，在静止起点定义：机头沿 ENU +Y，base_link 高 0.25 m；这是课程初始条件。雷达外参为 `(0,0,mount_z+0.035)` m，默认 0.335 m。PX4 使用 `EKF2_EV_CTRL=15`、`EKF2_EV_DELAY=0`、`EKF2_HGT_REF=3`，关闭 GNSS 融合，保留飞控原生气压高度作为外部定位失流后的降落后备；飞控自用 IMU、磁力计与健康检查仍保留。真值仅由独立评测读取。

启动时先等原始 IMU 连续 0.5 s 测到稳定重力，再送给 FAST-LIO；定位器用约 400 条静止 IMU（2 s）估计重力与陀螺仪偏置，避免仿真生成初期的零加速度被用于重力初始化。初始地图积累 0.15 s 的真实非重复方向扫描；之后按每帧更新。异常数值、过期状态、速度超界和位置跳变不会注入 PX4。`inspect` 不仅检查曾有输出，还要求采样窗口内持续输出 LIO 位姿和配准点云；健康状态未就绪时不要发送飞行指令。日志在 ROS Docker `/tmp/stage3-node-logs/{imu_clean,fastlio,lio_bridge,px4}.log`。失败时先保留日志和评测报告，落地后 down 冷启动。

这仍是 MID-360 仿真近似：SUPER/MARSIM 角度公式按 200 kHz 推进，当前 LIO 对照保留连续方位角到 Gazebo 栅格查询，不使用原 MARSIM 整度取整；回波按 60 Hz 的真实 Gazebo 分片查询并组成 30 Hz 帧。分片内各点具有同一真实查询时间，时间分辨率约 17～20 ms，不能称为实机 5 µs 发射时间复现；栅格重复、无回波与量程过滤会减少点数。反射率固定 100、tag=0x10、line=0 是仿真元数据。FAST-LIO 已进行时间补偿，但不能据此声称真实 MID-360 去畸变精度已验收。点云更新仍为约 30 Hz；200 Hz 里程计通过独立滤波副本按新 IMU 测量预测，保留 FAST-LIO 估计的重力、加速度偏置、陀螺仪偏置和过程噪声。每次有有效匹配的点云校正后重置该副本，并重放已经接收到的后续 IMU；不用插值重复发布 30 Hz 位姿。IMU 间隔超过 50 ms 或距最近点云校正超过 200 ms 时停止传播输出，控制桥继续执行数据超时降落。

固定源码：FAST-LIO ROS2 `a4743b095409588842a5b30ddfa27e29d2f99164`（GPL-2.0），ikd-Tree `e2e3f4e9d3b95a9e66b1ba83dc98d4a05ed8a3c4`，Livox ROS Driver2 `21445540f0d100dc86a7e6df312dd70bbdb4afdf`（MIT）。Livox 包只构建官方 CustomMsg / CustomPoint schema，未启动硬件驱动或要求 SDK。`prepare_lio.py` 可重复施加本地补丁：输出滤波速度、初始化传播输入和上帧结束时间、延长静止 IMU 初始化、依据已知静止启动收紧初始化协方差（仅用于仿真）、积累初始扫描覆盖、记录初始十帧传播诊断、独立 IMU 传播与协方差输出。实机部署应重新核实驱动、外参、时钟、IMU 噪声与许可证；没有将 Linux 构建产物部署到 RoboPi。

墙面标记对照来自 `lio_landmarks.json`：两侧各 18 个 0.2×0.7×2.0 m 蓝色实体块，中心 x=±2.9 m、z=1.7 m，y 从 −2.7 到 105.1 m 非等间距分布。向走廊内最多伸出 0.2 m。Gazebo 渲染、碰撞、接触传感器和验收净空均包含它们；没有将标记坐标传给 FAST-LIO 或 SUPER。`--wall-landmarks on/off` 仅在 up 切换，后续 inspect/verify 读取运行配置；评测 JSON 记录开关，不能把带标记结果归到原赛道。对比 GCOPTER 与 SUPER 时固定相同标记设置。

FAST-LIO 模式把未参与规划的 Orbbec RGB/深度输出降至 5 Hz，并将可视化输出限制为约 30 Hz，避免影响 LiDAR/IMU 与控制；几何模型保留，Stage 2 的 30 Hz 相机配置不变。这个相机速率不是后续视觉算法的验收配置。
