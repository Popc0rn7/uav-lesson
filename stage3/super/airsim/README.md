# Stage 3：SUPER 流程的 AirSim 替换后端

本入口只验证 PC 上 AirSim ↔ PX4 SITL；不接算力板，不启动 Gazebo。

## 统一运行入口

默认部署为 **PC 宿主机 AirSim + 原 PX4/Gazebo 镜像内的 PX4 SITL**。本次复用 SUPER 的起飞—往返—降落任务流程，不运行 SUPER 规划器、ROS、雷达或 Gazebo。

### 教师准备与场景配置

PC Linux 需要可用的 Docker、图形桌面/Vulkan，以及完整的 AirSim 场景包。默认使用已有 `submodules/AirSim/AbandonedPark/LinuxNoEditor`；镜像固定为本机已验收的 ID，无需构建镜像或在容器内安装 Unreal 依赖。

常规 up/status/task/down 使用 `uv run`，MessagePack 已纳入项目依赖。下面的临时环境仅供包含 pymavlink 的诊断入口使用。

**PC，课前准备诊断环境：**

```bash
uv venv /tmp/airsim-diagnostics-venv
uv pip install --python /tmp/airsim-diagnostics-venv/bin/python msgpack==1.2.3 pymavlink==2.4.50
```

默认配置为 `stage3/super/airsim/runtime.example.json`。换场景时提供自己的 JSON，并通过 `--config` 指定；相对路径以配置文件所在目录为基准，`binary` 例外，以 `scene_dir` 为基准：

| 配置 | 用途 |
| --- | --- |
| scene_dir | 完整打包场景目录，资源由宿主机直接读取，不复制到 Docker |
| binary | Linux 原生场景可执行文件；不用带额外 -settings 的 .sh 包装器 |
| scene_args | 场景所需参数，包括项目名、小窗口和 Vulkan；不传 -settings，由入口只生成一个 |
| settings | 输入 AirSim 配置；原文件不改写，入口为本次运行生成一份设置 |
| image / container | 原 PX4 镜像及专用容器名；可调整，换镜像后须重新验收 |
| task | PX4 估计 NED 坐标、米、m/s；起点 `(0,0,-3)`，终点 `(1,0,-3)`，速度 0.5 m/s，悬停 3 秒，误差容限 0.6 m |

本入口当前固定单机 `PX4`、host 网络和本机回环：TCP 4560，RPC 41451，控制 UDP 14540/14580。它会规范这些连接字段，但保留输入 settings 的传感器及 ViewMode。默认 NoDisplay 冻结主画面以减少负载，物理仿真和通信继续运行；需要看飞机时将输入设置的 ViewMode 改为 FlyWithMe，再 down/up。

场景已打包进二进制及资源文件，换地图需提供对应完整场景包，不是只替换一个 Gazebo SDF 文件。任意新场景的出生点、障碍与资源需求未验收；默认任务只验证 AbandonedPark 出生点附近短距离。

### 启动、执行与停止

**PC 图形桌面终端，仓库根目录：**

```bash
uv run stage3/super/airsim/runtime.py up
uv run stage3/super/airsim/runtime.py status
uv run stage3/super/airsim/runtime.py task
uv run stage3/super/airsim/runtime.py down
```

`up` 先启动宿主机 AirSim，检查属于该进程的 TCP 4560 监听，再启动 PX4。检查监听时不建立测试 TCP 连接，以免消耗 AirSim 的 accept。PX4 仍基于原镜像，挂载只读 `px4_start.sh` 与专用可写日志目录；启动 none_iris 和 simulator_mavlink，不启动 Gazebo。连续 IMU、有效位置、飞控健康以及 AirSim API 均通过后才报告就绪，默认总超时 90 秒。

