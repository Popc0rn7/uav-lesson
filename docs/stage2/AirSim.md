# Stage 2：AirSim＋PX4 竞速环境

Stage 2 使用 **PC AirSim 场景＋一个 PX4 SITL Docker**，不需要 Docker 2。先直接通过 MAVLink 验证 PX4 起降和运动，再接 QGroundControl（QGC）手动穿门竞速。后续阶段沿用场景和飞控容器，按自主算法需要增加 Humble Docker，再将算法迁移到 RoboPi。原 [Gazebo Hands-on](Hands-on.md) 和 [实测记录](Validation.md) 保留既有操作与验证边界。

## 组件与控制链

| 组件 | 职责 |
| --- | --- |
| PC AirSim / ADRL | 竞速场景、物理、传感器及赛门；使用本机已准备的包 |
| Docker 1 | 只运行 PX4 SITL，不运行 Gazebo；复用现有 PX4 运行镜像 |
| PC MAVLink 测试 | 直接向 PX4 发本地 NED 设定值，验证起降和短距离往返 |
| PC QGC | 后续由学员通过同一 PX4 完成手动竞速；当前不作为调试依赖 |
| 竞速 client | `start-race` 接原生 Tier 2 开赛、准备区与计时；手动飞行期间不获取 API/Offboard 控制，完整穿门计分仍待验收 |
| Docker 2 | 后续自主算法阶段再接入，Stage 2 不启动 |

当前入口为 `stage2/airsim/race.py`，复用 SUPER 的端口检查、进程身份检查、Docker 回收及 MAVLink 诊断工具。PC 的 `session.py` 为每个实例保持一条 AirSim RPC 连接，本地命令通过本轮目录的 Unix socket 请求查询；它不发送飞行设定值，也不是 Docker 2。关闭时先停止场景，再回收该代理，避免旧 rpclib 的短连接关闭竞态。Stage 3 的默认 SUPER 任务不参与本节启动。测试通过 PX4 估计位置控制；AirSim RPC 只检查状态和评测碰撞，不把场景真值反馈给控制。

## 教师准备（PC）

- Linux x86_64 图形桌面、X11/XWayland 和可用 Vulkan；本机包不包含 OpenGL RHI，不能使用 `-opengl4`。
- 已有 Docker Engine 和 `px4io/px4-sitl-gazebo` 镜像，包含 `10016_none_iris` 与外部 MAVLink 仿真模块。启动前 inspect 并固定实际镜像 ID；不自动拉取或编译。
- 本机竞速包软链接 `submodules/drone-race/ADRL` → `/home/wqy/airsim-drone-racing-lab/bin/ADRL`，需包含 `Engine`、`ADRL/Content`、`ADRL/Binaries/Linux/ADRL`。新 PC 单独准备包与链接。
- 上游子模块 commit `ecb0993c7ddd91d1e3c528cb207f61b59079aac2`，代码 MIT；二进制场景包的分发许可和资源要求需另行核实，不将包提交 Git。

**PC 仓库根目录**，课前安装依赖并检查场景与镜像：

```sh
uv sync --extra stage2 --extra flight-review
readlink -f submodules/drone-race/ADRL
test -x submodules/drone-race/ADRL/ADRL/Binaries/Linux/ADRL
sha256sum submodules/drone-race/ADRL/ADRL/Binaries/Linux/ADRL
docker image inspect px4io/px4-sitl-gazebo:latest --format '{{.Id}}'
docker ps --format '{{.Names}} {{.Image}}'
```

成功判据：ELF 可执行、场景资源完整、镜像存在，且没有其他实例占用同一组端口。`flight-review` 用于教师飞后查看 ULog；模型下载、ROS 构建均不属于本节。当前兼容副本只支持 SHA-256 为 `094ad6b3cb8f55b63a05ab6ca9ee91e18c3eac1d21b64b20451302ba427c68bc` 的 ADRL ELF，换包时拒绝套用固定地址补丁。

## 兼容副本与配置

Stage 2 入口通过 `prepare.py` 在忽略 Git 的 `artifacts/stage2-airsim/package-realtime-sitl/` 创建 ELF 副本并链接原场景资源。保留此前 `clearTrajectory()` 的 API 控制状态 guard，并跳过旧包处理执行器消息时自动启用锁步的分支；原来的执行器数据更新、取消任务和清空轨迹逻辑保留。原始包不修改，输入/输出摘要写入 `compatibility.json`。历史 `package/`、`package-realtime/` 副本保留但当前入口不再使用。此方案是已知旧包的二进制兼容适配，不是上游源码重新构建产物。

反汇编定位：原虚调用位于 VA `0x2d933a6`；guard 使用该包虚表 `0x50` 的 API 控制状态查询，允许时尾调用原 `0x2d0` 的速度方法。补丁使用可执行 LOAD 段尾的零填充并扩展该段大小，不覆盖其他代码。原生执行测试覆盖控制开启/关闭两条分支、参数保留及未知 ELF 拒绝；不将这些测试等同于整套仿真验收。

