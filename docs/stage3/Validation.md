# Stage 3 实测记录

## 2026-10-10：SUPER Humble 双 Docker 单机闭环

本次在当前 PC 实际构建、启动并执行虚拟飞行；没有连接 RoboPi 或实体飞控，没有调用模型/API。

| 项目 | 实际版本/条件 |
| --- | --- |
| Docker Engine | 29.1.5，Linux x86_64，host 网络 |
| ROS | Humble、rmw_fastrtps_cpp、域 10、ROS_LOCALHOST_ONLY=0 |
| 原 Humble 镜像 | `osrf/ros@sha256:1ee56d3ee5111f81e0a2a17b6ecd73447afb5c5b8a3c3574754f2646da9aee34` |
| 专用运行镜像 | `uav-stage3-ros:local`，ID `sha256:e0e51f96d58f3afacf53e04a2d015edd0afdf9e41c831584df37737eedca73e0` |
| 仿真镜像 | `px4io/px4-sitl-gazebo`，ID `sha256:70584c9eb1e928a9a621b939de0ebab0c91940860fb2f28848bd27f26a0432f4` |
| PX4 | 1.18.0 beta 基线，git `61907962c9220437ec01a98fa26bfbf5cbb254b5`，SITL |
| Gazebo | Harmonic 8.15.0，分区 `uav-stage3`，default 空场景 |
| 机型 | `x500_experiment`，单实例，MID-360S 近似雷达与 RGBD，未改 Stage 2 SDF |
| 图形 | `/dev/dri/renderD128`，EGL surfaceless，无 GUI |
| 通信 | PX4 uXRCE-DDS UDP 8888 → ROS 容器 Agent 2.4.2；使用既有已匹配消息包 |
| SUPER 来源 | 搬入 HEAD `71298ecf0a588f416085d471578e33cb0963d123`＋用户未提交修改＋Gazebo 入口补丁；原版本为 Jazzy/AirSim |

实际源码工作副本位于 `thirdparty/super_gazebo_ws/src/SUPER`，原仓库未覆盖。三个核心目录（super_planner、rog_map、mars_quadrotor_msgs）中 276 个 C/C++/消息/YAML/CMake/XML 文件按目录、文件名和内容累积得到 SHA-256 `f2ea1459f31129de87e679c06b6c495276ba93c3d40a08412e607dda119ad699`；commit 单独不能描述包含未提交修改的本次版本。

输入摘要：

- `stage2/models/x500_experiment/model.sdf`：`b72714f3bcea2efa6f6d53d9a7b3e279b362d776e414336832aa4bb0d014a794`。
- `stage2/models/mid360s/model.sdf`：`ac133716d6bf38e17e41b327316ad3ff832b946be75027ce0776d755e20e011c`。
- `stage3/super/super_gazebo.yaml`：`a825e04bd0f448d066dd2589805e11d96229932163dd281be3234e3675f339e6`。

## 通过的检查

1. Humble 核心构建依赖预检通过。新增 `libdw-dev` 后构建 mars_quadrotor_msgs、rog_map、super_planner 三个包成功。保留原机优化和终点保持修改，移除节点强制关闭 use_sim_time 的行为，支持配置绝对路径。
2. 实际 DDS/Gazebo 数据链：8 秒内 80 帧雷达原始点云、80 帧世界点云；原始每帧 8192 点，世界帧典型 717–746 点（距离裁剪、无效点过滤、降采样后）。PX4 里程计约 100 Hz、状态约 2 Hz，控制状态约 50 Hz，时钟持续前进。帧均来自实际运行的标准机，不是合成输入。
3. 初次开发容器飞行通过：起飞并悬停在 2 m，SUPER 规划到局部 ENU `(2,0,2)` m，误差 0.2144 m，随后降落并解除解锁。
4. 专用镜像及最终控制代码飞行通过：同样任务误差 0.2061 m，起飞、到点稳定和降落 Disarmed 三项全部通过。它不再挂载原 GCOPTER install volume。
5. 仓库 `build`、`down`、`up`、`inspect`、`verify` 入口实际运行；Python/Bash 语法检查与 Git diff 空白检查通过。
6. 最终完整冷启动回归通过：气压计 FluidPressure 探针收到连续数据并退出，inspect 的 ready=true；起飞、SUPER 到点和降落 Disarmed 三项通过，到点误差 0.2180 m。独立重新读取 PX4 vehicle_status 确认 arming_state=1。

一次运行资源快照：ROS 容器约 490 MiB、CPU 54%；SITL 约 374 MiB、CPU 85%。CPU 百分比按 Docker 单核 100% 计，不是峰值或资源预算验收。

## 启动与诊断发现

- 原工作副本使用 Jazzy，并存在丢失的 ProjectAirSim/IsaacSim 软链接。新核心构建不调用这些环境。
- PX4 默认 DDS 域 0 与课程 ROS 域 10 不一致；已在启动时设置 UXRCE_DDS_DOM_ID=10。
- ROS_LOCALHOST_ONLY=1 未复现已有 PX4 DDS 链路，使用已验证的 Fast DDS + localhost_only=0 后真实收发通过。
- 软件渲染明显影响仿真运行，最终采用实际 GPU render 节点。未把软件渲染作为可用飞行基线。
- 一次冷启动气压计在 Gazebo 有数据但 PX4 初始未收到，导致预检未通过。课程检查先等连续数据和 PX4 preflight，而非容器运行就算就绪；Stage 3 另提供基于实际 `gz.msgs.FluidPressure` 的启动订阅探针。
- 一轮诊断中桥重连与飞行验收发生重叠、仿真被干扰；该轮不算通过，已保留诊断并重置到全新状态。