`task` 明确执行解锁与飞行：起飞 → 起点悬停 → 终点悬停 → 返回起点悬停 → 降落解除解锁。每次运动重新申请 API 控制，每个航段有超时，并在悬停后检查实际估计位置误差；API 返回 true 不等于精确到点。异常或 Ctrl+C 会尝试取消任务并降落，参数按任务前快照恢复。通信完全丢失时降落请求不保证送达；相关失败写入报告。

独立发送降落请求：

```bash
uv run stage3/super/airsim/runtime.py land
```

每条命令可带 `--config /path/to/runtime.json`（仅 up 使用）及 `--state-dir /path/to/state`。默认状态和日志在被 Git 忽略的 `artifacts/airsim-runtime/`。task 使用当前启动时保存的配置；修改场景、任务或设置后先 down，再用新配置 up。

up 可用 `--image` 覆盖配置镜像。旧 `run_px4.sh` 已委托同一 up 实现，不再单独启动 PX4；它支持 `AIRSIM_PYTHON` 指定上述 Python 环境，并保留 `AIRSIM_PX4_IMAGE` 镜像覆盖变量。

重复 up 会检查同一配置的现有实例并复用；配置改变或状态异常时保留现场，不覆盖已有记录。down 确认 PX4 未解锁后停止两边，仅操作本入口的 PID/start time/二进制/设置路径和带唯一标签的容器 ID；日志保留。任务与生命周期命令互斥，task 中可用 Ctrl+C 触发降落。无法确认状态时，可显式 `down --force` 停止本入口拥有的仿真实例，不处理未知进程或容器。

### 成功判据、故障恢复与证据

- 成功：up 输出“AirSim 已监听”再输出“已就绪”；status 为双方运行、Disarmed/Hold；task 输出三个到点误差、任务通过和报告路径；最后降落解除解锁。
- TCP 端口检查使用 SO_REUSEADDR 并尝试 listen，容许退出后的 TIME_WAIT，但仍拒绝真实监听者；只有 EADDRINUSE 报占用，其他权限/网络错误保留原始原因。随机测试端口已复现旧检查在无监听者的 TIME_WAIT 状态下误报，新检查通过；真实监听者仍被拒绝。
- 端口或同名容器冲突：先用 `ss -ltnp`、`ss -lunp`、`docker ps -a` 确认已有实例用途。入口不会接管手动启动的 AirSim/PX4；先自行停止确认属于本任务的旧实例。
- 场景启动失败：查看本次 `airsim-console.log`；PX4 无传感器/定位不健康：查看 `px4-console.log` 与 `px4-logs/`。启动失败会清理本次创建的两边并保留记录；不关闭健康检查强行通过。
- 场景或 PX4 单独退出：不承诺自动重连，用 status 保留诊断，再 down/up 重建整对实例。
- down 报未解除解锁：先 land。Docker 不可访问、RPC 失联或无法验证进程身份时保留现场，不默认停止未知资源。

2026-10-14 实测统一入口：正常 up、重复 up 复用、往返 task、正常 down 均通过。3 m 高度、1 m 往返，起点/终点/返回点悬停后估计误差分别 0.171 / 0.139 / 0.252 m，passed=true，最终 Disarmed/Hold。证据 `artifacts/airsim-runtime/61b56b62d2c2433bb2d142306b37a760/task-1791965781267682773.json`，同目录保留 AirSim/PX4 日志及 ULog。

生命周期实测：用 /tmp 原生测试进程分别模拟 AirSim 不监听和已监听但不发送 HIL 传感器，两种启动超时都清理自有 PID/容器，phase=stopped，日志保留；未带标签的同名测试容器被拒绝接管且 ID 不变；管理锁冲突拒绝 down；实际仿真地面解锁后 down 被拒绝，随后 land 恢复解除解锁，未发起飞命令。故障证据位于 `/tmp/airsim-failure-no-listen/`、`/tmp/airsim-failure-listen/`。未验收飞行中断连或 task 的 Ctrl+C 故障降落分支。


## 本轮问题分级与边界

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
