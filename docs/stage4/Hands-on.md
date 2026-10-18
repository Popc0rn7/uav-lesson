# Stage 4：AeroVLA API＋AirSim＋PX4

本阶段在 PC 上运行 Town05、PX4 Docker 和 ROS 算法 Docker。模型由旧 AeroVLA 仓库的独立 HTTP 服务提供；以后将 ROS 算法职责迁到 RoboPi，模型服务仍可独立运行。实际通过项见 [Validation](Validation.md)，代码入口为 [`stage4/runtime.py`](../../stage4/runtime.py)。

## 教师准备（PC，仓库根目录）

需要 Linux、Docker、Vulkan/GPU、Town05 打包场景、旧 AeroVLA 的 Town05 任务与元数据、现有 PX4 和 Humble 镜像。Humble 基础镜像缺失时先按[开发路线](../../develop/README.md#准备算力镜像)构建；PX4 沿用 Stage 3 的课程镜像，需包含 `/opt/px4-gazebo/bin/px4-simulator_mavlink` 与 `10016_none_iris`，不将本机同名标签当作新机器已准备好的证据。源码/模型/地图的许可证分别核对；旧工作区的本地修改按当前版本使用，不复制训练工程或模型文件。

```sh
uv sync --extra stage4
uv run --extra stage4 stage4/runtime.py build
uv run --extra stage4 stage4/runtime.py prepare-task
uv run --extra stage4 stage4/runtime.py up --dry-run
```

默认从 `../AeroVLA` 读取按轨迹路径排序的 Town05 任务 0，输出 `artifacts/stage4/task.json`，已有文件拒绝覆盖。换任务使用 `prepare-task --source <旧仓库> --task-index 1 --task-file artifacts/stage4/task1.json`，启动时传同一个 `--task-file`。任务导出不导入 Torch、AirSim SDK 或旧评估框架。

场景和镜像通过 `stage4/runtime.town05.json` 配置；相对路径以该文件所在目录为基准。默认 Town05 地面出生点 Z=0（world NED），可在任务导出时用 `--ground-z` 指定经核实的地面高度。初始观测高度取数据集首帧，起飞前核实出生点没有悬空、陷地或障碍。任务数据和目标资产缺失时修复准备步骤，不改成另一个目标制造通过。

首版 ROS 镜像派生自 `uav-computer-ros-humble:local`，补充 Pillow；运行不挂载 SUPER install，也不加载 SUPER。PC uv 使用 Python 3.12+，ROS 容器使用系统 Python 3.10/Humble，二者的 venv 不混用。`uv sync --extra stage4` 只保留此项目所选 extras，若同时使用其他阶段，可并列添加其 `--extra`。

## 外部模型服务协议

用户在旧仓库启动模型服务，本仓库不管理服务进程。客户端按旧仓库 `scripts/serve_inference.py` 已实现的协议接入，详情见该仓库 `docs/inference-server.md`。

在 **PC 启动 Stage 4 的终端**设置（模板见 `stage4/.env.example`；入口只读取环境变量，不自动加载 `.env`）：

```sh
export AEROVLA_API_URL=http://127.0.0.1:8000/infer
export AEROVLA_API_TIMEOUT_S=30
# 有鉴权时另行 export AEROVLA_API_KEY，勿写入配置或提交 Git。
```

必须在 `up` 前设置，容器继承这些变量；运行中改变量需要落地后 down/up。HTTP key 使用 `Authorization: Bearer ...`，不进入任务快照。无需约定额外 health URL。

`GET /health` 返回 `{"status":"ready"}`；任务起飞前检查一次，推理期间不循环健康检查（服务的健康请求也可能排队）。

POST 到完整 `AEROVLA_API_URL`，`Content-Type: application/json`：

```json
{
  "front_image": "<前视 PNG base64>",
  "down_image": "<下视 PNG base64>",
  "position": [-20.261, 183.198, -2.125],
  "orientation": [0, 0, 0.386068, 0.922470],
  "target_position": [131.016, -31.086, -14.491],
  "instruction": "The target is 0 degrees from you. A table. Please control the drone."
}
```

position 和 target_position 为同一世界 NED 坐标（米），orientation 为 `[x,y,z,w]`。完整 instruction 保留原数据集格式，必须包含 `degrees from you.` 和后续 ` Please control`。服务端生成动态方向 prompt，完成双图缩放、拼接、模型预处理和解码。客户端不再发送 prompt。

响应：

```json
{
  "action": {"fwd": 1.0, "down": 0.0, "yaw": 0.1},
  "stop": false,
  "prompt": "<实际模型 prompt>",
  "raw_output": "20 49 53",
  "elapsed_seconds": 2.5
}
```

`fwd` 为 0～5 米，`down` 为 −5～5 米（正值下降），`yaw` 为 −1.1～1.1 弧度（正值向右）。`stop=true` 时不执行伴随动作。客户端保留本地请求编号和观测时间用于关联异步响应；服务不保存会话，也不要求回显编号。取消后返回的旧响应不能重新接管控制。

`elapsed_seconds` 是服务端预处理和推理耗时，另记 `http_seconds`（含网络和排队）。请求体上限 16 MiB，单图最大 4096×4096。400/413/415/500、无效 JSON、非有限或越界动作、缺字段都会终止任务并请求降落。原量化模型的 raw_output 还需包含三个 0～98 的动作 bin 或 LAND，防止旧解析器把格式错误默认为零动作。服务说明见旧仓库 `docs/inference-server.md`，服务进程由用户维护。

离线探测不连接模拟器、不起飞，但会调用模型服务：

```sh
uv run --extra stage4 stage4/runtime.py api-probe \
  --front /path/front.png --down /path/down.png
```

默认取导出任务的首帧位姿、目标坐标和原始指令；使用该首帧的双图，与旧离线模型结果对照。换任务传 `--task-file`。探测结果同时包含服务返回的实际 prompt。

## 启动与逐层验收（PC）

Stage 3/4 共用 AirSim/PX4/Agent 端口，同一时间只运行一套。先检查现有实例，入口拒绝接管未知进程或容器。

```sh
uv run --extra stage4 stage4/runtime.py status
uv run --extra stage4 stage4/runtime.py up --no-display
uv run --extra stage4 stage4/runtime.py inspect
```

`--no-display` 使用独立 Xvfb 和离屏渲染，仍需 GPU/Vulkan 与 Xvfb；桌面显示可省略该参数。Town05 默认添加 `-norhithread`：本机有窗口 Vulkan 路径曾在首帧图形管线缓存中 SIGSEGV，关闭独立 RHI 线程后已验证启动。此参数属于渲染兼容配置，不修改 PX4 或任务动作。`up` 只待命，创建目标物体并要求健康定位和至少两组有效双图。成功输出 `ready=true` 仅表示静止链路，不代表飞行或模型验证。

先执行**不调用模型**的固定动作验收：

```sh
uv run --extra stage4 stage4/runtime.py task --fixed-actions
uv run --extra stage4 stage4/runtime.py status
uv run --extra stage4 stage4/runtime.py down
uv run --extra stage4 stage4/runtime.py review
```

预期经 PX4 起飞到首帧高度，前进、右转并下降、回转并上升、小角转向、返回起始观测位姿，最后降落并确认 Disarmed。大偏航动作附带的前进分量按原规则不执行。报告的 `chain_completed` 与 `task_success` 分开；固定动作不应报告语义任务成功。

真实服务可用且固定动作通过后，重新 `up`，执行：

```sh
uv run --extra stage4 stage4/runtime.py task
```

首次真实模型验证使用独立任务文件，将 `control.max_steps` 显式设为 1；完成单步后按步数上限降落是预期的受限试验，不算完整任务成功。完整任务恢复原 200 步配置并重新启动。每轮只执行一次任务，避免旧响应、取消标记和历史状态串轮。

## ROS 接口与时序（ROS Docker）

在 PC 用 `docker exec -it uav-stage4-ros bash` 进入后，执行：

```sh
source /opt/ros/humble/setup.bash
source /opt/px4_ws/install/local_setup.bash
export ROS_DOMAIN_ID=10 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE=/lesson/stage3/super/race_view_dds.xml
ros2 topic list
ros2 topic hz /stage4/uav1/camera/front/image_raw
```

| 话题 | 类型与语义 |
| --- | --- |
| `/clock` | PX4 HIL `SensorCombined.timestamp` 仿真时间 |
| `/stage4/uav1/camera/{front,down}/image_raw` | `sensor_msgs/Image`，rgb8，各自 AirSim 采集时间，默认 5 Hz 采集 |
| `/stage4/uav1/camera/{front,down}/camera_info` | `sensor_msgs/CameraInfo`，256×256、90° FOV |
| `/stage4/uav1/odom` | `nav_msgs/Odometry`，PX4 估计；world ENU、body FLU，twist 为机体系 |
| `/stage4/uav1/observation/odom` | 与前视采集时间配对的最近 PX4 位姿，允许最大 100 ms 差，实际差在 sensors 状态记录 |
| `/stage4/uav1/imu` | `sensor_msgs/Imu`，PX4 FRD 转 FLU，无姿态字段 |
| `/stage4/uav1/{sensors,status}` | `std_msgs/String`，JSON 健康与控制状态 |

相机使用独立 RPC 工作线程，同次请求取前视/下视 RGB 与前、左、右、后、下五向 DepthPerspective；全部图像时间差、与 PX4 采样时间差都须在 100 ms 内，否则拒绝发布有效观测。深度不进入模型，只用于源仓库的近碰撞评估；缺帧或无效深度不会按安全处理。没有使用收包墙钟重写采集时间。静态 TF 提供机体到两相机 optical frame 的外参。

算法通过给定目标坐标与 PX4 估计位姿生成方向文字；当前不是无目标坐标的纯视觉搜索。AirSim 真值用于碰撞监测和离线评测，不反馈控制。

控制 50 Hz 使用单调墙钟定时，轨迹按仿真时间推进；推理独立线程等待，控制继续悬停。动作先转向，`abs(yaw)<0.25` 才执行前进，升降始终保留。新导出任务默认速度/加速度参考上限 8 m/s、4 m/s²、偏航速度 0.5 rad/s。旧任务文件保留原值，可在 `up --speed 8 --acceleration 4 --stable 0.15` 显式覆盖；运行快照记录实际参数。4.9 m 直线参考用时约 2.66 s、参考峰值约 3.45 m/s；短段受加速度限制，不会达到 8 m/s。垂直方向另限上升 2 m/s、下降 1 m/s、加速度 3 m/s²；组合动作按所有轴限制选择同一轨迹时长。Stage 4 settings 将 PX4 的 MPC_ACC_HOR/MPC_ACC_HOR_MAX 配为 4，速度与倾角限幅保持现有值。参考上限不等于真实速度硬上限。到点需误差≤0.6 m、偏航误差≤5°、速度≤0.2 m/s 并持续 0.15 仿真秒。

## 中止、恢复与证据

**PC 另一个终端**可随时执行：

```sh
uv run --extra stage4 stage4/runtime.py status
uv run --extra stage4 stage4/runtime.py land
# 已核实本入口实例碰撞或无法降落时：
uv run --extra stage4 stage4/runtime.py stop
```

land 锁存取消并请求 PX4 降落，迟到响应不会重新控制。stop 强制回收本入口资源，保留日志，不能记作正常降落。正常降落后才用 down。

| 条件 | 行为 |
| --- | --- |
| 模型 `stop=true` | 结束导航，降落；分别报告停止时目标距离、语义成功、Disarmed |
| API 错误/超时/无效输出 | 失败并降落，不自动重试动作 |
| 等待观测超过 5 墙钟秒 | 失败并降落 |
| PX4 状态/仿真时钟失流、估计重置、离开 Offboard | 失败并降落 |
| 新碰撞、起飞超过 45 秒、动作超过 30 秒 | 失败并降落 |
| 200 步或 1800 墙钟秒 | 失败并降落 |
| 控制进程退出 | PX4 Offboard 失联策略接管，需单独实测 |
| 降落等待超过 60 秒 | 报告未确认 Disarmed，保留实例以便独立恢复 |

语义成功沿用原任务的“模型停止且停止时目标距离≤20 m”，不能把它解释为精确抵达或已经识别物体。`chain_completed` 表示执行和降落没有基础链路错误，与 `task_success` 不同。

每轮目录在 `artifacts/stage4-runtime/<run-id>/`：配置、任务、源码摘要与镜像身份、`node-logs/`、`observations/<step>/`、`inference.jsonl`、`flight.jsonl`、`report.json`、`px4-logs/*.ulg`。`review` 只读飞行数据并生成 review.json，包括测量时刻对齐的位置、速度、姿态、角速度误差、motor 输出及参数更新；需在 down 结束 ULog 后执行。调参前继续检查对应 ULog 的估计、速度、姿态、角速度和执行余量；基础统计不替代完整飞行复盘。

常见启动失败先看 `airsim-console.log`、`px4-console.log`、`node-logs/` 和 `sensors.json`。场景弹窗点击 OK 后能继续运行，不等于场景崩溃；若 PX4 已有有效定位却停在 Manual，禁用遥控杆输入的配置可能报 `No manual control input`。Stage 4 启动器仅在未解锁且水平/高度定位有效时请求 Hold，再执行原有预检，切换记录在 `px4-standby.log`；不关闭检查或强制解锁。若提示实际 Vulkan SIGSEGV，先核对当前配置的 `-norhithread`，不要通过增加等待时间绕过。时间不一致先核实采样时钟，不放宽门限或改标签。端口占用先确认现有实例；TIME_WAIT 由公共管理器等待。API 在宿主机回环地址运行，Docker 使用 host 网络；换成远端服务时配置实际可达 URL，不把 HDC 当作 DDS。

## 独立故障验收（PC，显式起飞）

先确认普通 Stage 4 已落地并 down。以下每条命令各自创建并回收一个低速仿真实例，只允许串行执行，不访问付费 API，也不会停止旧仓库的真实模型服务：

```sh
uv run --extra stage4 stage4/verify_fault.py api-timeout
uv run --extra stage4 stage4/verify_fault.py cancel
uv run --extra stage4 stage4/verify_fault.py camera
uv run --extra stage4 stage4/verify_fault.py control
```

api-timeout/cancel 在临时端口启动慢响应测试 HTTP 服务；前者应超时降落，后者在请求挂起时人工降落，并等待迟到响应确认没有执行动作。camera 暂停本实例唯一 sensors 节点，验证 5 秒持续观测失流后降落，再恢复节点。control 终止本实例唯一控制节点，**不先发宿主机 Land**，要求 PX4 自身 Offboard 失联策略落地并 Disarmed。

证据在 `artifacts/stage4-faults/<run-id>/fault-report.json`、节点日志和 ULog。`passed=true` 必须包含实际 Disarmed；超时或状态未知时保留资源，使用 `runtime.py --state-dir artifacts/stage4-faults status/land/stop` 恢复。测试用控制进程退出时无法生成正常 report.json，以 fault-report 和 PX4 ULog 为准。

## WebUI 与提速（PC）

在独立终端启动，只读界面不持有任务管理锁，任务结束后继续保留结果；新的 up 会自动切换到新 run：

```sh
uv run --extra stage4 stage4/runtime.py webui
```

浏览器访问 http://127.0.0.1:8080 。布局和样式沿用源 UI：顶部提示词、中间前视/下视、输入 NED 位置和完整 XYZW 四元数、输出动作条、底部耗时/步数/距离/计时/阶段，支持全屏。双图直接读取 observations/<step>/ 的原始 PNG，输入位姿、提示词和动作也限定同一观测步；两张图都加载完成后再一起切换。新请求等待期间不显示旧动作；提示词先标记 PREVIEW，服务返回后显示实际 MODEL PROMPT。实时速度与飞控状态仍单独更新。HTTP 延迟包含传输和服务处理，服务端耗时取 elapsed_seconds；两者均属于显示的观测步。遥测超过 2 秒会显示过期提示，离线值不会标成实时。

默认只监听本机；需要跨机浏览时显式传 `--host 0.0.0.0 --port 8080`。界面不含飞行控制或密钥配置入口，也不读取 API 密钥。

旧任务已导出时，在确认落地且 Disarmed 后重建实例，显式选择提速参数：

```sh
uv run --extra stage4 stage4/runtime.py down
uv run --extra stage4 stage4/runtime.py up --speed 8 --acceleration 4 --stable 0.15
uv run --extra stage4 stage4/runtime.py task
```

已有运行不会热改参数。回到旧参考与等待时间用 `up --speed 1 --acceleration 1 --stable 1`；偏航和到点误差/速度阈值保持原值。WebUI 是宿主机标准库 HTTP 服务，无需重新构建镜像；源码或五向深度相机配置更新后，需重建运行实例。

源仓库连续控制优化在本链路中的对应关系：ClockSpeed 保持 1；图像调用复用 Stage 3 的二进制 MessagePack RPC，不经过旧 msgpack-rpc-python 的 UTF-8 解码路径，不需要安装该旧包。动作量程、大偏航分支和 STOP 规则保持 AeroVLA 语义；PX4 仍按位置与速度判据结束动作，避免速度×时长截止造成落点漂移。源端的 real_time 模式会暂停仿真，本链路推理时持续仿真并保持 Offboard 悬停，不迁入暂停行为。

## 源评估终止规则

按动作完成后的同步观测计数，不按 50 Hz 控制定时器计数；固定动作测试不进入语义评估。位置使用 PX4 世界 NED 估计，仿真真值仍只用于评测。

| 规则 | 迁移后的行为 |
| --- | --- |
| Oracle success | 任一动作后距目标严格小于 20 m，置位并保持；仅表示曾经靠近，不自动结束 |
| Model STOP | 距离≤20 m 为成功；大于 20 m 为 early_end 失败；均忽略伴随动作并降落 |
| 全局卡住 | 连续 16 次动作后 XY 位移小于 0.05 m，终止；首个动作后计数从 1 开始，与源实现一致 |
| 距离不下降 | 包含初始距离，最后 10 个距离值均不下降即终止；相等也算 |
| 深度近碰撞 | 五向深度按源实现裁剪至 0～100 m、量化至 uint8；任一相机像素值≤1 的占比严格大于 10%，终止 |
| 物理碰撞／步数上限 | 保留当前碰撞检查和降落处理；最后一步先更新评估再判定步数上限 |

源评估器会将卡住、距离不下降和深度近碰撞都写入 collisions；这里保留 evaluation.legacy_collision 兼容标志，同时给出独立 reason。物理碰撞仍由 collision/flight_collision 字段记录，避免混淆。源端远距离 STOP 可能继续请求模型，本链路按既有 API 契约立即降落，不复现这一行为。report.json 和 control.json 包含 evaluation 的 oracle_success、early_end、stuck_count、最近距离与终止原因；每步 input.json 记录 depth_fractions，可离线复核。

`/stage4/uav1/observation/depth` 为 std_msgs/String，包含同批 RGB 的 observation_time_s 和五向近距离像素占比。五向深度链路和新规则需要重新实飞；旧任务结果不能直接视为新评估规则下通过。