运行日志和 JSON 保存在 `/tmp` 或容器内，未提交 Git；失败报告不能用后续成功覆盖其验证范围。

## 尚未验收

密林/单墙绕障、碰撞专项、多次统计成功率、全部故障注入、新 PC 从官方基础镜像完整重建、GUI 展示、实际 MID-360 驱动/不重复扫描、LiDAR-inertial odometry、SUPER 上板、GCOPTER 与 SUPER 同场景速度对照，以及视觉算法。

目前结果证明本机 **Humble Docker → SUPER/ROG-Map → PX4/Gazebo Docker → 标准机低速空场景飞行** 闭环成立，不能将其表述为密林高速导航或板端迁移完成。操作见 [Hands-on](Hands-on.md)。


## perfect_drone_sim corridor 竞速（2026-10-10）

独立容器 `uav-stage3-race`，ROS 2 Humble / Fast DDS / 域 13 / 系统时间。镜像 `uav-stage3-race:local` 的 ID 为 `sha256:8f77bb2845af22311bd2ff6936e1bc48d4d495d3a33f5b6ef05f6a983772a46b`，从前述本机核心镜像派生；新增 GLFW 3.3.6、GLEW 2.2.0、Xvfb 与 Mesa 软件渲染。验收工具复用基础镜像中的 NumPy、SciPy 1.8.0 和 rclpy。`super_race.py build` 实际执行通过，五包构建完成（mars_quadrotor_msgs、marsim_render、rog_map、perfect_drone_sim、super_planner）。

场景和渲染源来自搬入的 SUPER 工作副本（上述 commit 加用户未提交适配）；中等难度 PCD 为 50,716 点，SHA-256 `2813b62f8377949f1c40657512bff05513ecc76c5cb09e30a2ac3e15bd5b66f1`。上游 perfect_drone_sim、marsim_render 的 package.xml 声明 BSD；仓库未找到顶层许可证文件，整体再分发授权仍需核实。沿用上游 10 m/s quiet 配置，课程配置 `stage3/super/super_race.yaml` 将地图高度 6→10 m、虚拟天花板 5→6 m，其他规划参数保持。

首次成功完成世界坐标 `(0,-50,1.5)` → `(0,50,1.5)` → 起点，去程 12.151 s、回程 12.260 s（包含到点稳定 1 s），两端误差 0.217945 m；峰值速度 10.01587 m/s，轨迹长度 201.69465 m、最小场景点云净空 1.13395 m。累计收到 3,140 条里程计、335 帧实际渲染雷达点云、2,425 条规划位置指令。末态零速度，passed=true。一次资源快照约 2.11 GiB / 93% 单核 CPU，非峰值或性能预算验收。

净空使用模拟器同一 ASCII PCD 建立 KD-tree，对相邻里程计位置之间按 ≤5 cm 插值检查最近场景点，不把该参考全局地图传给规划器。规划器接收运行时雷达点云。点采样净空不是实体物理碰撞判据；perfect_drone_sim 直接跟踪位置指令，不验收 PX4 动力学。开放顶棚允许三维绕障，不能宣称全程横向侧绕。默认雷达为 GENERAL_360（类型 2），178° 垂直视场、70 m 感知范围、10 Hz；尚未验收 MID-360 类型 3。

失败记录：首轮工具读取 Humble 点云结构化数组失败；随后全局地图发布时机导致工具超时，改为读取同一场景 PCD 后恢复。原配置安全走廊反复生成失败，诊断种子 z=3.75 m，而地图裁剪并扣除机器人半径后 box_max.z=3.70 m；仅扩大地图高度未消除虚拟天花板裁剪，最终同时调整虚拟天花板。失败诊断保存于 /tmp，未把这些轮次算通过。

未验收：GUI、实体碰撞响应、全程高度受限的水平绕障、多难度及 15/20/25 m/s 统计、MID-360 扫描真实性、SUPER 板端与跨机链路。运行入口与重置步骤见 [Hands-on](Hands-on.md)。

最终冷启动回归也通过：去程 12.141 s、回程 12.167 s，两端误差 0.217945 m；最小点云净空 1.33960 m、峰值速度 10.02594 m/s、轨迹 201.90103 m。实际高度 1.50–4.588 m，超过 4 m 侧墙高度，包含从立柱上方通过的轨迹；这是开放顶棚的三维竞速结果，不能当作高度受限的水平走廊绕障通过。最终证据在 `/tmp/stage3-race-cold-pass`，容器停在返回起点零速度状态。Python/Bash 语法、Git diff 空白检查通过。

可视化验收（同日）：独立 RViz Docker 成功连接当前 PC XWayland 桌面，OpenGL 4.5；单窗口截图确认实际雷达点云、飞机模型与跟随坐标系显示。域 13 同宿主双 Docker 的默认共享内存传输初始无数据，GUI 切换 UDP 后恢复。`view` / `view-close` / 保持窗口并重置模拟器均实测；已检查的跟随视角截图位于 `/tmp/stage3-race-rviz-follow.png`，未提交原始截图。软件渲染画面帧率随点云和窗口尺寸变化，尚未做 GUI 性能预算验收。

保持 RViz 开启的实际往返再次通过：12.208 / 12.164 s，到点误差约 0.218 m、净空 1.264 m。最终重置到初始位置供用户观看验收。

## Gazebo 实体 corridor 集成（2026-10-10）