旧包自动锁步入口位于 VA `0x2e1b2c2`：原 `0f8509fdffff` 仅在已经进入锁步时跳过初始化，否则依据 HIL flag / 时间戳启用；该段未检查 settings 的 LockStep 开关。实时副本改为无条件跳到原清理出口 `0x2e1afd1`，不改前面的执行器数据更新。配合 **ScalableClock / LockStep=false**，让 HIL 按实时时钟持续推进。当前 SITL 实时副本 SHA-256 为 `06a867622f0a02942b17e82793b7d5a073ad6ee325a720567578b32598790b27`。入口拒绝不一致的时钟输入，未知原包摘要或原指令不匹配均拒绝修改。Stage 3 不使用该副本，其时钟配置不变。

维护输入为 `stage2/airsim/settings.json`。唯一受控车辆名为 `PX4`，sysid=1；旧包显式配置 IMU、GPS、磁力计和气压计。场景从兼容副本可执行文件旁的 `settings.json` 读取本轮设置快照，不覆盖用户 `~/Documents/AirSim/settings.json`。输入修改后先 down/up，不修改生成文件或历史快照。

PX4 飞控的 MAVLink 身份仍为 1/1；AirSim 设置中的 `VehicleSysID` 是其控制客户端自身的身份，已恢复上游默认 135（compid 1），避免与飞控 1/1 重复。不能将它当作飞控目标编号。出生 `X/Y/Z/Pitch/Roll/Yaw` 已省略，由原生赛务从 `start_block` 的 `race_start` 组件分配固定出发槽位，不能用 PlayerStart 或自定坐标替代。

仓库 Stage 2、Stage 3 的 AirSim 启动入口均注入 Unreal Input 设置：`bCaptureMouseOnLaunch=False`、`DefaultViewportMouseCaptureMode=NoCapture`、`bDefaultViewportMouseLock=False`、`DefaultViewportMouseLockMode=DoNotLock`，并传入 `-NoMouseCapture`。用于关闭启动抢鼠与窗口锁鼠；无需修改原场景包。外部直接双击启动不经过本仓库入口，需要另行携带这些参数。

默认 level 为最简单的足球场 **`Soccer_Field_Easy`**，视角为 **`SpringArmChase`**（键盘 `/` 对应的跟随视角）。窗口使用 `-windowed`，启动器按当前桌面的可用区域最大化，保留窗口边框和桌面面板，不进入 fullscreen。只向本次场景 PID 的窗口发送最大化请求，并检查窗口管理器返回状态；需要支持 EWMH 的 X11/XWayland 桌面。出生点和朝向取原生固定准备区，相机配置沿用原输入。

旧包实测仅写 `Default Environment` 仍停留在 MainMenu。启动器在 **PX4 容器启动前** 经持久 RPC 执行 `simLoadLevel`、`simResetRace`，让原生赛务将两个机体放到固定出发槽位，再启动 PX4；之后只读取赛门、传感器、定位和起点误差，不再次切图或修改位姿。仅调整顺序和 JSON 时钟仍发生过停流，当前使用上面的实时兼容副本。不自动解锁、不启动比赛。preflight 是独立的解锁条件：未通过时保留场景供 QGC 配置和等待收敛，不因当前 Manual 模式未满足解锁条件而回收窗口；自动 `test` 仍要求 preflight 通过。若场景加载失败或传感器/定位超时，保存 `startup-error.json` 后回收本轮资源。

| 链路 | 端点 |
| --- | --- |
| 仿真 | PX4 TCP 客户端 → AirSim TCP 4560 |
| 旧 AirSim 控制/遥测 | AirSim 临时 UDP 源端口 → PX4 UDP 14580；旧兼容字段 `ControlPort` / `SitlPort` 指向远端 14580 |
| 地面站 | PX4 UDP 18570 → PC UDP 14550 |
| 独立 MAVLink 测试 | PX4 payload 链路 → PC UDP 14030 |
| AirSim RPC | PC 回环 TCP 41451 |

只支持本机 host 网络、单套实例。换容器名不隔离端口。当前车辆命名和基础运动测试不代表 ADRL 穿门计分已经适配。

## 启动与直接控制 PX4（PC）

前提：从能访问 X11 的 PC 桌面终端操作，`DISPLAY` 与桌面授权有效。**PC 仓库根目录，终端 A**：

```sh
uv run stage2/airsim/race.py up
uv run stage2/airsim/race.py status
```

可用 `up --display :1` 显式选择当前会话，但显示器和 Xauthority 由本机桌面决定，不硬编码其他用户的授权文件。预期出现 ADRL 窗口，只启动 `uav-stage2-airsim-px4` 一个容器，终端报告仿真链路就绪；此时不自动解锁。连续传感器、有效本地位置与 RPC 通过后才标记 ready，preflight 单独报告；`status` 同时读取当前 commander 状态及检查结果。TCP 4560 只有 TIME_WAIT 时自动等待最多 75 秒，不并发重试。

