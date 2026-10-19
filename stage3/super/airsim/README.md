# Stage 3：SUPER 流程的 AirSim 替换后端

本入口提供 PC 宿主机 AirSim＋Docker 1 PX4＋Docker 2 ROS 2/SUPER。保留独立 PX4 控制测试模式；不接算力板，不启动 Gazebo。

Stage 4 AeroVLA 复用本目录 runtime 的进程/容器管理、PX4 接入和时钟，通过显式 `ros_runtime` 启动不依赖 SUPER 的 ROS 工作负载；不改变这里的默认任务与参数。Stage 4 操作和验收独立见 [Hands-on](../../../docs/stage4/Hands-on.md)。

宿主机启动统一关闭 Unreal 的启动鼠标捕获与窗口锁鼠：runtime 注入 `-NoMouseCapture` 和 Input 的 NoCapture / DoNotLock 设置，便于在场景、QGC 与终端之间操作；不修改原包配置。该默认也用于 Stage 2 ADRL。Stage 3 场景的实际桌面效果须按当前包验证。

## SUPER 双 Docker 合并入口

### 失控、碰撞或命令卡住时（PC，另一个终端）

```bash
# 查看现场；task/fault 正在执行时也能调用。
uv run stage3/super/airsim/runtime.py status

# 请求正常降落，同时锁存取消标记，阻止航点/起飞状态机重新接管。
uv run stage3/super/airsim/runtime.py land

# 碰撞卡住、Land 长期不解除解锁、仿真不响应时：强制结束本轮仿真。
uv run stage3/super/airsim/runtime.py stop
# 等价旧入口：uv run stage3/super/airsim/runtime.py down --force
```

`land` 返回仅表示请求已发送，必须用 status 确认 Disarmed；碰撞后落地检测可能不成立，不能无限等待 Land。`stop` 不等待解除解锁，停止本入口拥有的 ROS/PX4 Docker 和宿主机场景，保留任务报告、节点日志和 ULog；这是仿真急停，不是正常降落。普通 `down` 仍拒绝停掉未解除解锁的实例，并直接提示 stop。

人工恢复使用独立互斥锁，任务/复盘占用 runtime.lock 时不会挡住 status、land、stop 或 down --force；同一时刻只执行一个恢复动作。stop 不接管未知资源，容器按所有权标签和 ID 核验，宿主机按 PID/启动时间/ELF/设置参数核验。强制回收时某一资源或日志操作失败仍会尝试回收其他已核实资源，未清理完则保留 stopping 状态并报告错误。正在创建资源的 up 不允许被并发接管，此时先中断 up 再 stop。

人工 land 后本轮任务被持续取消，需要 down/up 才能重新起飞；stop 后直接按选定配置 up。失败任务收到降落请求并不保证已经落地，不要把 phase=ready 当作解除解锁判据。

2026-10-15：已保存 `420d571d985b4a2a985025a30d0fbdb5/recovery-before-1792032898611537006.json`。该实例碰撞后持续 Armed/Land，`vehicle_land_detected.landed=false`，再次正常降落仍未恢复；实际 down --force 已回收场景和两个 Docker，保留日志。新增 stop、任务占锁恢复、身份边界、强制回收失败续行与预流阶段取消通过隔离测试；35 项回归通过，未为验证恢复流程再次起飞。

本轮将 `airsim_super_handoff` 的 AirSim 雷达、RGB 相机配置、过滤/0.1 m 体素降采样、ROG 配置、航点/carrot 与 RViz 合入本目录，拆为感知桥、航点任务和 PX4 控制三职责。原交接包已移到本机忽略提交的 `artifacts/references/airsim_super_handoff/`，不作为运行依赖，也不分发其中 reset/瞬移/SimpleFlight 脚本。合并时规划器基线为 SUPER commit `61c1d6244ce2950dbf7052a1a3e8caeab0773088`，当前修复版本由主仓库 gitlink 固定；交接包未提供自己的 SUPER 补丁/commit 或独立验收日志，不能认定源码完全相同。AirSim 本地源码 MIT；交接脚本未附独立许可证，重新分发时由维护者确认来源授权。

| 执行位置 | 职责 |
| --- | --- |
| PC 宿主机 AirSimNH | `PX4Multirotor` 动力学、HIL 传感器、LiDAR RPC；出生点在启动设置中确定 |
| Docker 1 `uav-airsim-px4` | 原 PX4 镜像，无 Gazebo；HIL→PX4/GNSS，DDS 收完整 XYZ 位置/速度/加速度 |
| Docker 2 `uav-airsim-ros` | XRCE Agent、时钟桥、PX4 控制适配器、雷达桥、SUPER/ROG、航点任务，RViz 可选 |

当前 AirSim 默认采用 **GPS 延迟补偿 200 ms＋姿态参考前馈 `MC_REF_FF=1`**，由 `settings.json` 的 `Vehicles.PX4.Parameters` 加载，常规和高速 settings 均保留这两个参数。仅改变 AirSim 后端，不修改 Gazebo。当前基线及默认入口为 A→B 单目标 10-ab，八航点仅保留为显式历史对照，不能替代 AB 验收。故障保护保持原值。修改配置后需要正常 down/up，新参数不会热加载到旧实例。

### 课前准备（PC）

先满足下文 Docker、场景 ELF、图形桌面前置条件，再准备统一算力镜像与 SUPER 编译产物：

```bash
python3 stage3/super/super_docker.py prepare
python3 stage3/super/super_docker.py build
```