新增实体世界、GENERAL_360 GPU 扫描、Gazebo transport C++ 预处理、PX4/ROS 时间与坐标适配、走廊高度约束补丁、双 GUI，以及实际高度/净空/接触/故障评测入口。原外部 SUPER 检出没有覆盖；仅补丁化本地工作副本。版本沿用上文双 Docker 基线，新增预处理使用 transport 13.6.0、msgs 10.4.0。

本轮核心源码指纹为 `bfd69de82020afead2edff346857c61508436a8414d6ef03ab1269413ee59973`：对三个核心目录中扩展名 `.cpp/.h/.hpp/.msg/.yaml/.cmake/.txt/.xml` 的 262 个文件按相对路径排序，累积 `相对路径 + NUL + 内容 + NUL` 后取 SHA-256。它覆盖本轮高度补丁，区别于前述空场景阶段的源码指纹。当前 PC GPU 为 AMD HawkPoint1，通过 renderD128 进行实体雷达渲染；GUI 使用当前 XWayland 桌面。

已实际验证：

- C++ 预处理与 SUPER 核心构建通过；Python/Bash 语法和 diff 空白检查通过。
- GENERAL_360 最终实体扫描 60.178 s 检查：10.0037 Hz、平均实时率 0.9989、最大帧间隔 0.2207 s、712,800 点/帧，passed=true。同一冷启动实例的 5 m/s 往返飞行期间采样，双 GUI 同时开启。原始 ROS 直接桥接大点云曾导致低频，现改为 Gazebo transport 内 10 cm 体素预处理后发布 ROS 点云，扫描射线数量保持。证据 `/tmp/stage3-gazebo-scan.json`。
- 侧墙接触正例 passed=true，临时探针产生 107 条接触记录，删除服务返回成功。Harmonic Contact 实际使用默认作用域话题，Contact.collision1/2 为 Entity；已据实际消息修正监测器。执行后必须冷启动清空记录。
- Gazebo 独立 GUI 显示实体场景与飞机；RViz 独立 GUI 显示实时实体扫描和 ROG 占据地图。只截图本任务窗口，证据在 `/tmp/stage3-gazebo-corridor.png`、`/tmp/stage3-rviz-entities.png`，不提交运行截图。

最终共同配置的两档冷启动往返均 `passed=true`，包含每端位置/速度稳定 2 s，双 GUI 同时开启，全程无障碍接触，最后自动降落解除解锁：

| 规划速度上限 | 去程 / 返程 s | 真值终点误差去 / 返 m | 最小实体净空 m | 实际机体高度 m | 实际峰值 m/s |
| --- | --- | --- | --- | --- | --- |
| 2 m/s | 79.646 / 61.450 | 0.05509 / 0.07292 | 0.75776 | 1.75188–2.01188 | 2.61581 |
| 5 m/s | 56.420 / 51.252 | 0.07991 / 0.24601 | 0.75937 | 1.80346–1.97419 | 5.04864 |

PX4 估计终点误差分别为 0.03534 / 0.03583 m（2 档）与 0.06816 / 0.15633 m（5 档）；执行参考 Z 全程固定 1.95 m。规划上限与实际速度不同，不能表述为实际全程严格限速 2/5 m/s。最大执行参考跟踪误差 0.55360 / 0.69012 m；位姿与真值按评测接收时刻比较的最大差异 0.29231 / 0.37039 m，并非同步定位精度专项验收。结果是各一次冷启动通过，没有做重复成功率统计。

证据分别为 `/tmp/stage3-corridor-2-final-pass/result-2.json`、`/tmp/stage3-corridor-5-final-pass/result-5.json`，逐帧记录为对应目录的 `trajectory-2.csv` / `trajectory-5.csv`。最终两档共同配置为 2 m/s² 加速度、1.0 m 走廊半径、1.2 m 栅格膨胀、`p_miss=0.4`、零仿真 GNSS 延迟，仅规划速度上限不同；参数见 Hands-on。布局 SHA-256 `57db6fc16a0e917584d46b6405c89d3eee3a73ba3878e32cdbe83a5cfd61da79`，2 档配置 `cd80285fc76e9788881712a7f2b7ed3dd4e7f10a253a84ca42f27a3ec94dfb2f`，5 档配置 `d657e093f45a8def0c0c7feb5e2a19062e56f4d3f29d61f92f6bf89f0eb66adc`。

实现边界：地面平面由实时雷达 RANSAC/SVD 拟合，经 PX4 外部高度融合；水平定位仍依赖仿真 GNSS。SUPER 规划 XY 指令与独立高度保持组合，只适用于本赛道垂直延伸障碍。规划器和控制桥不读取 Gazebo 真值或预制 PCD；真值只进入独立评测。高度拟合两项几何测试通过，但不代表完整 LIO。失败开发轮次曾出现高度超限、返程搜索超时和备用走廊失败，均请求降落且不计入通过；最终配置增大障碍余量并加强射线空闲更新，原竞速 demo 配置未改。

三项独立冷启动故障检查均 `passed=true`，触发降落后恢复暂停的进程或时钟，最终解除解锁；真值机体落地高度均约 0.251 m，障碍接触数均为 0：

| 注入故障 | 请求降落响应 s | 实际触发原因 |
| --- | --- | --- |
| 停止雷达预处理进程 | 0.49973 | planner or lidar timeout |
| 停止 SUPER 规划进程 | 0.50023 | planner or lidar timeout |
| 暂停 Gazebo 物理时钟 | 0.73932 | planner or lidar timeout |