默认应直接看到 Soccer_Field_Easy 足球场的原生准备槽位和飞机后方跟随视角；终端报告赛门数量与切图后就绪。`status` 的 `startup`、`window`、`level_loaded` 记录本轮默认项、实际窗口状态和已发现的赛门。教师可用 `up --settings /绝对路径/settings.json` 选择另一个输入，或 `up --window-mode windowed` 使用普通 1280×720 窗口；默认仍为最大化。更改后先 down/up。

**PC 终端 B**，先手动开赛，再运行控制器。开赛本身只调用原生 Tier 2 赛务、开放出发区并开始计时，不解锁、不起飞：

```sh
uv run stage2/airsim/race.py start-race
```

应看到原生比赛 UI / 计时，`status` 的 `race.phase` 为 `racing`；原生占位机 `drone_2` 在 Tier 2 被赛务隐藏。开赛前 `test` 会拒绝执行。基础测试会实际解锁并飞行；先确认出生点附近上方 2 m、水平 1 m 的空间可用：

```sh
uv run --extra stage2 stage2/airsim/race.py test
uv run stage2/airsim/race.py status
```

预期：PX4 Offboard 预发送后解锁，起飞至本地参考原点上方 2 m、悬停；以约 0.262 m/s 的参考峰值沿本地北向前移 1 m 再返回，最后请求降落并确认落地解除解锁。坐标为 PX4 本地 NED，单位米；Z 向下，不能把它当作场景世界坐标。往返轨迹按 PX4 仿真时间推进，墙钟只用于超时和失流检测。

短程测试限制水平 4 m / 高度 5 m 包络、起飞稳定等待 35 墙钟秒、降落确认 55 墙钟秒；跟踪/返回误差阈值为 0.8/0.3 m。测试临时设置无 RC 的 Offboard 模式及设定值失流降落参数，不关闭电源或其他解锁检查；确认落地或交还控制后恢复原值并读回核对。异常后不能确认落地、且尚未交还控制时，保留失流降落配置，原值记入 `parameters_restore_deferred`，由 land/stop 恢复现场后 down/up。报告写入本轮 `flight-*.json`；复用 SUPER 原始 PX4 启动脚本，并将本镜像实际 rootfs 的 `/root/.local/share/px4/rootfs/fs/log` 挂载到本轮 `px4-logs/`；换镜像必须复核实际路径。每轮额外保存 `flight-*.ulg` 快照与 `.ulog-review.json`，避免 PX4 日志清理删除历史飞行证据。复盘缺依赖或日志时明确记录限制，不输出零误差。失败报告也保留；默认 `success=true` 要求运动、误差、无新碰撞、落地解除解锁和参数恢复均通过，复盘可用性单独报告。

正常结束，**PC**：

```sh
uv run stage2/airsim/race.py down
```

默认 down 要求已确认解除解锁，仅回收本入口拥有的进程/容器并保留日志。没有通过实际飞行的配置不能作为课堂已验收流程。

## QGroundControl 连接与手动输入（PC）

先启动上述仿真，再打开同一台 PC 上的 QGC。默认 UDP 自动连接监听 `14550`，PX4 使用 `127.0.0.1:18570 → 127.0.0.1:14550`；不连接 AirSim 的 41451 或 4560。若未自动发现，在 QGC Application Settings → Comm Links 新增 UDP 链接，监听端口填 `14550`，远端地址保持空白，然后 Connect。自动连接与手动链接二选一，避免重复监听同一端口。成功判据为显示 PX4 车辆、电池与姿态持续更新，连接未丢失。

在 Vehicle Setup → Parameters 确认 `COM_RC_IN_MODE=1`（Joystick；当前镜像实测默认值）。使用屏幕摇杆时，在 Application Settings → General 启用 Virtual joystick；使用 USB 手柄时，在 Vehicle Setup → Joystick 选择设备、校准轴并启用，先检查轴方向与回中。菜单位置随 QGC 版本可能变化，参见 [官方虚拟摇杆说明](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/settings_view/virtual_joystick.html) 和 [Joystick 设置](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/setup_view/joystick.html)。

QGC 手动飞行也先执行上述 `start-race`，看到原生 Go / 计时和出发区开放后，再选择 Position 模式，等待定位与解锁检查通过，低高度起飞；用 AirSim 窗口观察飞机，用 QGC 摇杆控制 PX4。不要同时运行 `race.py test`。解锁失败先读 QGC 的检查消息并确认摇杆持续发送，不通过关闭检查或设置 `COM_RC_IN_MODE=4` 来替代摇杆配置。结束选择 Land，确认落地 Disarmed 后 down。当前已核实 QGC 心跳双向连通与参数，QGC 摇杆实飞、穿门竞速仍待验收。

诊断时区分连接和手动输入：2026-10-16 当前实例实际为 `gcs_connection_lost=False`、`manual_control_signal_lost=True`，本地/全球位置、姿态有效；这表示地面站在线但没有有效摇杆输入，不能把 Not Ready 当作 UDP 未连通。启用摇杆并查看 QGC 解锁检查，不能仅凭历史 GPS 警告判断当前定位故障。旧包 `Unsupported main mode` 也会通过 MAVLink STATUSTEXT 显示在 QGC，单条消息不足以定位连接或解锁问题。

