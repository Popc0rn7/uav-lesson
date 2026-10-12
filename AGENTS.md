# 仓库开发约定

## 使命与交付对象

本仓库承载无人机实践课程 demo，同时服务两类使用者：
- 学员：clone 到 PC 后，按 hands-on 文档完成仿真、板端开发和飞行任务。
- 课程维护者：从 PC 使用仓库脚本，通过 HDC 为 RoboPi 准备、部署和诊断环境。

默认使用中文编写课程文档与操作说明。交付应包含可运行代码、操作步骤、预期现象和故障排查；不能只提供方案。

## 系统边界

- PC：运行包含 PX4 SITL 与 Gazebo 的 Docker 环境，以及 QGroundControl、可视化、聊天 GUI、竞速计时和排行榜相关服务。
- RoboPi：运行 OpenHarmony，模拟无人机机载算力板，承载 ROS 自主飞行、视觉、多机协作与大模型推理。
- HDC：用于板端 shell、文件传输、部署与诊断。以太网用于 PC 与板端运行时通信；不要默认 HDC 已通过以太网配置好。
- PX4 是飞控；RoboPi 是算力板。算法从 PC 迁移到 RoboPi，不应描述为部署到 PX4 飞控。
- Stage 1 已验证 ROS 2 Humble、rmw_fastrtps_cpp、域 10 与板内 HTTP 127.0.0.1:8080；OpenHarmony AArch64、Linux 6.6.86、Python 3.12 ABI、Houmo 驱动 v1.4.0 与 TCIM v2.5.0 的证据见 docs/stage1/Hands-on.md。换设备或镜像时重新核实。PC PX4/Gazebo 当前基线见 Stage 2 文档；飞行消息接口及后续 SDK 组合仍待确认。

## 当前事实

- `stage3/jev.py` 已提供 Jev Decisions API 包装，`stage3/demo.py` 是文本情感决策示例。
- Stage 3 当前收束点：SUPER / FAST-LIO2 在 Humble Docker 中，使用 Gazebo 实体扫描、30 Hz 配准点云与约 200 Hz IMU 传播状态；带可选墙面标记的 2 m/s 往返与一次雷达失流降落已验收。原赛道纯 LIO、LIO 5 档、实机与板端仍待验证。入口、证据和并行开发边界见 docs/stage3/Development.md。
- Stage 1 常驻模型 ROS 聊天链路已有旧布局实测记录；当前文件重组后的部署尚待重新验收。自主飞行 API 和 PC 聊天 GUI 尚未实现。
- Stage 2 标准机为 `x500_experiment`（Orbbec Gemini 2 RGBD 几何近似＋MID-360S 规则 GPU 扫描近似），引用独立 `mid360s` 模型；启动时两个模型目录均需挂载。四图基础展示已获用户确认，改装后完整飞行仍待验收；操作与实测证据分别见 `docs/stage2/Hands-on.md`、`docs/stage2/Validation.md`。
- 路线与完成状态见 `docs/roadmap.md`。只有实际可运行并有验证证据的功能才标记完成。

## 实施原则

1. 优先完成最小端到端链路：PC 仿真 → RoboPi 通信 → 板端控制一个仿真无人机，再扩展算法与多机任务。
2. 区分课堂操作与课前准备。下载镜像、编译 SDK、转换模型等长耗时步骤放在教师准备流程中。
3. 每个命令标明执行位置（PC、Docker 或 RoboPi），并说明前置条件、成功判据与常见失败的恢复方式。
4. 部署脚本显式选择设备，支持重复执行，检查依赖和错误，保留诊断信息；避免覆盖未知板端文件或无关进程。
5. 不把 Linux ROS 二进制直接当作 OpenHarmony 可用产物。记录交叉编译工具链、架构、运行库、环境变量和依赖。
6. 仿真算法、赛道和模型记录版本、来源、许可证、配置、资源需求与验证条件。候选工作不能写成已复现成果。
7. 飞行接口提供明确的状态、坐标系、单位、超时和失败处理；模型建议经过确定性约束检查后才能进入控制接口。
8. 单机与多机实现明确命名空间、无人机标识、通信端点和仿真时间约定。
9. 对比算法时固定赛道、初始状态、资源预算、参数与评价规则；记录速度、成功率和失败原因。
10. 不提交 API key、`.env`、模型大文件、编译输出或运行日志。提供无真实密钥的配置示例。

## 仓库布局

- `stageN/`：该阶段在 PC 使用的代码和部署入口。
- `stageN/robopi/`：该阶段要传到 RoboPi 并使用的文件；部署时内容对应板端阶段目录。
- `src/`：仅放跨阶段通用工具或包，没有则不创建。
- `artifacts/models/`：大模型缓存或软链接；embedding 位于模型目录 hmquant/quant_embedding.bin，部署保持整个模型目录的相对结构。大文件不提交 Git。
- `docs/`：课程文档；`docs/AGENTS.md` 是代理准备板端环境的流程，随实现跟进。

上游推理工具直接获取运行产物，Stage 1 放在 stage1/robopi/qwen_infer/ 并忽略跟踪。
不复制维护上游 main.cc、编译工程或模型转换源码，不再使用 prepare_qwen_bundle.py 和 manifest。
不预建空目录，不为同一流程维护重复说明。

## 验证与报告

按变更运行必要检查。Python 代码先检查语法；网络 API、GUI、仿真和板端功能必须分别验证实际链路。没有设备、模型或网络条件时，明确报告未验证项，不把静态检查等同于课程验收。不要为验证而默认调用付费 API。

报告说明改动、验证结果和剩余依赖。涉及 RoboPi HDC、OpenHarmony ROS、Houmo NPU 的实际工作时，读取并使用对应可用技能。
