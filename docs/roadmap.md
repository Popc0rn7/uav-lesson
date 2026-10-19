# 课程实施路线图

## 验收通则

每项交付包含代码或配置、学员步骤、教师准备步骤、预期现象、排障说明与验证记录。验证记录注明版本、PC 配置、板端系统、网络拓扑和资源需求。具体软件兼容组合与模型选型待实测确认。

## 1. 熟悉硬件 · 20 min

板端准备流程见 [AGENTS.md](AGENTS.md)。源码、编译入口与上传包按 [厚摩交付](../houmo/README.md) 分别集中到 `houmo/src/`、`houmo/build/`、`houmo/deploy/`，模型在 `artifacts/models/`；已准备标准话题的 ROS 聊天节点与 PC 命令行客户端，流程见 [Hands-on](stage1/Hands-on.md)；板端与 PC 局域网标准消息收发已验证，正常问题触发板端 NPU 推理并回到 PC 的链路已验证，以下待办保持未完成。

1. 认识 PC 仿真飞控与 RoboPi 算力板的分工，连接硬件并进入 `hdc shell`。
2. 运行脚本，观察 ROS 包如何交叉编译、传输并在板端运行。
3. 在板端运行大模型节点，在 PC GUI 中聊天。

- [ ] Hands-on 文档：硬件、网络、HDC、编译、部署与运行。
- [ ] 教师准备与诊断脚本：设备选择、依赖检查、板端环境和恢复流程。
- [ ] LLM chat demo：板端节点与 PC GUI。

验收：学员可按文档进入指定板子、运行示例 ROS 包，并从 PC 获得板端模型回复。

## 2. 飞控 + 仿真学习 · 40 min

此阶段暂不使用算力板，在 PC 跑通飞控与仿真链路。

新主线从 Stage 2 统一为 PC AirSim＋Docker 1 PX4；Stage 2 不需要 Docker 2，先直接操作 PX4 验证起降和运动，再接 QGC 手动竞速。后续阶段沿用环境，按算法需要增加 Docker 2 Humble，再迁移到板端。旧 ADRL 的 PX4 基础链路已跑通，原生固定准备区与手动开赛流程已获用户验收；入口、证据和迁移验收顺序见 [AirSim 迁移](stage2/AirSim.md)。以下 Gazebo 内容保留历史实现与验收状态，不能作为 AirSim 迁移完成的依据。

标准机已确定为 `x500_experiment`（Orbbec Gemini 2 RGBD 几何近似＋MID-360S 规则 GPU 扫描近似），后续阶段沿用。PC 启动与 QGC 操作见 [Hands-on](stage2/Hands-on.md)，数据链路、性能和历史证据见 [实测记录](stage2/Validation.md)。当前 Baylands 模型加载与雷达/机体 IMU 数据已验证，用户已确认 RGB、D、雷达点云、表面体素展示可用。改装后的完整飞行、新 PC 复现、复杂场景性能和真实硬件对照仍待验收。

实施顺序：先固定 PX4、Gazebo、QGroundControl 的版本组合，交付单机空场景的启动、连接、起飞、悬停、降落与重置；验收通过后加入一个赛道的检查点与本地计时，再扩展三个赛道、传感器可视化和在线排行榜。JoyCan 在核实来源与连接方式后接入。为 Stage 3 预留单机标识、通信端点、坐标系与单位、仿真时间和状态接口记录；本阶段验收仍在 PC 完成。镜像构建、资源下载与版本核实属于教师课前准备。

1. 启动包含 PX4 SITL 与 Gazebo 的 Docker，用 QGroundControl 连接并观察状态与传感器。
2. 使用 QGroundControl / JoyCan 完成起飞、悬停、降落和三条难度递增的竞速赛道。

- [ ] 可重复启动、停止和重置的仿真环境。
- [x] 标准机基础四图展示：RGB、D、MID-360S 近似雷达点云与单帧表面体素；实际链路验证及用户展示确认。
- [ ] 标准机改装后完整飞行、新 PC 复现和复杂场景性能验收；继续调整雷达效果。深度点云与 IMU 为补充实验，世界坐标累计地图另行实现。
- [ ] 三个赛道及检查点、碰撞、超时、重置规则。
- [ ] 在线竞速排行榜：成绩提交、实时更新和统一计分规则。
- [ ] 核实 JoyCan 工具来源、连接方式与操作步骤。

