# 仓库开发约定

## 使命与交付对象

本仓库承载无人机实践课程 demo，同时服务两类使用者：
- 学员：clone 到 PC 后，按 hands-on 文档完成仿真、板端开发和飞行任务。
- 课程维护者：从 PC 使用仓库脚本，通过 HDC 为 RoboPi 准备、部署和诊断环境。

默认使用中文编写课程文档与操作说明。交付应包含可运行代码、操作步骤、预期现象和故障排查；不能只提供方案。

## 系统边界

- PC：运行包含 PX4 SITL 与 Gazebo 的 Docker 环境，以及 QGroundControl、可视化、聊天 GUI、竞速计时和排行榜相关服务。
- RoboPi：运行 OpenHarmony，模拟无人机机载算力板，承载 ROS 自主飞行、视觉、多机协作与大模型推理。
- HDC：用于板端 shell、文件传输、部署与诊断。PC↔RoboPi 的跨机 ROS 通信默认使用独立以太网 DDS，复用显式网卡白名单与单播 peer 的已验证范式；PC 同机通信保留必要的 UDP 回环。HDC fport 仅用于 HTTP/TCP 等管理或服务端点，不代替 DDS；不要默认 HDC 已通过以太网配置好。地址、网卡和路由按本次环境核实，不硬编码测试设备配置。操作入口见 Stage 3 AirSim README 的“板端以太网通信”。
- PX4 是飞控；RoboPi 是算力板。算法从 PC 迁移到 RoboPi，不应描述为部署到 PX4 飞控。
- Stage 1 已验证 ROS 2 Humble、rmw_fastrtps_cpp、域 10 与板内 HTTP 127.0.0.1:8080；OpenHarmony AArch64、Linux 6.6.86、Python 3.12 ABI、Houmo 驱动 v1.4.0 与 TCIM v2.5.0 的证据见 docs/stage1/Hands-on.md。换设备或镜像时重新核实。PC PX4/Gazebo 当前基线见 Stage 2 文档；飞行消息接口及后续 SDK 组合仍待确认。

## 当前事实

