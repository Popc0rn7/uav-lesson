# Stage 3：planner 与视觉迁移

本轮主线固定为 GCOPTER、SUPER，以及一个目标识别/追踪组合。每项先在 PC 的 ROS 2 Humble Docker 跑通，再迁移到 RoboPi OpenHarmony，最终由板端算法控制 PC 中的 `x500_experiment`。多机编队、探索与 Jev 飞行接入暂不属于本轮交付。

## 1. 当前检查结果（2026-10-10）

课程仓库原有代码只有 Jev 文本示例；实际 planner 工作位于相邻的 `../GCOPTER`、`../SUPER`，本轮优先复用这些版本。Docker 经用户授权后已可访问，已有 `gcopter-humble` 开发容器及持久化 build/install/log；早期检查仅启动开发容器；后续已完成专用双 Docker 标准机飞行闭环，没有连接板端。当前可运行入口见 [Hands-on](Hands-on.md)，本文件保留来源与迁移边界。

`thirdparty/GCOPTER`、`thirdparty/SUPER` 原目标误写为 `../GCOPTER`、`../SUPER`，已修正为 `../../GCOPTER`、`../../SUPER`。链接目标相对于链接所在目录解析。`thirdparty/` 被 Git 忽略，链接是本机开发配置，不会随 clone 分发；Docker 挂载应使用解析后的真实目录，或将两份源码分别挂载，单独挂载课程仓库不会包含链接外的源码。

新 PC 已有相邻源码时，**PC 仓库根目录**创建链接（已有路径时先检查，不覆盖）：

```sh
mkdir -p thirdparty
ln -s ../../GCOPTER thirdparty/GCOPTER
ln -s ../../SUPER thirdparty/SUPER
readlink -f thirdparty/GCOPTER
readlink -f thirdparty/SUPER
```

本机 GCOPTER HEAD 为 `b123cb619e791586bd7481e7f43e78206af058d2`，另有用户未提交的 `scripts/host_sim.sh` 修改，保持原样；搬入前的 SUPER HEAD 为 `2ad3419c127a617c6d7df6925e81a14175a9c096`；当前搬入版本为 `71298ecf0a588f416085d471578e33cb0963d123`，含大量未提交修改及新增文件，不能只用 HEAD 描述实际算法版本。GCOPTER 已有 Humble/ament 适配、PX4 控制桥、雷达建图、OpenHarmony 后端；历史 `docs/openharmony-sitl-verification.json` 记录 Docker 和板端控制实际虚拟 PX4/Gazebo 的验收。此证据属于其原场景与版本，不能替代课程 `x500_experiment` 的本次复验。当前 SUPER 六个核心/示例包均已选择 ROS 2/ament；原 ProjectAirSim 集成使用 ROS 2 Jazzy 和 PX4 v1.12.3，启动脚本仍写死 Jazzy。课程目标统一为 ROS 2 Humble，需要重新构建并验证，不能沿用原机 install/build。

本次已有 GCOPTER 可执行文件动态库解析无缺失，ROS/Python 消息依赖预检通过；轨迹数学与点云解析/变换测试共 6 项通过。独立域 54 下 CDR 轨迹/状态消息往返及后加入订阅者接收缓存地图的 QoS 检查均通过，没有发飞行命令。原开发容器缺少 SUPER 所需的 `libdw-dev`；用户明确授权安装后，已在专用运行镜像补齐，核心依赖预检、Humble 构建与标准机飞行通过，见 [Validation](Validation.md)。

**PC 仓库根目录**运行只读检查，不需要 ROS Python 环境：

```sh
python3 stage3/check_environment.py
```

前置条件：教师已准备 Docker、ROS 镜像和 Stage 2 SITL。成功判据为退出码 0、`action=baseline-visible`；这里只证明能看到基线，不证明容器内 ROS 依赖或飞行通过。失败时保留 JSON；Docker 权限问题由教师核实当前会话权限，缺镜像按 Stage 1 教师准备流程处理，SITL 未运行按 Stage 2 启动。脚本不自动安装、拉取或重启。

### 搬入 SUPER 的历史证据与外部链接

- `projectairsim_super_adapter/README.md` 和 `scripts/run_click_demo_ros2.sh` 明确使用 Jazzy；核心输入为 `/lidar_slam/odom`、`/cloud_registered`，输出为 `/planning/pos_cmd`，原控制监督器通过 MAVROS 向 PX4 发送设定值。
- `docs/real_forest_return_validation.zh-CN.md` 记录 2026-09-28 RealForest 去返程通过、Release 编译及相关测试通过；返程曾短暂指令超时。该结果仅属于原机配置，尚未在课程环境复验。
- `ProjectAirSim -> /home/wqy/ProjectAirSim/`、`dp550_isaacsim -> /home/wqy/dp550_isaacsim/` 在当前 PC 不可解析。旧 AirSim 启动脚本直接依赖前者，不能在本机原样运行；核心 planner 的 CMake 未直接依赖这些链接。接课程 Gazebo 时另写传感器/控制接入，不必为了读取 planner 源码复制外部仿真仓库。
- `stage3/prepare_super.py` 已改为保留已有 ament 配置，只转换 ROS 1 包；复制时保留软链接、排除原机构建产物。临时副本验证六个包均保留 ROS 2，关键 CMake/package.xml 与来源逐字一致。先前准备的 `thirdparty/super_humble_ws` 是搬入前副本，不作为当前 SUPER 基线。

## 2. 上游与移植边界