暂停物理世界同时停止点云、里程计和时钟更新，最后采样时刻不同使雷达新鲜度看门狗先触发；验收接受任一数据/时钟新鲜度看门狗在 3 s 内请求降落，同时要求 Gazebo 暂停服务确认、恢复后实际落地解除解锁与无接触。原脚本只接受时钟原因而判失败，修正后重新冷启动验证。三项最终证据在 `/tmp/stage3-corridor-faults/fault-{lidar,planner,clock}.json`；首个雷达检查也已按补充的实体落地/接触判据重新验证。

失败开发轮次还包括 5 m/s 立柱碰撞、净空不足和验收目标切换竞态；倒地后有一次不能自动解除解锁，通过确认虚拟飞机静止后手动复位 SITL 恢复，不计为通过。目标切换现等待控制桥明确 `hover: goal_reached`，最终两档通过均由验收脚本自动执行，无人工补发目标或手动解除解锁。

尚未验收：新 PC 从官方基础镜像完整重建、实际 MID-360 不重复扫描/完整 LIO、坡地与悬空障碍、板端迁移、GCOPTER 同场景对照和多轮成功率统计。本机现有镜像依赖与核心/预处理构建已通过；这些结果不代表上述项目完成。

补充链路采样：冷启动后 inspect ready=true，独立 8 s 窗口内 PX4 odom / 转换 odom 各 796 条、状态 16 条、预处理扫描与世界点云各 80 帧、控制状态 400 条、clock 1996 条。预处理末帧 24,308 点，世界帧 18,072 点；数量随位置变化。坐标转换与预处理没有降低实际扫描频率。

交付时已重新冷启动 2 m/s 待起飞场景，`inspect ready=true`，8 s 内两种里程计均 800 条、扫描/世界点云/高度均 80 帧、控制状态 400 条、clock 2000 条；PX4 独立检查 `arming_state=1`。Gazebo 与 RViz 两个窗口已打开并逐一截图检查，Gazebo 显示起点实体飞机与走廊，RViz 显示实时扫描及机体标记。最终截图在 `/tmp/stage3-gazebo-ready.png`、`/tmp/stage3-rviz-entities.png`。PC 执行 `python3 stage3/super/super_docker.py verify --scene corridor --speed 2` 可观看自动往返。

待起飞双窗口的一次资源快照：ROS 696.3 MiB / 209.77% CPU，SITL 599.2 MiB / 170.51%，Gazebo GUI 519.1 MiB / 104.65%，RViz 69.79 MiB / 12.59%；CPU 按 100%=一核计算。合计约 1.84 GiB / 4.98 核，不是飞行峰值或最低硬件配置验收。

自体回波过滤补充验证（2026-10-10）：C++ 预处理重新构建成功，已在落地解除解锁状态加载。默认开启 X500 包络过滤；原始扫描每帧约 159,661 个采样点落入包络（不是独立障碍数）。同时订阅同一 Gazebo 扫描，在独立比较话题关闭包络过滤并保留原有 0.6 m 距离过滤：30 对同时间戳输出帧数据完全一致，额外剔除数为 0。这说明本次静止状态的自体回波此前已被距离过滤去除；地面遮挡轮廓不会因此消失。重新 inspect ready=true，8 秒预处理扫描与世界点云各 80 帧，PX4 arming_state=1。未新增飞行验收，也未证明中途后退与自体回波有关；前述飞行验收属于修改前版本。

2026-10-12 操作入口修正：`inspect` / `verify` / `fault` 自动读取 ROS 容器中的场景和速度，保留显式参数一致性检查；实测在 2 m/s 容器调用 `verify --speed 5` 被拒绝。`verify` 增加就绪、30 秒 EKF 对齐、起飞与阶段等待状态提示。无参数 `verify` 冷启动实体走廊实测通过：去程 78.620 s、返程 63.530 s，真值终点误差 0.122 / 0.051 m，最小中心净空 0.959 m、实际高度 1.843～1.999 m，自动落地解除解锁、无接触；结果 passed=true。本次启用自体回波过滤。证据 `/tmp/stage3-20261012-verify/result-2.json`、`trajectory-2.csv`。无参数 inspect ready=true，8 秒扫描 80 帧、世界点云 79 帧。本次未复现用户报告的不起飞，原失败实例已被关闭，无原始状态证据，不能把起飞前的静默等待确认为原故障原因。等待循环中的周期提示在本轮飞行启动后补充，已检查语法，未额外重复飞行。

2026-10-12 雷达遮挡对比：走廊采用独立生成的 X500 模型，MID360 link 安装高度从 base_link 上方 0.10 m 提高到 0.30 m，扫描原点外参相应从 0.135 m 变为 0.335 m。增加半径 0.01 m、长度 0.25 m、质量 0.03 kg 的实体支架；Stage 2 模型未修改。高度估计、点云转换、自体过滤共享 `STAGE3_SENSOR_Z`；模型高度与外参由同一启动参数生成。Gazebo GUI 挂载来自运行 server 的实际模型路径。

同起点定点悬停、相同 GENERAL_360 扫描的五帧平均：原安装实际高度 1.90010 m，半径 2 m 内近机体射线对应的平地遮挡投影约 7.67403 m²；抬高后实际高度 1.89973 m，投影约 3.07486 m²，约减少 59.9%。这是有限区域、单次悬停的近似角度积分评测，不是全场景盲区面积或重复统计；有效原始射线按其方向投影到 z=0 平地，近距回波定义为 <0.65 m。没有用这些真值或投影数据控制飞机或补充规划点云。证据 `/tmp/stage3-lidar-mount-comparison/{baseline,raised}.json`。