验收：新 PC 按文档启动后能连接飞控，查看传感器，完成赛道并更新排行榜。

## 3. 全栈飞行 + 应用 · 80 min

将已在 PC 跑通的 ROS 算法迁移到 RoboPi。此环节内容较多，授课前确定必做主线与选做项目。

本轮优先完成 GCOPTER、SUPER 和一个目标识别/追踪组合，均按 ROS Docker 验证 → RoboPi 迁移 → 控制 PC 标准机验收推进；多机任务后续开展。来源、接口缺口和环境检查见 [Stage 3 实施入口](stage3/Bring-up.md)。SUPER 已通过本机 Humble Docker 的空场景 PX4 闭环、perfect_drone_sim corridor 往返，以及 Gazebo 实体 corridor 的 2/5 m/s 高度受限往返与故障降落；统一算法评测和板端迁移尚未完成。视觉首选候选为 YOLOX 小模型＋ByteTrack，待目标类别和板端推理条件确认。

1. 自主飞行：在相同赛道／密林场景对比 GCOPTER 与 SUPER 的速度和成功率。
2. 视觉算法：目标识别与跟踪，结合自主飞行完成任务。
3. 多机编队：参考 CAT-ORA，提供方阵变横排 demo，练习方阵变竖列或自定义队形。
4. 多机探索：参考 RACER 协作探索建图，结合 VLM 读取模拟外卖单据和地图，完成配送。

- [ ] PC ↔ RoboPi ROS 通信与板端控制单机的最小闭环。
- [ ] 复现 GCOPTER 和 SUPER，并建立统一评测配置。
- [x] SUPER 在 ROS 2 Humble Docker 与 PX4/Gazebo Docker 之间控制标准机完成空场景起飞、到点、降落；[步骤](stage3/Hands-on.md)与[实测](stage3/Validation.md)。密林避障、SUPER 上板和统一评测仍待完成。
- [x] SUPER 自带 perfect_drone_sim 中等难度 corridor 在 Humble Docker 完成 100 m 往返，提供计时、速度、点云净空与可重置入口；[操作与边界](stage3/Hands-on.md)。
- [x] SUPER 在 Gazebo 实体 corridor 完成高度受限的 2/5 m/s 冷启动往返；实体扫描、旧版 Gazebo/RViz 双窗口、当前 PX4/GNSS 2 m/s 的 Gazebo＋双 RViz 三窗口、碰撞正例及雷达/规划器/时钟故障后的自动降落均已实测；[步骤](stage3/Hands-on.md)与[证据](stage3/Validation.md)。实机 MID-360、上板和统一算法对照仍待完成；上述历史结果按各自传感器与定位配置区分。
- [ ] 复现目标识别与跟踪，确定模型和传感器接口。
- [ ] 复现 CAT-ORA，提供队形任务接口与多机配置。
- [ ] 复现 RACER，准备探索地图与模拟配送任务。
- [ ] 补齐当前未附在仓库中的多机编队参考资料。

验收：板端节点能控制 PC 中的仿真无人机；各应用独立提供可重置的场景与结果记录。算法名称为候选复现目标，尚未验证其 OpenHarmony 兼容性。

## 4. 大模型结合 · 60 min

1. 部署适配模型到 NPU，体验模型传输与运行，完成 VQA。
2. 使用 VLN / WAM / VLA 完成语义导航，暂收录 SPF 和 OpenFly 为候选工作。
3. 参考 Jev Drone，调用 Jev API 完成同一任务进行对比。
4. 开放任务：自行设计 Jev 选项与飞行接口完成任务。

- [ ] 明确 NPU 硬件、运行时、模型来源及权重分发许可。
- [ ] 准备 VLN / WAM 模型适配、获取与部署脚本。
- [ ] 设计可复现的语义导航场景、指令和成功判据。
- [ ] 包装其他飞行 API 给 Jev 调用，加入状态检查与超时处理。
- [ ] 建立本地模型与 Jev 的同任务对照，记录成功率、延迟与资源消耗。

验收：模型在目标板端完成 VQA；本地模型和 Jev 使用同一场景、观测与动作接口完成导航。API 包装完成不代表飞行任务已完成。

## 实施里程碑