- `stage3/jev.py` 已提供 Jev Decisions API 包装，`stage3/demo.py` 是文本情感决策示例。
- Stage 3 当前默认为 SUPER＋PX4/GNSS 定位，Humble Docker 与 PX4/Gazebo Docker 运行无附加标记的实体走廊；2 m/s 往返与 Gazebo＋点云 RViz＋ROG 体素地图 RViz 三窗口已验收。FAST-LIO2 为显式对照，提供约 30 Hz 配准点云与 200 Hz IMU 传播；带标记往返及持续雷达失流降落已验收，原赛道纯 LIO 完整往返仍失败。当前已移除固定高度投影、加高墙柱到 8 m，起飞高度 1.95 m；新场景 XYZ 执行已通过 2 m/s 一次往返，5 m/s XYZ、含悬空障碍三维避障、LIO 5 档、实机与板端待验证。入口、证据和并行开发边界见 docs/stage3/Development.md。
- AirSim 替换后端位于 `stage3/super/airsim/`；PC 场景＋PX4 Docker＋Humble SUPER Docker，当前基线及默认入口为 forest10-ab（10 m/s）单目标，八航点仅保留为显式历史对照。单目标 `runtime.forest10-ab.json` 保持 20 m 规划距离，已修正 A* 裁剪终点返回值并通过真实搜索回归；实飞已连续重规划，但碰撞中止，约 235 m 长任务未验收。入口与证据见该目录 README，上游问题报告见 `docs/stage3/SUPER-astar-clipped-goal-report.md`。
- Stage 3 AirSim/SUPER 的 RoboPi 后端入口已实现（PC 单容器＋板端原生，GNSS、无 LIO），构建、部署及无显示步骤见 AirSim README；单容器 PC 镜像、以太网 DDS、无显示 Docker 短程/forest1/forest10 基线已通过；目标构建、板端加载/消息序列化、1 m/s 短程与 forest1 往返已通过，低速雷达/规划器/时钟失流及控制桥退出降落通过；forest10 首轮因指令超时降落，三次成功冷启动待完成，证据见 docs/stage3/RoboPi-validation.md。
- 2026-10-16 后续 profile 确认板端重规划主要耗费线程 CPU；原门限 profile 轮及直接拉长前视的低速候选均发生碰撞。当前显式降级候选保留 0.1 仿真秒前视，增加 0.35 墙钟秒上限并检查原仿真预算，已部署，但低速因 lidar cloud timeout 保护降落，未通过；未继续高速，默认基线不变。后续 702 秒点云持续采样无应用队列丢弃，3939 帧全部完成配准；复现原始云接收空窗，并在 5.55 秒空窗同步捕获板端 IP 分片重组失败，网络接收问题尚未修复。本轮飞行实例已清理，Stage 1 保持 ready，HDC HTTP 映射已恢复。证据见 docs/stage3/RoboPi-validation.md。
- 后续 5 m/s 八航点实验使用 200 ms 前视／180 ms 仿真计算预算／350 ms 墙钟上限，实际峰值 5.194 m/s；第 3/8 航点途中因点云失流降落，无碰撞、已解除解锁，完整任务未通过。全 run 有 4 次超预算拒绝，先前按日志前缀判定阶段的结论已撤回（墙钟不能直接与仿真时间比较）；原基线不变，证据见 docs/stage3/RoboPi-validation.md。
- 已按用户要求改回 AB 默认基线。AB 5 m/s 的显式点云仅观察实验中，有效云空窗 6.598 秒仍持续接收 649 条规划指令、前进约 22.69 m；点云恢复后停在轨迹端点，连续 A* 失败及停点保持到期后因指令失流降落，无碰撞、未到 B。默认点云策略仍为 land，实验 observe 不自动扩展到其他任务；证据及日志时基纠错见 docs/stage3/RoboPi-validation.md。
- AirSim 已提供 PC 无窗口低频第三人称 RGB 录像和实际遥测／点云离线 MP4 回放，入口 flight_video.py、diagnostics/replay_video.py；操作见 AirSim README。AB 5 m/s 录像轮峰值 5.350 m/s，规划参考越东侧 20 m 边界后降落，无报告碰撞、已解除解锁，未到 B；视频输出与性能开销见迁移验证。
- Stage 1 新布局已于 2026-10-16 完整部署校验并通过真实以太网 ROS 两次文本、空请求拒绝、桥重启复用同一 worker、并发 429 和单图 VQA；DMA/CMA probe 失败经授权重启后早期加载驱动恢复，证据见 docs/stage1/Hands-on.md。自主飞行 API 和 PC 聊天 GUI 尚未实现。
- Stage 2 标准机为 `x500_experiment`（Orbbec Gemini 2 RGBD 几何近似＋MID-360S 规则 GPU 扫描近似），引用独立 `mid360s` 模型；启动时两个模型目录均需挂载。四图基础展示已获用户确认，改装后完整飞行仍待验收；操作与实测证据分别见 `docs/stage2/Hands-on.md`、`docs/stage2/Validation.md`。
- 路线与完成状态见 `docs/roadmap.md`。只有实际可运行并有验证证据的功能才标记完成。

