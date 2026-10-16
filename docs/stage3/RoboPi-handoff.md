# RoboPi 迁移交接（2026-10-16）

下一会话在另一台能正常渲染 AirSim 的 PC 继续验证。用户已确认新机器具备原 Docker image 和 AirSim 场景，编译产物按仓库流程重建即可；无需将搬运镜像、场景或旧编译缓存作为前置任务。本轮交接完成代码与证据整理，**完整 AB 任务仍未验收**。

## 阅读入口

以下路径相对仓库根目录。详细实现和历史数据不在本交接重复维护。

- [仓库约定](../../AGENTS.md)、[板端约定](../../robopi/AGENTS.md)、[AirSim 约定](../../stage3/super/airsim/AGENTS.md)。
- [AirSim README](../../stage3/super/airsim/README.md)：唯一操作入口；重点读“RoboPi 算力后端”“板端以太网通信”“端到端 profile 与显式降级配置”“AB 仿真实验的中止条件”“飞行录像与离线回放”。
- [迁移验证](RoboPi-validation.md)：实际通过项、失败边界、性能／网络证据、关键运行目录及最后门限修复；[开发交接](Development.md)记录其他 Stage 3 边界。
- 构建／部署入口：[stage3/robopi.py](../../stage3/robopi.py)、[stage3/board/](../../stage3/board/)、[board_backend.py](../../stage3/super/airsim/board_backend.py)。实际板端交付物在 [robopi/stage3/](../../robopi/stage3/)，共享源码在打包时解引用。

## 已确定的接续原则

- 标准流程是 AirSim＋PX4＋ROS＋SUPER，使用 GNSS，不使用 LIO。迁移 Docker 2 的算力职责；PX4、Agent、场景仍在 PC，ROS 算法原生运行于 OpenHarmony RoboPi。
- 迁移按“原 image 基线 → Dockerfile 增量 → 挂载源码／交叉编译产物”逐层对齐，复用输入未变的验证结果，不重建已工作的基础 ROS。
- 正式路线是 forest10-ab 的单一远端 B 目标，不能用八航点代替；板端 5 m/s 实验用 forest5-ab-observe。SUPER 内部仍为 20 m 局部规划范围。
- ROS 运行通信统一使用以太网；HDC 用于管理／部署，HTTP 可用 fport。新 PC 要核实实际接口／地址及双向 DDS，不把 HDC 在线视为网络链路通过。
- 用户允许仿真碰撞，希望看到实际算法行为，暂不优先处理偶发点云失流。两个 AB 配置对任务包络、参考速度／加速度、跟踪偏差、点云失流均仅记录。其他保留中止条件集中列在 README；不得再新增隐藏门限。
- robopi-forward-200ms 是显式板端实验档，不能写成 baseline。准确的前视／双时钟预算见 README；放宽计算预算必须与轨迹切换的仿真时间一致。

## 交接现场

- 上次 Stage 3 仿真已停止，发布最后修复前核实该次板端五个节点均停止；没有启动新飞行。
- 最新部署 release：`ec249152b59e5aecbeebf1fd35ce423ff533784c9203865dc6391ee2ad4982fe`，板端路径 `/data/local/workspace/stage3/releases/<release>/`。接管时重新列出设备并显式选择目标，不依赖旧 PC 的设备记录。
- 最新修复已通过 Docker 与实际板端 ROS 消息测试，详见验证文档最后一节；**尚未用修复后的 release 重飞 AB**。旧录像被人为任务包络提前降落，不代表最新代码表现。
- Stage 1 最后为 ready，历史 HTTP 转发和网络状态不保证换机后仍在。不为飞行迁移重启整板、替换系统库或接管无关服务；Stage 5 不在本次接续范围。

## 下一会话执行顺序

