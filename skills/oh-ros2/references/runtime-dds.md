# 环境、部署与 DDS 运行

## 环境初始化

优先读取并复用项目的 ros_env.sh。重定位 ROS 安装时，基础 Python/库路径要先配置，再 source 对应 local_setup；setup 中残留构建机器路径可能使它直接失败。

环境入口应保留用户显式选择的域、RMW 和项目配置。避免在通用环境脚本中启动节点或发业务命令。场景、地图和后端默认值属于项目配置，不属于所有 OpenHarmony ROS 项目。

确保直接执行的 Python 脚本有目标板存在的解释器；某些 OHOS 镜像没有 `/usr/bin/env`，常见 Linux shebang 不能直接使用。shell/Python/launch 直接打包，只有 native 扩展需要交叉编译。

## 部署与进程

只发送 runtime，不把 SDK 和构建缓存搬到板上，除非用户确实要求板端构建。复用基础 ROS 安装，以 overlay 或独立项目包提供自建内容。

传输前后校验归档与展开文件，保存可回退版本。核对板端 tar 支持的格式；已验证工程采用 GNU tar 格式避免板端 PAX 长路径兼容问题。检查 symlink、执行权限、解释器、ament index 和配置。

进程管理核对项目路径、PID 启动时刻和命令行；只操作项目拥有的进程。启动成功需观察目标节点和输出，不只检查 shell 退出码。停止后核对残留节点、进程和管理状态，并按任务需要验证重启。

主机/板端拆分时明确每个输出的所有者，避免重复的 mapper、规划器、执行桥或 `/clock` 发布者。启动顺序依据实际依赖，节点就绪与外部输入就绪分开检查。

## DDS 通信

HDC/SSH 负责管理，不自动承载 ROS 话题。跨机 ROS 2 使用实际 IP 网络上的 DDS。检查通信域、localhost 限制、接口、发现和 QoS；同一 RMW 作为已验证诊断基线，不声称不同 DDS 厂商永远不能互通。

容器 host 网络是 Linux 主机上的已验证选项，不是任何部署的必要条件。使用桥接网络时要明确发现和可达路径。网络接口变更或多网卡环境需要验证 DDS 实际选择的地址，不先假定 profile 配置一定必要。

验证序列：

1. 正确初始化环境；同板节点可收发。
2. 主机↔板端标准消息双向收发。
3. 自定义消息字段及 QoS 兼容。
4. 请求的业务链路、启动停止和故障处理。

可靠/尽力、durability、缓存地图的晚加入行为必须与实际发布者匹配。图可发现、topic list 存在或 ping 成功不等于消息交付成功。

仿真中所有需要仿真时间的节点使用 `use_sim_time` 并有实际 `/clock` 输入；真机按统一采集时间和时钟同步策略设置。用单调时钟检测“多久没有新数据”，避免暂停仿真也暂停失效计时。

## 按症状定位

| 症状 | 优先检查 |
|---|---|
| Python/ros2 启动失败 | bootstrap、libpython/libintl、Python 路径 |
| native import 或程序加载失败 | 目标 ELF、SOABI、NEEDED、实际库解析路径 |
| 已发现但收不到消息 | 类型版本、QoS、域、接口、localhost 限制 |
| 偶发停滞或失效 | 输入新鲜度、仿真时钟、DDS 交付、节点退出 |
| 业务目标被拒绝 | 地图、坐标、状态及原有业务门限，不先放宽门限 |

RoboPi 曾出现 `Failed to delete participant`：只能称为已观察的关闭告警，结合进程退出、残留和重启证据判断；不要一律解释成成功或失败。其他平台相同文本也需调查。

## RoboPi 以太网策略路由案例（2026-10-16）

本课程板端为 eth1 手工设置独立 IPv4 后，双向 ARP 成功，但 ping 与仅 bind 源 IP 的 UDP 无回复；同一个 UDP socket 加 SO_BINDTODEVICE 后回环成功。只读 netlink dump 发现默认 fwmark 规则先查表 99/109，早于 main 表。添加只匹配本次以太网源 /32 的 main 查表规则后，ICMP 与真实 ROS 标准消息双向回环通过；未修改默认路由、Wi-Fi 或防火墙。

这是当前设备规则组合的证据，不是所有 OpenHarmony 的初始化步骤。遇到类似现象先核对实际规则、源地址、路由表及绑定接口的对照；没有 `ip` 时可用只读 NETLINK_ROUTE dump。需要调整时限于本次专用源地址，检查优先级冲突，记录所有权并提供精确撤销方式。课程 `robopi/tools/ethernet_rule.py` 实现了这一流程，只有当前仓库存在时才引用。

多网卡实验可生成双方各自的 Fast DDS UDP 接口白名单和单播 initialPeers；记录实际 IP 与足够的 participant 探测范围。HDC fport 适用于 HTTP 等已支持端点，不等于 UDP DDS 运行网络已打通。

2026-10-16 C++ 时钟最小复现：当前 RoboPi 的 rmw_fastrtps 在同一 C++ 节点 use_sim_time=true（隐式订阅 /clock）后再创建 /clock 发布器，触发 cast_or_create_topic 的 nullptr 断言。false 时同一探针返回 0；PointCloud2/MarkerArray/Odometry 本身正常。不能据笼统断言认定点云 ABI 或 DDS 网络失败。外部仿真时钟应保持单一来源，SUPER 未使用的 Clock publisher 改为 setSimTime 显式调用时才创建；不要关闭 use_sim_time 绕过时间契约。诊断源码及编译入口见 stage3/board/probes，正负对照日志见本次 artifacts。

显式 UDP 接口与 initialPeersList 场景下，peer 列表须同时覆盖本机接口地址和远端地址。只列远端可导致跨机 DDS echo 通过，但同一 PC 的 Agent→clock/verifier 不发现，表现为板端收到 PX4 而 PC /clock、vehicle 均缺失。单条跨机 echo 不能替代多参与者本机＋跨机拓扑验证。

上述多参与者复验后进一步确认：PC 同机 Agent→ROS 需要 UDP 回环接口，PC 白名单和 initialPeersList 加入 127.0.0.1 后 sensor_combined echo 和完整静止验收通过（3.74 秒）。只加本机以太网 peer 能修复 ROS 节点互通但不足以覆盖 Agent；额外 SHM 对照无效，已撤回。板端仅以太网即可。