开发中低高度上升阶段（约 1.379 m）的样本已舍弃；最终抬高采样限定 1.85～2.05 m 高度带持续至少 3 秒且倾角 <10°。初版 Gazebo Python 绑定在结果写入后的解释器回收过程中 abort，几何数据已完整保存；当前有限时长测量工具取消订阅、写入与打印后使用进程退出规避该镜像 transport13 的 pybind 回收错误，抬高最终测量 exit=0。原高度悬停时打开 GUI 后观察到世界暂停，恢复世界后正常降落；当前 view 显式恢复世界并校验确认，后续抬高悬停已自动降落解除解锁。

C++ 可调外参预处理构建通过；地面高度单元测试覆盖原安装与抬高安装、地面高度 0.25/1.95/2.0 m 及倾斜姿态并通过。支架 visual/collision 使用不同名称，`SDF_PATH` 指向实际模型后 `gz sdf -k` 返回 Valid（退出 0）；保留上游 `gz_frame_id` 扩展警告。抬高版本实际 RViz 截图 `/tmp/stage3-lidar-mount-comparison/raised-rviz.png` 已查看。

抬高后的默认版本完整 2 m/s 冷启动验收通过（按 up → view → verify 的实际使用顺序）：去程 71.333 s、返程 64.728 s，真值终点误差 0.0441 / 0.1062 m；最小中心净空 0.8923 m，实际高度 1.8092～2.0074 m，峰值实际速度 2.3255 m/s，自动落地解除解锁、无接触，passed=true。证据 `/tmp/stage3-lidar-mount-comparison/flight-2.json`、`flight-2.csv`。本轮未重新验收抬高安装下的 5 m/s、故障注入、扫描长期性能或实际 MID-360 / RoboPi；此前这些检查使用原安装位置，不能直接当作抬高版本证据。

2026-10-12 MID-360 视场基线：默认走廊传感器改为 `--lidar mid360`，与 Livox 官方水平 360°、垂直 −7°～52° 和典型 20 万点/秒一致的规则 GPU 网格近似：1000×20 射线、10 Hz、最大 70 m，距离噪声标准差 0.01 m；没有模拟不重复扫描、逐点采样时间或反射率相关量程。旧 `super360` 为显式宽视场对照；前述遮挡面积减少 59.9% 的结论仅属于该对照，不能套到 MID-360。

默认高度链路为 PX4 原生气压高度，而不是近地雷达拟合；运行时确认 `EKF2_BARO_CTRL=1`、`EKF2_EV_CTRL=0`、`EKF2_HGT_REF=0`、`EKF2_GPS_CTRL=5`。没有向默认模式注入雷达外部高度，也没有放宽高度、接触、净空或终点验收门槛。控制仍使用 PX4 估计，不接入 Gazebo 真值；点云 / 状态 / 时钟及 PX4 本地估计健康看门狗继续生效。这是 GNSS/IMU/气压计辅助仿真，未完成 MID-360 LIO 或板端迁移。

一次冷启动 2 m/s 往返 passed=true：去程 68.889 s、返程 61.912 s，真值终点误差 0.0611 / 0.0411 m；最小中心净空 0.8192 m、实际高度 1.8484～2.0209 m、峰值速度 2.3109 m/s，自动落地解除解锁，无接触。证据 `/tmp/stage3-mid360-fov/result-2.json`、`trajectory-2.csv`。一分钟扫描通过：10.0006 Hz、平均实时率 0.99986、最大帧间隔 0.15617 s、20,000 射线/帧；证据同目录 `scan.json`。无参数 inspect ready=true，8 秒扫描与世界点云各 80 帧；默认模式不等待雷达测高话题。三个单元测试通过，包括官方视场/标称点率边界回归检查。本轮没有验证新模式下的 5 m/s、故障注入、重复成功率、实机不重复扫描或 LIO；之前宽视场的相关结果不替代新模式验收。

交付冷启动过程中另一次出现 PX4 `Found 0 compass` / `no heading reference`，导致 inspect ready=false；该次未起飞，不计为通过。启动预热补充 Gazebo 磁力计订阅，与气压计、GNSS 一起检查首帧及 5 秒预热。随后冷启动 inspect ready=true、PX4 preflight=true / arming_state=1，8 秒里程计、扫描、世界点云各 800 / 80 / 80 条。此启动修正后没有重复完整飞行；前述完整往返为相同 MID-360 点云与高度控制链路、修正预热前的通过结果。

2026-10-12 SUPER 感知方案对齐：依据硬件 BOM 的 MID360、作者 2025-04-15 部署说明的 30 Hz 点云，以及论文飞控 IMU 200 Hz，默认 MID-360 模式采用 30 Hz GPU 栅格载体（900×148、133,200 射线/帧），C++ 预处理按 SUPER/MARSIM MID_360 公式选择随仿真时间变化的角度。标称 200,000 次/秒角度采样，重复角度、空回波与体素过滤后点数减少；它是瞬时场景上的角度轨迹近似，没有实机逐点时间/运动畸变。原始规则 10 Hz 版本的证据保留，不能替代此版本。模式定义与未对齐项见 Hands-on 的 SUPER 感知表。

