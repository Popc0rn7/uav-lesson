# RoboPi 开发与交付约定

本目录维护实际要传到 OpenHarmony RoboPi 的课程程序、启动脚本及配置。PC 部署工具留在 `stageN/`，双 Docker 仿真留在 `develop/` 和各阶段目录。RoboPi 替代 ROS 算力容器，PX4/Gazebo、QGC、可视化及真值评测继续在 PC；算力算法不部署到 PX4。

## 文件与部署边界

- `stage1/` 对应板端 `/data/local/workspace/stage1/`；PC 部署入口为 `python3 stage1/deploy.py`，需先显式填写本次设备 TARGET。迁移只改变 PC 源路径，板端路径保持原值。
- `stage1/qwen_infer/` 是忽略 Git 的上游运行产物，获取及部署步骤只维护在 [教师准备流程](../docs/AGENTS.md)。不要维护其 C++、转换工程或构建源码副本。
- 模型缓存留在 `artifacts/models/`，按部署入口传到板端 models 目录；不在本目录复制大模型。
- 新阶段只有出现实际板端文件才建立目录。Stage 3、5 目前没有板端交付物，不复制 PC 目录制造迁移完成的假象。
- 不整体发送本目录或仓库。按部署入口选择交付文件，排除 AGENTS.md、skills、测试、缓存、日志和凭据。现有 Stage 1 使用显式文件清单。

板端手工修复需要同步回本目录或所属上游，再经相同部署流程验证；不要让设备成为唯一源码。共享算法维持单一源码位置，板端目录只维护需要的适配和交付配置；目标构建产物忽略 Git，记录其来源、SDK、源码提交和依赖。

## Codex skills

仓库版本为协作维护源，执行相关任务前读取所需入口及其按需参考：

- [hdc-master](../skills/hdc-master/SKILL.md)：目标选择、传输、shell、端口映射与诊断。
- [oh-ros2](../skills/oh-ros2/SKILL.md)：OpenHarmony 工具链、ABI、ROS 消息与跨机 DDS。
- [oh-houmo](../skills/oh-houmo/SKILL.md)：NPU 驱动、HAL/TCIM、模型及运行时。
- [robopi-wifi](../skills/robopi-wifi/SKILL.md)：按需使用的原生 Wi-Fi 工具，其 assets 是工具随包产物，不属于 Stage 1 部署清单。

只读取本次需要的技能，不为整理文件而连接设备。技能修改与应用修改一起审查；不要从个人目录反向覆盖仓库修复。Codex 自动发现需要安装到当前环境支持的 skill 目录；未安装时按上述路径直接读取，文件存在不等于当前工具目录已注册技能。预检中的 skill-files 默认包含仓库 skills，skill-available 仍须如实提供当前可用目录。

## 双 Docker 到 RoboPi 的迁移流程

1. 固定 PC 基线：源码提交、镜像摘要、场景、初始状态、算法参数和资源预算，引用该阶段 Validation；代码或新镜像尚未复验时注明。
2. 列出算力容器中每个进程及依赖，逐项决定留在 PC 或上板。核对目标 OpenHarmony/AArch64、libc、Python ABI、ROS/RMW、消息包、SDK；Linux 容器的 install 不能直接作为板端产物。
3. 明确运行契约：设备/无人机标识、命名空间、ROS 域、以太网地址、端口、DDS QoS、仿真时间与墙钟、坐标系、单位、频率和超时。HDC 管理通道与以太网运行通信分别检查，不假定 HDC 已走网口。真值只用于 PC 评测。
4. PC 完成目标构建和 ELF/依赖检查，脚本先做语法检查；部署前执行对应 skill 的必需项预检。部署须显式选目标、校验文件、检查空间和运行进程；已有不同文件先检查并保留回退版本，不停止无关服务。
5. 先验证板端加载/import，再做 PC↔RoboPi 消息收发和只读传感器检查，随后验证控制状态、坐标转换、限幅、失流和超时处理，最后在任务授权范围内完成仿真起飞、任务、降落与 Disarmed。实机验证单独进行。
6. 用相同场景和门限对照 Docker 基线，保存结果、失败原因、版本与运行条件到阶段 Validation；更新 Hands-on 的位置、前置条件、命令、预期现象和恢复方式。没有证据的层级保持待验证。

## 当前验收边界与排障

本次仅重组本地交付目录，未操作板端。Stage 1 有旧布局的 ROS 跨机聊天证据及 HTTP/VQA 单独实测，新目录完整部署和 ROS 聊天回归待验收；Stage 3 SUPER 与 Stage 5 跟随控制迁移待实现、待验证。目录存在、编译成功、HTTP 健康或 DDS 收发均不能代替飞行验收。

文件缺失先按教师准备流程检查上游 dist 和模型，不能用 Linux 产物补齐。连接失败先保存 HDC 错误并确认目标；HTTP 不通分别检查板端服务与本次端口转发；DDS 不通检查网卡、域、RMW、QoS 和时间。保留诊断，不通过重启整板、替换系统库或放宽控制约束掩盖问题。