1. **环境基线**：确认 PC、Docker、PX4、Gazebo、OpenHarmony、ROS、SDK 与以太网配置，提供启动和诊断流程。
2. **单机闭环**：PC 仿真 → 板端 ROS → 起飞／悬停／降落，记录消息接口和坐标系。
3. **课堂基础体验**：HDC、编译示例、LLM chat、可视化、三个赛道与排行榜。
4. **算法应用**：逐项复现单机、视觉、编队与探索，确定 80 分钟内的必做内容。
5. **语义任务**：模型适配、VQA、导航与 Jev 对照，形成可重复授课的完整流程。

Stage 3 当前收束点：MID-360 视场与时间分片扫描近似、FAST-LIO2 的 30 Hz 配准点云及约 200 Hz IMU 传播状态已在本机跑通；带可选墙面立体标记的 2 m/s 往返通过，GNSS 融合关闭，飞控保留气压降落后备。原赛道纯 LIO、LIO 5 档、实机精确时序/标定、多轮成功率及 RoboPi 迁移仍待验证。旧配置证据独立保留；后续分工见 [开发交接](stage3/Development.md)。


## Stage 4：AeroVLA API 语义导航

采用 Town05＋AirSim＋PX4 Docker＋ROS 算法 Docker，外部 AeroVLA 服务提供无会话推理。课程侧使用轻量 uv 环境，模型依赖留在旧仓库。入口与边界见 [Hands-on](stage4/Hands-on.md)，实际证据见 [Validation](stage4/Validation.md)。

- [x] Town05 相机／估计／时钟、低速固定动作、真实模型单步；任务 0 一次完整闭环通过：78 次模型请求，约 15.08 分钟，停止时估计目标距离 3.72 m，已降落并 Disarmed。多轮成功率另行验证。
- [x] API 超时、迟到响应取消、相机失流、控制进程退出的实际降落与 Disarmed 验收。
- [x] PC 只读 WebUI：与源 UI 对齐的模型观测双图/位姿/动作、飞行状态、速度与推理耗时；5 m/s、8 m/s²、稳定 0.15 秒的六次真实模型短程请求步骤中位数约 3.80 秒、实际峰值 4.80 m/s，已降落并 Disarmed；当前默认改为 8 m/s、4 m/s²，因 Stage 2 占用端口尚未实飞。
- [ ] 多轮稳定性与其他任务/地图验收。
- [ ] RoboPi 原生迁移。

## Stage 5 扩展：语义目标跟随

- [x] 独立 Gazebo 街区与可启动/停止/复位的红色方块车。
- [x] 标准机相机、真实本地 DINO＋深度测距、粗体素局部空间与 Jev 建议链路。
- [x] Jev 选择跟随行为、PX4 MAVLink Offboard 执行的 PC 初版：红色目标颜色/RGBD 跟踪，0.7 m/s 环路车辆，35 秒及60秒实际跟随；60秒同步评测水平间距中位数 7.92 m，高于车尾 2.16 m。
- [ ] 严格正对车尾、完整一圈、多轮成功率、复杂遮挡和绕障执行、通用车辆/动物跟踪。
- [ ] RoboPi 迁移与实机验证。

- [x] 真实 Qwen3.6-35B-A3B 视觉规划→DINO→Jev→PX4 单阶段闭环：60秒任务、32次真实Jev调用无错误，Jev确认 completed；运动后半段真值水平距离中位数7.95 m、上方2.11 m。
- [x] Qwen验收任务运行器：两阶段真实动态任务通过，Qwen分别accept；任务预算/timeout、预算外总结、进度与历史记账、redo/modify_stage/modify_plan通过受控协议及单元测试。
- [ ] 搜索/绕障技能、复杂场景下重规划效果与多轮稳定性验证。

架构、代码入口与[当前关键问题](stage5/Agent.md#9-当前仍存在的关键问题)见 [Agent介绍](stage5/Agent.md)；操作见 [Stage 5 Hands-on](stage5/Hands-on.md)，实测证据见 [Validation](stage5/Validation.md)。

2026-10-16 板端迁移进展：Stage 1 新布局完整部署和真实 ROS 常驻文本、桥重启、并发拒绝、单图 VQA 通过；Stage 3 AirSim/SUPER（GNSS、无 LIO）已通过单容器镜像、以太网 DDS 和无显示 Docker 短程/forest1/forest10 基线，板端构建/加载/序列化、短程与 forest1 原生规划控制往返已通过，低速四项故障降落通过；forest10 首轮失败，三次成功冷启动待完成。完整迁移不标记完成，实际证据见 [RoboPi 迁移验证](stage3/RoboPi-validation.md)，操作见 AirSim README。