| 算法 | 来源与现状 | 本仓库需完成的工作 |
| --- | --- | --- |
| GCOPTER | [官方仓库](https://github.com/ZJU-FAST-Lab/GCOPTER)原示例采用 ROS 1；本地 `../GCOPTER` 已完成 Humble/ament 适配，依赖 Eigen、OMPL；[MIT](https://github.com/ZJU-FAST-Lab/GCOPTER/blob/main/LICENSE) | 复用本地优化核心、消息和执行桥；对齐课程标准机的传感器、定位、域与失效处理，重新验收 |
| SUPER | [官方仓库](https://github.com/hku-mars/SUPER)提供 ROS 版本切换脚本与 ROS 2 launch；README 标明 ROS 2 仍在开发，列出的测试环境含 Foxy | 保留搬入版本的 ROS 2、规划优化和终点保持修改；由原 Jazzy/ProjectAirSim 接口迁移到 Humble/课程 Gazebo/PX4；核对各子目录许可证 |
| YOLOX 小模型＋ByteTrack（候选） | [YOLOX](https://github.com/Megvii-BaseDetection/YOLOX)代码为 Apache-2.0；[ByteTrack](https://github.com/FoundationVision/ByteTrack)代码为 MIT | 目标类别确认后选择 nano/tiny 权重；Docker 验证检测和 ID 连续性；核实权重许可、OpenHarmony 推理运行时及模型转换支持 |

本地源码 commit 已记录，正式准备还须记录未提交补丁、构建版本、镜像 ID/摘要和模型 SHA-256。不能从 Linux AArch64 的推理产物推断 OpenHarmony 可用，也不能把 YOLOX 的其他后端支持当成 Houmo NPU 支持。

## 3. 实施与验收顺序

1. **PC Docker 基线与单机控制**：核实 PX4 版本、当前 MAVLink/uXRCE-DDS 能力及所需消息包，再选控制桥；验证起飞、悬停、降落及输入超时处理。两种 planner 共用控制适配层。
2. **Docker planner**：GCOPTER 复用本地 ROS 2 适配和执行桥；SUPER 保留搬入版本的 ROS 2 修改，在 Humble 重新编译并接入课程仿真适配层。随后两者接入同一标准机、地图、初始状态与目标，完成可重置的避障飞行。
3. **板端最小控制闭环**：显式选择 HDC 目标，复验板端 ROS、RMW、SDK/ABI 和以太网 DDS；先由板端控制同一架 PC 仿真机，再迁移 planner 核心及目标依赖。Gazebo、QGC 和可视化留在 PC。
4. **板端 planner 对照**：相同输入先比对轨迹，再执行相同飞行任务；记录时延、CPU、内存、速度、成功率和失败原因。
5. **视觉 Docker → RoboPi**：固定目标类别、仿真目标资产和运动序列；先验证 RGB 检测、追踪，再迁移推理及关联模块。记录检测漏失、ID 切换、丢失恢复和端到端延迟；通过后接入有距离/速度限制的跟随任务。

构建、依赖下载、SDK 准备和模型转换属于教师课前准备。每步完成后补充实际命令、预期现象、排障和验证记录。SUPER 双 Docker 流程见 [Hands-on](Hands-on.md)：已完成 Gazebo 实体走廊的实时扫描、旧双窗口与当前 Gazebo＋双 RViz 三窗口、2/5 m/s 历史配置及当前 PX4/GNSS 2 m/s 高度受限往返，以及点云/规划器/时钟故障后的自动降落；范围与数据见 [Validation](Validation.md)。板端、统一算法评测和视觉步骤仍需后续实现。

## 4. 共同接口约束

- 单机标识初始约定 `uav1`，应用话题采用 `/stage3/uav1/`；实际 PX4 ID、端口和消息版本在接口核实后记录。跨机域沿用候选域 10，解除 localhost 限制前先验证以太网地址与 DDS 配置。
- 输入必须明确里程计、速度、姿态、点云、RGB、深度、相机内参、安装外参及时间源；仿真节点统一使用 `/clock`，超时和进程失联监控同时使用墙钟，防止仿真暂停掩盖故障。
- 应用世界坐标采用 ENU、机体系 FLU，米/秒/弧度；与飞控 NED/FRD 的转换只在控制适配层完成，另核实 Gazebo 世界原点与 PX4 估计原点，不只交换轴。
- Stage 2 雷达点云是传感器局部坐标且没有 world TF；[SUPER README](https://github.com/hku-mars/SUPER#27-notable-known-issues)明确其 ROG-Map 输入假定为世界坐标，不使用 `frame_id`/TF 自动变换。因此必须按采样时刻的位姿与安装外参实际变换 XYZ，不能只改 frame_id。
- 单帧表面体素不是占据地图，不能把未知区域当空闲。两种 planner 先用同一固定地图做对照，再单独验证在线建图条件。
- RGB/D 当前未同步或光学对齐，不能直接用 RGB 框索引深度推断目标距离。先完成二维追踪，再验证三维定位。
- 控制适配层检查输入新鲜度、有限数值、轨迹时序、速度/加速度/高度/边界和飞行状态；异常停止接受新轨迹，执行已验证的保持/降落策略，并记录飞控反馈。具体阈值和超时在首次闭环前固定到配置。

## 5. 继续运行所需信息

Docker 访问已恢复，普通沙箱命令仍不能直接访问 socket，本会话使用用户授权的 Docker 执行权限。SUPER Docker 核心依赖已补齐且预检通过。板端阶段还需核实 HDC 目标设备、实际 SDK/toolchain 与 ROS 目标库路径，优先核对 GCOPTER 已有板端流程；视觉阶段需确认跟踪对象及可用推理运行时。