1. 从用户本轮提交开始，读取上述约定与证据。新机器已有原镜像和场景；核实其路径、镜像身份和显示能力即可，不重复下载准备。
2. 按仓库技能检查当前 HDC 设备、目标 ABI、以太网及 ROS 环境。板端 SDK／依赖快照、固定 px4_msgs 和主机生成工具按 README 准备，运行 prepare/build/deploy；原 image 经 Dockerfile 得到 PC 运行镜像。具体命令只维护在 README。
3. 写新机器的 runtime 本地配置，选择 5-ab-observe 并核实任务、settings、场景路径和镜像名。正常显示时不加 --no-display；先检查窗口、传感器和静止 inspect，再执行任务。不沿用旧绝对路径、CMake cache 或历史启动快照。
4. 新建 state-dir，冷启动 up 生成新的配置快照；后续 task/status/down 始终使用同一 state-dir。先保持 5 m/s 和已有时序／传感器配置，记录实景录像、报告、profile、ULog 和自动 review，再考虑提速。
5. 验证是否真正到 B。换机改变仿真／墙钟比，不能把新机器飞成功直接归因于算法修改。失败时按 README 的明确中止条件定位具体层次，不以“command rejected”概括，也不凭结果调 PID／增加保护。

## 可重建产物与历史证据

镜像、场景和编译输出不提交 Git；新机器按流程重建，不要求携带旧 artifacts。SDK／ABI／依赖路径使用新机器实际配置，不能使用 Linux ROS 产物替代 OHOS 目标库。

历史日志和视频仍只在旧 PC 的忽略目录中，验证文档引用的 artifacts 路径是证据索引，clone 后不会自动存在。需要观看旧录像或重新分析旧数据时再单独取回相应 run；缺少旧日志不阻塞按新配置重新验证。无需迁移全部缓存或模型。

SUPER 源码已在分支 `feat/sim` 整合：`ca06b3a` 为运行／构建适配与双时钟重规划预算，`71acbdb` 为 profile 打桩和诊断日志。后续 `3be0d50` 同步 ROS2 CMake 模板，避免 select_ros_version.sh ROS2 覆盖 OHOS 构建适配；父仓库固定到该修复。兼容旧基线的增量仍维护在 [stage3/board/patches/](../../stage3/board/patches/)；构建器会检查并跳过已包含的补丁，原两次提交合并后的源码与原迁移工作树逐文件一致，追加修复只同步构建模板。本轮只做本地提交；换机拉取父仓库前须先 push SUPER 的该分支，保证子模块提交可获取。新机器构建前核实子模块基线，不用 reset 覆盖未知改动。

## 分析时不要重复踩坑

- 点云空窗已捕获板端 IP 分片重组失败；长时间观察未见应用 pending 队列逐渐堆积。结论与尚未区分的原因见验证文档，不重新用“可能网络／可能积压”代替证据。
- ReplanOnce 是板端 CPU 关键路径之一；比较 CPU、墙钟、仿真时间，不能把全部延迟归到通信。
- ROS 日志前缀未经核实不能直接与报告 sim_s 对齐，两机绝对单调时钟不能相减。旧的阶段归因错误已经更正，见验证文档。
- 失败报告轨迹在首个失败处结束，不含 finally 收尾降落；实景录像可覆盖该段。离线遥测／点云回放不是实景视频。

## Suggested skills

下一代理应调用对应 Skill 工具（若环境提供），并以仓库 SKILL.md 为维护源：

- [hdc-master](../../skills/hdc-master/SKILL.md)：设备识别、shell、文件校验、fport；实际设备操作前执行所需预检。
- [oh-ros2](../../skills/oh-ros2/SKILL.md)：OHOS ABI／交叉编译、目标环境、DDS／以太网与仿真时钟；板端开发必读。
- [oh-houmo](../../skills/oh-houmo/SKILL.md)：仅下一任务实际涉及 NPU／Stage 1 时调用，飞行迁移不默认加载驱动或请求模型。
- [robopi-wifi](../../skills/robopi-wifi/SKILL.md)：仅实际需要 Wi-Fi 时使用；ROS 运行仍采用以太网。