比赛复位入口为 PC 命令 `uv run stage2/airsim/race.py reset-race`。仅允许已解除解锁且 API 控制关闭；保留本轮输入、镜像和窗口方式，完整重启并返回 `prepared`，端口释放可能需等待最多 75 秒；下一轮仍须手动 `start-race`。启动不再调用 `simSetVehiclePose`，也不再读取 PlayerStart 作为出发点。原生源码 `URace::placeRacersAtStartPositions` 要求恰好两个参赛机体，此前单机体导致复位不摆放。当前保留唯一受控的 PX4 飞控机体，加一架原生 `SimpleFlight` 占位机 `drone_2`；它没有第二个 PX4 容器或课程控制器，开赛后由 Tier 2 隐藏/取消碰撞，不运行对手算法。

所有 ADRL 关卡共用此流程，准备位来自各自原生地图。启动时先由赛务摆放，再让重力和碰撞正常工作，连续检查两机体速度均小于 0.1 m/s、传感器和定位就绪，才标记 `prepared`。不暂停整个仿真来代替准备区。`start-race` 调用原生 `simStartRace(2)`，观察原生占位机退出比赛后才标记 `racing`；Python client 的 `simIsRacerDisqualified` 实际对应 RPC `simGetDisqualified`。课程自动控制器在此之前不建立控制链、不给设定值；若原生比赛被复位，也拒绝新控制任务。QGC 为独立地面站，操作者必须遵守先开赛再解锁的顺序；本入口不拦截它的所有 MAVLink 命令，不将此声明为额外的飞控权限隔离。