- Stage 5 已提供独立街区、标准机 RGBD（仿真深度上限 20 m）、本地 DINO 与 Jev client。PC MAVLink Offboard 的红色方块车后上方跟随已通过 35/60 秒试验，车速 0.7 m/s，60 秒真值评测水平间距中位数 7.92 m、上方 2.16 m。真实 Qwen3.6-35B-A3B（本地18080/v1，API模型名qwen3.6-35b-a3b）视觉规划→DINO/Jev→PX4单阶段60秒任务通过，32次Jev调用无错误并确认completed，运动后半段水平距离中位数7.95 m、上方2.11 m；使用颜色/RGBD 跟踪和显式仿真未知空间限速策略，未验证搜索、通用目标、复杂绕障、完整一圈或上板。入口与边界见 docs/stage5/Hands-on.md、Validation.md。
- Stage 5 mission现使用Qwen验收闭环：总budget仅限制Qwen执行请求，总timeout覆盖执行全程，最终额外总结1次；Jev的stage额度由Qwen分配。真实“观察确认→跟随10秒”动态任务通过，3次预算内Qwen、1次总结、20次Jev均成功；达标区间真值水平8.05m、上方2.14m，仍有1.57m横向偏差。redo/modify_stage/modify_plan由受控协议与单元测试验证；55项测试通过。验收期间车辆继续运动，不复位现场；没有搜索或复杂重规划效果保证。架构见docs/stage5/Agent.md。若PC18080不可达，先检查HDC映射；2026-10-15曾仅因转发丢失而不可达，板端worker3086仍ready。

## 实施原则

1. 优先完成最小端到端链路：PC 仿真 → RoboPi 通信 → 板端控制一个仿真无人机，再扩展算法与多机任务。
2. 区分课堂操作与课前准备。下载镜像、编译 SDK、转换模型等长耗时步骤放在教师准备流程中。
3. 每个命令标明执行位置（PC、Docker 或 RoboPi），并说明前置条件、成功判据与常见失败的恢复方式。
4. 部署脚本显式选择设备，支持重复执行，检查依赖和错误，保留诊断信息；避免覆盖未知板端文件或无关进程。
5. 不把 Linux ROS 二进制直接当作 OpenHarmony 可用产物。记录交叉编译工具链、架构、运行库、环境变量和依赖。
6. 仿真算法、赛道和模型记录版本、来源、许可证、配置、资源需求与验证条件。候选工作不能写成已复现成果。
7. 飞行接口提供明确的状态、坐标系、单位、超时和失败处理；模型建议经过确定性约束检查后才能进入控制接口。
8. 单机与多机实现明确命名空间、无人机标识、通信端点和仿真时间约定。
9. 对比算法时固定赛道、初始状态、资源预算、参数与评价规则；记录速度、成功率和失败原因。 AB 仿真实验不得新增隐藏的边界／跟踪误差／失流中止；当前仅观察策略及保留中止条件统一维护在 AirSim README 的“AB 仿真实验的中止条件”，改变终止行为须用户授权。
10. 不提交 API key、`.env`、模型大文件、编译输出或运行日志。提供无真实密钥的配置示例。

## 仓库布局

- `stageN/`：该阶段在 PC 使用的代码和部署入口。
- `robopi/`：板端交付文件的唯一维护位置，按 `stageN/` 对应板端阶段目录；开发、部署和迁移验收遵循 `robopi/AGENTS.md`。
- `skills/`：仓库维护的 Codex 板端 skills，随代码同步；使用时读取对应 `SKILL.md`，不要只依赖个人目录中的旧副本。
- `src/`：仅放跨阶段通用工具或包，没有则不创建。
- `artifacts/models/`：大模型缓存或软链接；embedding 位于模型目录 hmquant/quant_embedding.bin，部署保持整个模型目录的相对结构。大文件不提交 Git。
- `docs/`：课程文档；`docs/AGENTS.md` 是代理准备板端环境的流程，随实现跟进。

上游推理工具直接获取运行产物，Stage 1 放在 robopi/stage1/qwen_infer/ 并忽略跟踪。
不复制维护上游 main.cc、编译工程或模型转换源码，不再使用 prepare_qwen_bundle.py 和 manifest。
不预建空目录，不为同一流程维护重复说明。

## 验证与报告

按变更运行必要检查。Python 代码先检查语法；网络 API、GUI、仿真和板端功能必须分别验证实际链路。没有设备、模型或网络条件时，明确报告未验证项，不把静态检查等同于课程验收。不要为验证而默认调用付费 API。

报告说明改动、验证结果和剩余依赖。涉及 RoboPi HDC、OpenHarmony ROS、Houmo NPU 的实际工作时，读取并使用对应可用技能。
