# AirSim 替换后端的配置约定

本目录属于 Stage 3 的 SUPER 流程，承载 Gazebo 的 AirSim 替换后端。宿主机运行打包场景，原 PX4/Gazebo Docker 镜像只运行 PX4 SITL，两边通过网络连接。当前往返任务复用 SUPER 的任务流程，尚未接入 SUPER 规划器。不要迁回 Stage 2，也不要把本目录的控制测试描述为 SUPER 避障验收。

操作入口、预期现象、已知问题与实测证据只维护在 [README.md](README.md)。本文件指导 agent 怎样替用户配置新场景，不另维护一套启动流程。

## 两份输入配置

| 文件 | 消费者与职责 |
| --- | --- |
| `runtime.example.json` | `runtime.py` 默认读取的实际运行配置，虽名为 example，并非只供展示。指定场景目录、二进制、启动参数、settings 文件、PX4 镜像、容器及任务 |
| `settings.json` | AirSim 原生设置的输入文件，指定 ViewMode、车辆和传感器等；由 runtime 配置的 settings 字段选用 |

`up` 会从这两份输入生成 `artifacts/airsim-runtime/<运行ID>/settings.json`，并把该文件作为唯一 `-settings=` 传给场景。不要修改生成文件、运行状态或历史报告来改变配置。task 使用 up 时保存的任务配置，不会即时重新读取后来修改的 JSON。

## 接到“帮我配一个新场景”时

1. 先看当前输入配置与用户提供的场景目录、二进制。信息已有时直接检查文件并配置，不重复追问。确实缺少路径、目标场景或任务范围时，只补问必要信息；已有的启动或飞行授权在当前会话中继续有效。
2. 检查完整打包目录和资源是否存在。读取场景自带 `.sh` 了解项目名、渲染参数与路径，但 runtime 的 binary 必须指向可执行的 Linux ELF，不能指向包装脚本。不要复制场景资源进镜像或假设换一个 SDF 就能换 AirSim 地图。
3. 用户明确要切换默认场景时，修改默认 runtime/settings 输入。需要保留多个场景时，在本目录建立有含义的配置名，例如 `runtime.park.json`、`settings.park.json`，通过 runtime 的 settings 字段关联；不要无意义地复制相同设置。
4. 修改 scene_dir、binary 和 scene_args。相对 scene_dir/settings 以 **runtime 配置文件所在目录** 为基准；相对 binary 以 **scene_dir** 为基准。配置放在其他目录时重新计算路径，不能直接把默认 JSON 复制到 /tmp 后沿用原相对路径。
5. scene_args 是参数数组，不是 shell 命令字符串。沿用场景实际项目名和必要参数；不得包含 `-settings`，避免两份参数导致加载错误设置。保持原 PX4 镜像，除非用户要求换镜像或已发现不可用；新镜像须重新验证模块与版本。
6. 按用户目标设置画面、传感器及短距离任务。低性能 PC 默认保留小窗口、`-nosound` 和 `ViewMode: NoDisplay`；NoDisplay 冻结主视图，不停止物理仿真，也不能免除场景加载成本。需要观察新场景时可改 FlyWithMe，并说明资源取舍。
7. 先做配置、路径和代码必要检查，再按会话授权实际启动、验收。交付具体配置、运行命令、预期现象和已验证/未验证范围，不只给方案。

## 当前连接字段由入口固定

先读 `runtime.py` 的 `runtime_settings()`，不要承诺修改输入 settings 中以下字段就能生效：

- 唯一车辆键 `PX4`，VehicleType 必须为 `PX4Multirotor`。
- Multirotor、RPC 开启、RPC 41451、本机回环地址。
- UseSerial=false、UseTcp=true、LockStep=true。
- AirSim 监听 TCP 4560，PX4 主动连接；控制 UDP 为 AirSim 本地 14540、PX4 本地 14580。

当前仅支持 Linux、host 网络、单机及一对运行实例。换容器名不等于隔离端口。用户要求远程连接、多机、其他端口或车辆名时，需要同时适配 runtime、RPC 客户端、控制任务及 PX4 启动方式，不能只改 JSON。

## 任务坐标与范围

- start_ned_m / goal_ned_m 是 **PX4 估计的本地 NED 坐标**，单位米：X 北、Y 东、Z 向下；−3 表示参考原点上方 3 m。不要照搬 Gazebo/SUPER 的 ENU 坐标，也不要把 AirSim 场景真值原点等同于 PX4 本地原点。
- 当前任务不规划、不避障。先了解新场景的出生点附近空间，再选短距离目标；保留默认低速作为首轮配置，不把旧场景验收直接转移到新场景。
- `round_trip.py` 当前校验：目标水平半径≤3 m，高度1～5 m；起终点间隔≥0.8 m；速度0.1～1 m/s；悬停1～10 s；到点容限0.15～1 m；航段超时5～60 s。修改范围前说明依据，不能为绕过失败随意放宽。
- API 返回 true 不代表精确到点；使用悬停后的估计位置误差和报告判定结果。真值可辅助评测，不能反馈给控制。
- 每次 move/rotate 前重新 `enableApiControl(true)`，避免 hover 后内部控制请求丢失；不以 isApiControlEnabled 为唯一依据。保留任务前参数快照、按顺序恢复参数和异常后尝试降落的处理。

## 运行管理与验证

在 PC 仓库根目录使用 `uv run stage3/super/airsim/runtime.py`，动作和完整操作见 README。新配置仅在 up 时用 `--config` 选择；更改输入后 down/up，task 不自动重载。

- 修改前先 status，确认现有运行实例用途和飞行状态。只停止管理器记录且身份验证通过的进程/容器，不接管手动实例、不杀未知端口占用者。
- up 顺序是宿主机场景 → 检查该进程的 TCP 监听 → PX4 Docker → 连续传感器、有效定位、健康状态与 RPC 检查。不要用连接 4560 的探测消耗 AirSim 的 accept。
- 端口检查需区分真实占用、TIME_WAIT 与权限/沙箱错误。不能把所有 OSError 写成“已占用”，也不能仅凭没有 LISTEN 就宣称没有 TCP 状态。
- 启动失败只清理本次创建的资源，保留日志。down 默认拒绝停止未解除解锁的实例；force 仅是用户显式选择的仿真停止操作，不作为正常重启流程。
- 先验证启动和静止链路；按授权做任务时记录起飞、往返、悬停误差、降落与解除解锁。没有运行条件就报告未验证，不能以 JSON/语法检查替代实际验收。
- 当前已接受初始化 Unsupported main mode 为该 SITL 组合的已知非阻塞警告，不额外设置 SYS_HITL 或手动开启 HIL，不以消除该警告作为换场景的目标。其他新错误仍单独诊断。
- 进入 PX4 的 IMU、气压计、磁力计和 GPS 属于接入验收范围；相机、雷达及场景全局真值接口仅在用户要求时扩展。不要为单纯换场景启动 ROS、规划器或板端流程。

日志、生成设置、状态与任务报告留在忽略 Git 的 artifacts 目录，不提交场景包、二进制、ULog、运行日志或凭据。更新 README 中的场景适用范围和证据；涉及 Stage 3 流程边界时同步 docs/stage3 的入口链接，不重复维护操作说明。