200 Hz 模拟 IMU 放在 base_link / 飞控位置，保留时间戳、FLU、rad/s、m/s²（含重力）；白噪声参数沿用 PX4/Gazebo 近似，非 SUPER 实机标定值。主要原始测量话题剔除仿真绝对姿态，orientation_covariance[0]=-1。PX4 自用的上游 IMU 保持原样；新增零位姿、极小质量的传感器 link 只用于课程 ROS 观测。当前 PX4 估计里程计仍约 100 Hz，没有伪装成 FAST-LIO2 的 200 Hz 传播状态。

一次冷启动 2 m/s 实体走廊完整往返 passed=true：去程 66.301 s、返程 63.560 s，真值终点误差 0.0518 / 0.0767 m，最小中心净空 0.9987 m，实际高度 1.8037～1.9784 m，峰值速度 2.2249 m/s；自动落地解除解锁、无接触。证据 `/tmp/stage3-super-sensors/result-2.json`、`trajectory-2.csv`。一分钟扫描通过：30.2902 Hz、实时率 0.99980、最大帧间隔 0.0880 s；133,200 是内部载体射线数，不是发给规划器的点数。证据同目录 scan.json。

实际 ROS 8 秒窗口：预处理 243 帧、世界点云 238 帧、IMU 1601 条、PX4 里程计 800 条；IMU frame=base_link，orientation_available=false。世界末帧点数仅 166，反映该相位上视方向与去重过滤，不能把标称角度样本数理解为每帧有效障碍点。诊断脚本初版把 NumPy bool 直接写入 JSON 报错，已显式转换并实测恢复。C++ 扫描测试验证相邻帧方向集合不同、索引范围与采样预算、无效时段，Release 模式显式保留断言；CTest 1/1、Python 3/3 通过。没有新增 5 m/s 或故障注入验收，没有真实 MID-360 录包、完整 LIO、板端部署或精确硬件外参验收。


## 2026-10-12 收束版本：FAST-LIO2 与 200 Hz 传播

本节记录 FAST-LIO 显式对照配置；当前默认 PX4/GNSS 配置另见文末。仅在当前 PC 验证，没有连接 RoboPi 或真实雷达，没有调用付费 API。

本节 FAST-LIO 对照使用可选墙面标记、安装高度 0.30 m。Gazebo 载体为 1800×64 / 60 Hz，垂直 −7°～52°，按 SUPER/MARSIM 角度轨迹组成约 30 Hz Livox CustomMsg；分片时间偏移是真实查询时刻相对区间起点的 ns。约 17～20 ms 时间粒度、固定反射率等仍是仿真近似。FAST-LIO ROS2 固定 a4743b095409588842a5b30ddfa27e29d2f99164；源码补丁与接口见 Hands-on。点云校正约 30 Hz，独立滤波副本按 IMU 预测约 200 Hz。实际 PX4 参数读回：EKF2_GPS_CTRL=0、EKF2_BARO_CTRL=1、EKF2_EV_CTRL=15、EKF2_HGT_REF=3、EKF2_EV_DELAY=0。规划定位只来自 LiDAR/IMU；真值只用于评测。

双窗口冷启动 2 m/s 往返 passed=true：去程 70.061 s、返程 78.097 s；LIO 终点误差 0.0440 / 0.0304 m，实际终点误差 0.2219 / 0.0920 m。最小中心净空 1.0933 m，实际高度 1.9154～2.0059 m，峰值速度 2.1887 m/s；无障碍接触，正常降落解除解锁。评测接收时刻的最大位姿/真值差 0.2117 m，并非同步定位精度专项验收。证据在 PC /tmp/stage3-fastlio/final-200/{result.json,trajectory.csv,logs/}，原始日志与轨迹不提交 Git。

扫描检查分别通过：56.8037 / 60 Hz、平均实时率 0.9309、最大帧间隔 0.1122 s；另一窗口 57.0808 / 60 Hz、平均实时率 0.9568。第二窗口采样时飞行已结束，不能描述为完整返程性能测试。证据同目录 scan-takeoff.json、scan-landed.json。启动采样窗口测得传播状态 197.7 Hz、课程里程计 198.1 Hz、配准点云 30.0 Hz、IMU 198.3 Hz（均按仿真时钟计）；时间戳无重复或倒退，采样 Livox 点偏移为 16～32 ms，timebase 与 header 一致。当前 PC 四容器资源快照约 2.9 / 2.6 / 1.3 / 0.2 个 CPU 核、958 / 588 / 661 / 75 MiB 内存，非峰值预算。

独立冷启动雷达失流测试 passed=true：飞行进入轨迹后等待 1 s，SIGSTOP 时间分片雷达进程；0.5193 s 内控制桥请求降落，随后恢复雷达，正常解除解锁、无接触、最终高度 0.2270 m。报告在该测试 ROS 容器 /tmp/stage3-corridor/fault-lidar.json。该轮只证明失流响应及恢复数据后的降落；持续关闭雷达直到落地的独立补测见下文。

开发失败轮次不计入通过：初始化使用近零重力、初帧姿态抵消导致地图倾斜、首组零偏移点未覆盖去畸变边界，以及原赛道纵向漂移均曾导致失败。另一次低分辨率 / 200 Hz 开发配置失流后发生仿真障碍接触，落地仍保持解锁；确认本任务 SITL 落地静止后，使用容器内 commander 强制解除解锁恢复。最终版本恢复较细水平网格、修正分片时间边界、仅对齐航向、增加有效匹配门槛，并保留原生气压高度。没有放宽终点、高度、接触或净空验收门槛。