完整构建方法及基础镜像覆盖参数见 [Stage 3 教师准备](../../../docs/stage3/Hands-on.md#教师准备pc)。统一镜像增加 `python3-msgpack`，RPC 使用轻量 MessagePack 客户端，不安装旧 AirSim Python SDK/tornado。场景与源码是独立依赖，不会自动拉取或重编 AirSim。本机初次准备约 4 分钟镜像构建、2 分钟核心编译，时间随网络/机器变化；运行保留 60×60×16 m 局部地图和 200000 点/秒的 16 线雷达，需核对 CPU/GPU/内存预算。

### 任务配置与运行（PC 图形桌面终端，仓库根目录）

```bash
# 如有旧实例，先 status 确认落地未解锁，再 down；不要停止未知实例。
# 默认 forest10-ab 单目标；短程回归需显式加 --config stage3/super/airsim/runtime.super.json。
uv run --extra flight-review stage3/super/airsim/runtime.py up
uv run stage3/super/airsim/runtime.py inspect
uv run stage3/super/airsim/runtime.py view
uv run stage3/super/airsim/runtime.py snapshot
uv run --extra flight-review stage3/super/airsim/runtime.py task
uv run stage3/super/airsim/runtime.py status
uv run stage3/super/airsim/runtime.py down
```

`up` 在 PX4 就绪后启动 Docker 2，检查连续时钟/DDS/GNSS/配准点云与非空占据/膨胀地图；默认不解锁。`inspect` 只读。`task` 才请求起飞、稳定悬停、逐航点往返和降落。正常成功需任务报告 `success=true`、到终点稳定、按任务配置完成降落解除解锁或悬停，且没有非着陆碰撞或故障；跟踪误差仅作性能指标，不单独判任务失败。旧任务配置的误差门限已移除，报告中的 `max_tracking_error_m` 仍表示实际观测指标；报告记录实际速度，规划速度上限不保证实际运动严格限速。`view` 在同一算法容器启动 RViz，显示连接在 up 时从桌面环境只读挂载；未配置 DISPLAY/XAUTHORITY 时查看 `rviz.log` 并从有效桌面重启。RViz 使用软件 OpenGL，关闭窗口不停止控制链。`snapshot` 只读保存相机 0 的 RGB PNG 和仿真采集时间/相机 pose 元数据，不申请 API 控制权。

| 输入文件 | 用途 |
| --- | --- |
| `runtime.super.json` → `task.low.json` | 显式低速回归：出生 NED `(0,0,0)`，1 m/s、2 m/s²；ENU `(0,2,2)`→`(0,0,2)`，中间航点稳定后返程，最后降落 |
| `runtime.forest1.json` → `task.forest1.json` | 树林短程：出生 NED `(42.60,160.11,0)`，ENU `(-9.35,33.53,2)`→`(0,0,2)`，1 m/s；已完成一次实际去回 |
| `runtime.forest5.json` → `task.forest5.json` | 与 forest10 相同的树林八航点，仅配置速度改为 5 m/s；板端重规划放宽实验结果见迁移验证，不沿用 10 m/s 的验收结论 |
| `runtime.forest8.json` → `task.forest8.json` | 交接 demo4 八航点树林路线，8 m/s、8 m/s²，连续推进，**待验证，非默认** |
| `runtime.forest10.json` → `task.forest10.json` | 显式历史对照：10 m/s 八航点；两轮成功证据不能当作 AB 基线通过 |
| `runtime.forest10-ab.json` → `task.forest10-ab.json` | 10 m/s、约 235 m 单远端目标，无任务层 carrot；已开始飞行但碰撞中止，未到 B |
| `runtime.forest15.json` → `task.forest15.json` | 显式 15 m/s 需求对照，历史实际峰值仍约 10 m/s，不代表达到 15 m/s |
| `planner.base.yaml` | 交接航点版 SUPER 参数；启动时从任务覆盖速度/加速度、虚拟地面/天花板与 odom 超时，生成本次 `planner.yaml` |

运行配置中的 `super_task` 指向任务 JSON，相对 runtime 文件解析；`ros_image`/`ros_container` 指定 Docker 2。任务 JSON 保存出生 NED XYZ/朝向、**出生点相对 ENU XYZ 航点**、边界、速度/加速度、超时、悬停时间、航点 `stop/pass` 策略、终点 `land/hover` 行为及雷达 FRD 安装外参。交接绝对场景航点减去出生水平坐标后使用；高度相对起飞参考，未把场景真值当作 PX4 原点。新配置只在 up 时读取，生成设置/任务快照不得手工修改；换任务先落地 down/up。低速地图虚拟地面 −2 m 留出膨胀余量，避免未起飞时估计微小负 Z 让 ROG 拒收点云。

### 终端实时仪表盘（PC 终端显示，Docker 2 运行）

`runtime.py task` 和 `fault` 现在默认实时显示遥测：交互终端原地刷新约 4 Hz，退出时恢复光标并保留最后快照，随后输出任务结果与复盘。无需重建 Docker 或为仪表盘重启当前实例；已经运行中的旧 task 进程不会热加载新显示代码。

**PC，仓库根目录，实例已就绪**：

```bash
# 在当前任务终端自动显示仪表盘，并实际执行任务。
uv run --extra flight-review stage3/super/airsim/runtime.py task

# 另开终端，只读观察；任务正在执行时也能打开。
uv run stage3/super/airsim/runtime.py dashboard

# 只观察 10 秒后退出；不会起飞或降落。
uv run stage3/super/airsim/runtime.py dashboard --seconds 10
```

仪表盘显示实际总速度、水平速度、垂直速度（向上为正）、实际下发的参考速度、配置速度、当前窗口 track 阶段均速/峰值、ENU 位置、同测量时刻的位置误差、仿真/墙钟比、数据新鲜度、PX4 解锁/导航状态、控制状态及任务进度。独立观察入口还显示最近一轮报告的成功/失败、峰值、航段均速和原因，任务结束后可直接查看。

速度来自 PX4/GNSS 估计，单位 m/s **按仿真秒**，不是画面按墙钟播放的位移速度；`仿真/墙钟=0.71` 表示仿真比实时慢。新鲜度为旁路收到消息后经过的墙钟时间，不是测得的单向网络延迟。未收到/失流的数据以 `--` 显示，不伪装成零速度；位置误差只在参考时间序列能够有效插值时显示。

当前窗口均速按唯一里程计测量时间加权，跳过失流及非 track 阶段；中途打开观察不代表完整任务统计。上轮报告的数据与当前窗口分开显示。进度 `waypoint=8/8` 仅表示正在执行最后一个航点，不能代替 `success=true`。新任务报告保存 `summary.dashboard_window`，原始测量和自动复盘仍保留。

`Ctrl+C` 的区别：在 **task 终端**中断会沿用原有的中止/降落流程；在 **独立 dashboard 终端**中断仅关闭只读观察。仪表盘不修改控制参数、轨迹、发布频率或看门狗。只读 dashboard 不持有任务互斥锁，也不阻塞 status/land/stop。

非交互输出自动每秒生成一行纯文本；可用 `--dashboard plain` 强制纯文本、`--dashboard off` 关闭仪表盘。显示代码运行在 Docker 2，PC 管理器实时转发输出，不再等整轮任务结束才显示。当前已完成任务的实例可直接运行 dashboard 查看，重新起飞前仍按任务要求 down/up 回到配置出生点。

验证：57 项隔离回归通过，包含实时转发、失流显示、测量时间统计、任务 CLI 报告共存、失败任务复盘、观察入口无控制发布器与锁边界。现有已解除解锁实例实测 plain 和伪终端 ANSI 显示、正常结束及 Ctrl+C 退出，均恢复终端且无遗留观察进程；转录位于 `artifacts/airsim-dashboard-checks/`。没有为验证仪表盘重飞用户的 8 m/s 任务。

### 接口、时间与故障恢复

- 域 10、`rmw_fastrtps_cpp`、单机 `uav1`、XRCE UDP 8888；不要与 Gazebo 主 demo 同时启动。换容器名不能隔离端口。
- `/lidar_slam/odom` 唯一来源为 PX4/GNSS；world ENU、机体 FLU。`twist.linear` 保持 SUPER 约定的 world ENU 速度，与通用 ROS Odometry 的 child-frame 速度语义不同，外部消费者须另做转换。不使用 SimpleFlight 状态或 AirSim 真值反馈。
- `/cloud_registered` 为 world ENU XYZI。雷达必须 `SensorLocalFrame`；传感器 FRD 外参先变到机体 FLU，再用采集时刻 PX4 位姿配准。位置线性插值、姿态 SLERP，只接受间隔≤50 ms 的位姿括号；延迟超过 0.5 s、复位、缺位姿时丢帧。没有逐点时间的 AirSim 扫描只做帧级配准，不宣称逐点去畸变。
- `UXRCE_DDS_SYNCT=0`，以 PX4 HIL 的 `SensorCombined.timestamp` 发布 `/clock`。本地 AirSim 源码的 HIL 与 LiDAR 均来自同一仿真 clock；实测位姿括号验证同源，而非用 RPC 收包墙钟盖章。SUPER、里程计、点云和航点计时统一仿真时间；通信看门狗用 PC 单调时间。
- `/planning/pos_cmd` 经现有适配器做时间、数值、边界、速度/加速度及跟踪距离检查，再进入 PX4 Offboard。航点节点只发 `/stage3/uav1/goal` 与任务请求，不持有 AirSim API 控制权；跟踪中允许更新 carrot。
- 规划、雷达、定位、时钟失流或估计器复位触发降落；桥进程退出由 PX4 的 `COM_OF_LOSS_T=0.5`、`COM_OBL_RC_ACT=4` 兜底。通信/仿真完全停住时只能请求降落，不能保证动作已执行。正常降落后确认 Disarmed 再 down；碰撞或卡住时直接 stop 回收本轮仿真。

**PC，已就绪并确认空域，故障测试会实际起飞：**

```bash
uv run stage3/super/airsim/runtime.py fault --case lidar
uv run stage3/super/airsim/runtime.py fault --case planner
uv run stage3/super/airsim/runtime.py fault --case clock
```

故障入口只在本次拥有的算法容器内唯一识别目标进程，跟踪中 SIGSTOP，验证预期原因与解除解锁，最后 SIGCONT 恢复。报告、点云/任务状态、节点日志、PX4 ULog 均保留在 `artifacts/airsim-runtime/<运行ID>/` 并忽略 Git。AirSim 正常着地的向上地面法线接触仅在降落状态且估计高度≤0.3 m 时记录为着地接触，其他新碰撞判失败。

### 本轮合并验证

2026-10-14：Python/Shell 语法、22 项 Stage 3 回归（含六项新增几何/配置测试和六项 Offboard 测试）、统一镜像离线自检及 SUPER 核心编译通过。本次统一 Humble 镜像 ID `c24f47188837b14600ec211bbc7d98f00c212aad7ff70cb4a446c02e8a1be894`，基础使用本机 `osrf/ros:humble-desktop-jammy`（ID `d558d73d8965`）；固定 PX4 消息/Agent 提交及 apt 包记录在镜像 `/opt/uav/`。PX4 镜像保持 `70584c9eb1e9`。静止 DDS、PX4/GNSS、同源时间、配准点云、占据/膨胀地图均有连续实际数据。

| 实际验证 | 结果 | 本地证据（`artifacts/airsim-runtime/` 下，忽略 Git） |
| --- | --- | --- |
| 1 m/s 2 m 停稳往返 | 通过一次，76.24 s 墙钟，最大跟踪误差 0.708 m，实际速度峰值 1.367 m/s；无空中碰撞，落地解除解锁 | `bf879d89a269420390fb8dcecf94458c/fly-task-1791983567917104722.json` |
| 雷达停流 | `lidar cloud timeout`，降落解除解锁，节点恢复 | 同目录 `fault-lidar-1791983681216649067.json` |
| 规划器停流 | `SUPER command timeout`，降落解除解锁，节点恢复 | 同目录 `fault-planner-1791983818927819891.json` |
| 时钟发布停流 | `state or clock timeout`，墙钟看门狗请求降落，解除解锁，节点恢复 | 同目录 `fault-clock-1791983898603601681.json` |
| 1 m/s 树林约 35 m 去回 | 通过一次，169.67 s 墙钟，最大跟踪误差 0.343 m，实际速度峰值 1.215 m/s，仿真倍率 0.728；轨迹高度 1.424～3.500 m，完成 carrot 更新、三维执行、返程与降落，无空中碰撞 | `a1203ed2385549f881eb7fea16a965c7/fly-task-1791984107974504389.json` |
| RViz / RGB | 同一算法容器 RViz OpenGL 4.5 启动；相机返回并人工检查 1920×1080 PNG。未将进程启动等同于所有 RViz 图层人工验收 | 两目录 `rviz.log`；树林目录 `camera-1791984412426662625.png`、`camera-1791984480664122632.png` |

首轮连续推进的 1 m/s 短程往返完成并解除解锁，但评测器误判着地接触，最大跟踪误差约 1.21 m；该轮不标记通过，原报告保留在 `98361a80b65d4588a942042569c1b062/`。短程航点按配置停稳后返程；长树林任务仍支持 `pass` 连续推进。连续故障测试另修复了评测器读到上一轮失败状态的竞态，必须确认新任务已启动再判断结果。

本轮没有调整 PX4 控制增益或动力学，没有重飞 Gazebo、执行付费 API 或上板。树林 8 m/s 完整路线、独立悬空障碍任务、多轮成功率、状态停流/估计器复位/桥进程退出专项、实机和板端仍未验证。

2026-10-14 收尾时切回默认低速配置，静止链路与重复 up 已通过，PX4 Disarmed/Hold，当时 AirSim、两个 Docker 和 RViz 保留待命；运行目录 `a662dfefb6bf41faa9d8bea09b799f7e/`。历史报告仍保留各自任务配置与实例，不混写为同一轮。

## 每轮飞行复盘（PC）

后续 task/fault 无论成功或失败都会调用 `review_flight.py`，在原报告旁写入 `.review.json`、`.review.txt`，安装绘图依赖时另有 `.review.png`。原始飞行报告/ULog 不改写，复盘失败不会覆盖飞行成败。完整复盘使用可选依赖：

```bash
# PC，仓库根目录；首次安装属于课前准备。此命令会实际起飞。
uv run --extra flight-review stage3/super/airsim/runtime.py task

# PC，只读复盘已有报告，不启动/停止仿真或修改参数。
uv run --extra flight-review stage3/super/airsim/review_flight.py \
  artifacts/airsim-runtime/420d571d985b4a2a985025a30d0fbdb5/fly-task-1792029999298257137.json
```

未装可选依赖时自动输出基础 ROS 复盘，并明确标记缺失的内环证据。ULog 默认在同一运行目录中按 tracking 时间窗口匹配，也可 `--ulog /path/to/file.ulg`；活跃日志只解析打开时已有的文件前缀。新报告分别记录 SUPER 规划参考、适配器实际下发参考的 XYZ 位置/速度/加速度、仿真时间戳和接收时刻；按 PX4 测量时间插值匹配，禁止跨失流区间外推。旧报告中的 `tracking_error_m` 是最近收到的规划参考与位置之差，不直接当作严格时间对齐的飞控误差。

复盘顺序固定为：

1. **配置与任务阶段**：保存本轮任务快照、ULog 参数及窗口内变更；分开起飞/跟踪/悬停/降落，控制指标仅统计碰撞前 tracking。失败后明确记录是否确认解除解锁，未确认不能写“安全降落”。
2. **参考和通信时序**：检查 p/v 一致性、加速度/jerk、规划与下发参考间隔、消息年龄、仿真倍率。ULog 的记录频率不等于 Offboard 实际发送频率。
3. **估计与地图**：核对 PX4 创新检验比、位置/高度/航向复位；报告没有独立场景真值或障碍净空时，不声称排除定位/感知误差。
4. **由外到内定位问题**：外部位置参考→实际位置，PX4 内部速度目标→速度，姿态目标→姿态，角速度目标→角速度；分别输出 RMS/P95/最大值。速度延迟扫描是响应匹配，不是网络延迟测量。
5. **执行余量与模型**：看倾角目标是否贴限、电机输出和分配器未实现推力/力矩标志。电机接近 1 不单独证明物理饱和，分配器报告可实现也不证明真实电机/机体模型完全匹配。

下一次先固定同一路线、出生点、航点 stop/pass 策略、资源预算和参数快照；按证据决定先排查时间/坐标/电机映射/模型，还是由角速度环→姿态环→速度/位置环逐步调参。每轮只变一个因素，报告保留变化与结果；不同路线的 1 m/s 与 8 m/s 记录只是诊断参照，不能作为公平性能对比。

2026-10-15 已只读回顾现有 8 m/s 碰撞日志和历史 1 m/s 树林日志：8 m/s 碰撞前对齐位置最大误差约 2.776 m、姿态误差 P95 30.12°、角速度误差 P95 0.896 rad/s，速度响应最佳匹配延迟约 0.42 s；分配器未实现推力/力矩标志占比均为 0。历史 1 m/s 的姿态误差 P95 约 0.73°。这些证据支持优先检查大动态下内环响应、轨迹需求和模型匹配，不足以直接确定 PID 根因。原 ULog 外部参考约 0.2 s 记录一次，细节与规划/实际发送时序仍待新记录补足。两份 `.review.*` 与原报告同目录；本轮未飞行、未调参，自动挂接通过离线测试，尚未以新的一轮飞行验收。

## 独立 PX4 控制测试入口

以下为保留的独立 PX4 控制测试，显式选择配置 `runtime.example.json`，不运行 SUPER/ROS/雷达；与上面的 SUPER 模式互斥。

### 教师准备与场景配置

PC Linux 需要可用的 Docker、图形桌面/Vulkan，以及完整的 AirSim 场景包。本机 AirSim 源码使用 `~/AirSim`，默认使用 **AirSimNH**，场景 ELF 由仓库根目录 `.env` 的 `AIRSIM_NH` 指定（配置见[根 README](../../../../README.md#pc-airsim-场景路径)）。2026-10-14 已确认本机源码、场景启动脚本、x86-64 ELF 与资源目录存在；脚本使用项目参数 `AirSimNH`，入口直接执行 `AirSimNH/Binaries/Linux/AirSimNH`。实际启动与飞行结果见上面的合并验证和下文独立控制证据。源码目录本身不能作为打包场景启动。镜像保留历史已验收 ID，当前 PC 使用前仍需核实该镜像存在，无需为路径调整重建镜像。

常规 up/status/task/down 使用 `uv run`，MessagePack 已纳入项目依赖。下面的临时环境仅供包含 pymavlink 的诊断入口使用。

**PC，课前准备诊断环境：**

```bash
uv venv /tmp/airsim-diagnostics-venv
uv pip install --python /tmp/airsim-diagnostics-venv/bin/python msgpack==1.2.3 pymavlink==2.4.50
```

独立控制测试需显式选择 `stage3/super/airsim/runtime.example.json`；不带配置的 up 默认选择 forest10。换场景时提供自己的 JSON，并通过 `--config` 指定；路径支持 `~` 展开为当前用户主目录，相对路径以配置文件所在目录为基准，`binary` 例外，以 `scene_dir` 为基准：

| 配置 | 用途 |
| --- | --- |
| scene_dir | 完整打包场景目录，资源由宿主机直接读取，不复制到 Docker |
| binary | Linux 原生场景可执行文件；不用带额外 -settings 的 .sh 包装器 |
| scene_args | 场景所需参数，包括项目名、小窗口和 Vulkan；不传 -settings，由入口只生成一个 |
| settings | 输入 AirSim 配置；原文件不改写，入口为本次运行生成一份设置 |
| image / container | 原 PX4 镜像及专用容器名；可调整，换镜像后须重新验收 |
| task | PX4 估计 NED 坐标、米、m/s；起点 `(0,0,-3)`，终点 `(1,0,-3)`，速度 0.5 m/s，悬停 3 秒，误差容限 0.6 m |

默认窗口为 1280×720，由 `scene_args` 中的 `-ResX=1280`、`-ResY=720` 显式指定。删除分辨率参数不会自动放大：Unreal 会沿用场景 `Saved/Config/LinuxNoEditor/GameUserSettings.ini` 保存的窗口尺寸（例如之前的 640×360）。调整尺寸后 down/up；如需全屏，将 `-windowed` 换为 `-fullscreen`。

本入口当前固定单机 `PX4`、host 网络和本机回环：TCP 4560，RPC 41451，控制 UDP 14540/14580。它会规范这些连接字段，但保留输入 settings 的传感器及 ViewMode。默认 FlyWithMe 显示场景并跟随飞机；需要减少画面负载时可将输入设置的 ViewMode 改为 NoDisplay，再 down/up。NoDisplay 会冻结主画面，物理仿真和通信继续运行。

场景已打包进二进制及资源文件，换地图需提供对应完整场景包，不是只替换一个 Gazebo SDF 文件。换机器/场景需重新确认出生点、障碍和资源预算，不能照搬本机路线。下文 AbandonedPark 的记录仅为历史证据，不能作为 AirSimNH 的验收结果。

### 启动、执行与停止

**PC 图形桌面终端，仓库根目录：**

```bash
uv run stage3/super/airsim/runtime.py up
uv run stage3/super/airsim/runtime.py status
uv run stage3/super/airsim/runtime.py task
uv run stage3/super/airsim/runtime.py down
```

`up` 先启动宿主机 AirSim，检查属于该进程的 TCP 4560 监听，再启动 PX4。检查监听时不建立测试 TCP 连接，以免消耗 AirSim 的 accept。PX4 仍基于原镜像，挂载只读 `px4_start.sh` 与专用可写日志目录；启动 none_iris 和 simulator_mavlink，不启动 Gazebo。连续 IMU、有效位置、飞控健康以及 AirSim API 均通过后才报告就绪，默认总超时 180 秒。AirSimNH 在本机机械盘首次加载曾耗时约 70 秒，窗口出现前需等待场景初始化；以就绪检查而非窗口出现判断连接成功。

`task` 明确执行解锁与飞行：起飞 → 起点悬停 → 终点悬停 → 返回起点悬停 → 降落解除解锁。每次运动重新申请 API 控制，每个航段有超时，并在悬停后检查实际估计位置误差；API 返回 true 不等于精确到点。异常或 Ctrl+C 会尝试取消任务并降落，参数按任务前快照恢复。通信完全丢失时降落请求不保证送达；相关失败写入报告。

独立发送降落请求：

```bash
uv run stage3/super/airsim/runtime.py land
```

每条命令可带 `--config /path/to/runtime.json`（仅 up 使用）及 `--state-dir /path/to/state`。默认状态和日志在被 Git 忽略的 `artifacts/airsim-runtime/`。task 使用当前启动时保存的配置；修改场景、任务或设置后先 down，再用新配置 up。

up 可用 `--image` 覆盖配置镜像。旧 `run_px4.sh` 已委托同一 up 实现，不再单独启动 PX4；它支持 `AIRSIM_PYTHON` 指定上述 Python 环境，并保留 `AIRSIM_PX4_IMAGE` 镜像覆盖变量。

重复 up 会检查同一配置的现有实例并复用；配置改变或状态异常时保留现场，不覆盖已有记录。down 确认 PX4 未解锁后停止两边，仅操作本入口的 PID/start time/二进制/设置路径和带唯一标签的容器 ID；日志保留。任务与普通生命周期命令互斥；status/land/stop/down --force 不受任务锁阻塞，task 中也可用 Ctrl+C 请求降落。无法确认状态时，可显式 `down --force` 停止本入口拥有的仿真实例，不处理未知进程或容器。

### 成功判据、故障恢复与证据

2026-10-14 本机 AirSimNH 启动复验：`up` 通过 AirSim 监听、连续传感器、有效定位、健康状态与 RPC 检查；随后切换 FlyWithMe 并重启，双方再次就绪。证据目录 `artifacts/airsim-runtime/8fd5ed6d91e140038888e6a5af738931/`。本轮未起飞，不能作为 AirSimNH 往返任务验收。

- 成功：up 输出“AirSim 已监听”再输出“已就绪”；status 为双方运行、Disarmed/Hold；task 输出三个到点误差、任务通过和报告路径；最后降落解除解锁。
- TCP 端口检查尝试 SO_REUSEADDR 和 listen；若仍不可绑定，读取本网络命名空间 IPv4/IPv6 的 TCP 状态。仅有 TIME_WAIT 时明确提示并自动等待释放（每端口最多 75 秒，不计入后续场景启动超时），不用反复手动 up；真实监听或其他活动连接仍报占用，权限/网络错误保留原始原因。不修改系统 TCP 参数。旧场景未启用地址复用时，SO_REUSEADDR 本身不能保证绕过 TIME_WAIT。
- 端口或同名容器冲突：先用 `ss -ltnp`、`ss -lunp`、`docker ps -a` 确认已有实例用途。入口不会接管手动启动的 AirSim/PX4；先自行停止确认属于本任务的旧实例。
- 场景启动失败：查看本次 `airsim-console.log`；PX4 无传感器/定位不健康：查看 `px4-console.log` 与 `px4-logs/`。启动失败会清理本次创建的两边并保留记录；不关闭健康检查强行通过。
- 场景或 PX4 单独退出：不承诺自动重连，用 status 保留诊断，再 down/up 重建整对实例。
- down 报未解除解锁：先 land。Docker 不可访问、RPC 失联或无法验证进程身份时保留现场，不默认停止未知资源。

2026-10-14 实测统一入口：正常 up、重复 up 复用、往返 task、正常 down 均通过。3 m 高度、1 m 往返，起点/终点/返回点悬停后估计误差分别 0.171 / 0.139 / 0.252 m，passed=true，最终 Disarmed/Hold。证据 `artifacts/airsim-runtime/61b56b62d2c2433bb2d142306b37a760/task-1791965781267682773.json`，同目录保留 AirSim/PX4 日志及 ULog。

生命周期实测：用 /tmp 原生测试进程分别模拟 AirSim 不监听和已监听但不发送 HIL 传感器，两种启动超时都清理自有 PID/容器，phase=stopped，日志保留；未带标签的同名测试容器被拒绝接管且 ID 不变；管理锁冲突拒绝 down；实际仿真地面解锁后 down 被拒绝，随后 land 恢复解除解锁，未发起飞命令。故障证据位于 `/tmp/airsim-failure-no-listen/`、`/tmp/airsim-failure-listen/`。未验收飞行中断连或 task 的 Ctrl+C 故障降落分支。


## 本轮问题分级与边界

### 本机 AirSimNH：PX4 主线验收与合并接口（2026-10-14）

本轮固定 AirSimNH 场景、本机 PX4 镜像 ID、单机 `PX4`、FlyWithMe、1280×720。AirSim 源码参考来自 `~/AirSim`，打包场景位于 `/mnt/disk1/wqy/Airsim-Scene/AirSimNH/LinuxNoEditor`；未重编场景，源码检出版本不代表打包二进制版本。PX4 为 1.18 beta，提交 `61907962c9220437ec01a98fa26bfbf5cbb254b5`。

首轮证据目录：`artifacts/airsim-runtime/09418f7beafa4afdac986c33a428404a/`；最终复验目录：`artifacts/airsim-runtime/bab271d4f8dc4c5c82cf18be3488147f/`。仅保留本机，不提交日志。

| 验证 | 实际结果与证据 |
| --- | --- |
| 飞控传感器 | `sensors/summary.json`：加速度、角速度、气压、磁场、GPS、本地位置各 120 帧，时间戳持续递增；发布率依次为 333.33、333.33、333.33、333.33、47.62、111.11 Hz（仿真时间）。气压与磁场仍有重复值，不等于独立测量率 |
| RPC 短距离往返 | `task-1791973127711465849.json`：3 m 高度、0.5 m/s、1 m 往返通过；三个悬停点误差 0.130 / 0.129 / 0.178 m，最终落地解除解锁 |
| 原生 PX4 Offboard XYZ | `offboard-1791973312633244592.json`：2 m 起飞，12 秒水平 X/Y 各 1 m、上升 0.5 m 的平滑往返；50 Hz 目标发送，三轴位置、速度、加速度同时有效；跟踪 RMSE 0.065 m，最大 0.136 m，返回误差 0.053 m |
| Offboard 设定值停流 | 同一报告：保留 MAVLink 心跳与遥测，仅停设定值，约 1.52 秒墙钟后进入 LAND；不补发降落命令，实际落地、解除解锁，随后恢复 Hold |
| 最终版本复验 | 最终目录 `offboard-1791973699403191584.json`：复用默认 payload 链路，XYZ RMSE 0.094 m、最大误差 0.182 m、返回误差 0.073 m，停流 1.22 秒后 LAND，实际落地解除解锁且清理后 ready=true；`sensors/` 的六类传感器均重新采满 120 帧 |

首轮 Offboard 报告 `offboard-1791973238871991700.json` 的 XYZ 已通过，但脚本将 pymavlink 的 `LAND` 名称误认为应该是 `AUTO.LAND`，故报告失败；最终报告已用修正后的脚本重新实际飞行通过。另一个 `offboard-1791973222006177908.json` 是诊断端口冲突，在解锁前退出。保留失败记录，不改写为成功。

后续同一会话从独立 Offboard 切回 RPC 时，两次起飞命令均 accepted 但未离地并自动解除解锁，证据为 `rpc-controls.json` 和 `task-1791973489017348174.json`；不得忽略该失败。旧验证器动态停止自建 MAVLink 实例后曾出现 trajectory_setpoint 更新计数存在、listener 却报未发布的异常，根因未确认。当前验证器已改为复用默认 payload 链路；最终实例在 Offboard 后立即执行 `verify_flight.py`，实际完成起飞、悬停、1 m 位置目标、−0.25 m/s 速度、10°/s×2 s 偏航、返回与降落，`rpc-controls.json` 的 error=null，偏航变化 19.79°。`final-px4-check.json` 确认 Disarmed/Hold、无 failsafe、健康检查 OK、参数恢复及 trajectory_setpoint 正常发布。修正版已通过一次顺序切换；旧版失效的精确根因未确认，不把这次规避写成上游问题已修复。

**PC，双方已通过 up 就绪，使用上文准备的诊断 Python 环境：**

```bash
/tmp/airsim-diagnostics-venv/bin/python stage3/super/airsim/verify_offboard.py --run
```

该入口独立于 ROS，使用 MAVLink `SET_POSITION_TARGET_LOCAL_NED`，位置/速度/加速度/yaw 有效，忽略 yaw rate；以 PX4 的 `LOCAL_POSITION_NED` 作为反馈，不向控制输入场景真值。XYZ 轨迹来自固定余弦函数，位置、速度、加速度数值导数一致；这是控制接口测试，不是 SUPER 规划轨迹或避障结果。通过阈值为最大跟踪误差≤0.8 m、返回误差≤0.3 m，报告另保留逐帧状态与实际误差。最终默认链路 XYZ 段的 118 条记录中有 45 个不同的 PX4 位置时间戳，最大接收年龄 0.265 秒；它证明低速设定值执行，不代表高速轨迹跟踪或高频 DDS 反馈已验收。

测试持有 runtime 管理锁，需要已落地未解锁；复用本入口 PX4 默认 payload 链路（PC UDP 14030 ↔ PX4 UDP 14280），拒绝端口已有客户端，退出只关闭自己的 PC socket，不创建/停止飞控 MAVLink 实例。默认 XYZ 模式不改遥测发布率；圆周速度档临时调整该链路的遥测流并恢复。报告同时记录 PX4 测量时间戳与墙钟接收新鲜度，50 Hz 指墙钟目标发送率，不代表反馈采样率。不要同时运行其他控制器。测试临时设置 `COM_RC_IN_MODE=4`、`COM_OF_LOSS_T=0.5`、`COM_OBL_RC_ACT=4`，结束恢复原值（本轮快照分别为 1 / 1 / 0，已核对恢复）。**失流降落结果只适用于这些测试参数**，不代表默认 AirSim runtime 已采用 Gazebo 的失流策略。异常尝试降落并恢复参数；通信完全丢失不保证降落请求送达。默认 XYZ 保持 4 m 水平/5 m 高度范围，圆周档范围见下节；不绕过解锁健康检查；不适用于真实设备。

以下接口表保留合并前独立 PX4 测试的证据边界；感知、时钟、DDS 与 SUPER 现已按本页顶部合并入口接入，不能再用表中旧的 disconnected 状态描述当前实例。

| 合并项 | 现有 Gazebo/SUPER 约定 | AirSim 接入要求与本轮边界 |
| --- | --- | --- |
| 飞控执行 | `super_px4.py` 将 `/planning/pos_cmd` 的 ENU XYZ 位置/速度/加速度转换为 NED，经 DDS 发送给 PX4 | 本轮以 MAVLink 证明 PX4 能在 AirSim 动力学下执行同类设定值；DDS 传输、消息版本、更新率仍需独立验收，不把 RPC moveToPosition 代替连续轨迹执行 |
| 定位与原点 | 默认 PX4/GNSS；世界 ENU，机体 FLU，飞控 NED/FRD；位置/速度转换为 `(y,x,-z)`，位置叠加局部原点 | 用 PX4 估计定位，不用 AirSim 真值反馈；AirSim 出生点和 PX4 原点不同，不照搬走廊 `.25 m` 地面偏置、1.95 m 起飞层及走廊边界 |
| 感知与地图 | `/cloud_registered` 为 world 点云；`/lidar_slam/odom` 为 world 定位；ROG-Map 积累并膨胀障碍 | 他人提供 AirSim 传感器/ROS 适配后，先核对采样时刻、雷达外参、机体/世界轴向与点云可用性，再接地图。默认 settings 未配置 LiDAR，不能宣称已有避障输入 |
| 时钟与消息 | 单机 `uav1`，ROS 域 10，PX4 XRCE Agent 8888；状态和点云新鲜度/复位受检查 | 本轮 XRCE client 为 disconnected，未验证 DDS。合并时确认域、px4_msgs 版本后缀及同源仿真时间；不能混用墙钟、AirSim 纳秒和 PX4 微秒时间戳 |
| 失流与控制权 | 50 Hz 飞控设定值，规划/状态/雷达超时处理；Gazebo 启动脚本明确配置失流降落 | 本轮仅覆盖设定值停流；规划失流、点云失流、状态/时钟停流、估计器复位及桥进程退出需在合并后注入验证；RPC 控制与 SUPER 控制不能同时持有执行权 |
| 避障复现 | Gazebo 的固定走廊、障碍、速度档及评价条件已有证据 | AirSimNH 不是同一赛道，先建立可重复的出生点、障碍任务和碰撞评测，再验收 2 m/s 避障；不能把本轮短距离低速结果写成 SUPER 避障复现或跨场景公平对比 |

合并顺序：先静止核对 PX4 估计定位与点云/时钟 → 在 ROS/DDS 链路复验同样低速 XYZ → 检查 ROG 占据及膨胀地图 → 接 SUPER 完成低速单障碍去回 → 再按固定场景、参数和资源预算评测速度档与失败率。雷达/LIO、SUPER 实际避障、多轮成功率和实机/板端均不在本轮已完成范围内。

### 本机圆周速度档：1 m/s 通过，2 m/s 紧弯未通过（2026-10-14）

本轮不改仿真机型或控制增益，不放宽 PX4 的速度/加速度/倾角设置。读取到 `MPC_XY_VEL_MAX=12 m/s`、`MPC_ACC_HOR_MAX=5 m/s²`、`MPC_TILTMAX_AIR=45°`。这些参数不是对实际运动速度/加速度的统一硬裁剪：速度反馈会有超调；各加速度参数作用于特定飞行模式或轨迹生成环节，不能假定会替外部轨迹做全部约束。Offboard 的速度、加速度与位置一起输入时是控制器前馈，外部仍需生成一致、可执行的参考。参见 [PX4 Offboard 说明](https://docs.px4.io/main/en/flight_modes/offboard#copter) 和 [参数参考](https://docs.px4.io/main/en/advanced_config/parameter_reference#MPC_XY_VEL_MAX)。

实际响应还受 AirSim 机体质量、惯量、电机响应、阻力及 PX4 控制增益共同影响；本轮没有把 AirSim 参数与 Gazebo x500 对齐。参考速度档不能写成实际全程严格限速，模型中的物理能力也不会因提高 PX4 上限自动提升。

**PC，已 up 就绪并确认当前落地点附近空域：**

```bash
/tmp/airsim-diagnostics-venv/bin/python stage3/super/airsim/verify_offboard.py --run --speed 1
# 第一档通过且空域仍适用，再单独执行第二档：
/tmp/airsim-diagnostics-venv/bin/python stage3/super/airsim/verify_offboard.py --run --speed 2
```

速度档使用 2 m 高度、2 m 半径、两圈水平圆周，3 秒平滑加减速，默认圆心在起点 NED 方位 180°；整条路径最大离起点 4 m，诊断包络为水平 6 m / 高度 5 m。该包络是为新圆周轨迹预先设置的范围，不是失败后放宽门限。持续实时检查跟踪误差 0.8 m 门限，返回误差需≤0.3 m，实测峰值需达到参考档位的 80%，失败停止升档并尝试降落。降落期间继续记录包络越界，不能因越界中断降落等待。轨迹执行前后查询碰撞时间戳用于评测，不把场景位姿或碰撞真值反馈给控制。深度预检是离线选空域，不是在线避障。

最终轨迹以 PX4 LOCAL_POSITION_NED 时间戳和估计实时率推进，误差参考与 PX4 测量时间对齐，不把旧测量直接与最新设定值比较。为减少遥测限流，临时停用 payload 链路上的 GPS_RAW_INT/HIGHRES_IMU 消息，位置消息请求 50 Hz；这不停止进入 PX4 的 GPS/IMU 传感器。退出逐项核对恢复的周期。本机 PX4 对 GPS_RAW_INT 的查询返回 −1 表示默认事件驱动，而设置命令的 −1 表示停流；已通过设置 0 恢复默认并核对实收消息，不能原样回写该负值。

| 最终实测 | 参考 / 实测峰值 | 结果 |
| --- | --- | --- |
| 1 m/s 两圈 | 1.00 / 1.31 m/s | passed=true，RMSE 0.266 m、最大误差 0.429 m、返回误差 0.049 m；无新轨迹碰撞，自动落地解除解锁，参数/消息周期恢复、健康检查通过 |
| 2 m/s 紧弯 | 2.00 / 约 2.45 m/s | 轨迹开始约 3.6 秒后，逐控制周期检查触发误差>0.8 m；中止并实际落地解除解锁。没有完成两圈，不计通过 |
| 3 m/s | 未执行 | 第二档未通过，停止升档；不能宣称已验证 |

最终证据在 `artifacts/airsim-runtime/bab271d4f8dc4c5c82cf18be3488147f/`：`offboard-1791974718271125294.json`（1 档）、`offboard-1791974816172130703.json`（2 档）、`speed-summary.json`（派生汇总），空域深度检查在 `speed-survey*/`。2 档常规日志约 10 Hz，触发门限按每次设定值循环检查，常规采样的最大值可能低于触发瞬间；当前脚本已补充单独记录触发事件，既有历史报告不改写。

保留开发轮次：`offboard-1791974427291134255.json` 为首轮 1 档，飞行完成但 GPS 消息恢复校验失败，随后地面恢复并复验；`offboard-1791974576888940055.json` 为首轮 2 档误差中止，降落监测又因包络抛错，随后统一 land 入口确认落地。后续已修复恢复语义和降落等待，并按仿真时间/测量时间对齐重跑。复查完整窗口实时率约 1，时间对齐修正并未消除 2 档误差，因此不能把失败归因于实时率不同。

当前结论只适用于这条半径 2 m 的紧弯：2 m/s 时向心加速度为 2 m/s²，是 1 m/s 时的四倍。已经实际飞到约 2.45 m/s，但轨迹跟踪尚未验收；既不能称为“PX4 限速到 1 m/s”，也不能推断所有 2 m/s 直线任务失败。控制参数、动力学匹配、采样/执行时序的影响仍需隔离，下一步可固定轨迹分别测试直线启停和较大半径转弯，再决定是否调参。未复现 SUPER 避障。

本轮按用户约定暂不继续动力学与控制调参，先提交当前工作。Python 语法、10 项 AirSim 单元检查和 diff 空白检查通过；最终重建场景恢复出生点待用，`artifacts/airsim-runtime/0cd8b14a890d4fb2a1893cb42fabe7b3/speed-test-standby.json` 记录未解锁、Hold、无 failsafe、健康检查 OK。这些检查不替代尚未通过的高速轨迹或 SUPER 避障验收。

### 当前采用的处理结论

- 悬停后控制请求丢失：作为使用注意事项处理，每次 move/rotate 前重新调用 `enableApiControl(true)`；不以 `isApiControlEnabled()` 为唯一判断依据，现有飞行脚本已执行该约定。
- 初始化 `Unsupported main mode`：用户确认接受为当前 SITL 的已知非阻塞警告。PX4 拒绝这条不完整命令，AirSim 不等待 ACK、继续初始化；现有传感器和基础起降链已实际通过。因此保留原二进制与当前 PX4，不手动设置 HIL、不改 SYS_HITL，不以消除该警告作为验收条件。该处理只适用于当前已验证的 SITL 组合，不能推广为硬件 HITL 配置方法；其他新的控制失败或健康检查失败仍应单独排查。

后文保留根因、源码适配方向和证据，作为维护参考，不代表当前方案要求修改或重编 AirSim。

### 一级：接口、版本兼容及进入 PX4 的传感器

首先区分两条接口：AirSim 仿真桥向 PX4 提供传感器数据、接收执行器输出；AirSim 控制 API 则通过 MAVLink 向 PX4 发出飞行指令。基础起飞成功只能证明部分链路可用，不代表所有控制 API 与当前 PX4 版本兼容。

- `moveToPosition` 首轮 RPC 非标准异常：一级待查。后续成功不能作为已修复证据；需核查具体异常、模式切换、参数交互和重复性，确定是否为下载包控制 API 与 PX4 1.18 beta 的兼容问题。
- `command 520 unsupported`、`Unsupported main mode`：一级待查，核对发送方、指令含义及当前 PX4 的响应，判断必要握手或控制功能是否受影响。
- IMU（加速度计、陀螺仪）、气压计、磁力计以及仿真 GPS：本配置的飞控传感器链，按一级核查消息解析、单位/轴向、频率、时间戳、延迟、有效标志和 EKF 融合。GPS 的全球坐标是 PX4 定位输入，不与场景真值查询混为一谈。
- 执行器反馈：一级核查输出消息、通道/旋向、归一化及时间闭环。已完成基础起降，但完整电机映射与长期 lockstep 兼容性未验收。
- 着陆高度偏移、飞控位置/姿态重置：先检查传感器输入、时间和融合是否正确。若确定为控制调参或正常估计收敛，再归二级；不能先把可能的接口问题当作普通调参。
- 悬停摆动与制动超调：归因待定，先排除接口/单位/时序问题，再考虑动力学与调参，不直接认定为版本问题。

### 二级：正常使用中需要避免的操作问题

- 同时传两份 `-settings=`，实际加载第一份配置；直接调用二进制只传一份配置。
- AirSim 重启后 PX4 残留 CLOSE-WAIT；当前恢复方法为重启本任务 PX4 容器，自动重连未验证。
- 释放 AirSim API 控制后转入 Position，无遥控器时再次解锁被拒；恢复 Hold 并重新检查健康状态，不绕过检查。
- 位置 API 修改速度参数，失败或恢复顺序可能留下限制；检查并先恢复最大速度，再恢复巡航/手动速度。如果进一步确认属于版本不兼容导致的异常，根因提升到一级，恢复步骤仍保留在二级。
- logger 订阅数量警告影响诊断记录完整性，后续需要确认关键飞控话题是否被记录。
- `NoDisplay` 冻结主画面，不用黑屏或刷新情况判断仿真连接是否成功。

### 本轮不关注：不经过 PX4 的数据接口

相机、深度、雷达及 AirSim 场景全局真值/地面真值 API，不属于本轮 PX4 接入验收。真值可以辅助离线评测，不能馈入控制，也不验收其对算力板的接口。AirSim API 中异常的估计角加速度字段暂不用于评测；除非有证据显示其源头影响进入 PX4 的 IMU 消息，否则本轮不扩展排查该 API 字段。

## 一级问题排查结果（2026-10-14）

以下实测更新前述待查项，适用于当前下载场景包与镜像，不能推广到其他 AirSim/PX4 版本。

### 控制接口

1. **悬停之后位置 API 异常：根因已在下载二进制中定位。** 未解锁状态下做四次对照，`enableApiControl(true) → hover → moveToPosition` 两次均抛同样的 RPC 非标准异常；在 hover 后再次 `enableApiControl(true)` 两次均能执行到位置等待并因未解锁、不能到达目标而返回 false。两组的 `isApiControlEnabled()` 都报告 true。进一步用 GDB 捕获实际运行二进制：`checkOffboard()` 入口的 `control_requested_=0`、offboard=0；执行到抛异常分支的真实错误文本是 `You must call requestControl first.`，调用栈为 RPC → moveToPosition → moveToLocalPosition → checkOffboard。没有进入 PX4 对位置指令的拒绝路径，不能归因为 PX4 1.18 不支持位置控制。
2. **旧能力查询命令不兼容：已确认。** 独立诊断 MAVLink 链路实测命令 520 返回 ACK result=3（UNSUPPORTED）；命令 512、param1=148 返回 AUTOPILOT_VERSION（capabilities=59647）及 ACK result=0（ACCEPTED）。AirSim 检出源码仍使用 520。需要修改 AirSim 桥源码时，应把能力查询迁移为 REQUEST_MESSAGE/AUTOPILOT_VERSION，并只在收到对应消息后完成查询。本轮没有重编下载场景包，也没有证据证明 520 是位置异常的直接原因。
3. **启动的 Unsupported main mode：根因已由真实发送路径确认。** 按原低负载参数重启场景，在下载二进制 sendCommand 完成 pack 后捕获 command=176、param1=61、param2=0、param3=0，调用栈明确来自 `setHILMode → processMavMessages`；解除断点后双方日志出现 Unsupported main mode。base=61 含 CUSTOM_MODE_ENABLED 和 HIL_ENABLED，却没有提供有效的 custom main mode。对照精确 PX4 1.18 提交与 v1.11.3 官方 Commander 源码：旧版没有未知 custom main mode 的拒绝分支，保留 TRANSITION_NOT_CHANGED 并接受；当前版本明确拒绝并报警。因此属于旧 AirSim 启动命令构造缺陷被新版严格检查显露出来，而非正常位置/速度控制模式编号不一致。SITL 仿真桥已工作且 PX4 hil_state=0，不应为消除警告盲目启用 HITL。后续修桥需区分 SITL/HITL；若确需 DO_SET_MODE，应提供完整、有效的当前 main/sub mode。

**位置异常的完整状态链：** `hover → loiter → setMode(AUTO, LOITER)` 会清除 MavLinkVehicleImpl 的内部控制请求。原本运动任务的 SingleTaskCall 应通过 beforeTask/startOffboardMode 重新申请控制，但 SingleCall 构造函数先在根调用中执行 CancelToken.reset()，而 reset 将 recursion_count 从 1 清成 0；SingleTaskCall 随后按 count==1 判断根任务，跳过 beforeTask。实际二进制反汇编与运行断点均验证这一点：moveToPosition 的任务初始化后 recursion_count=0，随后 checkOffboard 的控制请求也为 0。外层 is_api_control_enabled_ 没有同步清除，所以 API 报告 true 仍会失败。

这是 AirSim 的锁/任务生命周期与控制状态管理缺陷。源码修复方向是把取消/完成标志的重置与锁递归计数维护分开，在持锁期间保持计数，让根任务的 beforeTask/afterTask 正常执行；再同步或明确外层 API 标志的语义。现有二进制的运行规避仍是每次 move/rotate 前显式 enableApiControl(true)。本轮没有修改或重编上游源码、没有修补运行二进制；RPC 把实际异常包装成“非 std::exception”的进一步原因未确认，不影响已定位的控制失败触发点。

根因证据：`/tmp/airsim-task-rootcause-gdb.txt`（计数与异常调用栈）、`/tmp/airsim-rootcause-gdb.txt`、`/tmp/airsim-mode-startup-capture.txt`（启动命令参数、真实调用栈与警告）。二进制调试符号指向 2022 年构建的场景包，检查使用随包的 AbandonedPark.debug；地址仅适用于本下载产物。用于对照的官方源码是 PX4 `61907962c9220437ec01a98fa26bfbf5cbb254b5` 与 `v1.11.3`，不是仅凭当前 AirSim 检出源码推断。

诊断中重启 PX4 后 AirSim 未自动重连，正常退出请求也未完成；已结束该唯一且未解锁的旧场景进程，按原设置重启并捕获启动路径。调试器均已解除附加并退出，双方恢复常驻，最终 Disarmed、Hold、健康检查 OK、速度参数为机型默认值；本次深查没有起飞。

### setHILMode 的目的与版本迁移

`setHILMode` 的原意是告诉外部飞控使用仿真传感器/执行器链，设置 MAV_MODE_FLAG_HIL_ENABLED；它不是 Hold、Offboard 或起飞模式。AirSim 将同一辅助行为用于 PX4 连接初始化，但本课程是 PC 上的 SITL，不是实体飞控 HITL。

| 已核对源码 | 不完整 DO_SET_MODE（custom main=0） | 真正 HIL 状态启用方式 |
| --- | --- | --- |
| v1.11.3、v1.12.3、v1.13.3、v1.14.4、v1.15.4、v1.16.0、v1.17.0 | 未知 custom main 没有显式拒绝分支，保持无模式变化并 ACK accepted；不代表设置 HIL 成功 | Commander 启动时 `-h`；硬件 rcS 根据 SYS_HITL 启动对应仿真链 |
| 本机 1.18 beta 提交 61907962… | 显式拒绝未知 custom main 并报警 Unsupported main mode | 同样在启动时配置；不能靠本条 DO_SET_MODE 开启 HIL |

严格校验的已确认变化范围是 v1.17.0 到本机 1.18 beta 提交之间，尚未定位首次引入该检查的具体提交。不能描述成“1.18 才将 HIL 从命令迁移到参数”：v1.11.3 已有 SYS_HITL → sensors start -h / commander start -h 的启动路径。

当前容器使用 POSIX/SITL rcS，实际 `sensors start`、`commander start` 不带 -h；独立的 simulator_mavlink 模块直接解析 TCP 中的 HIL_SENSOR、HIL_GPS，不以 vehicle_status.hil_state 为接收门槛。普通 MAVLink 接收器的硬件 HIL 分支才有 HIL 状态门槛；两条接收路径不能混淆。因此当前 hil_state=0 与仿真传感器持续进入 PX4 并不矛盾。

**当前操作结论：** 不需要手动设置 HIL，也不设置 SYS_HITL=1。手动切 Hold/Offboard 只改变飞行模式，无法修复 AirSim 初始化指令的缺字段；补足该命令 main/sub mode 只能修正模式报文，也不会替代硬件 HIL 启动配置。将来适配 AirSim 源码时，SITL 路径应跳过这种 HIL 开关请求；硬件 HITL 按 PX4 的 SYS_HITL 与重启流程准备。不要为去掉警告而更换当前已经验收的 SITL 运行路径。

依据：[MAVLink DO_SET_MODE 参数定义](https://mavlink.io/en/messages/common.html#MAV_CMD_DO_SET_MODE)、[PX4 硬件仿真说明](https://docs.px4.io/main/en/simulation/hardware)、官方 [v1.11.3 Commander](https://github.com/PX4/PX4-Autopilot/blob/v1.11.3/src/modules/commander/Commander.cpp)、[v1.17.0 Commander](https://github.com/PX4/PX4-Autopilot/blob/v1.17.0/src/modules/commander/Commander.cpp)、[本机精确提交 Commander](https://github.com/PX4/PX4-Autopilot/blob/61907962c9220437ec01a98fa26bfbf5cbb254b5/src/modules/commander/Commander.cpp)。

**规避后的飞行回归：** `verify_flight.py` 的主体实际完成起飞、悬停、1 m 位置目标、−0.25 m/s 速度指令、10°/s×2 s 偏航、位置返回和降落，报告 error=null。偏航估计从 28.23° 到 47.78°，变化 19.55°；位置 API 在距目标约 0.49 m 时已返回 true，说明成功返回不代表精确到点。证据 `/tmp/airsim-guarded-flight.json`。随后增加了状态停流/非有限值检查、起飞前参数快照与异常清理保护；这些最后的保护分支只做了语法检查，未再次飞行或注入故障验收。

### 进入 PX4 的传感器

静止及低速飞行分别采样各话题 120 帧，六项均持续更新且没有倒退时间戳；这里只覆盖秒级窗口，不代表长时间无失流。

| PX4 话题 | 仿真时间下发布率 | 检查结果 |
| --- | --- | --- |
| sensor_accel / sensor_gyro | 333.33 Hz | 3000～3001 µs 间隔；静止加速度均值约 `(0.0065,−0.0032,−9.8062)` m/s²，角速度近零；PX4 选择对应仿真设备，错误计数与 clipping 均为零 |
| sensor_baro | 333.33 Hz | 原始数值约每 21 ms 变化，重复旧值；静止约 99896 Pa，飞行约 99862 Pa，压力变化方向及约 3 m 高度的量级一致 |
| sensor_mag | 333.33 Hz | 原始向量约每 21 ms 变化，重复旧值；静止均值约 `(0.246,−0.066,0.368)` Gauss，量级正常 |
| vehicle_gps_position | 47.62 Hz | 21000～21001 µs 间隔；3D fix，15 颗卫星，速度有效，默认 GPS 延迟参数为 10 ms |
| vehicle_local_position | 111.11 Hz | 9000～9001 µs 间隔；XY/Z 和速度有效 |

PX4 的 estimator_status_flags 显示 GNSS 位置/速度、气压高度、GNSS 高度、3D 磁力计融合均启用；所观察的磁场、气压和 GNSS fault 标志均为 false。IMU 本轮只核对静止量级及基础运动结果，尚未逐轴动态验证所有旋转和轴向。

**单位与时钟源码核对：** AirSim 的压力由 Pa×0.01 转成 HIL_SENSOR 的 hPa，当前精确 PX4 提交将其×100 恢复为 Pa；没有发现百倍压力单位错误。PX4 使用主 HIL_SENSOR.time_usec 推进仿真时钟。气压计/磁力计重复值获得新的发布和 sample 时间戳，且 AirSim 检出源码每帧标记相关 fields_updated；这意味着发布率不等于独立测量率，对融合噪声/延迟的影响仍未评估，不宣称完整传感器时序验收通过。

静止证据 `/tmp/airsim-sensor-summary.json`、`/tmp/airsim-sensor_*.txt`；飞行采样证据 `/tmp/airsim-dynamic-sensors/summary.json` 及同目录原始文本。未扩展相机、雷达或场景全局位置接口。

### 可复用诊断入口

Python 环境准备统一见上文“教师准备与场景配置”。

**PC 仓库根目录，双方已连接：**

```bash
python3 stage3/super/airsim/inspect_sensors.py
/tmp/airsim-diagnostics-venv/bin/python stage3/super/airsim/probe_protocol.py
```

前者只读 PX4 传感器，保存到 `/tmp/airsim-sensors`；后者仅发送能力查询，使用独立 payload 链路（本地 UDP 14030、PX4 UDP 14280），不得同时运行另一个占用 14030 的客户端。默认传感器采样不足、超时或时间倒退会以非零退出；这不代替数值与融合检查。

**PC 仿真飞行回归：** 仅适用于本入口命名的容器、单机 PX4 和当前已检查的出生点附近空间；不适用于真实设备或未知场景。

```bash
/tmp/airsim-diagnostics-venv/bin/python stage3/super/airsim/verify_flight.py --run
```

需要显式 `--run` 才会解锁；全程使用 PX4 估计 NED、米、m/s，偏航为度。测试含动作超时、运动前重新申请控制、异常后尝试取消任务与降落，确认落地后解除解锁；速度参数按起飞前快照恢复，最大速度先恢复，最后回到 Hold。默认证据 `/tmp/airsim-flight-check.json`，失败退出非零。通信完全丢失时自动降落请求不保证送达，脚本会保留失败报告，不能将其等同于板端或实机故障保护。

## 已验证范围

2026-10-14，本机镜像 `sha256:70584c9eb1e928a9a621b939de0ebab0c91940860fb2f28848bd27f26a0432f4` 包含 `px4-simulator_mavlink` 和 `10016_none_iris`。在无外部网络的一次性容器中以本入口相同的工作目录和机型启动，成功进入 TCP 4560 等待状态；8 秒后主动终止检查。镜像不需要重新编译即可启动该后端。

随后用户启动 AbandonedPark，实际完成静止接入检查：PX4 `ver all` 为 1.18.0 beta、git `61907962c9220437ec01a98fa26bfbf5cbb254b5`。TCP 4560 双端 `ESTAB`；连续 IMU 样本时间递增 3000 µs；连续 GPS 样本更新，3D fix、15 颗卫星；本地位置 XY/Z 及速度有效；执行器输出持续发布且处于未解锁值；`commander check` 返回 `Preflight check: OK`，`commander status` 为 Disarmed、Hold、无 failsafe。一次容器快照 CPU 9.60%、内存 10.37 MiB，仅指 PX4，不含 AirSim。NoDisplay 下仍有连续传感器更新。检查未解锁、未起飞，不能据此认定电机映射或飞行闭环通过。

AirSim 单独重启后旧 PX4 TCP 曾留在 CLOSE-WAIT，重启专用 PX4 容器后恢复；不是版本不兼容的证据。启动日志有 `command 520 unsupported`、`Unsupported main mode` 及 logger 订阅数量警告，未阻止本次静止传感器与定位检查，其原因和影响仍待核查。

下载包内 AirSim 的精确源码版本、电机映射精度、长期 lockstep 稳定性及图形性能尚未验证；基础飞行证据见上文与下节。当前检出的 AirSim 源码仅用于核对配置字段，不能证明下载二进制与其版本一致。

### 最小飞行实测（2026-10-14）

同一镜像、场景和 NoDisplay 配置下，通过 AirSim RPC 的 PX4Multirotor 控制接口发出命令，由 PX4 执行飞控控制；未通过直接设置位姿移动飞机。一次完整序列完成以下动作：

| 动作 | 指令和实测结果 |
| --- | --- |
| 起飞 | `takeoff(25)` 返回 true；PX4 估计 NED Z 从约 −0.014 m 到 −2.707 m，随后悬停约 −2.83～−2.93 m |
| 悬停 | `hover()` 返回 true，多次保持 4 秒；存在厘米至分米级小幅摆动，未做精度验收 |
| 速度控制 | `moveByVelocity(0.25,0,0,3)` 返回 true；估计 X 从 0.005 m 到 0.717 m，制动后在约 0.8～1.0 m 附近悬停 |
| 偏航控制 | `rotateByYawRate(10,2)` 返回 true，之后继续悬停；未记录完整偏航轨迹，不能量化角度跟踪误差 |
| 位置控制 | 以 0.5 m/s 返回 `(0,0,−2.927)`，API 返回 true；返回时 X=0.262 m，随后制动超调到约 −0.259 m，再回到 −0.106 m，不能将 API 返回当成精确到点 |
| 降落 | `land(45)` 返回 true；PX4 日志确认 Landing detected，随后解除解锁，最终 Disarmed、无 failsafe |

该完整序列的临时采样证据位于 PC `/tmp/airsim-flight-third-result.json`，首轮失败证据为 `/tmp/airsim-flight-first-result.json`，不提交运行日志。采样位置和速度来自 PX4 估计，不是场景真值轨迹；另有一次 AirSim 真值查询用于核对飞行状态，未馈入控制。

首轮已完成起飞/悬停，但 `moveToPosition` 抛出 RPC 非标准异常，随即降落。后续在动作前重新申请 API 控制，速度、偏航及位置返回均完成；该首次记录之后已定位根因，见上文“控制接口”；仍不据单次飞行承诺长期稳定性。释放 API 控制会切换至 Position 模式，无遥控器时再次解锁被健康检查拒绝；切回 Hold 后检查恢复 OK，未绕过健康检查。

AirSim 位置 API 会修改 PX4 的速度参数，并可能因异常或参数恢复顺序留下受限值；测试完成后先 reset `MPC_XY_VEL_MAX`，再 reset `MPC_XY_CRUISE` 和 `MPC_VEL_MANUAL`，恢复机型默认值，并切回 Hold。场景碰撞查询记录了降落接地，尚未做逐帧障碍碰撞评测。以上仅证明基础飞行控制链可用，电机映射精度、悬停调参、反复起降、长时间稳定性及更复杂轨迹仍待验证。

## 独立诊断：响应与通信（显式启用）

`diagnostics/` 是独立入口，不修改正常任务、settings、PID 或模型。运行产物都保存在忽略提交的 `artifacts/airsim-diagnostics/<ID>/`。正常入口仍使用原控制器；诊断配置拒绝正常 `task/fault`，正常实例也拒绝被诊断控制器接管。当前固定端口仅支持一个实例，独立测试发现端口占用即退出，不自动关闭现有实例。

### 只读观察正在运行的实例

前置条件：PC 已有本入口管理的 AirSim/PX4/ROS 实例；在 **PC 仓库根目录**执行：

```bash
uv run --extra flight-review stage3/super/airsim/diagnostics/diagnose.py capture --seconds 15 --hil
```

该命令不发布目标、不解锁，飞行中也可单独运行。它观察 `/clock`、规划参考、适配器参考、DDS 输入及里程计，并通过临时最小权限 `NET_RAW` 容器捕获本机 TCP 4560；结束时只删除自己创建的抓包容器。省略 `--hil` 可只记录 ROS。输出 `ros.jsonl`、`hil.pcap`、抓包丢包/CPU 元数据、配置/代码摘要及 `analysis.json`。默认观察正常状态目录；其他实例显式传 `--state-dir`。

成功判据：采集退出 0、manifest 的 completed=true、抓包无丢包，运动期间有足够唯一参考配对。静止没有 adapter/DDS 目标是正常情况，不能把空结果解释为零延迟。观察有开销：本机 8 秒静止样本中 ROS 观察约占单核 9.5%，抓包约占单核 1.4%；对照实验必须保持相同采集方式。

可在 **PC** 带对应 ULog 重新分析：

```bash
uv run --extra flight-review stage3/super/airsim/diagnostics/diagnose.py analyse artifacts/airsim-diagnostics/<ID> --ulog <本轮ULog路径>
```

测量边界：

- ROS 旁路到包时间不是 PX4 收包时间；静止重复目标不猜测匹配，回调先后差允许为负。
- HIL 只配对相同 `time_usec` 的 HIL_SENSOR / HIL_ACTUATOR_CONTROLS，结果含 PX4 运算与调度，是主机墙钟请求到回复耗时，不能称为纯网络延迟。额外报告 TCP 重传、重组缺口、内核丢包及墙钟变化。
- 可选 ULog 以唯一位置目标关联内部位置控制目标，提供源时间戳到目标生成的代理耗时，仍非精确 DDS 接收延迟。
- 回复后的 AirSim 电机和物理应用时间不可由该 PCAP 直接测量。飞行复盘的速度响应延迟也不等于通信延迟。

### 无 SUPER 的固定轨迹响应

前置条件：正常实例已由操作者正常降落、关闭，固定端口空闲，出生点附近 3 m 水平范围无遮挡。以下命令在 **PC 仓库根目录**运行；它们只生成诊断快照，保留源配置。先建立独立实例，不起飞：

```bash
uv run --extra flight-review stage3/super/airsim/diagnostics/diagnose.py response-up --load baseline
```

成功后打印“诊断状态目录”，下文用 `<诊断状态目录>` 代替该完整路径。诊断 Docker 2 只启动 Agent、时钟桥和固定轨迹控制器，不加载 SUPER、雷达桥或正常控制适配器。使用与正常任务相同的 PX4 DDS 全 XYZ 位置/速度/加速度接口和 GNSS 估计，不用真值控制，不更改飞控参数。传感器仍按启动快照在 AirSim 中运行。

明确起飞（**PC**）：

```bash
uv run --extra flight-review stage3/super/airsim/diagnostics/diagnose.py response-run --state-dir <诊断状态目录> --run --hil
```

先建立旁路观察，再起飞至相对 2 m，悬停，两轴各 1 m 平滑往返，再飞窗口化八字并降落。轨迹按仿真时间推进，50 Hz 墙钟控制发送；默认参考速度上限 1.5 m/s、加速度上限 2.5 m/s²。测量时间对齐误差持续超过 0.8 m / 0.25 仿真秒、越界、状态/时钟失流或碰撞则中止降落。请求降落不等于确认落地；成功必须确认解除解锁。初始轨迹定义在 `diagnostics/response_profile.json`，仅在 response-up 时读取。运行期间不自动改档或调参。

结果：独立 runtime 目录内 `response-*.json` 及 `.review.json/.txt/.png`（ULog 数据足够时），旁路数据位于同一诊断 ID 下的 `capture-*`。采集窗口为 120 墙钟秒；仿真过慢或降落超过窗口时，飞行报告继续记录，但旁路不会覆盖尾段，应明确标记。`response-run` 返回前会等待该采集结束。

恢复命令（**PC**，另一终端，同一诊断状态目录）：

```bash
uv run stage3/super/airsim/runtime.py land --state-dir <诊断状态目录>
uv run stage3/super/airsim/runtime.py status --state-dir <诊断状态目录>
uv run stage3/super/airsim/runtime.py down --state-dir <诊断状态目录>
# 失控、碰撞或无法降落：仿真急停，保留证据
uv run stage3/super/airsim/runtime.py stop --state-dir <诊断状态目录>
```

每轮只执行一次固定轨迹；中止后先回收该诊断实例，再重新 response-up。启动/预检失败查看该目录 `startup-inspect.log`、`node-logs/response.log`；抓包失败查看 capture 目录 `hil.stderr.log`，不要通过重启正常实例解决观察工具错误。

负载对照：回收上一轮诊断实例后，分别 `response-up --load render-low`（只覆盖 ViewMode=NoDisplay）、`--load lidar-low`（只将雷达设为 50000 点/秒），再执行相同 response-run。源配置、出生点、轨迹和采集方式保持相同；源配置已是 NoDisplay 时 render-low 没有有效差异，不作为独立对照。这里只比较去掉规划后的 AirSim 负载；完整 SUPER 运行负载仍需用只读 capture 在相同正常任务中对照。先看时序有无缺口，再看 ULog 位置/速度、姿态/角速度与执行器余量，最后才决定调参。

2026-10-15 验证：43 项隔离回归测试通过；当前正常实例未解锁时实际旁路采集成功，最新证据 `artifacts/airsim-diagnostics/5e41f462a10b4b4e914adbc4706e1c2c/analysis.json`，1749 组 HIL 精确配对，P95 0.262 ms，最大 0.551 ms，内核丢包 0。仅为静止样本，不能排除飞行负载瓶颈。独立启动已实测在正常实例占用端口时拒绝，未关闭现有资源；固定轨迹实际飞行尚未验证，不能记作飞行验收通过。

### 四轮实飞诊断（2026-10-15）

在独立临时 Xvfb 显示下，各运行一次相同的低速固定轨迹（两轴 1 m 往返＋八字），均完成降落并确认解除解锁。ULog 核对四轮共 115 项 `MC_*` / `MPC_*` 参数一致。未修改正常 runtime/task/settings 输入；第四轮的定位补偿参数只存在于隔离实例，随容器回收。原先已就绪的 8 m/s 树林实例仅采集静止基线，未再次执行该路线。

| 对照 | AirSim GPS 延迟 | PX4 `SENS_GPS0_DELAY` | 位置误差 P95 / 最大（m） | 姿态误差 P95 |
| --- | --- | --- | --- | --- |
| 原配置，FlyWithMe | 默认 200 ms | 10 ms | 0.389 / 0.463 | 1.62° |
| 只改 NoDisplay | 同上 | 10 ms | 0.404 / 0.470 | 1.71° |
| NoDisplay，只将 GPS UpdateLatency 设为 0 | 0 ms | 10 ms | 0.091 / 0.108 | 1.34° |
| NoDisplay，恢复原 GPS 延迟，只改定位补偿 | 默认 200 ms | 200 ms | 0.123 / 0.149 | 1.46° |

误差为测量时间对齐的 PX4 估计状态对参考，统计 tracking 阶段；不是真值误差，也不代表 8 m/s 树林验收。每条件仅一次，未建立多次成功率。第三轮有一次起飞前气压计自动校准，记录在参数对照证据中；四轮控制参数未变。

关键证据与结论：

- 原延迟下，运行中打包场景 RPC 的 GPS 时间戳比 IMU 旧约 210～228 ms；UpdateLatency=0 后为约 3～18 ms。与本机 AirSim 源码 `GpsSimpleParams` 的默认 0.2 s 延迟一致。源码中 HIL_GPS 使用发送时刻 `getSimTime()`，而非保留 GNSS 原采样时间；打包二进制精确版本仍未知，不把源码行为直接视作二进制版本证明。
- 第四轮在起飞前实测 `SENS_GPS0_DELAY=200`，ULog 参数事件也确认由 10 改为 200，发生在 tracking 前；传感器约 200 ms 延迟保留。相对 NoDisplay＋10 ms 补偿，位置误差 P95 改善约 70%。这支持优先处理 GPS 数据时效和定位补偿匹配，不能把响应差直接归因于 PID。
- 四轮 tracking 的 HIL 请求到回复 P95 为 0.32～0.39 ms，捕获丢包与 TCP 重组缺口均为 0；DDS 目标旁路到包间隔约 20 ms，最大约 21.4 ms；从源时间戳到 PX4 内部目标生成的代理耗时 P95 为 27～30 ms。低速独立链路中未发现能解释数百毫秒响应差的通信积压。完整 SUPER 运动期规划到适配器链路仍待单独验证，不能据此排除其负载瓶颈。
- 原配置与 NoDisplay 的 ULog 内部速度目标匹配滞后均约 0.61 仿真秒。另以同一外部轨迹速度参考统一拟合，四轮最佳平移分别约 0.24、0.25、0.09、0.13 仿真秒；两者参考不同，不可混称同一指标或当成网络延迟。统一外部参考的速度 RMS 误差分别约 0.226、0.230、0.073、0.093 m/s。
- 四轮仿真/墙钟比均约 0.81～0.82；NoDisplay 降低了 GPU 总利用率，却没有改善该比例或跟踪误差。不能由此断言无单线程/物理仿真瓶颈。低速下均无电机高端饱和、无分配器推力/力矩未达成、无位置/高度/航向估计重置；高速姿态误差问题尚未复验。

证据位于忽略提交的 `artifacts/airsim-diagnostics/`：

| 条件 | 诊断 ID |
| --- | --- |
| 原配置 | `52a7d26852e14c66a819d4268b158d99` |
| NoDisplay | `44fcdcde76f24fe5ae1ce7d770bd3025` |
| GPS 零延迟 | `891a55dee49542dda828d0fe63c9e9e2` |
| 原 GPS＋200 ms 补偿 | `38425f5b02874a46bb16b9037310263e` |

各 ID 包含 runtime/task/settings 快照、飞行报告、ULog 与 `.review.*`、`capture-*/analysis.json`、资源样本及 `diagnosis-summary.json`。`session-20261015/` 另存参数、输入文件完整性对照和汇总脚本。四轮诊断结束时，GPS 两种实验输入仅保存在 artifacts，正常配置尚未采用；后续采用状态见下节。复核时区分 ULog 的初始参数、起飞前参数事件和 tracking 期间参数，不能只读日志初始 10 ms 就误认为第四轮未生效。

本轮结束清理所有诊断容器及临时显示；普通实例保持停止，原配置和历史日志保留。现有桌面 X11 端点无有效显示输出，未在隐藏显示上重建常规实例。后续应先在可用桌面会话恢复正常启动，再以显式候选配置验证 200 ms 定位补偿、完整 SUPER 低速链路及逐级提速；不能直接返回原 8 m/s 路线。

### 补偿落盘与百毫秒响应诊断（2026-10-15 后续）

按用户确认，AirSim 专用 `settings.json` 现在显式配置 GPS `UpdateLatency=0.2` 秒、PX4 `Parameters.SENS_GPS0_DELAY=200` 毫秒。保留模拟传感器延迟，修正定位融合的时间归属；没有消除物理响应时间。Gazebo、正常 `MC_*` / `MPC_*` 控制参数和任务速度未改。更换模拟 GPS 延迟或 PX4 版本时重新核对，不能把 200 ms 当作跨设备通用值。现有运行不热加载输入，必须正常 down/up。

新增只读分析工具 `diagnostics/response_latency.py`，在 **PC 仓库根目录**运行，需已有飞行报告和匹配成功的 `.review.json` / ULog：

```bash
uv run --extra flight-review stage3/super/airsim/diagnostics/response_latency.py <本轮飞行报告.json>
```

输出同名 `.latency.json`：分别拟合外部速度参考、PX4 内部速度目标、姿态目标、角速度目标到对应 PX4 测量状态的最佳时间平移。均匀 20 ms 采样，所有候选平移使用相同有效窗口，禁止跨失流、阶段边界或外推；扫描 −200～800 ms、步长 10 ms。静止/激励不足不出数值。另报最优 RMS、零平移 RMS 和 RMS 距最优不超过 1% 的区间，该区间不是统计置信区间。这些值描述闭环相位/跟踪特征，不是通信 RTT，不同环路或参考的数值不能相减、相加。

使用上述统一算法重新分析历史相同固定轨迹，并新增单因素姿态前馈实验：

| 条件（同为 NoDisplay 固定轨迹） | 内部速度目标→估计速度 | 外部速度参考→估计速度 | 后者约合墙钟 | 姿态目标→估计姿态 |
| --- | --- | --- | --- | --- |
| 原 GPS，10 ms 补偿 | 610 ms | 260 ms | 318 ms | 270 ms |
| 原 GPS，200 ms 补偿 | 320 ms | 130 ms | 159 ms | 270 ms |
| 上一条件＋仅 `MC_REF_FF=1` | 180 ms | 80 ms | 98 ms | 50 ms |

内部速度、外部速度和姿态三项平移均为仿真时间；墙钟列按当轮约 0.817 的仿真/墙钟比换算，不能把 80 ms 仿真时间直接称作 80 ms 实时响应。原工具对补偿后较弱内部速度激励不给出拟合；新工具在相同采样、窗口及激励条件下补齐比较，并保留整条误差扫描曲线。外部参考的最优区间较平坦：前馈实验的 1% 区间为 50～110 ms 仿真时间（约 61～135 ms 墙钟），最优点 98 ms 墙钟不代表每个动作或 P95 都低于 100 ms。

定位补偿后的姿态滞后约 270 ms 仍存在。已核对当前 PX4 提交 `61907962c9220437ec01a98fa26bfbf5cbb254b5` 的姿态控制实现：参考模型平滑姿态目标，比例控制追踪参考，`MC_REF_FF` 控制参考角速度的前馈。诊断时 PX4 原默认该项为 0；`MC_ROLL_P=MC_PITCH_P=4`。小角度理想比例模型的时间常数约为 1/4 秒，与测得慢跟随的量级相符，但实际系统还包含参考模型、内环和机体动力学。机制见[对应版本源码](https://github.com/PX4/PX4-Autopilot/blob/61907962c9220437ec01a98fa26bfbf5cbb254b5/src/modules/mc_att_control/AttitudeControl/AttitudeControl.cpp)、[PX4 控制结构说明](https://docs.px4.io/v1.18/en/flight_stack/controller_diagrams)。

本次诊断时，前馈仅在隔离实例启用，未写入正常 settings；后续采用状态见文末。ULog 核对相对 200 ms 补偿对照，`MC_*` / `MPC_*` / `SENS_GPS*` 的起飞前有效参数唯一差异为 `MC_REF_FF: 0→1`。同一低速固定轨迹完成并解除解锁：位置误差 P95 从 0.123 降至 0.080 m，姿态误差 P95 从 1.46° 降至 0.53°；无高端电机饱和或分配器推力/力矩未达成，估计无位置/高度/航向重置。每条件仍仅一次，不能据此默认启用前馈或承诺高速稳定性。

另已用当前正式补偿配置完成一次 **完整 SUPER 1 m/s、2 m 短程往返**（未开姿态前馈）：报告 `fly-task-1792048677070890554.json`，无空中碰撞、落地解除解锁，位置误差 P95 0.310 m、最大 0.359 m。387 组唯一规划/适配器参考配对的时间戳年龄 P95 12 ms；DDS 目标到包间隔 P95 20.3 ms、最大 20.8 ms；内部目标生成代理耗时 P95 30 ms；HIL 全采集窗口 P95 0.196 ms、最大 5.60 ms，抓包丢包为 0。该短任务外部速度拟合约 160 ms 仿真时间／196 ms 墙钟，内部速度拟合约 380 ms；轨迹不同，不与固定轨迹误差直接作性能对比。证明补偿已接入完整低速链路，仍不能将独立实验的百毫秒指标转移为完整 SUPER 或 8 m/s 验收。

工程目标应分开定义：数据传输与调度、开始响应、轨迹相位滞后、达到目标/制动完成时间。百毫秒级跟随是可继续验证的目标；若要求速度跳变后 100 ms 内完全达到目标，则还受加速度限制，例如 2 m/s 的速度变化在 2 m/s² 加速度下至少需 1 s。对持续轨迹应同时评价误差、动态需求、估计质量和执行余量。

证据：

- `artifacts/airsim-diagnostics/latency-followup-20261015/`：完整 SUPER 运行、旁路采集、汇总 `results.json`、单因素参数对照、源码版本摘要与 `latency-comparison.png`。
- `artifacts/airsim-diagnostics/43d6b296747d4e2fab582fab49b0c135/`：独立前馈实验的配置快照、报告、ULog、`.review.*`、`.latency.json` 和 HIL/ROS 数据。
- 重现前馈实验可显式选择保存的实验输入：`diagnose.py response-up --runtime-config artifacts/airsim-diagnostics/latency-followup-20261015/attitude-ff-input/runtime.json --load render-low`，然后按前文 response-run / land / down 流程执行。该输入是本机忽略提交的实验快照，不是课程默认配置。

本轮两次新增飞行均已确认解除解锁并回收容器，临时显示也已移除；常规实例保持停止。当时 GPS 补偿已采用，姿态前馈仍为实验项；后续按用户确认启用的状态与验收见文末。提速和多次重复期间不放宽失流或误差保护。

### 当前采用：GPS 补偿＋姿态参考前馈（2026-10-15）

用户确认后，正常 AirSim `settings.json` 已采用 `SENS_GPS0_DELAY=200`、`MC_REF_FF=1.0`，GPS `UpdateLatency=0.2` 秒保持不变。无需再选择诊断输入或手动执行 param set；引用该 settings 的 `runtime.super.json` / `runtime.forest1.json` / `runtime.forest8.json` 在 up 时加载相同控制配置。其他 MC/MPC 增益、前馈限幅、参考模型频率、任务速度与故障保护未改，Gazebo 不受影响。

使用完整 SUPER 的正式配置实际验证：

| 路线 | 结果 | 测量时间对齐位置误差 P95 / 最大 | 实际速度峰值 |
| --- | --- | --- | --- |
| `runtime.super.json`，1 m/s、2 m 短程去回 | 完成，落地解除解锁，无空中碰撞 | 0.131 / 0.139 m | 1.108 m/s |
| `runtime.forest1.json`，1 m/s、单程约 35 m／往返约 70 m | 完成，落地解除解锁，无空中碰撞；约 160 墙钟秒 | 0.087 / 0.154 m | 1.080 m/s |

两轮 ULog 均确认 `MC_REF_FF=1`、`SENS_GPS0_DELAY=200`；无高端电机饱和、分配器推力/力矩未达成或位置/高度/航向估计重置。位置指标来自 PX4 估计，不是真值误差；每条路线仅本次一次，不据此宣布高速或多轮验收。树林飞行 tracking 高度约 1.92～3.29 m：2 m 是航点高度，SUPER 仍可规划三维升降。

证据保存在忽略提交的目录：

- `artifacts/airsim-diagnostics/ff-adoption-20261015/`：短程 `fly-task-1792050997102079367.json`、ULog、`.review.*` / `.latency.json`、`acceptance.json` 和时序采集。
- `artifacts/airsim-diagnostics/ff-adoption-forest1-20261015/`：树林 `fly-task-1792051275385049164.json`、ULog、`.review.*` / `.latency.json`、`acceptance.json` 和时序采集。主旁路窗口为前 120 墙钟秒，未覆盖整轮 160 秒；补充窗口已在解除解锁后，不能当成返程尾段证据。飞行报告和 ULog 覆盖整轮。

**手动观察（PC 图形桌面终端，仓库根目录）**：前提是没有其他实例占用固定端口；当前验收实例和临时显示均已清理。先确保桌面已连接且有有效显示输出；无需沿用验收用的临时 DISPLAY。

```bash
# 已验证的树林低速去回；up 只启动，不解锁。
uv run --extra flight-review stage3/super/airsim/runtime.py up --config stage3/super/airsim/runtime.forest1.json

# 可选：打开点云、轨迹与体素地图 RViz；AirSim 跟随窗口由 up 自动打开。
uv run stage3/super/airsim/runtime.py view

# 明确执行起飞、去树林端、返回、降落；结束自动保存报告并复盘。
uv run --extra flight-review stage3/super/airsim/runtime.py task

# 确认 Disarmed 后正常关闭。
uv run stage3/super/airsim/runtime.py status
uv run stage3/super/airsim/runtime.py down
```

本轮验收没有启动 RViz；手动开启会增加显示负载，不直接拿其墙钟速度与本轮无 RViz 记录作严格性能对比。期望看到飞机起飞至约 2 m，沿规划路线进入树林后返程，必要时升降避障，最后落地解除解锁。需要先看更短动作时，将 up 的配置替换为 `runtime.super.json`，其余命令相同。场景加载及 TIME_WAIT 自动等待可能需要一段时间，不重复并发 up。

异常恢复（**PC 另一终端**）：

```bash
uv run stage3/super/airsim/runtime.py land
# 碰撞、Land 卡住或不能确认解除解锁时，仿真急停：
uv run stage3/super/airsim/runtime.py stop
```

人工 land 后本轮锁存取消，重新试飞需 down/up。不要用 `runtime.forest8.json` 作为首轮观察：它仍保留 8 m/s、8 m/s² 八航点需求，此次未重新验收。

### 用户八航点飞行复盘与 15 m/s 目标（2026-10-15）

运行 `5e6b8e7df2234dfbbd275dfe9e7d35c2` 的启动快照实际为 **8 m/s、8 m/s²、pass 策略、12 m carrot**，已加载前馈和 GPS 补偿。报告 `fly-task-1792053061960038121.json` 的 `success=false`：`SUPER command timeout; waypoint=8/8`；后续已解除解锁，场景查询也为 Landed。进入第 8 航点阶段不代表终点已到达；最后跟踪样本距最终目标约 10.0 m。

| 本轮指标 | 结果 |
| --- | --- |
| track 阶段实际速度：按测量时间加权均速／P95／峰值 | 5.91 / 7.21 / 7.60 m/s |
| 测量时间对齐位置误差 P95／最大 | 0.957 / 1.251 m，超过当前 0.8 m 验收门限 |
| 姿态／角速度误差 P95 | 11.70° / 0.952 rad/s |
| 仿真/墙钟比 | 0.706 |
| 估计器重置／高端电机饱和／分配器推力力矩未达成 | 本轮未发现 |

`node-logs/planner.log` 的末段（约 1598～1645 行）显示 A* 连续超过 0.1 s 搜索预算，轨迹生成失败，旧轨迹结束后 FSM 从 FOLLOW_TRAJ 转入 GENERATE_TRAJ 并继续失败；规划参考停止，随后触发控制失流降落。备用轨迹优化与安全多面体生成也有失败记录。因此当前证据支持先排查末目标/地形可达性、规划约束及搜索预算，不能仅将其解释为通信慢，更不能用放宽失流保护掩盖断供。

此后只读场景查询记录接触 `Landscape_0` 且 Landed；落点地形高度高于出生点，不能仅以相对高度不为零判断未落地。该查询只用于评测，没有进入控制反馈。仪表盘期间没有重启或改变该用户实例。原报告、ULog 和 `.review.*` 保持原样，额外分析保存于 `artifacts/airsim-dashboard-checks/user-flight-analysis.json`。

用户目标是实际 15 m/s，目前 **未达到、未验证**：任务配置校验仍限 8 m/s，本轮 PX4 `MPC_XY_VEL_MAX=12` m/s，15 m/s 也需要重新核对感知/规划前视距离、制动空间和轨迹动态约束。先解决末段断供与 8 m/s 跟踪误差，再按固定路线与单因素逐档扩展；本次仪表盘工作没有提高速度上限、修改 PID 或放宽保护。

### 刹停后等待重规划（2026-10-15）

AirSim 的 `planner.base.yaml` 设置 `fsm.stationary_replan_hold_timeout: 10.0`（仿真秒）。已完成轨迹的末端速度、加速度均小于 0.001 时，规划器在 `GENERATE_TRAJ` 中持续发布固定停止点，继续重规划；成功后恢复轨迹执行。保持不代表到达任务目标，不推进航点。超过保持期限则停止发布，交给原有控制端失联降落保护；规划器真正卡住时，控制端 0.5 秒墙钟看门狗仍生效。Gazebo 未配置此选项，默认关闭。

更新规划器二进制并重新 `down/up` 后生效。预期日志为 `Stationary trajectory ended; hold endpoint while replanning.`，随后出现重规划成功，或 `Stationary replan hold expired` 后保护降落。此改动不解决终点附近 A* 搜索失败，也不保证停止点始终安全；不保持尚有明显末端速度或加速度的轨迹。

本次验证记录：独立 Docker 编译通过，C++ 保持判据与超时边界测试通过，6 项 AirSim 配置/几何回归测试通过；上一轮末端参考满足保持判据。新二进制已安装供下次启动使用，未重启现有进程。实际树林飞行效果尚待重新运行验证。

### 树林终点高度修正（2026-10-15）

运行 `1652c999bd9746e483e40c7f7034a54a` 证明刹停保持已生效，但保持期间 A* 始终超时。备份走廊距障碍约 0.2 m 的失败发生在降落触发之后，不能作为保持阶段规划失败的原因。

只读采集的飞后 ROGMap 在最终 XY 附近 2 m 范围内有 Z=3.5～3.9 m 的地表状占据点；原终点 Z=2 m 低于这些点。从停止点到原目标直线的最小障碍距离约 0.03 m，目标 Z=6 m 时约 2.34 m。`task.forest8.json` 仅将最后航点 Z 改为 6 m（出生点相对 ENU，非离地高度），其他航点、速度、保护期限不变。这是飞后局部地图证据，不等于精确地形测绘或实际规划验收。输入修改须 down/up 才生效。

同路线实际对照运行 `b07c7e5a964c4892b1341edbf69790c1`，报告 `fly-task-1792059540722448241.json`：仅最终航点 Z 从 2 改为 6 m；飞机到达最终目标，进入 `terminal goal hold / WAIT_GOAL`，随后任务进入 `landing; waypoint=8/8`，控制端 `land: requested landing`，最终确认解除武装。未出现刹停保持超时。请求降落时估计位置约 `[-37.514, 231.817, 6.057]`，距配置目标约 0.10 m。

本轮峰值约 7.72 m/s、跟踪阶段平均约 5.50 m/s；测量时间对齐位置误差 P95 0.985 m、最大 1.851 m，旧验收参考匹配指标最大 1.909 m，仍超过配置 0.8 m 门限。无电机高端饱和或分配器未达成。终点规划及主动降落链路已有本轮证据，完整 8 m/s 路线仍未通过严格跟踪门限，不能标作全任务验收通过。地图快照位于忽略跟踪的 `artifacts/airsim-diagnostics/goal-height-20261015/`。

用户随后确认：跟踪误差用于提速性能评价，不作为任务成败门限。已移除检查器完成分支中的 0.8 m 硬门限，继续输出最大误差与复盘 P95/RMS；无误差采样时报告 null，不记为零。上述历史运行的报告保留原结果，不追改。任务是否完成仍检查到点、结束行为、飞行阶段碰撞及故障；降落由 PX4 管理，降落阶段不检查 AirSim 碰撞，结束须确认解除武装。历史段落中的“未通过跟踪门限”仅描述当时的验收规则，后续不再应用。

### 10 → 12 → 15 m/s 两轮提速对照（2026-10-15）

按用户指定顺序，每档两轮；任一档两轮任务均失败即停止。六轮均完成八航点，到终点稳定后由 PX4 降落并解除武装；无飞行阶段碰撞或失流失败，因此未触发提前停止。**这是三档配置下任务成功，不代表实际达到 12 或 15 m/s。**

共同条件：AirSimNH 原树林路线、终点 ENU Z=6 m，起点重置后每轮重新启动；8 m/s² 加速度上限、20 m carrot 前视/6 m 刷新、20 m 规划范围、45 m 雷达过滤范围；FlyWithMe 1280×720，无 RViz。PX4 水平速度上限统一为 16 m/s，GPS 延迟与补偿、姿态前馈及其他增益保持原值。六轮之间仅改变配置速度档位；这组 20 m carrot 与此前 8 m/s 的 12 m carrot 不同，不作严格跨组归因。

| 配置速度 m/s | 轮次 | 任务 | 实际峰值 m/s | 跟踪均速 m/s | 规划参考峰值 m/s | 对齐位置误差 P95 / 最大 m |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 1 | 完成 | 9.77 | 6.50 | 9.55 | 0.949 / 1.317 |
| 10 | 2 | 完成 | 10.08 | 6.68 | 9.95 | 1.113 / 1.331 |
| 12 | 1 | 完成 | 9.84 | 6.50 | 9.51 | 1.187 / 1.554 |
| 12 | 2 | 完成 | 10.03 | 6.48 | 9.91 | 1.196 / 1.384 |
| 15 | 1 | 完成 | 9.94 | 6.72 | 9.76 | 1.015 / 1.615 |
| 15 | 2 | 完成 | 9.79 | 6.50 | 9.94 | 1.027 / 1.168 |

速度均为 PX4 估计的 ENU 三维速度、按仿真秒定义；均速仅统计 track 阶段并按唯一里程计测量时间加权，不包括起降或等待。跟踪误差仅作性能指标。仿真/墙钟比约 0.71～0.73，不将该指标乘进速度。

六轮 ULog 均确认 `MC_REF_FF=1`、`SENS_GPS0_DELAY=200`、`MPC_XY_VEL_MAX=16`，XY/Z 估计重置均为零。10 档姿态误差 P95 约 10.9°，12/15 档约 12.8～13.2°；电机高端饱和比例分别为 1.6～2.1%、5.4～5.7%、4.0～4.7%，推力分配未达成约 0.5～5.2%，力矩分配未达成约 0～1.5%。这些是调度/轨迹/动力学后续分析指标，不独立判任务失败。

12 和 15 档实际速度仍约 10 m/s，规划器参考峰值本身也仅约 9.5～9.9 m/s；启动日志确认正确加载 12/15 的轨迹速度上限。因此下一步应先分析当前路线/前视范围/加速度与轨迹优化为何没有输出更高参考速度，不能将未达到目标速度直接归因于 PX4。未在本组中途修改 PID、加速度、规划权重或故障保护。

默认 runtime/settings/task 未改成高速档。仅将 AirSim 任务速度输入范围扩展至 (0,15] m/s，加速度仍限 (0,8] m/s²；7 项配置/几何回归测试通过。独立测试配置、结果 JSON/CSV 与每轮启动/任务/清理输出位于忽略跟踪的 `artifacts/airsim-speed-sweep-20261015/`，各轮原始报告与 ULog 的绝对路径见 `summary.json`。全部测试实例已关闭，未删除飞行记录。

### 复用 forest10 / forest15 配置

`runtime.forest10.json` / `runtime.forest15.json` 分别引用 `task.forest10.json` / `task.forest15.json`，共同使用 `settings.forest-fast.json`（PX4 水平速度上限 16 m/s）。参数与上述两轮测试一致：20 m carrot、8 m/s² 加速度上限、最终航点 ENU Z=6 m；配置速度分别为 10 / 15 m/s。两档实测实际峰值均约 10 m/s，15 档不代表已达到实际 15 m/s。

PC 图形桌面终端，在仓库根目录执行（先确认上一轮已落地解除武装）：

```bash
uv run stage3/super/airsim/runtime.py down
uv run stage3/super/airsim/runtime.py up --config stage3/super/airsim/runtime.forest10.json
uv run --extra flight-review stage3/super/airsim/runtime.py task
```

选择 15 档时，将 up 的配置换成 `stage3/super/airsim/runtime.forest15.json`。切换配置必须 down/up；task 使用启动快照。正常现象为逐航点飞行、终点稳定后 PX4 降落并解除武装；实际速度和跟踪误差见终端仪表盘及自动复盘。启动失败查看本轮日志，未确认飞行状态时先 status，不重复启动。原默认配置及 forest8 不变。


### 默认 10 m/s 与 A→B 单目标长任务（2026-10-15）

2026-10-16 用户明确当前基线为 AB：`runtime.py up` 不带 `--config` 时默认选择 `runtime.forest10-ab.json`。此前的 forest10 八航点仅保留为显式历史对照，不再作为默认或迁移验收基线。独立 PX4 控制测试仍可显式选择 `runtime.example.json`；短程 SUPER 使用 `runtime.super.json`。已有运行使用启动快照，默认值变更不影响当前实例。

单目标基线配置为 `runtime.forest10-ab.json` / `task.forest10-ab.json`：保持 forest10 的出生点、终点、10 m/s、8 m/s²、传感器、地图、控制和保护，只保留最终 B 点 `[-37.57, 231.76, 6]`（出生点相对 ENU 米）。起飞点 A 约为 `[0, 0, 2]`，直线距离约 235 m；任务层 `goal_mode=direct` 向 SUPER 发一次最终 B 点，不发送中间 carrot 目标。SUPER 内部仍使用原 20 m 局部规划范围和滚动重规划；不保证全局绕开任意障碍或局部死路。单航段超时 300 仿真秒，总任务超时仍为 600 仿真秒。

**PC 图形桌面终端，仓库根目录**，前提为上一实例已落地解除武装并正常 down：

```bash
uv run stage3/super/airsim/runtime.py up --config stage3/super/airsim/runtime.forest10-ab.json
uv run --extra flight-review stage3/super/airsim/runtime.py task
uv run stage3/super/airsim/runtime.py status
uv run stage3/super/airsim/runtime.py down
```

预期：起飞到 2 m、悬停初始化后，直接以远端 B 为规划目标，沿途自主避障和重规划，到点速度低于 0.3 m/s 且在 1.5 m 容限内保持 2 仿真秒，再由 PX4 降落并确认解除武装。任务报告应为 `waypoint=1/1`；跟踪误差仅作为性能指标。与八航点对照时查看任务成败、耗时、实际均速/峰值、轨迹、规划失败和跟踪误差，不把配置速度等同于全程速度。查看自动 `.review.*` 与对应 ULog。规划失流、碰撞或超时按原逻辑降落；人工恢复使用上文 land/stop。静态检查不替代本配置实际飞行结果。

本机首轮实测：运行 `0aba8d80026e4011aac6439f52c6e8b0`，报告 `fly-task-1792069232143690800.json`。起飞及悬停成功，但未进入 tracking；规划器反复报告 `Cannot find continuous corridor on path`、`SearchPolytopeOnPath ... failed` 与 `ROG Box search failed, box size is zero`，随后控制端 `planning timeout`，任务失败。约 44.1 墙钟秒后确认降落解除武装，无飞行阶段碰撞；实例已正常 down。全程速度峰值约 1.11 m/s 属于起降，不是长航段速度；无 tracking 样本，故跟踪误差、姿态跟踪、执行余量没有任务段指标。自动复盘与 ULog 位于同运行目录；此证据不支持归因为 PX4 高速跟踪问题，也尚未定位走廊生成失败的根因。7 项配置/几何检查和 2 项隔离 ROS 检查通过，后者确认移动后仍仅发布同一个远端目标。下一步应检查远目标路径搜索返回路径与局部地图边界、连续走廊生成的衔接，不靠恢复任务层 carrot 或放宽超时冒充单目标通过。


### 单目标裁剪返回值修复与 10-ab 实测（2026-10-15）

核心 A* 仅增加每次调用独立的 `goal_clipped` 标记：窗口外目标成功裁剪并完成邻域调整后设置；搜到裁剪点返回 `REACH_HORIZON`，真实目标仍返回 `REACH_GOAL`。调用方原本接受二者，但仅后者追加精确最终目标，因此不再将局部裁剪点直接连到远端 B。20 m planning_horizon、A* 窗口、任务目标、速度、感知与控制参数不变；保留原有路径分段与安全保护。

验证：Humble 离线增量编译通过；真实 A* 隔离回归的近目标、轴向远目标、10-ab 远目标、先到距离截止、远目标后再近目标五次搜索均通过。修复前源码链接同一测试程序时，近目标成功，远目标错误返回 `REACH_GOAL`，被测试捕获；新代码远目标输出末端约 `[0.1,17.5,2.1]`，10-ab 末端约 `[-2.9,17.5,2.3]`，均返回 `REACH_HORIZON`。回归使用无障碍、未知可通行地图，仅验证搜索返回值；构建与正负对照记录位于 `artifacts/airsim-diagnostics/clipped-goal-10-ab-20261015/`。

实际飞行运行 `2c646a1c1e464a23a42dca83eaf119b4`，报告 `fly-task-1792072116489356565.json`：**任务失败，未到 B**。初次规划成功，进入 FOLLOW_TRAJ 并多次重规划成功，突破此前“起飞后规划超时”的阻塞；随后 AirSim 在出生点相对 ENU 约 `[-6.92,13.86,3.71]` 报告接触 `InstancedFoliageActor_0`，检查器中止并请求降落。约 49.1 墙钟秒后确认解除武装，实例已正常 down。全程估计速度峰值约 9.62 m/s；终端 track 窗口均速约 5.38 m/s，该窗口仅约 2.93 仿真秒，不能作为 235 m 全程均速。

已读取对应 ULog 与自动 `.review.*`；指标仅统计碰撞前 tracking：测量时间对齐位置误差 P95/最大约 0.937/0.988 m，姿态误差 P95 12.74°，角速度误差 P95 0.974 rad/s。未见 XY/Z/航向估计重置，未见高端电机饱和或推力/力矩分配未达成。ULog 外部参考最大记录间隔约 0.219 s，不能据此判定 Offboard 发布频率。碰撞后的备用走廊失败不能倒推为碰撞前原因；本轮尚不能区分规划/建图净空不足与跟踪误差对碰撞的贡献，没有调整 PID、放宽碰撞检查或故障保护。原八航点没有在本轮重飞，不宣称已完成其修复后飞行回归；10-ab 长任务仍未验收。


### 整理与上游问题报告（2026-10-16）

旧 SimpleFlight 交接运行脚本已归档到忽略 Git 的本地参考目录，当前课程入口只维护本目录。移除 SUPER runtime 中不会执行的独立 RPC 任务块、无人消费的任务误差门限与未使用导入，保留真实报告误差指标、独立 PX4 控制回归和显式诊断工具。直接目标模式只计算并发送最终目标；失败任务已流式显示的输出不在异常末尾重复打印。配置和控制参数未调整。

[SUPER 远目标裁剪报告](../../../docs/stage3/SUPER-astar-clipped-goal-report.md)包含上游代码来源、无仿真复现、最小修复与验证范围。整理后完整 Python 回归 60 项通过；A* CTest 五种搜索场景及静止保持 C++ 测试通过。未为代码整理新增飞行，不将上述 10-ab 的碰撞记录改为成功。

## RoboPi 算力后端（2026-10-16，迁移验证中）

标准迁移路线为宿主机 AirSim＋单个 PC Docker（PX4、MicroXRCE Agent、HIL `/clock`、原始雷达 RPC 桥）＋OpenHarmony RoboPi 原生 ROS/SUPER。板端运行控制桥、雷达过滤/GNSS 采样位姿配准、ROG-Map、SUPER 和航点任务；不运行 AirSim、Gazebo、Agent 或 LIO。Docker 原后端仍为默认，任务输入、GNSS 延迟补偿、控制参数和完成规则保持现有约定。

### 教师准备（PC 仓库根目录）

前置条件：本次明确的 HDC 设备、以太网 DDS 可达；匹配当前镜像的 OHOS SDK、ROS/第三方目标开发快照、Python 3.12/NumPy 目标头文件、主机生成工具，以及与 `develop/docker/Dockerfile` 相同固定提交且干净的 px4_msgs 源码。模型推理与飞行性能测试分时进行。不要将相邻 GCOPTER 的旧快照直接标作当前设备已验证。

```bash
# 只读核实设备/基础 ROS；替换本次实际 connect key。
python3 stage3/robopi.py preflight --target '<connect-key>'
# 从当前设备导出目标开发快照；SDK 和主机 venv 须先按 skill 核验。
python3 stage3/board/prepare.py --target '<connect-key>' \
  --sdk '<OHOS SDK native目录>' --host-python '<主机生成工具venv>/bin/python'
python3 stage3/robopi.py build --config artifacts/robopi-stage3/board-config.local.json --jobs 2
python3 stage3/robopi.py deploy --target '<connect-key>'
# 使用与基线相同的 PX4 镜像；构建新的单容器 PC 镜像。
python3 stage3/robopi.py pc-image --px4-image '<已核实的PX4镜像摘要>'
```

`build` 输出到忽略 Git 的 `artifacts/robopi-stage3/`，顺序构建 PX4 消息、SUPER 消息、ROG-Map 与规划器；检查目标 ELF、SOABI、RPATH 并保留源码/SDK证据。目标 PCL、yaml-cpp 等依赖须实际可用，入口不自动下载/安装或用 Linux 库补齐。构建入口检查并幂等应用 `stage3/board/patches/` 中的补丁，上下文不符即停止且不覆盖本地修改。OHOS 默认关闭依赖 libdw 的崩溃栈处理，Linux 默认保持开启；算法参数不变。目标 libyaml 有库和头文件但缺 CMake 配置时，使用本目录构建适配解析已核验目标文件。当前镜像的通用 PNG 链接指向 1.6.43，而头文件与 PCL 需要带 PNG16_0 符号版本的 1.6.50；构建选择同一目标快照内与头文件匹配的库，作为 release 私有依赖打包，不改板端系统链接。SDK/ABI/依赖变化时保留旧构建与证据，使用新构建目录；源码变化可由 Ninja 增量重建。单容器镜像用原 PX4 的 glibc loader 和完整依赖闭包运行 PX4，ROS 仍使用 Humble/Jammy 运行库。

`deploy` 从 `robopi/stage3/` 收集脚本、共享源码链接的实际内容及构建 install，生成内容寻址 release；不传源码链接、SDK 或缓存。远端为 `/data/local/workspace/stage3/releases/<摘要>/`，重复部署校验后复用，不覆盖旧 release。每次运行独立保存 task/planner 快照和进程身份；停止检查 PID、启动时刻、命令行、exe 与工作目录。缺文件、ABI不符或 HDC失败即停止，不接管其他项目。

### 无显示运行与验收（PC 仓库根目录）

先填写 runtime 中本机真实 scene_dir/binary；其他机器的 `/mnt/disk1/wqy/...` 不是通用路径。下面从短程配置开始。保持任务、settings 与场景路径的解析规则；复制 runtime 到 artifacts 时需将 settings/super_task 改为绝对路径。

```bash
# 可以先预览，不访问 Docker/设备，也不启动 Xvfb。
uv run stage3/super/airsim/runtime.py up \
  --config '<本机短程runtime.json>' --compute robopi --target '<connect-key>' \
  --pc-address '<PC以太网IPv4>' --board-address '<板端以太网IPv4>' \
  --image uav-airsim-robopi-pc:local --no-display --dry-run
# 通过预检后启动；up 只待命，不起飞。
uv run stage3/super/airsim/runtime.py up \
  --config '<本机短程runtime.json>' --compute robopi --target '<connect-key>' \
  --pc-address '<PC以太网IPv4>' --board-address '<板端以太网IPv4>' \
  --image uav-airsim-robopi-pc:local --no-display
uv run stage3/super/airsim/runtime.py status
uv run stage3/super/airsim/runtime.py inspect
uv run --extra flight-review stage3/super/airsim/runtime.py task --dashboard plain
# 确认 Disarmed 后清理，再切换配置重新 up。
uv run stage3/super/airsim/runtime.py down
```

`--no-display` 使用本次管理器拥有的独立 Xvfb、640×480 、`-RenderOffScreen` 和 `ViewMode=NoDisplay`，不显示 AirSim 主窗口，不启动 RViz，仍保留 Vulkan/物理/雷达。需要 PC 已安装 Xvfb；不是关闭渲染器，不保证 GPU 或物理负载消失。状态记录包含虚拟显示身份，清理只停止本次显示。不要用 `-nullrhi` 绕过传感器与场景验证。

后续命令从启动快照取得设备、release、配置与后端，不能再次传 `--target/--compute` 更换现场。`dashboard` 继续在 PC 仿真容器内观察；板端模式不支持通过 `view` 启动额外 RViz。板端点云线格式为传感器局部 FRD、原始采样纳秒时间戳、XYZ FLOAT32；话题 `/stage3/uav1/lidar_raw`。板端只用 PX4/GNSS 里程计插值配准，不消费 AirSim 真值。域 10、Fast DDS UDP、仿真时间和墙钟看门狗沿用既有契约。

短程和 forest1 仅用于定位问题；正式迁移验收以 forest10-ab 单目标为基线，每次换配置先 down/up。同样的 NoDisplay 条件下对照 Docker 与板端 AB 冷启动；八航点只做显式对照，其通过不能代替 AB。记录实际速度、参考速度、跟踪误差、原始点云吞吐与频率、CPU/内存和仿真/墙钟比（板端每 2 秒采样到本次 run 的 resources.jsonl，down 时取回 board-logs；报告 raw_sensors 记录原始点云频率/吞吐），不能静默降低点数、速度或放宽超时。单目标 forest10-ab 仍单独保留其既有失败边界。

故障测试在独立冷启动的低速配置中逐项执行，前置条件为静止链路就绪、Disarmed：

```bash
uv run --extra flight-review stage3/super/airsim/runtime.py fault --case lidar --dashboard plain
# 各轮落地并 down/up 后分别选择 planner、clock、control。
```

雷达/规划器在板端暂停，clock 在 PC 暂停；暂停覆盖降落过程后恢复。control 测试终止板端控制桥，监督器停止其余本项目节点，检查 PX4 Offboard 丢失后 AUTO_LAND 及解除武装；该轮之后必须 down/up。所有注入都由 PC 管理器核验本次实例后执行，PC 检查容器不需要 HDC 二进制。成败均复盘 `.review.*`/ULog，控制桥退出后的降落以 PX4 状态判断，不能用陈旧控制状态宣称正常落地。

`land/status/stop` 保持可在任务占锁时使用。HDC取消失败仍尝试 PC PX4降落，但报告板端取消未确认；不能保证板端已经停止。stop 会继续回收可核验的 PC 资源；若板端状态未知，状态保持 stopping，恢复 HDC 后重试 stop。急停不计作降落验收。

### 本轮实际证据与限制

已完成单容器 PC 镜像构建、以太网真实 DDS 往返，以及 NoDisplay 条件下 Docker 基线的短程、forest1、forest10 八航点飞行；均无碰撞并确认解除武装。板端交叉构建、加载/消息序列化、1 m/s 短程与 forest1 往返也已通过；低速四项故障降落已通过；forest10 首轮因指令超时降落，三次成功冷启动待完成，不能将 PC 结果计为其上板验收。实际运行、版本和复盘证据见 [RoboPi 迁移验证](../../../docs/stage3/RoboPi-validation.md)。

### 板端以太网通信

本仓库 PC↔RoboPi 的跨机 ROS 通信默认沿用本节的独立以太网 DDS 范式，跨阶段复用 `src/uav_dds.py` 生成配置；网卡、地址和所需源策略规则按实际环境核实，本次临时测试地址不是课程固定地址。HDC 用于管理；`fport` 仅转发 HTTP/TCP，不能代替 DDS。`up --compute robopi` 必须明确两个接口地址，先只读核对两端 IPv4 及网卡 carrier，再生成本次 PC/板端 Fast DDS 接口白名单与单播 peer 配置（同时包含本机与远端；PC 还允许 127.0.0.1 UDP 回环及其单播 peer，支持同一容器内 Agent、桥及检查器通信）。Stage 1 的 `verify.py --dds-profile <PC配置.xml>` 可复用同一配置；板端 serve.sh 启动前设置对应 `FASTRTPS_DEFAULT_PROFILES_FILE`。

本次镜像存在优先于 main 表的 fwmark 策略路由：即使源 IP 为以太网，默认 socket 仍可能走 Wi-Fi。先核对实际网卡和源路由，不能把“ARP 已通”当作 DDS 已通。需要时在 **RoboPi shell** 用已部署的 `robopi/tools/ethernet_rule.py add --source <板端测试IPv4>` 添加仅匹配测试源 /32 的 main 表规则；默认优先级 10000，冲突即拒绝。`status` 查看，`remove` 仅撤销本工具保存所有权的规则。本工具不设置 IP、默认路由或防火墙。网卡地址和规则均为临时配置，重启后恢复再复验；PC 可使用不自启、不落盘的 NetworkManager 测试连接，勿覆盖原网络。成功判据必须包含普通 socket 的双向 UDP/实际 ROS 消息收发。

### OpenHarmony 时钟话题诊断

本次镜像的 rmw_fastrtps 在同一 C++ 节点同时订阅和发布 `/clock` 时会断言。最小探针 `stage3/board/probes/ros_topics.cpp` 的 String、PointCloud2、MarkerArray、Odometry 创建均成功，`use_sim_time=false` 加 Clock 发布器成功；改为 true 则在 Clock 发布器处返回 134。SUPER 改为只有显式调用 `setSimTime()` 时才分配时钟发布器，标准飞行没有调用它，仍由 PC HIL 桥唯一发布时钟；没有关闭仿真时间或改用墙钟。

**PC 仓库根目录**：已完成目标构建后，`python3 stage3/board/probes/build.py` 可复用该构建的真实编译/链接命令生成 `artifacts/robopi-stage3/probes/ros_topics`。探针不发送运动命令；按 HDC skill 传输并 chmod 后，在与 release 相同的 ROS/DDS 环境中运行，比较 `--ros-args -p use_sim_time:=false` 与 true。当前镜像预期后者复现上述故障，不能把该负对照写成通过。完整日志在迁移验证目录；换镜像应重新核实。

### 搜索期限与板端性能回归

当前 `stage3/board/patches/` 还包含两项保持既有搜索语义的适配：启动时不变的高度环境配置缓存，避免每个邻格反复 getenv；显式 Release `-O3` 防止 SDK 后加的 `-O2` 覆盖上游优化级别。另补充超时实际耗时/展开次数日志，不改期限、速度、地图或返回码。配置变更仍需 down/up。

**PC 仓库根目录**，完成目标 build 后：`uv run stage3/board/probes/astar.py --budget 0.1` 复用上游真实 A* 回归，生成板端空图探针及配置。按 HDC skill 上传生成的 `astar_budget`、`astar-empty.yaml` 并 chmod；在 release 的 ROS/私有库环境下，用域 191、ROS_LOCALHOST_ONLY=1、独立 ROS_LOG_DIR、unset FASTRTPS_DEFAULT_PROFILES_FILE 运行 `<探针路径> <配置路径>`。探针不连接 PX4、Agent 或 AirSim，不发运动指令；六项必须打印预期 CASE 与 WALL_SECONDS 并正常退出。`--budget 5` 仅供测量未优化版本完整耗时，不能计为 0.1 秒期限通过或写入飞行配置。真实树林与故障验收仍使用原期限，失败保留原记录。

### 端到端 profile 与显式降级配置

**PC**：完成带 `SUPER-runtime-profile.patch` 的目标 build/deploy 后，在本机 runtime JSON 增加 `"board_profile": true`，按前文以太网与 `--no-display` 命令 up。默认不记录 profile。原生规划器分别记录 PlanFromRest、ReplanOnce、探索/备用轨迹及 A* 的单调墙钟、线程 CPU 和进程 CPU；现有节点原位记录原始点云发出、板端接收/配准、有效指令接收与 setpoint 发布，避免板端另起一个高频观察节点。

`status` 给出本次 run_dir。**PC 终端 A** 在任务前运行以下只读旁路（替换容器及本次 run 目录，默认示例 120 秒，可设为 660 秒做持续观察，上限 1800 秒）；**终端 B** 执行前文 task，确认 Disarmed 后 down：

```bash
docker exec '<本次PC容器>' bash -lc \
  'source /opt/ros/humble/setup.bash; source /opt/px4_ws/install/local_setup.bash; source /super_ws/install/local_setup.bash; python3 -u /lesson/stage3/super/airsim/diagnostics/trace_ros.py --seconds 120 --token profile --compact' \
  > '<本次run目录>/observer-profile.jsonl'
# down 已取回 board-logs/profile；PC 原始记录在 profile/raw.jsonl。
uv run stage3/board/analyse_profile.py '<本次run目录>'
# 点云队列与失流诊断，可分析同一实例中的多次任务及降落后持续采样。
uv run stage3/board/analyse_cloud.py '<本次run目录>'
```

点云诊断逐帧记录原始云接收、解码 CPU/墙钟、配准发布和控制桥新鲜度接受结果；每秒记录队列长度、最老帧年龄、位姿及输入/输出新鲜度，溢出、过期、插值失败分别记录原因与位姿括区。`cloud-summary.json` 按分钟汇总，并以同一原始帧时间戳关联 PC 发布记录与板端接收空窗，不把两台机器的绝对单调时钟相减。PC 发布事件记录在 publish 调用前，不能单独代替线缆报文证据。默认关闭 profile，队列、算法和保护门限不因观测改变。

正常 down 结束容器时观察器可能随容器退出；保留已有 JSONL，分析必须有实际飞行报告及完整测量文件，缺项不会伪装成 0 延迟。点云总时长以 PC 发出→PC 收到板端配准结果的同机单调时钟计算，再扣除板内驻留；余量仍包含双向 DDS、序列化和回调调度，不是独立单向网络延迟。嵌套 scope 不相加，线程 CPU 之外的时间可能是调度、锁或阻塞；进程 CPU 还包含其他线程。profile 产生额外开销，不能替代关闭 profile 后的飞行验收。

经用户授权的临时降级由本机 runtime 的 `"planner_timing": "robopi-relaxed"` 显式选择；默认 `baseline` 不变，仅限 RoboPi 后端。保留 `replan_forward_dt=0.1` 仿真秒，仅增加 `replan_wall_limit=0.35` 墙钟秒：总重规划必须同时满足墙钟不超过 350 ms、消耗的仿真时间不超过原前视的 90%（90 ms）；仿真时间倒退也拒绝。默认 baseline 保持原 90 ms 墙钟门限。该配置用于低于实时速度的仿真，不能据此给实机放宽；指令/雷达/时钟失流门限、A* 搜索期限、碰撞、状态、边界和限幅均保持原值。最初直接拉长前视到 0.35 s 的候选发生低速碰撞，已经撤回，不作为可用方案。需 down/up；先在已通过的低速任务回归，再扩展高速。profile 用完将 `board_profile` 关闭，不将降级模式的通过写作原 forest10 基线通过。实测范围见迁移验证。

当前 `robopi-relaxed` 仍是实验档：恢复连接后的低速复验因配准点云失流保护降落，未通过，不能作为临时可用或高速验收配置；默认 baseline 未改。阶段证据与恢复后的服务状态以迁移验证为准。

5 m/s 实验使用 `runtime.forest5.json` 的相同场景、settings 和八航点，按本机路径复制到 artifacts 后显式设置 `"planner_timing": "robopi-forward-200ms"`，并按板端运行命令启动。该档将 `replan_forward_dt` 从 0.1 增至 0.2 仿真秒，总仿真计算预算由 90 增至 180 ms，墙钟上限 350 ms；轨迹切换前视同步调整，仍拒绝过期或时间倒退的规划。它与只放宽墙钟的 `robopi-relaxed` 是不同实验档。指令、点云、时钟保护，A* 搜索期限、加速度和飞行控制参数不变；需冷启动 down/up，不从上次降落位置直接重启任务。关闭 profile 做飞行验证，结果见迁移验证；尚无实机适用结论。

后续约 702 秒持续采样完成 3939 帧配准，无队列丢弃，采样队列最大 1；复现 3.45 秒原始云接收空窗导致保护降落。另一次 5.55 秒空窗同步记录到板端 IP 分片重组失败，已定位到网络接收层；不是逐渐增加的 Python 配准积压。该问题尚未修复，具体计数、复盘与适用边界见迁移验证的“点云持续观测与 IP 分片证据”。


### AB 点云失流影响实验

当前以 AB 单目标为基线。`runtime.forest5-ab-observe.json` 是显式 RoboPi 实验入口，任务来自 10-ab，速度设为 5 m/s，并使用前述 200 ms 前视预算；当前两个 AB 任务均显式采用下述仅观察策略。按板端步骤填写本机场景、镜像路径并冷启动；不要用八航点替代。该实验打开 profile，先启动旁路观察再执行 task，碰撞会作为实际失败记录，之后才尝试收尾降落。

非 AB 任务的 `lidar_loss_action` 缺省为 `land`（既有 0.5 墙钟秒无新鲜点云降落）；当前两个 AB 配置均显式设为 `observe`。显式 `observe` 关闭飞行中的这项降落及新目标的点云新鲜度拒绝，只记录失流／恢复。起飞前仍等待健康状态和新鲜地图，状态／时钟、指令有效性与指令失流、人工降落保持原值。控制日志包含 `lidar stale/recovered`，`control.jsonl` 记录 `cloud_loss_started/ended`，可将空窗与规划指令、执行参考和碰撞时间关联。未出现失流或先因其他原因停止时，不据此推断失流后果；实验结果见迁移验证。

### AB 仿真实验的中止条件（2026-10-16 门限审计）

`task.forest10-ab.json` 与 `task.forest5-ab-observe.json` 均显式设置 `trajectory_limits_action=observe`、`lidar_loss_action=observe`，Docker 与 RoboPi 使用同一控制桥。任务包络、参考速度、参考加速度、跟踪偏差超限只记录，不拒绝轨迹、不裁剪参考、不自动降落；飞行中点云失流也只记录。其他任务缺省策略仍为 land。此策略用于当前 AirSim 仿真，不作为实机参数。

历史录像中参考东向位置 20.00217 m 超过任务上界 20 m，控制桥直接拒绝并降落；当前逻辑已移除此类 AB 实验中止。`bounds_enu_*` 仍用于输入航点与起飞目标的静态校验，不能再解释为必须将绕障轨迹限制在其中。

| 层次 | 当前条件与行为 |
| --- | --- |
| 控制桥任务包络 | 旧 ENU 范围为 [-60,-10,0.2]～[20,250,10] m；AB 轨迹越界只记录 |
| 控制桥参考动态／跟踪门限 | 速度 > 任务速度+1 m/s、加速度 > 任务上限+0.5 m/s²、参考位置偏差 >3 m；AB 仅记录 |
| 控制桥点云 | 超过 0.5 墙钟秒未收到新鲜云，AB 只记录失流／恢复；起飞前仍等待新鲜云 |
| 控制桥指令有效性 | 非有限 p/v/a、时间戳年龄不在 [-0.05,0.3] 仿真秒、无本地位置仍拒绝并降落；错误原因单独报告 |
| 控制桥状态与运行连续性 | 定位 >0.5、状态 >1.5、时钟不更新 >0.5 墙钟秒，估计不健康、估计重置、仿真时间倒退或退出 Offboard 会降落 |
| 控制桥阶段等待 | 起飞 >30、初次规划 >10、轨迹指令失流 >0.5 墙钟秒会降落 |
| 任务节点 | 控制状态 >1.5、位置或时钟 >0.5 墙钟秒失流会中止；AB 单航段 >300、总任务 >600 仿真秒会中止；到 B 并稳定后按 finish=land 正常降落 |
| 规划器 | 虚拟地面 -2 m／天花板 11 m、局部规划范围 20 m、速度／加速度约束仍参与算法；A* 搜索预算 0.1 仿真秒，ReplanOnce 预算由 planner_timing 选择；失败可导致停发轨迹。静止终点重规划保持最多 10 仿真秒，期满停发后会触发控制桥指令失流降落 |
| PC 任务观察器 | 实际新碰撞、任务失败、启动未确认 3 墙钟秒、等待超过 mission_timeout_s×3+60 墙钟秒会结束报告，失败收尾请求降落；runtime 外层默认 2000 墙钟秒超时 |
| PX4 | Offboard 心跳失联 0.5 秒后按 COM_OBL_RC_ACT=4 降落；PX4 自身的估计／执行故障处理继续有效，实际值以参数快照和 ULog 为准 |

门限变化写入 `trajectory_limits_changed` profile 事件及控制日志，包含具体类别、p/v/a、时间戳年龄与跟踪偏差；任务报告新增 `experiment_policies`，记录本轮策略。不要再添加隐藏的任务边界、误差门限或失流自动降落；新增会改变实验终止条件的行为必须在此表明确说明并经用户授权。上述审计不等于所有异常都继续控制：数据失效、控制失联与真实碰撞仍会结束本轮实验。

PC 改动后必须 down/up 生成新任务快照；RoboPi 还须先重新 deploy 控制桥，再 down/up。已有 release、启动快照及历史录像不会被自动修改。本次修复有合成消息回归，尚未重飞 AB。

## 飞行录像与离线回放（PC）

前置条件：PC 有 ffmpeg/libx264，离线回放使用 `flight-review` 的 NumPy/Matplotlib；板端算法不增加依赖。已有飞行报告可以生成遥测回放，但没有事先保存的 RGB／点云不能事后还原。失败报告的 `records` 在首次失败处结束，不包含 finally 收尾降落；实景录像可覆盖这一段。

实景录像使用独立外部相机，640×360，默认每墙钟秒抓取 2 帧，NoDisplay 下也可用。先从本次实际使用的 settings 生成一个新副本（不会覆盖已有文件），将本机 AB runtime 的 settings 改为该输出，再按前文 down/up：

```bash
uv run stage3/super/airsim/flight_video.py configure \
  stage3/super/airsim/settings.forest-fast.json artifacts/settings.video.local.json
# 在本机 runtime 中只改 settings 为上面文件的绝对路径；其他飞行参数保持本次实验原值。
```

**PC 终端 A**：替换当前 state-dir 和实际 run_dir；output 必须是全新的目录。可以先用另一目录录 3～6 秒静止预热并查看 PNG，再录整次飞行。录像器只查询车辆位姿并移动外部相机，不发布飞行控制、不改飞机位姿；真值只用于拍摄。

```bash
uv run stage3/super/airsim/flight_video.py record \
  --state-dir '<本次state-dir>' --output '<本次run_dir>/video' --seconds 360 --fps 2
```

**PC 终端 B**：按前文 task 执行 AB；确认解除解锁后，用 `touch '<本次run_dir>/video/stop'` 结束录像，等待终端 A 返回，再正常 down。录像遇到连续三次 RPC 错误会停止并留存 errors.jsonl，不接管飞机。相机每帧的仿真时间戳、采样墙钟、耗时和相机姿态在 frames.jsonl，原始 PNG 在 video/frames/。

```bash
# 离线编码，按相机仿真时间戳保持每张实拍帧，不做运动补帧。
uv run stage3/super/airsim/flight_video.py encode \
  '<本次run_dir>/video' '<本次run_dir>/airsim-third-person.mp4' --gamma 1.6
```

MP4 使用兼容播放器的 20 fps 容器，相同图像重复保持，实际采样仍是 2 Hz 墙钟；时间轴使用 AirSim 仿真时间，画面角标为录像起点后的仿真时长。`--gamma` 只调输出亮度，原始 PNG 保留。它不等于无开销录像；summary.json 记录抓帧耗时，本轮视频条件下结果见迁移验证。

只看轨迹时可以不启用相机，直接离线生成视频；若要显示障碍物，在前述 `trace_ros.py --compact` 旁路命令额外加 `--cloud-dir /run/airsim/visual-clouds`，每墙钟秒保存一帧配准点云，仅为显示限至最多 25000 点，不改变算法输入。旁路在 task 前启动，down 后退出。

```bash
uv run --extra flight-review stage3/super/airsim/diagnostics/replay_video.py \
  '<本次run_dir>/fly-task-实际时间戳.json' '<本次run_dir>/telemetry-replay.mp4' \
  --cloud-dir '<本次run_dir>/visual-clouds'
# 未保存点云时省略 --cloud-dir，画面会明确标示缺少障碍点云。
```

回放按仿真时间展示已记录的 PX4 估计位置、下发参考、高度和速度；没有机体姿态的补造，不能把它当作相机实拍。点云只取当前时刻以前最后保存的一帧，并标注其年龄。视频、帧、点云和运行日志都留在忽略 Git 的 artifacts，不提交仓库。

2026-10-18：NH/Town05/race 路径统一接入根 `.env`；本轮仅验证配置解析、ELF/资源存在和回归测试，未启动场景或飞行，既有飞行结论不变。

### 2026-10-19 本机场景路径配置

本仓库默认 runtime.*.json 使用 `"binary_env": "AIRSIM_NH"`，从根 `.env` 或同名环境变量读取场景 ELF 路径，环境变量优先。包根由 `<包根>/<项目>/Binaries/Linux/<ELF>` 结构推导。旧自定义配置仍支持显式 scene_dir/binary；其中 `${AIRSIM_SCENE_DIR}` 兼容从根 `.env` 读取场景目录，相对环境路径以仓库根为基准，其他相对 scene_dir 以配置目录为基准。本次未复制/重编译场景或启动仿真。

板端准备入口 prepare.py 的 --sdk/--host-python 可省略，默认读取根 .env 的 OHOS_SDK/OHOS_HOST_PYTHON；显式 CLI 参数优先。OHOS_TOOLCHAINS_DIR 指向 SDK 配套 toolchains（含 hdc），不等于 Native SDK 根。主机工作区核验由仓库 skills/oh-ros2/scripts/board_workspace.py --project . 管理，流程见该 skill 的 references/board-workspace.md。