原生机制核对见固定源码快照 [Race.cpp](https://github.com/microsoft/AirSim-Drone-Racing-Lab-Source/blob/93a461fa90ee59fadf82e8cadaa5e3db80fe50b0/Unreal/Plugins/DroneRacing/Source/DroneRacing/Private/Race.cpp)、[RacingLibrary.cpp](https://github.com/microsoft/AirSim-Drone-Racing-Lab-Source/blob/93a461fa90ee59fadf82e8cadaa5e3db80fe50b0/Unreal/Plugins/DroneRacing/Source/DroneRacing/Private/RacingLibrary.cpp) 和 [CompManager.cpp](https://github.com/microsoft/AirSim-Drone-Racing-Lab-Source/blob/93a461fa90ee59fadf82e8cadaa5e3db80fe50b0/Unreal/Plugins/DroneRacing/Source/DroneRacing/Private/CompManager.cpp)。源码用于核对行为，不宣称本机 ELF 由该提交重新构建。Stage 3 的非 ADRL 场景不具备这套原生赛务，不能直接声称已接入竞速生命周期。


## Offboard 控制权与退出（PC）

默认 `test` 自动管理 Offboard，不需要另开脚本切模式：预发送设定值 2.5 秒；切模式和解锁分别等待命令 ACK 及真实 PX4 心跳状态，最长各 6 秒；收到拒绝则中止，不盲目重试解锁。带目标字段的 ACK 只接受发给本客户端 sysid 245 的回复（旧式无目标字段的回复仍结合实际状态判断）。位置/速度/加速度设定值约 50 Hz，记录实际最大墙钟发送间隔。

一旦新鲜 PX4 心跳显示已经退出 Offboard，或飞行中被解除解锁，当前控制器锁存退出：不再发设定值，不切回 Offboard，也不在异常清理中强制发 Land 覆盖接管者。降落中若被切到其他模式，也停止重发 Land。正常脚本任务被外部接管时保留未完成结果与 `control_released/released_mode`；这与脚本崩溃有明确区别。心跳停流属于通信故障，不据过期模式声称人工接管；本机无法继续发送设定值时，PX4 的失流策略负责后续处理。

**PC 仓库根目录**，教师可在同一实例落地后验证失流退出：

```sh
uv run --extra stage2 --extra flight-review stage2/airsim/race.py test --finish loss
```

该模式仍先起飞和往返，再停止设定值、继续发客户端心跳，要求 5 墙钟秒内观察到 LAND，并确认落地解除解锁；不通过主动 NAV_LAND 冒充失流降落。它临时使用 `COM_OF_LOSS_T=0.5` 与 `COM_OBL_RC_ACT=4`，结束恢复并核对原值。

**PC**，验证外部 Hold 接管的协议路径（无需 QGC GUI）：

```sh
uv run --extra stage2 --extra flight-review stage2/airsim/race.py test --finish handoff
# 本项通过后飞机保持空中 Hold；由管理入口明确请求降落。
uv run stage2/airsim/race.py land
uv run stage2/airsim/race.py status
```

验证器通过 MAVLink 模式指令模拟接管请求，观察控制器退出，继续观察 Hold 2 秒，要求没有新增设定值或重新进入 Offboard。该模式的 `success=true` 表示接管验证通过，报告同时明确 `landed_disarmed=false`；不能当作降落完成。随后独立执行 land，并通过 status 确认 Disarmed；未解除解锁时不 down。人工 land 会取消本轮，下一轮试飞先 down/up。

本节验证的是 PX4 模式协议、控制器退出与恢复路径，尚未验证 QGC GUI、虚拟摇杆或物理手柄的人工飞行。

## 故障恢复（PC）

```sh
uv run stage2/airsim/race.py status
uv run stage2/airsim/race.py land
# 仅在碰撞、卡住或不能正常降落时，仿真急停：
uv run stage2/airsim/race.py stop
```

`land` 请求 PX4 降落并取消本轮测试；仍须通过 status 确认解除解锁。人工 land/stop 后重新测试需 down/up。stop 是仿真资源回收，不记为降落成功。启动中的 up 应先 Ctrl+C，等待启动清理完成后再 status。未知端口占用、同名未知容器和未知资源文件会拒绝接管/覆盖，不杀其他进程。

若启动失败，按终端给出的运行目录查看 `airsim-console.log`、`px4-console.log`；场景崩溃后的 UDP 错误不一定是网络根因，应先定位第一个异常。`No IMU with name ... exist on vehicle` 表示旧包没有得到 IMU，检查显式 Sensors 输入。当前 SITL 适配已省略旧包不合法的 HIL 模式请求；若新日志仍出现 `Unsupported main mode`，检查是否使用本文的 `package-realtime-sitl` 启动入口，修复说明见下文。旧包还可能输出天气资源/材质告警，需与真正的初始化异常区分。

窗口突然消失时先检查 `status` 的 `startup_error` 和本轮 `startup-error.json`。切图期间一次 `sensor_combined -n 2` 查询超过 6 秒，旧入口会直接退出并回收窗口；现改为在总启动期限内继续检查。只有场景退出、明确加载错误或总体等待超时才失败。`Preflight check: FAILED` 也不再单独触发启动回收；它仍禁止自动试飞，并需在 QGC 中解决后才能手动解锁。

## 验证记录


2026-10-11 旧工作目录记录了 TCP 和单次传感器连通，但随后在 `clearTrajectory` 的控制请求检查处崩溃；没有完成 QGC 飞行。

2026-10-16 已完成实际基础飞行：ADRL 包的默认 MainMenu / Blocks 初始场景、PX4 commit `61907962c9220437ec01a98fa26bfbf5cbb254b5`、本机镜像 ID 前缀 `70584c9eb1e9`、Vulkan/X11；没有 QGC 或 ROS 容器。场景输入和控制参数未沿用 SUPER 的高速或 GPS 前馈配置。当前修复依据如下：

- 原初始化崩溃：独立 ELF 副本为 `clearTrajectory` 的速度指令添加 API 控制状态条件。
- GDB 抓到 `No IMU with name ... exist on vehicle`：补齐旧包需要的显式 IMU/GPS/磁力计/气压计，不以现代 AirSim 的隐式默认推断旧包行为。
- 系统调用证实旧兼容端口字段表示远端：修正为 PX4 14580；原来错误指向 14540 时收到 ECONNREFUSED，socket 关闭后心跳继续发送触发 EBADF。
- 旧包 GCS 心跳也使用 1/1：只接受 autopilot=PX4 的心跳来判断模式/解锁，避免转发的 GCS 心跳造成 `Mode(0x00000000)` 误判。第一次起飞因此误判中止，随后已降落解除解锁，失败报告不改写。
- 后续冷启动飞行发现旧 rpclib 短连接关闭竞态：`shutdown: Bad file descriptor` 使场景退出，lockstep PX4 停流，本轮只能仿真急停，不能记为降落。最终改为每实例一条持久 RPC 连接。另一轮新 rootfs 尝试出现 HIL 停滞，原因未定位；最终保留原 PX4 启动方式，仅修正日志挂载。

运行 `b6322aee8c3c4944a6485c1aca6addf9` 的 `flight-1792122631826486127.json` 已通过：起飞至 2 m、悬停、北向 1 m 平滑往返、正常降落解除解锁，运动期间无新碰撞；在线最大位置跟踪误差 0.161 m，返回误差 0.086 m。对应 ULog 往返段复盘位置误差 P95 0.135 m、姿态误差 P95 0.913°，未见 XY/Z/航向估计重置、高端电机饱和或推力/力矩分配未达成。该轮 ULog 从容器实际 rootfs 目录读回；后续入口将日志直接挂载到已核实路径，保留原 PX4 启动方式。

最终版本冷启动运行 `1942c49f7d2846538cd1095f303635cc`，报告 `flight-1792123357727437215.json`：完整起飞、悬停、1 m 往返、降落解除解锁通过，往返期间无新碰撞；最大跟踪误差 0.126 m、返回误差 0.080 m。ULog 自动落盘、独立快照和复盘均成功；往返段位置误差 P95 0.113 m、姿态误差 P95 1.077°、角速度误差 P95 0.0235 rad/s，无估计器重置、高端电机饱和、推力/力矩分配未达成或 ULog 掉包/损坏。飞后经持久 RPC 连续查询 200 次后，传感器、定位和 preflight 仍就绪；随后正常关闭。该记录是最终配置一次冷启动飞行验证，不宣称多轮成功率或新 PC 复现已验收。

上述基础版本通过四项回归（guard 两分支/参数、未知二进制拒绝、转发 GCS 不覆盖 PX4 心跳、仅 GCS 不算就绪）。运行记录、设置快照、ULog 与复盘均位于忽略 Git 的 `artifacts/stage2-airsim/`，没有修改原场景包或用户 Documents 设置。

### Offboard 进入、失流与接管补充验证（2026-10-16）

运行 `afb433304050483fa78a1923bf06aedf`，沿用同一场景/镜像与短程路线，三轮之间不重置现场；改动只在 PC 控制器，不修改 PX4 固件或仿真执行器链路。

| 结束方式 | 实测结果 | 在线最大跟踪 / 返回误差 | 报告 |
| --- | --- | --- | --- |
| loss | 停止设定值约 1.36 墙钟秒后观察到 LAND，随后落地解除解锁；最大设定值发送间隔 22 ms | 0.110 / 0.074 m | `flight-1792124067541211555.json` |
| land | 正常起飞、往返、主动降落解除解锁；最大发送间隔 26 ms | 0.134 / 0.060 m | `flight-1792124145321621206.json` |
| handoff | 接管到 LOITER，观察 2 秒期间新增设定值为 0；最大发送间隔 21 ms。随后由独立管理命令降落并确认解除解锁 | 0.155 / 0.088 m | `flight-1792124225282291315.json`、`handoff-recovery.json` |

1.36 秒包含心跳模式发布/接收的观察延迟，不是 PX4 内部失流计时器的精确延迟。handoff 轮保存了 mode 命令 176 / arm 命令 400 的 accepted ACK 与对应 OFFBOARD/解锁状态；三轮均核对恢复 `COM_RC_IN_MODE=1`、`COM_OF_LOSS_T=1`、`COM_OBL_RC_ACT=0`。ULog 往返段位置误差 P95 分别 0.103 / 0.121 / 0.131 m；均无估计器重置、高端电机饱和、推力/力矩分配未达成或日志掉包/损坏。handoff 的 ULog 快照覆盖交还控制前的飞行，后续降落确认另存于恢复记录，不将二者混为控制器自己完成降落。

Python 语法检查与 9 项回归通过，新增覆盖他人 ACK 不确认本客户端命令、拒绝 ACK 中止进入、接管后阻止设定值/模式/清理 Land、降落中接管和过期心跳不误判人工接管。故障场景的单元测试与三项协议实测不等于 QGC 人工操作或多机控制验收。

QGC 手动飞行、顺序穿门/漏门规则、竞速计时、排行榜、竞赛重置与后续阶段迁移仍待验收。直接控制 PX4 的基础运动通过也不能替代这些验收。

### Building99 默认启动补充验证（2026-10-16）

运行 `3b3b5d743065466e90647d162aafb9b9` 完成默认配置冷启动：自动调用 `simLoadLevel("Building99_Hard")`，发现 13 个赛门，切图后传感器、本地定位和 preflight 连续就绪；最终 PX4 为 Disarmed / Hold，无 failsafe。X11 确认水平与垂直最大化且无 FULLSCREEN，客户区为本机桌面可用的 1876×927；截图为飞机后方跟随视角。输入快照与 `startup-building99.png` 留在该轮目录。本项只验证场景启动默认值，未在 Building99 起飞，不将前述 MainMenu / Blocks 的飞行结果转记为 Building99 飞行验收。

同日用户报告启动关窗：原用户轮次 `f1c601a3bdff46d1ad0532502033755c` 没有保存终端错误，不能仅凭其退出日志确认触发原因。后续复现分别得到当前 Manual 模式 preflight 持续 FAILED 导致总体超时，以及 `aa063780c4c5498b99a7a4ed3f35bb04` 切图后 `sensor_combined -n 2` 超过 6 秒导致立即清理，后者 traceback 已保存。修复将仿真初始化与解锁条件分开，并对单次 PX4 查询超时在总期限内重试；失败原因写入状态与独立 JSON。

修复后 `ef1ce91337a5448dbd7de5e6d32accfe` 冷启动通过：Building99 13 个赛门、传感器/定位就绪，窗口非全屏最大化 1876×927；当前 Disarmed / Manual、无 failsafe，preflight FAILED 被明确报告但场景保留。QGC 已在 PC 监听 UDP 14550，PX4 地面站实例收到 sysid255/compid190 心跳，端点为 18570→14550，`COM_RC_IN_MODE=1`。11 项回归和 Python 语法检查通过；新增覆盖初始化允许 preflight 未通过、自动试飞仍拒绝，以及切图查询超时不直接抛出。没有进行 QGC 摇杆飞行，本轮保留运行供用户配置。

### 鼠标与地面站身份修正（2026-10-16）

- 本机聚焦 ADRL 窗口后，X11 `XGrabPointer` 探测返回 0，未被场景独占捕获；启动参数包含统一的 NoCapture / DoNotLock 设置。Stage 3 入口共用这些参数，未在本轮启动 Stage 3 场景。
- 旧顺序下多次出现切图/在线复位后的 HIL 停流，非 lockstep 候选也未解决，已撤回。当前顺序先地图与起点，后 PX4，运行后仅读取校验；`reset-race` 完整重启，不在线瞬移。独立 Offboard 验证器本轮仍有等待 payload 遥测超时，未解锁的失败报告保留，不能转记为起降通过。
- 从 QGC 实际目的 UDP 14550 被动采样，确认 PX4 为 sysid1/compid1/autopilot12/type2，AirSim 为 sysid135/compid1/autopilot0/type6，不再共用 1/1；不会把 AirSim 的未解锁 GCS 心跳当作飞控状态。原输入 VehicleSysID=1 是本次地面站状态污染的明确配置问题。

最终运行 `2fe6a0a90f984196a22809988b6aed47` 使用原 SteppableClock / LockStep、QGC 已连接，直接 PX4 CLI 验证低高度起降，未增加第二 MAVLink 控制客户端：临时 COM_RC_IN_MODE=4、MIS_TAKEOFF_ALT=1，Takeoff→Hold→Land→Disarmed。ULog `direct-px4.ulg` 记录仅一次 1→2→1 解锁变化、全程 failsafe=0，最大高度 0.980 m、水平偏移 0.021 m；最后 landed=1。落地后恢复并读回 COM_RC_IN_MODE=1、MIS_TAKEOFF_ALT=2.5。

`direct-px4-review.json` 覆盖完整解锁区间：姿态误差 P95 0.204°、角速度误差 P95 0.00969 rad/s，无 XY/Z/航向估计重置、无高端电机饱和或 ULog 掉包/损坏。完整区间含地面启停，力矩未达成占比约 8.5%，不宣称全段分配无异常；本项不是位置轨迹跟踪或穿门验收。`direct-px4-summary.json`、`qgc-heartbeat-review.json` 和原 UDP 数据保留在本轮目录。该记录验证真实 PX4 状态稳定和地面站身份隔离，尚未完成用户手持 QGC 摇杆的穿门飞行，也未逐帧验收 QGC GUI 标签。

最终 Python 语法检查、Stage 2 的 14 项回归通过；共享 runtime 的 7 项恢复回归中 6 项通过、1 项按条件跳过。本轮最终保留场景运行，飞机已落地解除解锁、Hold、preflight OK，供 QGC 继续操作。

### QGC 自行断连：旧包自动锁步停流修复（2026-10-16）

用户重新 up 的 `3c669a2b4a824b6193e1781080f7b5b8` 在进程存活、缓存 commander 仍显示 Disarmed 时，IMU 无法提供第二帧，QGC 目的 UDP 14550 的 5 秒抓包没有心跳；AirSim RPC 仍正常且未暂停，HIL TCP 连接仍 ESTABLISHED、收发队列为空。这次断连的直接原因是仿真输入停流、PX4 锁步时钟不再推进，不能通过继续显示缓存状态或放宽 QGC 超时解决。QGC 当时有两个 14550 监听，本轮未修改它们，修复后在相同 QGC 配置下验证。

反汇编确认旧包会依据 HIL flag / 匹配时间戳自动启用锁步，入口分支未检查 JSON 的 LockStep；此前只改 JSON 的非 lockstep 尝试不足以关闭该行为。新增受摘要和指令约束的实时副本，保留执行器更新并跳过自动锁步，默认 ScalableClock / LockStep=false。原包、历史兼容副本及 Stage 3 不改。原生 x86_64 测试实际执行原/修改后的比较与跳转片段，覆盖初始和已激活两种状态，确认实时分支不再进入锁步初始化；并保留原 clearTrajectory guard 测试。

最终 `62a0dc5b992b4ae085dc31999cdbe3ac` 冷启动后持续 IMU 时间戳推进、preflight OK。对 **QGC 实际入口**连续被动采集约 180 秒：180 个 PX4 心跳，首末跨度 178.998 s，最大间隔 1.0024 s，超过 2 秒的间隔为 0；20 个样本处于 Armed，覆盖 1 m 起飞、悬停及落地。AirSim 的 180 个 GCS 心跳保持 sysid135，PX4 为 sysid1。结束查看实际 QGC GUI 为 Ready / Hold；这是一次三分钟验证，不宣称长期稳定性或新机器验收。

PX4 CLI 起降报告 `direct-flight.json`：最大高度 0.973 m、水平偏移 0.0224 m，仅一次解锁和落地解除解锁，无 failsafe。COM_RC_IN_MODE 与 MIS_TAKEOFF_ALT 已恢复原 1 / 2.5。ULog 快照和 `direct-flight-review.json`：无日志损坏/掉包或 XY/Z/航向估计重置，姿态误差 P95 0.249°、角速度误差 P95 0.0132 rad/s，无高端电机饱和或推力未达成；完整解锁段含地面启停，力矩未达成约 9.9%，不宣称全段分配无异常。

证据另含 `qgc-heartbeats.jsonl`、`qgc-heartbeat-summary.json`、`qgc-connected.png`。15 项 Stage 2 回归、Python 语法和 diff 检查通过。`status` 新增 `live_sensor_position_ready`，实际采两帧递增传感器、定位与 RPC，避免把历史 phase=ready 当作当前链路健康；此字段不等于允许解锁。最终场景保留运行，飞机落地解除解锁、Hold，仍需用户完成 QGC 摇杆穿门验收。


### Unsupported main mode 初始化请求修正（2026-10-16）

用户在足球场启动时看到 QGC `Error: Unsupported main mode`，时间对应旧包初始化。源码和反汇编确认：`setHILMode()` / `setNormalMode()` 构造 MAV_CMD_DO_SET_MODE（176），只填写基础 Mode，将 CustomMode / CustomSubmode 留为 0；当前基础模式保留 CUSTOM_MODE_ENABLED 时，PX4 会将其解释为不支持的主模式 0。此前失败请求没有使 SITL 进入 HIL；正常起降并不依赖它。

当前入口使用 `package-realtime-sitl`，在原摘要和指令校验下，将 VA `0x2e1b8ab` / `0x2e17c9b` 的两处 sendCommand CALL 替换为 NOP，只省略设置/清除 HIL 标志的冗余请求。SITL 继续使用本身的外部仿真器；正常模式切换、QGC 控制和 Offboard 调用不改，不过滤 PX4 错误消息。此适配只用于当前 none_iris SITL，不作为真实飞控 HITL 支持。

运行 `389b72d8ba234de9b67b2e3cc216948c` 冷启动 Soccer_Field_Easy 成功，12 个赛门、场景初始化通过；完整 PX4 与 AirSim 启动日志均无 Unsupported main mode，commander 为 Disarmed / Hold、preflight OK、无 failsafe。仍有单独的 `command 520 unsupported` 警告，本项未处理，也不将其写作所有初始化警告消失。旧消息可能仍保留在 QGC 历史列表，应按新时间戳区分。

16 项回归、Python 语法和 diff 检查通过；新增原生执行测试分别运行原/修正后的两处 CALL 片段，确认原先发送、修正后不发送。当前包只验收冷启动和错误消除，本次未重新飞行。原运行包、原始场景包均未覆盖。

### 原生固定准备区与手动开赛修正（2026-10-16）

此前使用 PlayerStart 只解决了出生朝向，没有进入原生固定准备槽位。原生赛务仅在恰好两个参赛机体时摆放出发位，因此单机体调用 reset 不会完成该流程。本次恢复原生双机体准备条件，使用地图自身的 start_block / race_start；第二机体仅为 SimpleFlight 占位，Tier 2 开赛后由原生赛务隐藏并取消碰撞。PlayerStart 不是竞速准备区；该替代摆放实现已删除。

- 足球场运行 `e75fb1134a334d4d90a7fa5bf1c4b063`：原生摆放 PX4 / drone_2 于各自槽位，PX4 位置为 (0.75, -2.0, 2.8210) m（AirSim NED）。开赛前自动试飞命令被拒绝；手动 start-race 后原生计时开始、准备区前方屏障消失、占位机退出。前后截图 `native-prepared.png` / `native-racing.png` 与状态记录 `native-start-review.json` 留在该轮目录；未解锁或起飞。
- Building99 运行 `3f26c0e8713b4b70abcb5082bb5455ac`：仅更换关卡配置，原生摆放和手动 Tier 2 开赛通过。PX4 槽位约 (-0.6286, 0.7902, 2.0207) m，区别于该图 PlayerStart；未填写地图坐标，未解锁或起飞。记录为 `native-prepared-review.json`。
- 最终恢复默认足球场，运行 `4a1313b7009c4d14be302d6ff085537b` 保留在 prepared。实际 RPC 确认两机体均未被取消资格、API 控制均关闭，位置保持原生槽位；记录为 `native-prepared-review.json`。用户下一步手动执行 start-race。

20 项 Stage 2 回归、Python 语法及 diff 检查通过，新增覆盖开赛前拒绝控制、原生复位后拒绝新任务、确认原生开赛后才更新状态及开赛失败保留准备态。本轮验证原生准备/开赛流程及视觉上的屏障变化，没有进行飞行、屏障碰撞受力或完整穿门计分验收；实际验证关卡为足球场与 Building99，不将共用入口等同于全部关卡实测。其他非 ADRL 场景没有此原生赛务，本次未将它们描述为已接入。

2026-10-18 用户验收确认原生固定准备区与手动开赛流程正确，并同意第二机体仅作占位、不接控制器。此确认覆盖当前准备与开赛交互，不扩展为完整穿门、排行榜或其他阶段迁移验收。