当前只完成一次最终配置的完整冷启动往返与一次上述失流测试。原始几何纯 LIO、LIO 5 m/s、多轮成功率、真实 MID-360 驱动/录包、板端迁移与 GCOPTER 同场景比较仍未验收。Python 几何/视场检查 6 项、C++ 扫描轨迹 CTest 1/1 已通过；静态检查不替代这些未验收项。


持续雷达失流补测（2026-10-12）：相同最终 FAST-LIO、标记开启、2 m/s 配置，独立冷启动。进入跟踪后等待 1 s，再 SIGSTOP 时间分片雷达节点，并保持停止直到 PX4 解除解锁。passed=true，0.5198 s 内请求降落；落地时传播里程计已静默 8.0668 s，无障碍接触，最终实际高度 0.2270 m。整个降落阶段没有恢复雷达或注入新的 LIO 位姿，没有强制解除解锁。该测试验证了传播停止与飞控气压后备；结束后清理逻辑才恢复雷达进程。证据在 PC /tmp/stage3-fastlio/fault-persistent/{result.json,logs/}。先前恢复雷达后降落的报告独立保存在 /tmp/stage3-fastlio/fault-recovered/result.json，不覆盖历史条件。

## 2026-10-12 无墙面标记对照与回归

针对原走廊 `--wall-landmarks off` 做了独立冷启动 2 m/s 试验，检查可否不依赖额外墙面实体。原整度方位扫描的无标记轮次失败：最大定位与真值差 13.58 m，随后发生接触及仿真数值失稳；仅在确认本任务 PX4 已解除解锁后重置。证据 `/tmp/stage3-fastlio/no-landmarks-current/`。将仿真雷达的 MARSIM 方位波形改为连续角度以覆盖 1800 列后，另一轮无标记试验无接触且正常降落，但去程未达到 0.3 m 真值到点门槛，最大定位与真值差约 1.21 m；证据 `/tmp/stage3-fastlio/no-landmarks-continuous/`。连续角度是本课程的仿真采样实验，不等同于原 MARSIM 的整度取整或真实 MID-360 出厂扫描标定。

进一步依据仿真明确静止启动和前 400 条 IMU 样本收紧 FAST-LIO 初始化协方差，不使用 Gazebo 真值作定位输入。连续角度＋静止先验组合的无标记轮次：去程真值终点误差 0.1047 m；回程规划器报告到点时，真值仍距起点约 3 m，最终超时，passed=false。最大定位与真值差 3.5603 m，最小中心净空 1.0832 m，无接触，正常降落解除解锁。证据 `/tmp/stage3-fastlio/no-landmarks-stationary-prior/{result-2.json,trajectory-2.csv}`。因此当前不能宣称原走廊的纯 LiDAR/IMU 无标记完整往返通过；无标记纵向约束仍是待解决问题。

相同新代码、标记开启的独立回归 passed=true：去程与回程真值终点误差 0.1676 / 0.0826 m，最小中心净空 1.1021 m，最大定位与真值差 0.2489 m，无接触，自动降落解除解锁。证据 `/tmp/stage3-fastlio/marker-regression-continuous/{result-2.json,trajectory-2.csv}`。这只验证新组合没有破坏有标记 demo，不能单独归因于角度采样或初始化先验。

目前的 1.95 m 是课程控制桥为该走廊选择的固定飞行层，不是用户指定的 PX4 限制。PX4 Offboard 接口可接收三维位置、速度、加速度；当前桥将 SUPER 的 Z 参考投影到 1.95 m，并令 Z 速度/加速度为零，以固定飞行层核对水平避障。三维轨迹执行及含悬空障碍场景尚未验收。

## 2026-10-12 PX4/GNSS 默认演示与 ROG 地图展示

走廊默认改为 `localization=px4`、`wall-landmarks=false`，不启动 FAST-LIO；PX4/GNSS 提供估计位姿，仿真 MID-360 回波经预过滤和坐标变换后仍输入 SUPER/ROG-Map。运行中实际读回 `EKF2_GPS_CTRL=5`、`EKF2_EV_CTRL=0`、`EKF2_BARO_CTRL=1`。RViz 将 `/cloud_registered` 实时回波、`/rog_map/occ` 0.2 m 占据体素、`/rog_map/inf_occ` 安全膨胀区域分层显示。后两者是同一 ROG-Map 的两种输出，不是两个建图算法。独立订阅实际收到占据图 1268 点、膨胀图 24099 点；这是一次静止视野快照，不代表性能上限。实际 RViz 窗口截图已检查：青色方块墙体/立柱与淡橙色膨胀区域可区分，截图时显示约 19 fps；ROS/SITL/RViz 的资源快照分别约 2.24/1.67/0.31 核、759/468/108 MiB，非峰值。

双窗口、无附加标记的 2 m/s 冷启动往返 passed=true：去程和回程实际终点误差 0.05965 / 0.05835 m，时间 63.230 / 63.110 s；最大定位与真值差 0.11253 m，最小中心净空 1.02069 m，实际高度 1.8611～2.0435 m，峰值速度 2.1585 m/s。无障碍接触，自动降落解除解锁。起飞前 `inspect ready=true`，约 30.23 Hz 雷达帧、100.07 Hz PX4 位姿；地图图层由 ROG ROS2 publisher 在订阅者存在时实际发布。证据在 PC `/tmp/stage3-px4-rogmap-demo/{result-2.json,trajectory-2.csv,rviz-voxels.png}`。图形窗口仍是课程仿真效果，不代表真实 GNSS 遮挡环境中的定位可用性。

## 2026-10-12 三窗口展示拆分

