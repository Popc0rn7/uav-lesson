# AirSim/SUPER 的 RoboPi 迁移验证

2026-10-16，标准流程为 AirSim＋PX4＋ROS/SUPER，定位为 PX4/GNSS，无 LIO。操作只维护在 [AirSim README](../../stage3/super/airsim/README.md#robopi-算力后端2026-10-16迁移验证中)。本记录区分 Docker 基线、通信、构建和实际板端飞行；尚未达到完整迁移验收。

## 当前结论

Stage 1 新目录交付回归通过。Stage 3 的 OpenHarmony 原生短程、forest1 往返与雷达/规划器/时钟/控制桥四项低速故障降落通过；构建、部署、消息 ABI 和真实以太网链路均已验证。forest10 在默认调度下两次失败、CPU 亲和对照也失败，因此三次成功冷启动尚未完成，完整迁移不标记完成。上述早期失败均触发保护降落并确认 Disarmed、无碰撞；后续原门限 profile 轮出现碰撞，详见下文，不扩展早期无碰撞结论。

## 固定条件

本机 AirSimNH，SUPER 提交 `4461128ff139ab986c0229a6e29f7e17c060d4cf`（含远目标裁剪返回值修复），任务与传感器配置未调参。场景运行使用 Xvfb、`-RenderOffScreen`、NoDisplay 640×480，无 AirSim 可见窗口或 RViz。PC 另有既有 Stage 5 服务，未停止；部分基线同时进行交叉构建，仿真/墙钟比例受资源竞争影响，不能直接作为同资源性能对照。

原 PX4 镜像摘要 `px4io/px4-sitl-gazebo@sha256:29a5a1b5af77e5d39b67bc6664d36acead63f9dfb829475216522b1feec8036e`；基线 ROS 镜像为现有 Humble 加 python3-msgpack 的独立镜像。每轮 inputs-evidence.json 保留实际 image ID、源文件哈希、子模块状态、场景 ELF 哈希及 task/settings 快照。OHOS 构建关闭目标上不可用的 libdw 崩溃栈处理，Linux 默认保持原行为。

## 本次执行与三层迁移流程的对应

本次最终产物按三层对齐，但首次执行中依赖、启动与通信问题交错排查，没有严格在每层形成检查点后再进入下一层。后续按 `robopi/AGENTS.md` 固定顺序执行，并复用未变化层的证据。

| 层 | 本次实际对应 | 边界 |
|---|---|---|
| 原 image | 复用板端已有 Humble/Fast DDS，核实 OHOS libc、Python 3.12 SOABI、基础消息与运行库 | 对齐运行能力和消息接口，不复制 Jammy 系统，也不把 Python 3.10 扩展直接上板 |
| Dockerfile 增量 | 当前设备依赖快照提供 PCL/Eigen/yaml 等；固定提交 px4_msgs 在目标 ABI 下生成并编译，环境入口显式初始化 | SDK/colcon 等生成工具留 PC；Agent、HIL 时钟、原始 RPC 桥随仿真留 PC；当前无 LIO，不要求搬入 Gazebo 专用桥 |
| 挂载内容 | SUPER/ROG/自定义消息交叉构建；Python、task/planner 配置及共享源码链接解引用打包 | 部署 runtime release，不传 Linux install、SDK、build 缓存或整个仓库 |

三层产物完成后统一检查 source 顺序、路径、Ethernet DDS、QoS、唯一 `/clock`、坐标与超时；再逐级验收业务功能。`build-input.json`、`build-evidence.json`、release 文件清单和每次运行快照提供对应证据，内容变化时回到所属层，不默认全量重建。

## PC Docker 基线

证据目录 `artifacts/airsim-migration-baseline/`（忽略 Git），每次飞行均保留报告、ULog 和自动 `.review.*`。

| 任务 | 运行 ID | 结果 | 实际全程峰值 | 仿真/墙钟比 |
|---|---|---|---|---|
| 短程 1 m/s | `843fbf3538bc48979cb30606f74b9862` | 2/2、无碰撞、落地解除解锁 | 1.122 m/s | 0.703 |
| forest1 | `799d16fb96c74873a5a6a5c987eae75e` | 2/2、无碰撞、落地解除解锁 | 1.168 m/s | 0.580 |
| forest10 八航点 | `0ddee67e4b984df4863447531b6a356e` | 8/8、无碰撞、落地解除解锁 | 9.979 m/s | 0.623 |

forest1 的测量时间对齐位置误差 P95 约 0.085 m、最大 0.138 m；ULog 未见高端电机饱和或推力/力矩分配未达成。forest10 全程 111.04 墙钟秒，报告跟踪误差峰值 1.731 m 为性能数据，不用旧 0.8 m 门限中止。forest10 自动复盘首次因调用解释器没有 pyulog 而只完成 ROS 分析，已使用项目 `.venv/bin/python` 补齐 ULog 复盘；姿态误差 P95 10.77°，速度最佳匹配延迟约 0.12 仿真秒，未见推力/力矩分配未达成。外部参考 ULog 记录间隔上限约 0.231 秒，不能据此推断 Offboard 实际发布频率。单目标 forest10-ab 未重测，既有碰撞失败结论保留。

## 原 PC 的重规划表现补充

重新检查同批 Docker 2 的 `node-logs/planner.log`：短程记录 0 条 Replan overtime，forest1 为 7 条（约 90.4–104.2 ms），forest10 为 74 条（约 90.2–194.1 ms）。三项任务仍均完成，无碰撞并确认 Disarmed；这些是整份日志中的告警计数，不是完整调用次数或超时率。PC 也有预算超限，不能概括为每次都小于 90 ms。

旧 PC 基线未保存当前同口径的墙钟/线程 CPU scope 分布，也未保留 time_consuming.csv，因此不能用告警子集推断主机中位数、P95 或相对板端的倍数。精确性能对照仍须对 PC Docker 2 使用同样打桩和固定任务/资源条件。ReplanOnce 是新轨迹更新关键路径；已提交轨迹由独立命令定时器采样，单次重规划失败不等于控制指令立即中断，上游点云/地图新鲜度同样影响整个闭环。

## 板端基础与通信

当前板端为 OpenHarmony AArch64、Linux 6.6.86、ROS 2 Humble、rmw_fastrtps_cpp、域 10，Python SOABI `cpython-312-aarch64-linux-ohos`，NumPy 2.4.0、SciPy 1.16.3。PC↔RoboPi 以太网在本次临时 172.30.10.0/24 子网完成 ping（约 1 ms）和真实 ROS DDS 请求/回传；Fast DDS 显式绑定接口及单播 peer。板端 fwmark 策略路由曾抢先选择 Wi-Fi，增加仅匹配本次板端源 /32 的 main 表规则后普通 socket 收发通过。HDC fport 用于 Stage 1 HTTP，不承担 DDS。

依赖从当前设备导出，原始归档、SHA-256、重定位清单、目标 Python 元数据均保留在 `artifacts/robopi-stage3/target/`。SDK 为已核验 OHOS native 26.0.1.45 Beta1，px4_msgs 为固定干净提交 `57f88be3c01a8c593c23507e4ca136767115ca22`。四个目标包已完成交叉构建及 ELF 审计（自建产物无 RPATH；目标私有 PNG 仅保留可重定位的 $ORIGIN RUNPATH），`board-build-17.log`、`build-input.json`、`build-evidence.json`、`elf-audit.json` 保留证据。板端加载与短程往返已通过；forest1、三轮 forest10 及故障注入继续逐层验证。

Stage 1 新布局完整部署、实际 ROS 常驻文本、空请求拒绝、ROS bridge 重启、并发 429 和单图 VQA 已通过，详见 [Stage 1 Hands-on](../stage1/Hands-on.md#新目录部署回归2026-10-16)。驱动首次因 DMA/CMA 分配不足而 probe 失败；用户授权重启后早期加载成功，未修改系统库、内核或 CMA 启动参数。

## 板端启动层的实际修复

首轮部署归档中的根 `./` 条目被当前 OHOS tar 的 `-C` 安全检查拒绝，改为直接归档各顶层文件。首次 launch 因 colcon 环境脚本读取未定义变量而被 `set -u` 中断，改为完成环境初始化后再启用 nounset；失败均保留日志，没有起飞。

C++ 规划器加载成功后曾在创建 `/clock` 发布器时触发 rmw_fastrtps 断言。独立无运动探针（`clock-probe-false.log`/`clock-probe-true.log`）证明 String/PointCloud2/MarkerArray/Odometry 均能创建；use_sim_time=false 时 Clock 发布成功，true 时返回 134。补丁将 SUPER 的时钟发布器改为显式调用 setSimTime 时才创建，飞行流程仍只消费 PC HIL 桥时钟。该诊断覆盖真实设备，不以禁用仿真时间掩盖问题。旧失败运行 `48e2476fbcf84205a14d1b24381c05e3` 已回收，未起飞。

时钟修复后的交叉构建与 ELF 审计通过。构建同时固定源码 include 优先级，避免 merged install 的旧头文件遮蔽源码；未知返回码的诊断函数补充默认文本。完整主机回归运行 69 项，结果通过，含 3 项因 ROS 环境跳过（ROS 专项单独在容器验证）。

时钟修复后四个板端节点均存活，首轮静止检查仍失败：只有板端 odom/control/task/sensors，PC /clock 与 vehicle 缺失，云被判过期。原因是显式 initialPeersList 只含远端，未覆盖同机 Agent/clock/检查器；配置已增加本机接口地址，继续冷启动验证。未执行飞行、未放宽传感器超时。

补充同机 peer 后，板端配准点云、非空 ROG 地图和原始雷达吞吐均可被 PC 观察，约 7.6 Hz、1.37 MB/s；仍未收到 PC Agent 的 sensor_combined/vehicle，故静止保护继续拒绝起飞。额外共享内存传输对照未解决，已撤回；随后改为复验回环 UDP 白名单。以上均为静止链路诊断，不能计作飞行通过。

回环 UDP 白名单修复后，运行 `3f4d9b94f32a4aa69cf33b3738476882` 的静止验收于 3.74 秒通过，clock/vehicle/cloud/ROG 全部有效，控制状态 local_ready。PC profile 同时允许本次以太网接口和 127.0.0.1，并以本机/远端/回环为单播发现地址；板端 profile 保持以太网限定。sensor_combined 实际 echo 通过（loopback-sensor-probe.log）。原始雷达约 7.73 Hz、1.40 MB/s。仅配置同机 peer 或添加 SHM 均不足，相关失败日志保留。

## 板端短程通过

运行 `3f4d9b94f32a4aa69cf33b3738476882`，release `07fdab43a2f6e678bcb09bc8369f005268b95200d6c961ff1e88ef41c4775de4`，报告 `fly-task-1792129262130335465.json`：2/2 往返，无碰撞，45.27 墙钟秒，PX4 确认 Land/Disarmed。全程速度峰值 1.116 m/s，报告跟踪误差峰值 0.165 m，仿真/墙钟比 0.711。已查看 `.review.json/.txt` 和匹配 ULog：参考运动学残差、测量对齐跟踪/估计/姿态与角速度、分配器记录均已生成；未见电机高端饱和或推力/力矩未达成，速度最佳匹配延迟约 0.14 仿真秒。外部参考 ULog 记录间隔上限约 0.237 秒，仍不能据此判定真实发送频率。

原始雷达末次累计状态约 7.22 Hz、1.25 MB/s；完整本次运行（含起飞前待命）的 36 个资源样本中，五个自有进程合计 CPU 中位数 427%、峰值 472%（100% 为一个核心），合计 RSS 峰值 931 MiB，系统可用内存最低 5.92 GiB。以太网收/发中位数约 1.39/5.49 MB/s，包含地图/可视化和诊断流量，不能等同纯控制流量。数据见本次 `board-logs/resources.jsonl` 和 `resources-summary.json`。本轮已正常 down，四个算力节点、监督器、场景、容器与 Xvfb 均按所有权回收。

这证明最小 PC 仿真→以太网→OpenHarmony 原生规划/控制→PX4 仿真闭环已运行。forest1、三次 forest10 冷启动及四项故障飞行继续验证，未完成项不记为通过。

## forest1 首轮失败与性能定位

运行 `d76bc4b014ef4d848b97eff6320661cb`，报告 `fly-task-1792129424451682621.json`：静止检查通过，起飞悬停后首个目标 `[-3.3,11.5,1.9]` 的 A* 连续触发原有 0.1 仿真秒搜索期限，控制桥触发 planning timeout 并降落。44.90 墙钟秒后确认解除解锁，无碰撞、未进入 tracking；速度峰值 1.124 m/s 属于起降，不是路线速度。原始雷达累计约 5.80 Hz/0.93 MB/s，地图/时钟与里程计仍在。

已查看规划器日志及自动 review。因没有 tracking 区间，自动 review 不生成任务段 ULog 内环统计；另直接检查真实 ULog，局部 NED XY 范围均不足 3 cm、Z 到 -1.973 m，经历 Offboard→Land、最终 arming_state=1，0 dropout；记录为 `takeoff-landing-ulog.json`，不将缺少 tracking 指标解释为飞控故障。实例已正常 down，三轮 forest10 暂不启动。

编译命令检查发现 OHOS SDK 将 `-O2` 追加在 SUPER 自身 `-O3` 后。下一轮显式保留上游预期的 Release `-O3`，补充 A* 超时的实际仿真耗时与展开次数日志；不改搜索期限、地图点数、任务速度、控制保护或路线。另以无运动的空图搜索探针区分基本搜索兼容性与场景负载。

`-O3` 首轮仍规划超时（384285bd77704411bb8a129f7e6a9bed），记录展开约 4700–5700 节点后触发 0.102 仿真秒期限；启动期间另有短时独立探针，不将该轮作为隔离性能基线。无输入空图的搜索方向对照：5 m 轴向约 1 ms，forest1 首目标约 0.188 s，远端斜向裁剪约 0.360 s。大小核对照中同一目标大核约 0.194 s、小核约 0.516 s，默认已接近大核性能，因此没有加入强制 CPU 亲和或改变系统调度。探针为计时对照使用 5 秒测试预算，不用于飞行，实际飞行搜索期限仍为 0.1 仿真秒。

进一步定位到高度兼容层在每个邻格反复 getenv 扫描环境。将启动时不变的上下界缓存为进程常量；改变环境配置必须 down/up，与现有运行契约一致。真实板端百万次同输入微基准：无边界时旧/新结果校验和一致、0.314→0.018 s；显式上下界时校验和也一致、0.453→0.020 s。不会恢复高度投影、改变边界数值或放宽搜索期限。补丁和完整重建已通过，继续以真实 A* 和飞行验证。

缓存后的真实 A* 空图探针在原 0.1 秒测试期限内六项全部通过：轴向近目标 0.00041 s、forest1 首目标 0.03759 s、轴向远裁剪 0.00072 s、10-ab 斜向远裁剪 0.07227 s、距离截止 0.04943 s、再次近目标 0.00021 s。返回码、路径点数与终点均保持预期，forest1 同目标比此前约 0.188 s 明显改善；这只证明合成空图搜索，不代替树林飞行。日志 `astar-empty-cached-budget.log`，探针源码/配置与构建命令保留 artifacts。

缓存修复后的第一次冷启动（1dfd44d501e647039a36bdef64669659）未进入飞行：PC enp1s0 与板端 eth1 均 carrier=0，双方临时 IPv4 消失，节点记录 All whitelist interfaces were filtered out。HDC USB 仍在线，实例已自动回收。用户恢复接线后，两端 carrier=1，恢复本次 NM 临时连接、板端地址及源策略规则，普通 ping 重新通过。新增 up 前的只读地址/物理链路预检，缺地址时在创建场景和节点之前停止，避免将断线误记作算法失败。

恢复接线后的运行 `946ff140da2d4ef5bf7d1f12c4cea164` 静止检查于 3.85 秒通过，已进入 forest1 轨迹跟随。Linux 兼容构建及真实 `astar_clipped_goal` CTest 通过（1/1，1.18 秒）；主机 69 项回归通过，含 3 项因 ROS 环境跳过，锁文件离线一致性检查通过。飞行结果以本轮最终报告为准。

## 板端 forest1 缓存修复后通过

运行 `946ff140da2d4ef5bf7d1f12c4cea164`，release `5196906678838e0d5be10f7574cee2b8249d18be0aa89a6e26c2ce35cce3037a`，报告 `fly-task-1792130358971414897.json`：2/2 航点，无碰撞，209.10 墙钟秒，Land/Disarmed 已确认。全程速度峰值 1.146 m/s，tracking 峰值 1.036 m/s、时间加权均值 0.641 m/s，仿真/墙钟比 0.691，不能只凭峰值宣称全程达到配置速度。

已查看自动 review 和匹配 ULog：测量时间对齐位置误差 P95 0.0624 m、最大 0.1590 m，姿态误差 P95 0.334°，速度最佳匹配延迟约 0.11 仿真秒；未见电机高端饱和或推力/力矩分配未达成。外部参考最大记录间隔 0.237 秒，不据此推断实际 Offboard 发送频率。规划器仍有 replan overtime 警告，原始雷达末次累计约 6.56 Hz/1.02 MB/s；这轮只证明低速树林往返，后续三轮 forest10 与故障仍需实测。已正常 down 并保存板端资源/节点日志。

forest1 完整自有运行（含待命）162 个资源样本：进程合计 CPU 中位数 504%、峰值 563%，RSS 峰值 1128 MiB，系统可用内存最低 5.70 GiB；eth1 收/发中位数约 1.14/8.51 MB/s，包含地图可视化与诊断。完整统计见该 run 的 `resources-summary.json`，不将网卡吞吐等同纯控制流量。

## forest10 首轮失败；高速验收未完成

运行 `009e750200654b2a8ac242c77474f89f`，报告 `fly-task-1792130677153759009.json`，同一缓存修复 release。54.95 墙钟秒时因 `SUPER command timeout` 保护降落，在第 2/8 航点中止，无碰撞，最终 Land/Disarmed。全程速度峰值 6.595 m/s，tracking 时间加权均值 0.793 m/s，仿真/墙钟比 0.697；不能记为 10 m/s 任务通过。三次成功冷启动验收尚未完成，失败后未自动重复后两轮。

已查看 planner 日志和匹配 ULog：规划器多次 ReplanOnce 超过原前视预算，随后出现备用/探索轨迹优化与走廊失败；最后控制桥超过原 0.5 墙钟秒未收到有效指令而降落。ROS 原始点云仍约 6.63 Hz/1.09 MB/s，没有证据将其归因以太网再次断开。ULog 对齐位置误差 P95 0.846 m、最大 0.913 m，姿态误差 P95 9.10°，速度最佳匹配延迟约 0.14 仿真秒，无电机高端饱和或推力/力矩分配未达成；外部参考最大记录间隔 0.228 秒。本轮已正常 down，完整板端日志和复盘保留。后续先定位耗时模块，不能通过放宽指令失流或重规划门限制造通过。

## 低速故障注入

雷达项：运行 `ea7a431dbed44a9ab376a15c48dedf07`，报告 `fault-lidar-1792130858495227541.json`。刚进入 tracking 后暂停板端配准点云，观察到 `land: lidar cloud timeout`，29.06 墙钟秒后确认 landed/disarmed，无碰撞。完整 ULog 的 nav_state 包含 Offboard(14) 与 AUTO_LAND(18)，arming_state 包含 2 并最终为 1；0 dropout、无损坏，证据 `fault-ulog-lifecycle.json`。

该项 tracking 仅约 0.39 仿真秒，没有足够的参考/位置匹配样本，自动 review 明确保留内环指标缺失；不能从这次故障试验推断 PID 性能。临时测试编排器最初将缺少 tracking 指标误判为 ULog 文件缺失并停止，已改为故障项直接校核完整 ULog 的解锁/降落状态；不更改飞行成功条件或故障触发门限。规划器、时钟、控制桥项继续独立冷启动验证。

规划器项通过：运行 `91e7c286c14a40e6b63796a5ed20c428`，报告 `fault-planner-1792131108722072314.json`，暂停板端规划器后触发 `SUPER command timeout` 并 landed/disarmed。匹配原始 ULog 已独立校核 arming/nav 状态，内环 tracking 区间仍过短，不生成性能结论；本轮正常 down。时钟和控制桥项继续。

时钟项通过：运行 `05a87bbc6ac64e2ead8e0c093b7d7bd0`，报告 `fault-clock-1792131244290926060.json`。暂停 PC HIL 时钟后，板端触发 `state or clock timeout`，28.57 墙钟秒内 landed/disarmed，无碰撞；原始 ULog 包含 Offboard(14)、AUTO_LAND(18)，最终 arming_state=1，0 dropout、无损坏。已正常 down。规划器项耗时 29.89 墙钟秒，ULog 状态与完整性检查同样通过。

控制桥退出项通过：运行 `ff84d8ecb9834657ae111a599692b8cc`，报告 `fault-control-1792131380299554950.json`。终止本项目板端 control 后，监督器停止其余算力节点，PC 观察 PX4 自行 AUTO_LAND，31.32 墙钟秒后 confirmed landed/disarmed，无碰撞。匹配原始 ULog 包含 Offboard(14)、AUTO_LAND(18)，最终 arming_state=1，0 dropout、无损坏；自动 review 保留了参考序列不足的限制，不用于通用内环性能结论。已正常 down。

四项故障的原始 ULog 均独立复核模式和解除解锁状态；低速故障降落验收通过。这不改变 forest10 高速失败和三次成功冷启动尚未完成的结论。

已实际执行仓库入口 `stage3/board/probes/astar.py --budget 0.1`，完成编译、HDC SHA 校验及独立域 191 板端运行，六项均通过，完整日志 `astar-repository-probe.log`。因此该诊断不再依赖临时手工生成源码；末尾 Fast DDS participant 删除警告保留，进程正常返回 0。

## 高速复测的模块耗时定位

只增加 `SUPER-runtime-profile.patch` 日志字段后重新交叉构建及 ELF 检查通过（`board-build-18.log`），部署 release `4e26c8b1e6d28718fd3abe7953226f6dfe44c3c5f6cd58176f219faca5efb75a`。运行 `1911ee81bc2546a48ef6ec751fed46ee`、报告 `fly-task-1792131602209345074.json` 再次于第 2/8 航点因指令超时降落，55.67 墙钟秒，无碰撞并确认 Disarmed；复盘/ULog 与板端日志齐全，已正常 down。

33 条超时警告（仅超时子集，不能当作全体重规划分布）的总耗时中位数 0.165 s、最大 0.295 s；探索轨迹前端中位数 0.046 s、备用轨迹优化中位数 0.054 s，而可视化中位数 0.0015 s。原 `replan_forward_dt=0.1`，代码接受门限为其 90%；没有放宽该门限。统计 `replan-timing-summary.json`。

自有规划器线程只读采样发现多个活跃 executor 线程位于 CPU 0–3；此前独立 A* 探针在 CPU 4–7 明显更快。进一步对照只将本项目规划器现有线程限定 CPU 4–7，保存每线程原 affinity 与进程身份，其他节点及系统调度不改，正常 down 后限定随进程消失。该试验是否改善真实飞行以最终报告为准，不由核号推断通过。

CPU 亲和对照结果：运行 `f604b7b11b4740fd88c1f56bb6632708`，报告 `fly-task-1792131808234532546.json`。限定本项目规划器线程 CPU 4–7 后推进到第 3/8 航点，仍因 SUPER 指令超时失败，60.55 墙钟秒后 landed/disarmed，无碰撞。速度峰值 7.143 m/s、tracking 时间加权均值 1.251 m/s，仿真/墙钟比 0.659。匹配 ULog 的位置误差 P95 0.998 m、姿态误差 P95 11.96°，高端电机饱和样本占 1.28%，分配器推力/力矩未达成占比仍为 0；不能以这些指标单独归因 PID。规划器后续还出现真实场景 A* 超时。已保存 `cpu-affinity.json`、节点日志与复盘并正常 down；实验限定未写入默认配置，所有相关线程随进程退出。

剩余工作是保持当前路线、点数、速度、时序和保护约束，对探索前端与备用轨迹优化做可复现的性能优化，再从 forest1 回归进入三次 forest10 成功冷启动；没有依据直接放宽门限或宣布硬件达不到。实机、Stage 5 上板与 forest10-ab 长任务均不在本轮通过范围。

本轮收尾：所有自有仿真容器、AirSim/Xvfb、板端飞行节点及亲和实验已回收，既有 Stage 5 两个 PC 容器仍运行。此前为隔离性能而暂停的 Stage 1 模型与 ROS bridge 已恢复，健康 ready；真实以太网文本/非法请求及常驻复用复验通过（`artifacts/stage1-validation/restored-after-flight.json`）。本次以太网测试地址、源策略规则和 HDC 18080→8080 保留供继续开发，均为临时状态。

## 三层流程固化与端到端 profile（2026-10-16）

用户确认后续以“原 image → Dockerfile 增量 → 挂载内容”为执行主线，已写入 `robopi/AGENTS.md`，每层记录对应物、PC 例外和通过证据；本次对应见前表。用户同时授权先 profile，再在必要时采用明确的降级门限；这不改变原基线验收结果。

已增加可选 `board_profile`，默认关闭，目标构建及 ELF 检查通过（`board-build-profile.log`），release `a3b9a4b24fea2e9e8e52203a967cbc3f865f5944d27bebbc00ca00a7fa3ffaf8`。原生函数分别记录 CLOCK_MONOTONIC、CLOCK_THREAD_CPUTIME_ID 与 CLOCK_PROCESS_CPUTIME_ID；原位 Python 记录器覆盖 PC RPC/发云、板端收云/配准及控制接收/发布，PC 另有只读观察器。原始 JSONL、汇总及运行条件均保留。

原门限 profile 运行 `1bdb96097c6a4f968ca5ad756be2fdd6`，报告 `fly-task-1792134166573788583.json`：第 2/8 航点时与 `InstancedFoliageActor_0` 碰撞而中止，48.13 墙钟秒内完成收尾降落，最终 Disarmed。不能称为无碰撞或指令超时保护成功；自动 review/匹配 ULog 已检查。profile 会增加开销，该轮还因首次输出目录权限问题在未起飞待命阶段修复后继续，因此不是与旧飞行严格同初始地图时长的性能对照。

| 计算范围 | 样本 | 墙钟中位数 / P95 | 线程 CPU 中位数 / P95 |
|---|---:|---:|---:|
| ReplanOnce | 26 | 122.5 / 262.6 ms | 119.4 / 258.5 ms |
| 探索轨迹生成 | 41 | 67.2 / 120.1 ms | 66.6 / 119.4 ms |
| 备用轨迹生成 | 29 | 46.0 / 177.7 ms | 45.7 / 175.4 ms |
| A* | 39 | 32.1 / 58.5 ms | 31.6 / 58.1 ms |
| 点云配准及打包 | 541 | 84.2 / 106.3 ms | 84.1 / 106.3 ms |

ReplanOnce 非 CPU 部分中位数 1.39 ms、P95 5.79 ms，支持主要耗时确实在板端 CPU 执行，不能再仅根据总墙钟推测调度/网络等待。嵌套 scope 不可相加；统计含失败收尾，不能等同碰撞前追踪段分布，也不能据此证明硬件没有优化空间。

344 帧完整匹配的点云链路，以同机 PC 发出原始云→PC 收到板端配准云计时：总时长中位数 151.3 ms、P95 326.4 ms；板内接收到发出的驻留中位数 107.6 ms、P95 275.8 ms；逐帧扣除后余量中位数 35.7 ms、P95 156.1 ms。余量包含双向 DDS、序列化与未测回调调度，不是单向线缆延迟。PC RPC 中位数 1.95 ms、P95 3.15 ms。各统计分位数不能直接相加，记录窗口不同的计数差不能当丢包率。

该轮有效指令接收间隔中位数 10.5 ms、P95 35.4 ms、最大 88.1 ms；setpoint 发布间隔中位数 20.0 ms、P95 24.1 ms、最大 39.4 ms。该轮首先碰撞，未证实是指令通信中断；前述超时失败与这轮碰撞分开记录。汇总见本 run 的 `profile-summary.json`。

基于上述测量，新增显式 `planner_timing=robopi-relaxed`：重规划前视 0.1→0.35 s，按原 90% 规则计算接受预算 90→315 ms。前视和预算保持一致；指令、点云、时钟失流、A* 期限及飞行限幅不变。默认 baseline 不变，拒绝未知模式或在 Docker 基线静默忽略该设置。关闭 profile 后先验证 forest1，再试 forest10；只有实际通过的范围才推荐临时使用。操作只维护在 AirSim README。

首个降级候选（将前视和原预算一起拉长到 0.35 s）低速回归失败：运行 `d4b9bf08d62f4943a568f43286b06324`，报告 `fly-task-1792134396227870763.json`，183.87 墙钟秒后因新碰撞中止，最终 Disarmed。review/ULog 已检查并正常 down；没有继续执行高速。此候选已撤回，不建议临时使用，也不以重规划连续成功替代避障验收。

随后核对时间单位：generateExpTraj 的 `replan_process_start_WT` 实际来自 getSimTime，轨迹前视和内部生成超时采用仿真秒；ReplanOnce 的最终原 90% 检查却使用 TimeConsuming 墙钟秒。当前仿真/墙钟比约 0.62，不能将 90 ms 仿真预算与 90 ms 墙钟预算直接等同。后续显式降级改为保留 0.1 仿真秒前视，增加 0.35 墙钟秒计算硬上限，同时仍拒绝总仿真耗时超过 0.09 秒或时间倒退的重规划；baseline 默认原行为不变。该修正仍须实际飞行验证，不把时钟单位问题认定为本次碰撞的唯一原因。

后续双时钟候选已经交叉构建/ELF 审计通过（`board-build-clock-budget-retry.log`），但部署预检失败：HDC 显式目标 `d62903433941363131137f1d31cb9c00` 为 USB Offline，PC enp1s0 carrier=0。不是候选算法飞行失败；该候选尚未部署或验收。上一轮报告已确认 Disarmed，PC 仿真容器/场景已经回收，既有 Stage 5 两容器仍运行；板端 stop 因掉线未确认，运行状态保留 stopping，待连接恢复后先重试 down。

Stage 1 为隔离 profile 已核实空闲和所有权后暂停（worker 7368，见 `artifacts/stage1-validation/pause-for-profile.log`），因本次掉线尚未恢复；不能沿用上一轮 ready 状态。已经请求恢复供电、USB 和 eth1 网线，未自动重启设备或改系统配置。恢复后依次确认设备/链路、完成旧实例清理、部署并复验双时钟候选、恢复 Stage 1。

离线验证：72 项主机回归结果通过，含 3 项因 ROS 环境跳过；profile 统计测试覆盖跨主机时钟偏移、CPU/等待分离和缺测拒绝。五个 SUPER 补丁从干净上游逐项重放及最终逆向检查均通过（`patch-replay-check.log`），防止叠加补丁的上下文在后续 clone 时失效。构建证据增加功能标记，启动 profile/降级前检查所选 release 支持相应能力，避免旧 native 静默忽略新参数。

用户恢复连接后，HDC 身份预检重新通过，板端未重启（uptime 约 14022 秒）。恢复本次 PC/eth1 IPv4 与已有源规则，网络预检通过；旧 stopping 实例的板端清理和日志回收完成。双时钟预算 release `3b50bb5a22ce346ad4e976801657410e526d19e106e9962da0e8d860f07354dc` 已部署并通过完整校验，开始关闭 profile 的 forest1→forest10 分级复验。Stage 1 仍按性能隔离约定暂停，飞行测试结束后恢复。

## 连接恢复后的双时钟候选实测

release `3b50bb5a22ce346ad4e976801657410e526d19e106e9962da0e8d860f07354dc`，关闭 profile，保留原 0.1 仿真秒前视并启用 0.35 墙钟秒上限。低速运行 `db72cbee478e438787b175394435bebe`，报告 `fly-task-1792138496164567190.json`：第 1/2 航点中途因 `lidar cloud timeout` 保护降落，64.39 墙钟秒后 Disarmed，无碰撞。原始雷达末次累计 6.55 Hz/1.02 MB/s，配准云最后时间戳落后于原始流；不能将此轮失败归类为 SUPER 指令超时，也不能仅凭原始雷达仍流动排除配准/排队/传输新鲜度问题。

已查看 review/匹配 ULog：对齐位置误差 P95 0.0874 m、最大 0.1531 m，速度最佳匹配延迟约 0.16 仿真秒；参考最大记录间隔 0.222 秒，不能推断实际发送频率。whole run 日志有 224 次 ReplanOnce succeed 和 79 次总预算拒绝（包含收尾，不作独立成功率）；例如 wall=123.3 ms/sim=105.0 ms、wall=87.3 ms/sim=96.0 ms 均因仿真耗时超过原 90 ms 而拒绝，证明该档并非只放宽墙钟而接受过期轨迹。原始日志及 `clock-budget-summary.json` 保留。

低速未通过，未执行后续 forest10。已正常 down，PC/板端本项目飞行节点均已清理。此档仍为未通过的实验配置，不作为临时可用方案；默认 baseline 没有修改。下一步若继续性能优化，需要分解原始点云解码、位姿等待、配准/体素处理和消息回调的尾延迟，不能把所有失流保护一并放宽。

本轮最终收尾：Stage 3 状态 stopped，自有 PC/板端飞行进程均回收；既有 Stage 5 两个 PC 容器保持运行。Stage 1 模型与 ROS 桥已恢复，worker PID=8714/start_ticks=1433105；健康 ready，真实以太网两次文本约 0.60/0.50 秒、空请求拒绝与同一 worker 复用再次通过，证据 `artifacts/stage1-validation/restored-after-profile.json`。HDC 18080→8080 映射及本次以太网地址/源规则保留。

## 点云持续观测与 IP 分片证据

用户要求延长实测并定位积压后，增加可选逐帧接收/解码、队列快照、丢弃原因与控制桥接受记录。只调整观测，不改配准、任务输入、点数或失流保护；仍选双时钟实验档。release `8bb6c8cde779158581d81107b97a507f7d6c3a3a6affd59d273b903c908bbf8d`，运行 `b811807d07934c1dba23ad5263bf99c6`，本次证据位于 `artifacts/airsim-runtime/<run>/`（此次使用 runtime 默认状态目录，不在前述 airsim-robopi-validation 下）。NoDisplay、GNSS、无 LIO；Stage 1 常驻模型保持 ready/空闲，未发推理请求，不能将这轮 CPU 负载直接等同之前暂停模型服务的测量条件。

PC 旁路连续观察 660 秒，板端从启动到正常停止累计 702.45 秒；先静止 90 秒再执行 forest1，覆盖起飞、追踪、保护降落及落地后持续采样。完整 `cloud-summary.json`：

| 指标 | 实测 |
| --- | --- |
| 原始云接收／配准发布／控制桥接受 | 3939／3939／3939 帧 |
| 队列快照（1 Hz） | 中位数 0、P95 0、采样最大 1 |
| 溢出、过期、位姿插值失败、无效／空云丢弃 | 均为 0 |
| 配准与打包墙钟 | 中位数 88.7 ms、P95 104.9 ms、最大 115.2 ms |
| 位姿／处理队列等待 | 中位数 3.52 ms、P95 7.33 ms、最大 42.48 ms |
| 原始云接收回调空窗 >0.5 秒 | 0.501、3.449、1.755、5.550 秒 |

按分钟汇总未见等待时间持续增长：飞行窗口 P95 约 24.6 ms，之后静止窗口回落至约 3.6 ms。队列快照不能保证捕获每个瞬时峰值，但逐帧记录没有溢出或过期丢弃，所有收到的原始帧均完成配准；“Python 点云逐渐堆积”不符合这轮证据。

首个实际飞行报告 `fly-task-1792140754063722591.json`：66.36 墙钟秒，第 1/2 航点触发 `lidar cloud timeout`，无碰撞，确认 Disarmed。触发前有效云间隔为 508.6 ms；原始云回调最终空窗 3.449 秒，PC 在两端匹配帧之间持续记录 21 帧发布，这些时间戳全程未出现于板端原始云回调。空窗期间队列为 0，位姿及 1 Hz 快照持续更新，未见控制桥拒收旧云。因此本次不能归因为配准循环阻塞或应用层排队。

已查看该轮 review 与匹配 ULog：对齐位置误差 P95 0.1478 m、最大 0.1651 m，指令接收间隔最大 22.3 ms、实际下发参考最大 32.4 ms（ROS 记录）；ULog 外部参考最大记录间隔 0.219 秒，不用于推断发送频率。速度最佳匹配延迟约 0.19 仿真秒，未见电机高端饱和或分配器推力／力矩未达成；0 dropout、无损坏。

为观察长运行负载，从第一次落地位置再次启动同一任务；未复位现场。这次在进入追踪前因旧 SUPER 指令相对当前位姿误差 4.040 m 被原控制约束拒绝，报告 `fly-task-1792140978627038683.json`。这是独立的暖重启限制，不算第二次点云失流保护或可对照的冷启动飞行。review 无 tracking 区间，未作内环性能推断；已直接读取对应 `08_56_23.ulg`：Offboard→AUTO_LAND，arming 2→1，无 dropout，证据 `second-flight-lifecycle.json`。其降落收尾另出现 5.550 秒原始云接收空窗，PC 期间持续记录 29 帧发布。

此次空窗被 180 秒板端以太网报头采样及 1 Hz 内核计数覆盖。AF_PACKET 采样接收 246825 个本次地址对报文，采样 socket 丢包计数为 0；整个采样窗口 122808 个 IP 分片，重组失败累计增加 3518。覆盖空窗的相邻计数边界内，`ReasmFails` 增加 **3474**，`ReasmTimeout` 增加 3；空窗中间连续多个采样点 `ReasmOKs` 停止增长，`ReasmFails` 随新分片增长；UDP `InErrors/RcvbufErrors/InCsumErrors` 增量均为 0。报头看到点云样本约 180 KB（最大 180621 字节），RTPS 大 UDP 报文长度约 65476 字节，在 MTU 1500 的以太网上进一步发生 IP 分片。证据 `ethernet-board.pcap`、`network-counters.jsonl`、`network-summary.json`；临时采样脚本保留在本次 run，限时退出，没有改内核参数。

这些证据将原始云空窗定位到板端 IP 分片重组环节，而不是把所有网络延迟统称为线缆慢。两端协商 1 Gbps，20 次 ping 无丢包、RTT 平均 0.844 ms／最大 1.005 ms，网卡错误／丢弃计数为 0；这些小包结果本身不能排除大 UDP 分片失败。PC 包级采样仅覆盖后续正常段，不能拿它声称已经确认故障时每个分片在两端完整一致。当前尚未区分最初分片缺失与内核重组资源耗尽的具体诱因，也没有做减少 UDP 报文长度的 A/B；不能写成已经修复。后续修复优先验证避免 IP 分片的 DDS 传输配置，保持点数和保护门限不变。

新增分析回归覆盖故障前后事件边界、旧云拒收、PC/板端时钟偏移下按帧关联与缺测拒绝。Stage 3 全部 74 项主机测试结果为 71 通过、3 项因 ROS 环境跳过，Python 语法及 diff 检查通过。最终 Stage 3 状态 stopped，自有节点／场景／虚拟显示已回收；既有 Stage 5 两容器保持运行。Stage 1 worker 8714 仍 ready/空闲，发现此前 HDC 映射缺失后恢复 18080→8080，并从 PC 实际读取 health；没有额外推理请求或重启板子。

## 放宽重规划预算的 5 m/s 八航点实验

用户明确要求放宽重规划超时并尝试 5 m/s 后，新增显式 `robopi-forward-200ms` 实验档：规划前视 0.1→0.2 仿真秒，外层仿真计算接受预算 90→180 ms，墙钟上限 350 ms。内部探索轨迹仍检查前视期限，时间倒退仍拒绝；不能只把墙钟上限调大而忽略原 90 ms 仿真约束。原 `baseline`、`robopi-relaxed` 均保持原值。此档同时调整切换前视，不是单一墙钟门限的因果对照，也不据此证明实机适用。

`task.forest5.json` 与 forest10 任务只在名称和 `speed_m_s=5` 上不同；八航点、20 m carrot、8 m/s² 加速度、settings、20 万点／秒、定位和控制参数不变。NoDisplay、GNSS、无 LIO，关闭 profile，冷启动运行 `f11783ff91f34a02b277afde23b4134f`，release 复用 `8bb6c8cde779158581d81107b97a507f7d6c3a3a6affd59d273b903c908bbf8d`，只部署新 task/planner 快照，无需重编 native。证据位于 `artifacts/airsim-robopi-validation/<run>/`。

报告 `fly-task-1792141744669083995.json`：56.18 墙钟秒，第 **3/8 航点途中**因 `lidar cloud timeout` 保护降落，无碰撞，确认 Disarmed。跟踪速度峰值 **5.194 m/s**，记录内速度 ≥4.5 m/s 累计约 **2.706 仿真秒**，追踪阶段约 11.97 仿真秒、累计路程约 19.56 m；不能将短时达到 5 m/s 写成完整八航点通过。末次追踪位置约 `[-0.642,15.941,2.114]`，已到第二个航点附近，第三个目标尚未完成。

规划日志共有 34 条 `ReplanOnce succeed`，成功日志无时间戳，不拆分阶段或计算调用成功率。4 条外层预算拒绝带 ROS 日志前缀时间，但该前缀不能直接当作节点仿真时间。此前将其与报告仿真时间比较，得出“均在降落收尾、追踪无超时”的结论是错误的，现已撤回；该轮关闭 profile，阶段归属尚未可靠重建。4 条仍因消耗仿真时间 192–204 ms 超过 180 ms 拒绝，墙钟 260–307 ms，说明放宽后时间约束仍生效。证据 `planning-phase-summary.json`。本轮终止原因是点云失流，不是重规划／指令失流。

已查看自动 review 与匹配 ULog：ROS 同刻对齐位置误差 P95 0.531 m、最大 0.577 m；追踪阶段指令接收间隔最大 21.0 ms、下发参考间隔最大 33.8 ms。ULog 无损坏、无 dropout，未见电机高端饱和或推力／力矩未达成，速度最佳匹配延迟约 0.12 仿真秒。ULog 外部参考最大记录间隔 0.219 秒，不据此推断发送频率。飞行期间保存的网络计数窗口内 IP `ReasmFails` 增加 1559，UDP `InErrors/RcvbufErrors` 均无增长；本轮关闭逐帧 profile，不能用此整窗增量单独还原故障瞬间。

配置／运行回归仍为 74 项中 71 通过、3 项 ROS 环境跳过，语法检查通过。已正常 down 并回收自有节点和仿真。该档仅证明短时达到 5 m/s，完整任务仍未通过；没有放宽点云、指令或时钟看门狗，没有修复既有 IP 分片问题，也未做不同预算下的重复成功率对照。

## AB 基线纠正与点云失流仅观察实验

用户明确基线是 AB 单目标，前述八航点 5 m/s 试验不能代替 AB 验收。默认入口现改为 `runtime.forest10-ab.json`，八航点只保留为显式历史对照；本轮从 AB 构建 5 m/s 配置，未使用八航点。

保护来源已查 Git：迁移前提交 `04cab248cd14f538d686a534637491f51dd65b5a`（2026-10-16 10:47:08）中的 `super_px4.py` 已含 `track` 点云超时降落，以及 AirSim 任一活动阶段点云超时降落。当前迁移修改之前就有这段逻辑，不是本轮 IP 分片故障后临时加的。但它是控制桥的附加保守策略，不是 SUPER/PX4 必需接口；既有记录没有验证 0.5 墙钟秒对当前链路的合理性。代码历史只能证明引入时点，不能证明当时设计依据。

按用户允许仿真碰撞、观察失流影响的要求，任务新增显式 `lidar_loss_action=observe`：不因飞行中点云 >0.5 秒未更新而降落，新目标也不因旧点云拒绝；失流／恢复保留日志和 profile 事件。起飞前新鲜地图、健康状态、指令有效性、状态／时钟、SUPER 指令失流和人工降落机制沿用原值。默认仍为 `land`，未知值拒绝。没有为了获得碰撞而强行修改规划器自身的停点／备用轨迹行为。

本轮 release `365762603c9a75b03bd762c819d4880ec92979c1bec797e760ee8f44e4579fbc`，运行 `130451f096c348838bba4363c5e028c5`，任务 `task.forest5-ab-observe.json`，NoDisplay、GNSS、无 LIO、200 ms 前视／180 ms 仿真预算／350 ms 墙钟上限，开启 profile。相对 AB 原任务仅改变名称、速度为 5 m/s 和点云失流策略；B 仍为 `[-37.57,231.76,6]`，直接目标、20 m 局部规划范围、8 m/s² 和点云设置保持原值。

报告 `fly-task-1792142338089792670.json`：78.58 墙钟秒，实际追踪速度峰值 5.386 m/s；未到 B，无碰撞，最终因 **SUPER command timeout** 降落并确认 Disarmed。以下时序直接使用同一板端 `control.jsonl` 的单调时钟，而不是拿日志前缀与仿真时间比较：

| 事件 | 相对空窗前最后有效云的墙钟时间 | 实际表现 |
| --- | --- | --- |
| 最后有效云 | 0 s | PX4 估计位置约 `[-1.15,13.78,5.51]`，速度约 4.85 m/s |
| 超过失流检测门限 | 0.508 s | `cloud_loss_started`，action=observe、mode=track；没有降落 |
| 新鲜点云恢复 | 6.598 s | 仍为 track，位置约 `[12.88,31.42,5.05]`，速度约 4.97 m/s |
| 恢复后减速并停在轨迹端点 | 随后数秒 | 参考速度降到 0，实际位置保持约 `[15.3,35.0,5.9]` |
| 指令超时降落 | 恢复后 17.196 s | 规划停止输出后触发原 0.5 秒指令看门狗；不是点云降落 |

6.598 秒有效云空窗内仍接受 **649 条规划指令**，最大指令间隔 156.5 ms，小于原 0.5 秒门限；PX4 估计轨迹累计前进约 **22.69 m**。原始云回调也出现 6.597 秒空窗，PC 在匹配帧之间记录 44 帧发布；整 run 应用队列采样最大 1，只有 1 次位姿括区丢弃。恢复后的观察中点云继续更新，控制仍持续接收并执行停点指令。不能把“点云失流”描述为立刻失控或必然碰撞，也不能把这一次自然失流当成对所有场景无影响的证明。

原生日志显示：空窗后段开始出现 A* 原 0.1 仿真秒搜索超时；恢复后仍连续搜索失败，已提交轨迹结束，触发 `Stationary trajectory ended; hold endpoint while replanning`。停点保持原 10 仿真秒到期后出现 `Stationary replan hold expired; stop commands for controller failsafe`，随后控制桥 `SUPER command timeout`。点云空窗前也已有外层重规划超预算拒绝，因此本轮不是“除失流外一切正常”的因果对照，不能把后续规划失败全部归因于失流。若需确定失流的独立影响，应再做相同场景和初态下的受控暂停对照；本轮没有声称已完成该对照。

已查看自动 review 和匹配 ULog：无碰撞、无损坏、无 dropout，速度最佳匹配延迟约 0.13 仿真秒，未见电机高端饱和或推力／力矩未达成；ULog 参考最大记录间隔 0.267 秒。证据均位于 `artifacts/airsim-robopi-validation/<run>/`：`loss-impact-summary.json`、`loss-impact.png`、生成脚本、原始 profile、飞行报告、review 与 ULog。图中位置／速度为 PX4 估计，按 ROS 消息时间戳关联 PC 遥测与板端单调时钟，事件附近有采样误差；没有跨主机相减绝对单调时钟。

新增策略主机配置校验通过，完整主机回归 75 项中 72 通过、3 项 ROS 环境跳过；独立无网络 Humble 容器实际运行 3 项 ROS 测试，验证失流仅观察、恢复事件、默认失流降落、AB 远端目标不变和人工降落。本轮已正常 down，默认策略未改成 observe，AB 尚未验收成功。

## 无窗口实景录像与离线点云回放

按用户需要查看实际飞行，增加 PC 端 `flight_video.py`：独立 ExternalCamera、640×360、默认 2 Hz 墙钟采样，车辆局部 NED 加本次出生点转换为外部相机全局 NED。只调用读取车辆位姿、设置相机位姿及获取图像的接口，不发布飞行命令或修改飞机位姿。相机位于飞机后方／侧方 5／3 m、上方 6 m；静止预热后已人工查看地面和起飞后的画面，机体及环境可见。保留 NoDisplay，不打开场景窗口或 RViz。

新运行 `f63b716f6f6045758516e33b2c50b5e8` 复用 release `365762603c9a75b03bd762c819d4880ec92979c1bec797e760ee8f44e4579fbc`，仍为 AB 单目标、5 m/s、200 ms 前视及点云失流仅观察，新增独立相机；没有降低点数、修改飞行控制或放宽边界。先进行 6 秒／3 秒静止抓帧预热，再启动录像与飞行，等待条件与上轮不同，不能把不同结果直接解释为录像开销的因果对照。

报告 `fly-task-1792146142005721726.json`：69.69 墙钟秒，跟踪峰值 5.350 m/s；规划参考位置 `[20.002,48.094,7.007]` 超过原任务东侧 `x<=20 m` 边界，被控制桥拒绝并降落。报告未记录碰撞，确认 Disarmed，未到 B。触发时参考与实际位置误差约 0.236 m，不是越过位置误差门限。已查看 review 和匹配 ULog：同刻对齐位置误差 P95 0.536 m／最大 0.611 m，速度最佳匹配延迟约 0.11 仿真秒，无 ULog 损坏或 dropout，未见电机高端饱和或推力／力矩未达成；参考最大记录间隔 0.222 秒，不据此推断发布频率。

实景抓帧共 149 帧，74.38 墙钟秒，全部为 640×360；抓帧 RPC＋PNG 保存耗时中位数 102.2 ms、P95 157.5 ms、最大 232.1 ms。本轮报告仿真／墙钟比 0.643，不能假定相机零开销。旁路另保存 95 帧配准 world 点云（包含飞行前后观察窗口），仅供离线显示；不反馈到算法。

输出位于 `artifacts/airsim-robopi-validation/<run>/`：

- `airsim-third-person.mp4`：真实 AirSim RGB，包含起飞、飞行及收尾降落；H.264／640×360，按图像仿真时间戳编码。20 fps 容器重复保持实际采样帧，没有光流补帧。输出 gamma=1.6 只提高显示亮度，原始 PNG 和每帧时间／相机姿态完整保留在 video/。
- `telemetry-cloud-replay.mp4`：H.264／1000×600、8 fps，约 27.88 仿真秒，来自实际 PX4 估计位姿、下发参考和已保存点云；显示高度、速度、点云年龄。没有补造机体姿态；失败任务的 report records 到首次失败为止，不含收尾降落，画面已明确标示。RGB 录像覆盖完整降落过程，两者不能只按视频起点秒数直接对齐，原始数据保留绝对仿真时间戳。
- `video-validation.json`：ffprobe 元数据与整段解码通过结果；已人工查看实景和点云回放的代表帧。仅凭播放器可以打开，不等同飞行验收。

上一轮 `130451f096c348838bba4363c5e028c5` 已从原报告补出 `telemetry-replay.mp4`，约 35.88 仿真秒；该轮没有原始相机帧和点云，不声称补出了实景或障碍物。录像及回放复用操作仅维护在 AirSim README。

新增相机坐标／方向、settings 保真与覆盖拒绝、编码时间回跳拒绝测试；主机完整回归 78 项中 75 通过、3 项 ROS 环境跳过，脚本语法检查通过。新实景／点云 MP4 均经整段解码检查。本次仿真、虚拟显示与自有板端节点已正常清理，Stage 1 常驻服务仍 ready。未对 Stage 5 执行启停；收尾时 docker ps -a 已不含先前 Stage 5 容器，原因未核验，不自动重建无关工作负载。

### AB 外层实验门限审计与修复（2026-10-16）

forest10-ab 同样共用 super_px4.py，原本有任务包络、参考速度/加速度、3 m 跟踪偏差直接降落，以及缺省点云失流降落。当前 10-ab 与 5-ab-observe 显式设置 trajectory_limits_action=observe、lidar_loss_action=observe：上述超限只记录，轨迹保持原值；非有限指令、无位置、过期指令独立检查并给出明确原因。任务报告记录实际策略。其他任务缺省行为保留。保留的任务超时、状态/指令失联、规划器保持期限、PC 碰撞收尾及 PX4 Offboard 失联行为已集中列入 AirSim README 的中止条件表。

验证：Python 语法检查通过；host 79 项测试中 76 通过、3 项 ROS 环境跳过；隔离 Humble Docker 的 4 项 ROS 测试全部通过。使用真实 PositionCommand 对两个 AB 配置重放 20.00217 m 东向参考，确认继续接受；同时越界、超速、超加速度、偏差 >3 m 时仍接受且记录，切回 land 策略则拒绝；NaN 与过期时间戳仍拒绝。未运行新的仿真飞行，不能据此宣称 AB 完成。

已通过 HDC 发布独立 release `ec249152b59e5aecbeebf1fd35ce423ff533784c9203865dc6391ee2ad4982fe`，保留旧版本。发布前确认上次 Stage 3 的 supervisor/control/lidar/planner/mission 全部未运行。新 release 在实际 OpenHarmony Python/ROS 消息环境重放同一测试通过（两个 AB 配置、仅观察与 land 对照、非有限/过期拒绝），无 ROS 节点启动、无飞行命令；证据 `artifacts/robopi-stage3/ab-guard-check.json`。首次测试工具缺少 app/airsim 导入路径，补齐后通过；未修改板端全局环境。下次 up 使用新 release 和当前任务输入，不复用旧启动快照。