用户将叠加视图改为 Gazebo＋两个独立 RViz：`super_gazebo_cloud.rviz` 只订阅 `/cloud_registered`，按高度着色展示当前点云；`super_gazebo_map.rviz` 只订阅 ROG 的 `/rog_map/occ` 与 `/rog_map/inf_occ`，用青色方块和淡橙色点展示积累占据体素与安全膨胀区域。两窗仍显示机器人和飞行路径。对应 GUI 容器为 `uav-stage3-gazebo-view`、`uav-stage3-rviz-view`、`uav-stage3-rviz-map-view`；`view-close` / `down` 会清理全部三个。实际截图逐一核查，点云与体素图不再叠在同一 RViz 窗口；两个 RViz 静止画面约 19～20 fps。窗口在当前双屏桌面分别放置，不代表单屏可同时完整显示。飞行中的资源快照：点云 RViz 0.3345 核 / 75.58 MiB、地图 RViz 0.3289 核 / 92.81 MiB、Gazebo GUI 1.0354 核 / 522 MiB；均非峰值。

随后按默认 PX4/GNSS、无标记、2 m/s 独立冷启动并保持三窗口开启，完整往返 passed=true：去程 / 回程 65.452 / 63.712 s，真值终点误差 0.15737 / 0.10808 m；最小中心净空 0.95282 m，实际高度 1.6087～1.9586 m，峰值速度 2.1703 m/s，无接触，自动降落解除解锁，末次实时率约 1.0003。证据 `/tmp/stage3-px4-three-view/{result-2.json,trajectory-2.csv,cloud-rviz.png,map-rviz.png,gazebo.png}`。飞行验收后将两个 RViz 的路径线宽从 0.30 m 缩到 0.08 m，重新打开窗口并分别截图检查，未因此重复飞行；这只改变渲染，不改变 ROG 地图或控制输入。

## 2026-10-12：通用算力镜像直接构建

已取消 `gcopter-humble` 快照与 install 复制。`develop/docker/Dockerfile` 从 OSRF Humble 基础镜像直接构建 `uav-computer-ros-humble:local`，SUPER 和 FAST-LIO2 使用同一依赖镜像，算法源码仍挂载编译。原有运行实例未由本轮重启或替换。

| 版本项 | 实际构建值 |
| --- | --- |
| 平台 | PC Linux amd64，Ubuntu Jammy / ROS 2 Humble |
| 基础镜像 | `osrf/ros@sha256:1ee56d3ee5111f81e0a2a17b6ecd73447afb5c5b8a3c3574754f2646da9aee34` |
| 最终算力镜像 ID | `sha256:c3fa439c7a5819aa1bb9cdda37865c316f05b597013881d4af7331b15b14b220` |
| px4_msgs | `57f88be3c01a8c593c23507e4ca136767115ca22`，VehicleStatus v4 |
| XRCE Agent | v2.4.2，`57d086216d01ec43121845d385894a25987f8a2c`，使用 Humble 系统 Fast DDS / Fast CDR |
| SUPER 来源 | 原工作区旁 SUPER，HEAD `71298ecf0a588f416085d471578e33cb0963d123`＋已有未提交修改＋课程准备补丁 |
| FAST-LIO2 / Livox 来源 | `prepare_lio.py` 的固定提交及课程补丁 |

实际通过：

- 镜像从固定官方基础镜像构建完成；构建历史没有课程 GCOPTER 快照层。软件包列表和源码版本在镜像 `/opt/uav/packages.tsv`、`/opt/uav/sources.txt`，apt 源未快照锁定，不宣称逐字节复现。
- `/opt/uav/check_runtime.py` 离线自检 `passed=true`：ROS 包可见、NumPy/SciPy/YAML 可导入、六种 PX4 消息 CDR 往返、VehicleStatus v4、Agent 动态库无缺失。隔离网络中 Agent UDP 18888 初始化成功，三秒后由 timeout 停止，没有占用仿真 UDP 8888。
- 从源码构建 SUPER 的三个核心包、FAST-LIO2/Livox 两个包和课程雷达包通过；算法编译使用单线程。正式 `lio-build --build-jobs 1` 入口通过，强制重新配置后成功生成 `timed_lidar`。SUPER/FAST-LIO2 有上游编译警告，没有编译错误。
- 最终镜像中四个可执行文件（SUPER、FAST-LIO2、prefilter、timed_lidar）的动态库检查通过，六个课程 Python 适配/诊断模块导入通过，PositionCommand 和 Livox CustomMsg 的 CDR 往返通过。
- 新镜像中现有 Python 几何/视场/高度测试 6/6 通过，C++ MID-360 扫描测试通过（`PASS non-repeating masks: 5629 / 5006 cells`）。PC 默认 Python 缺 NumPy 的首次测试未通过，随后在目标 Humble 镜像内验证，不把 PC Python 环境当作运行基线。
- 只读订阅现有 PX4/旧 Agent：使用课程 `race_view_dds.xml` 的 UDP 传输配置，十秒内收到里程计 779 条、VehicleStatus 15 条，没有发送控制消息。首次未传入 DDS 配置时计数均为零；这说明独立诊断容器也需要使用实验通信配置。正式 up 入口继续显式传入该配置。

上述只读订阅验证了新镜像消息与现有通信链路的兼容性，未验证新 Agent 与 PX4 的完整联调、新镜像全节点启动、飞行或故障降落。历史飞行证据属于旧镜像与原配置；新实例仍需按 Hands-on 重新 inspect、飞行及故障验收。没有板端或 GUI 复验。
