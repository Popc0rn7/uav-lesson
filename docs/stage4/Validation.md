# Stage 4 验证记录

日期：2026-10-18。操作入口只维护在 [Hands-on](Hands-on.md)。本轮是上游 SimpleFlight → AirSim/PX4 HIL＋ROS Docker 接入，推理服务留在相邻 AeroVLA 工作区，通过用户提供的 `/health`、`/infer` 协议联合测试。没有执行 RoboPi 部署。

## 环境与来源

- 算法契约取相邻 `../AeroVLA` 当前工作区，包含本地 demo/实时控制及新推理服务修改；上游 HEAD 为 `2c5ae0987a484ab92f00dd9d9ed493cb3e98e492`。不是仅凭上游 commit 复现的洁净检出。
- 地图：`/mnt/disk1/wqy/traveluav_env/envs/carla_town_envs/Town05/LinuxNoEditor`，直接运行 `CarlaUE4/Binaries/Linux/CarlaUE4`。场景、任务数据、模型均未复制提交。
- PX4 使用本机 `px4io/px4-sitl-gazebo:latest`，实际镜像 `70584c9eb1e9…`；ROS 基础 `uav-computer-ros-humble:local` 为 `c24f47188837…`，Stage 4 派生镜像 `uav-stage4-ros:local` 为 `e68fa025330074f4f3fcc3ab468da53015a3f12d249e1b4d5a134794db8067b8`。
- PC 使用本仓库 uv/Python 3.12 环境；ROS 使用镜像 Python 3.10.12、Humble、rmw_fastrtps_cpp、域 10；不安装模型依赖或旧 AirSim SDK。
- 任务 0：`Carla_Town05/0a20bf13-3d61-4a1a-8e3e-84bab68e1eea/merged_data.json`，目标 `SM_PlasticTable`。起始观测 NED `[-20.261,183.198,-2.125]`，目标 `[131.016,-31.086,-14.491]`，出生参考 Z=0。实际输入以各 run 的 task/settings 快照为准。
- 每轮的源码摘要、镜像完整 ID、配置、节点日志和 ULog 留在 `artifacts/stage4-runtime/<run-id>/`；故障轮在 `artifacts/stage4-faults/`。这些证据不随 clone 分发。

## 已执行的基础验证

| 验证 | 实际结果 | 证据 |
| --- | --- | --- |
| uv 轻量环境、镜像构建、任务导出与 dry-run | 通过；课程侧没有 Torch/Transformers/conda 依赖 | pyproject/uv.lock；prepare-task 和运行快照 |
| Stage 4 单元与真实本机 HTTP 测试 | PC 28 项通过，ROS 镜像内另3项入口测试通过，覆盖协议、HTTP 错误说明、超时、取消、动作范围、坐标、参考与垂直限幅约束、待命模式切换、WebUI 跨轮与过期状态、非 SUPER runtime 挂载 | `stage4/tests/` |
| Stage 3 公共层回归 | PC 的管理/端口/恢复/Offboard 23 项通过；ROS 镜像内 SciPy 接口/几何 9 项通过 | `stage3/super/tests/test_airsim_*.py` 的对应子集；未把未执行的 ROS 专项计入 |
| Town05 HIL＋DDS＋双图/估计/时钟 | 通过，连续有效双图，典型图像/位姿差约 3 ms | 成功 run 的 sensors.json、startup-inspect.log |
| 实际 RGB 图像检查 | 前视和下视图已保存，前视人工检查颜色与场景正常 | 长任务 `observations/0/`；后续启动另存 camera-check/ |
| 独立离线真实模型请求 | 通过；同帧输出 `00 03 00`，动作 `[0,-4.693877551,-1.1]`，与旧 model_check/result.json 一致 | 任务 0 的 frontcamera/downcamera/000000.png 与旧离线检查；API 实测约 1.072 s，服务处理约 1.046 s |

早期两个启动轮分别暴露并修复了 PYTHONPATH 覆盖 Humble 路径、NumPy float32 直接赋给 ROS float64 字段的问题；失败轮自动清理，未起飞。记录分别在 `c1efdf7e1b0c4e7d9ad362ff5d5c8609` 与 `1a41c76ef53a4dcd9d5e14177f58a737`，不计为链路通过。

## 固定动作与真实单步

**固定动作 run：`7dacbae44d28444cabfd1a38d4b268c6`**。

四步动作、返回初始观测位姿、降落和 Disarmed 已通过，约 40.46 墙钟秒。大偏航步保留原规则，不执行伴随前进量。参考速度上限 1 m/s，实际峰值约 1.248 m/s；不能将参考约束写成真实速度严格上限。

ULog 复盘中，Offboard 段位置误差中位数约 0.042 m、P95 约 1.424 m、最大约 1.944 m，较大误差位于起飞建立过程；尚未单独完成原因分解，未据此调 PID。姿态误差 P95 约 6.79°、角速度误差 P95 约 0.517 rad/s，motor 输出峰值约 0.682、无≥0.98 样本。motor 数值仅作输出余量代理，不等于控制分配可行性证明。

**真实在线单步 run：`ff321c9ea1d4495097f1fe1bc9e404b1`**。

显式 max_steps=1，模型返回 `93 48 35`：fwd≈4.745 m、down≈−0.102 m、yaw≈−0.314 rad。按原规则仅转向和升降，没有执行该步前进量；随后因 step limit 降落并确认 Disarmed，约 21.42 秒。HTTP 约 0.318 s，服务处理约 0.311 s。报告失败原因是预先设定的步数上限，**不是完整语义任务通过**。推理阶段悬停位置误差 P95 约 0.163 m。

上述 ULog 的最终有效参数确认 `SENS_GPS0_DELAY=200`、`MC_REF_FF=1`、`UXRCE_DDS_SYNCT=0`、`COM_OF_LOSS_T=0.5`、`COM_OBL_RC_ACT=4`。这两项 AirSim 参数是在初始参数记录后、起飞前更新，复盘必须读 changed_parameters，不能只读 initial_parameters。

固定动作和单步降落期间捕获 Road_Road_Town05_20 接触；发生在 Offboard 轨迹结束后的降落阶段，不能误记为航段撞障，也不能无条件忽略所有碰撞。后续报告分别保留接触事件、降落开始时间及 flight_collision 标记。

## 默认长任务

run：`b9618287165741cea2a93334261d00f4`。原任务 0、max_steps=200、1800 秒墙钟上限、1 m/s 参考，连续真实服务推理，不暂停仿真。本轮完成：78 次真实模型请求，最后返回 `06 49 49 LAND`，stop=true；未执行伴随的 0.306 m 前进量，正常降落并确认 Disarmed。耗时 904.74 墙钟秒（约 15.08 分钟），停止时 PX4 估计目标距离 3.720 m，降落后估计距离 2.673 m，按原模型停止＋20 m 判据 task_success=true。此为单次指定任务成功，不代表多轮稳定性或通用搜索。

最后一条 Offboard 参考约在 sim_s=1792297286.159；目标物体 `stage4_target` 的接触在 sim_s=1792297287.467，记录的控制阶段为 land。该接触属于最终降落，不是模型仍在执行航段时的撞障。实际是否 Disarmed 另由 PX4 状态确认，未将 LAND 文本或接触事件当作解除解锁证明。

完整任务 ULog：`px4-logs/2026-10-18/04_06_19.ulg`，review.json 为复盘索引。测量时刻对齐的 PX4 位置误差 P95≈0.0435 m，速度误差 P95≈0.0448 m/s，姿态误差 P95≈1.005°，角速度误差 P95≈0.0728 rad/s；最大位置误差≈1.942 m 仍集中在初始起飞。实际速度峰值≈1.253 m/s，motor 输出峰值≈0.672，无≥0.98 样本。推理期间相对悬停参考的位置误差 P95≈0.030 m。

复盘曾在四元数符号切换处产生虚假的约 177° 插值误差；已用同号连续化后再插值修正，并新增同一姿态 q/−q 的回归。修正后的最大姿态误差约 12.27°，不能把旧插值尖峰归因于真实翻转。

全 78 次调用的 HTTP 中位数≈0.291 s、P95≈0.396 s，服务预处理＋推理中位数≈0.285 s；观测到观测的完整步骤中位数≈11.799 s、P95≈12.003 s。

在前 49 次调用的观测周期中，完整一步（双图观测→HTTP→旋转/位移→稳定→下次观测）中位数约 11.799 仿真秒，范围 5.799～13.599 秒；本轮时钟与墙钟基本同步。HTTP 中位数约 0.287 s，服务处理约 0.281 s。时间主要用于平滑执行约 4.9 m 位移以及两段到点等待，不是模型推理占用约 12 秒。

长任务中独立 ROS 订阅实测：heartbeat 约 49.999 Hz、setpoint 约 49.998 Hz，最大墙钟接收间隔约 20.34/20.42 ms，见 heartbeat-check.json。ULog 对这两个话题有日志降采样，不能用其约 10/5 Hz 的记录频率误判实际发布频率。

实际 prompt 与本地同观测预览逐项对照一致。全局 actor pose 与车辆局部真值的只读查询支持 XY 出生偏移转换，记录在 world-frame-check.json；查询没有反馈控制。定位与 prompt 使用 PX4 估计，目标坐标仍为给定任务信息。

## 故障与后续边界

API 超时轮 `6460f1d662534b99a5e38fb8058f4da0` 已通过：TimeoutError 后降落、0 个动作执行、约 15.90 秒并确认 Disarmed。迟到响应取消轮 `f55576b5050c4326acdaf4a2794e75c9` 已通过：请求挂起时 land，等待迟到响应后仍为 0 个动作，约 15.56 秒并确认 Disarmed。相机失流轮 `fac105fbbd7a48c6bb2559f0fa931b45` 已通过：暂停 sensors 后 camera observation timeout 降落，约 20.90 秒并确认 Disarmed。控制进程退出轮 `77f1d5cd95f14b91a526ef2be168afe5` 已通过：在运动阶段终止控制节点，未先发送宿主机 Land，PX4 自动进入 AUTO_LAND 并最终解除解锁。ULog 状态序列为 Offboard/Armed（sim_s≈1792297641.023）→AUTO_LAND/Armed（≈1792297649.567）→Disarmed（≈1792297655.916），详见 px4-state-transitions.json。四项故障均已实际验证并各自清理；测试入口为 verify_fault.py，各轮独立保存 fault-report.json 和 ULog。单元测试不能代替这些实际恢复验收。

仍未验证：多轮成功率、其他任务/地图、无目标坐标搜索、复杂避障、实机与 RoboPi。Stage 4 没有接入 SUPER 或局部避障规划器；模型结束和到达目标分别判断。

首次迁移验收结束时，普通运行与故障运行的 state.phase 均为 stopped；Docker 仅保留原先的 houmo-sam3 容器。用户的真实 AeroVLA /health 仍为 ready。没有停止该模型服务或连接 RoboPi。

## 有窗口启动修复（2026-10-18 后续）

用户直接运行 `up` 的 `efd030dde0c24d8ea01f83312d1da8b3` 失败：Town05 已监听 HIL，PX4 已连接 TCP 4560，随后场景在首帧 Vulkan 图形管线缓存中 SIGSEGV，栈含 FVulkanPipelineStateCacheManager::NotifyDeletedGraphicsPSO / TSet::Remove；PX4 因 HIL 断流报 poll timeout。不是定位或 DDS 尚未就绪，不能仅放宽启动等待时间。原完整任务验证使用离屏模式，没有覆盖有窗口启动。

以实际桌面 DISPLAY=:1 运行，只增加 `-norhithread`，`b1589a179f33417c994ae86055a484df` 已通过有窗口 HIL、PX4 健康状态、ROS 双图与时钟静止链路，保持未解锁待命。默认 Town05 配置已加入该参数；未因此宣称有窗口完整飞行通过。没有删除场景缓存、修改外部场景包或更换 PX4 镜像。

公共 runtime 现在优先识别场景退出，并在匹配 Vulkan SIGSEGV 时直接给出 airsim-console.log 路径，不再把它笼统报告为 PX4 未就绪；新增回归已通过。

后续 `9e490853403046f883cb41ada6eee2f7` 表明上述渲染参数并未解决所有启动失败：点击弹窗 OK 后，HIL、RPC、有效定位都正常，但 PX4 停在 Manual，`commander check` 返回 FAILED。ULog `px4-logs/2026-10-18/04_48_52.ulg` 的事件包含 `No manual control input`；不能把这一轮归因为场景崩溃。相同配置曾进入 Hold，因此只记录观察到的模式差异，尚未确认初始模式差异的来源。

修复为 Stage 4 专用启动回调：仅在 Disarmed、Manual、xy_valid/z_valid 都成立时请求 `commander mode auto:loiter`，随后仍按原来的健康检查验收。共享 Stage 3 默认路径不执行该回调。没有修改预检参数、自动解锁或起飞。

有窗口 run `96055e7a4ae043a79f20d3cd14764b2a` 已实际启动通过，inspect 显示 ready=true、healthy=true、cameras_ready=true、armed=false。本次冷启动自行进入 Hold；随后在同一未解锁仿真中显式切到 Manual，再调用新回调，实际回到 nav_state=4、arming_state=1、pre_flight_checks_pass=True，`commander check` 返回 OK，切换证据见该 run 的 px4-standby.log。16 项 Stage 4 测试通过；本轮仅验证静止启动和模式恢复，没有重跑有窗口完整任务。

## WebUI 恢复与提速（2026-10-18）

本轮改动为 PC 展示与 ROS 动作执行配置，不涉及 RoboPi。新增标准库只读 HTTP WebUI，显示实时双图、估计位置/速度/目标距离、阶段、解锁状态、模型输入输出与两种推理耗时。相机节点将原有 RGB 帧写成小尺寸 JPEG，不增加 AirSim 采样请求；UI 不反馈控制。页面 JS 已语法检查，实际 HTTP 页面、状态接口与两路 256×256 JPEG 解码通过；运动中两次前视图像摘要不同，遥测持续更新。状态接口实测显示四次真实推理的 http_seconds/elapsed_seconds/action，跨 run 自动切换。未做浏览器截图或自动化布局验收。

新导出任务默认参考速度/加速度由 1/1 改为 3 m/s、3 m/s²；保留 yaw_rate=0.5 rad/s、到点容差、速度≤0.2 m/s 与稳定 1 秒要求。既有任务支持 up --speed/--acceleration，输入文件不被参数覆盖，实际运行使用 task 快照。当前本机默认 artifacts/stage4/task.json 已切换 3/3，原文件保存在 task.slow.json；历史 run 快照不变。

- 固定动作 run `525275f9168145409d0847ca575149ad`：四步、返回和降落通过，37.08 墙钟秒，确认 Disarmed。参考为 3/3，但测试平移仅 1 m，实际峰值 1.447 m/s，不据此宣称达到 3 m/s。ULog 为 px4-logs/2026-10-18/05_04_20.ulg，review.json 已生成。ULog 位置误差 P95≈2.084 m，最大≈2.122 m，较大误差集中在初始起飞；flight.jsonl 中 move/return 最大误差约 0.147/0.143 m。motor 输出峰值≈0.713，没有≥0.98 样本。
- 真实模型受限 run `58ec36a470124f328ca26f9c63adfaee`：显式 max_steps=4，四次请求后按预期 step limit 降落，45.34 秒并确认 Disarmed；报告 failed 是预设步数上限，不是语义任务成功。实际速度峰值≈3.064 m/s，因此参考 3 m/s 仍非实际速度硬上限。三个观测周期分别约 6.387、7.599、7.800 秒，中位数≈7.599 秒；样本很少、包含转向步，不能替代旧 78 步完整任务分布。相比旧任务中位数 11.799 秒，本轮短程中位数约缩短 36%。HTTP 中位数≈0.291 s，服务处理≈0.284 s。flight.jsonl 的 move 位置误差 P95≈0.364 m，infer 悬停误差 P95≈0.160 m；takeoff P95≈2.125 m，不能忽略初始建立过程。

两轮均仅在降落阶段记录道路接触，flight_collision=false；降落完成另由 PX4 Disarmed 确认。源码、task/settings、stage4-source.json、inputs-evidence.json、node-logs、flight.jsonl、inference.jsonl、observations、report/evaluation/review 和 px4-logs 都在对应 artifacts/stage4-runtime/<run-id>/。镜像沿用本页前述 PX4 与 ROS 身份，没有重建或调 PID。18 项 Stage 4 测试与 23 项共享 PC 管理层回归通过。完整 200 步提速导航、多轮成功率与提速配置下全套故障回归仍待验证；先前 1/1 完整导航与故障结果保持为旧基线证据。

本轮有窗口联测 `41893e45efea4fdc8566fb2c8c5148e8` 被缺失 DepthCamera 材质的弹窗阻塞，未达到 PX4 启动；由操作者中止并自动清理，没有起飞。上述两轮飞行使用 --no-display，WebUI 仍提供实时画面。

短程验证后已恢复普通 200 步任务，待命 run `fd16fe69b56d4d16bbd012822f8f0e76`（--no-display）：ready=true、idle、armed=false、3 m/s 与 3 m/s²。WebUI 仍在 127.0.0.1:8080，已自动跟踪该 run，未替用户启动完整任务。真实模型短程 ULog 为 px4-logs/2026-10-18/05_06_32.ulg，motor 输出峰值≈0.702、无≥0.98 样本。

## 接近 SimpleFlight 的动作节奏（2026-10-18）

按用户要求继续提高参考速度/加速度，并缩短到点稳定时间：默认 5 m/s、8 m/s²、stable_s=0.15；到点位置≤0.6 m、偏航≤5°、实际速度≤0.2 m/s 的条件仍保留。4.9 m 水平 quintic 参考约 1.882 s，旧 SimpleFlight 的 3 m/s 速度指令为 1.633 s。Stage 4 settings 明确将 MPC_ACC_HOR/MPC_ACC_HOR_MAX 设置为 8；PX4 原有水平速度限幅 12 m/s、倾角 45° 保持。为避免将高水平加速度一并施加到升降，轨迹另限上升 2 m/s、下降 1 m/s、垂直加速度 3 m/s²，斜向动作选择满足所有限制的公共时长；起飞与垂直动作也使用这些限制。CLI 增加 up --stable，dry-run 同样反映覆盖参数。

实际 run `80383dc066314bad9535d852a01d41ad`：Town05 任务 0、显式 max_steps=6、--no-display、相同 PX4/ROS 镜像与真实 API。六次调用后按预设 step limit 降落，37.64 墙钟秒，Disarmed confirmed；不是完整语义任务成功。五个观测周期约 3.801、3.801、3.798、3.600、3.600 s，中位数 3.798 s，比上一轮 3/3/1 的 7.599 s 约缩短 50%。HTTP 中位数 0.282 s、P95 0.293 s，服务处理中位数 0.276 s；实际速度峰值 4.803 m/s。道路接触仅发生在 land 阶段，flight_collision=false。

提速有跟踪代价：flight.jsonl 中 move 位置误差 P95≈0.871 m、最大≈0.913 m（上一轮 P95≈0.364 m），infer 悬停误差 P95≈0.375 m（上一轮≈0.160 m）。到点判据通过后才取下一帧；不把航段最大跟踪误差误写成最终到点误差。初始起飞最大误差仍约 2.124 m。ULog 的 Offboard 姿态误差 P95≈12.00°、最大≈20.84°，motor 输出峰值≈0.740、无≥0.98 样本；这些仅作为本轮跟踪和输出代理，没有据此宣称复杂避障或全任务通过。

ULog 为 px4-logs/2026-10-18/05_13_47.ulg；review.json 新增 MPC 加速度、速度、倾角参数索引，最终 MPC_ACC_HOR/MPC_ACC_HOR_MAX 均为 8.0。配置、源码摘要、双图输入、inference.jsonl、flight.jsonl、节点日志、报告与 ULog 仍保存在同 run 目录。19 项 Stage 4 回归通过，含水平提速时升降速度与加速度仍受限的数值检查。本机任务文件旧 3/3/1 配置备份为 artifacts/stage4/task.3mps.json，新默认任务为 5/8/0.15、200 步。

用于比较的旧 SimpleFlight 历史 run 为相邻仓库 eval_results/navigation_demo/20261016-151723-644371：任务 0、real_time=false、135 次请求，去除每步五次重复传感器快照后，136 个观测的时间戳跨度 416.943 s、步骤中位数约 2.874 s，模型调用中位数约 0.356 s。该旧轮最终 phase=mission ended、success=false，不能作为旧完整任务成功证据；也没有逐段速度采样可证明它实际始终为 3 m/s。当前短程样本与旧全程动作分布不同，3.798/2.874 只能作节奏参考，不是严格速度比实验。新配置的完整任务、多轮成功率、复杂障碍和全套故障回归待验证。

验证后恢复普通待命 run `19cf6c6866524b59a5edd6e58b553f2c`：ready=true、idle、armed=false、5/8/0.15、max_steps=200；WebUI 自动跟踪该 run，stale=false。未自动启动完整任务。

## 8 m/s、4 m/s² 与源仓库连续控制核查（2026-10-18）

按用户要求将默认参考速度改为 8 m/s、加速度改为 4 m/s²，stable_s 仍为 0.15。同步更新本机 task.json，并保留 task.5mps-8acc.json 作为上一组备份。Stage 4 settings 默认 MPC_ACC_HOR/MPC_ACC_HOR_MAX=4；启动生成 settings 时这两项跟随任务实际 acceleration_m_s2，避免 CLI 覆盖后参考与 PX4 配置不同。8/4 下 4.9 m quintic 轨迹由加速度限制时长为 2.661 s、参考峰值约 3.453 m/s；速度上限提高不会使每条最多 5 m 的独立动作达到 8 m/s。比 5/8 的 1.882 s 更慢、更平缓，未把这次调整表述为短段再次提速。

源仓库建议逐项核查：

- 图像 RPC：Stage 4 一直复用 Stage 3 的 stage3/super/airsim/rpc_client.py，没有新增 RPC 实现。它使用 socket＋msgpack.Unpacker(raw=False)，不调用旧 msgpack-rpc-python Client，也没有 pack_encoding/unpack_encoding 参数；MessagePack 的 BIN 载荷仍返回 bytes，文本键正常解码。新增分片响应回归，包含非法 UTF-8 的 PNG 字节与中文文本键，验证二进制不被文本解码。实测 PC msgpack=1.2.3，ROS 镜像 msgpack=1.0.3，两边均没有 msgpack-rpc-python 或 msgpack-python 旧包；没有为了复用旧库补丁而重装依赖或换通信实现。本轮没有实际 simGetImages 延迟数据，不将 5 Hz 发布率当成 RPC 0.2 s 的证明。
- 仿真倍率：Stage 4 settings 与生成预览 ClockSpeed 均为 1；源仓库模板也已为 1。保留，不新增调时层。
- 动作执行：继续沿用任务读取/目标修正、NED/xyzw 契约、动作量程、大偏航不伴随前进、STOP 忽略伴随动作的规则。源端 CRUISE_SPEED=3 的速度×时长截止会有落点偏差；PX4 适配保留已有位置参考与到点检测，没有改回定时截止，也没有新增另一套执行器。

21 项 Stage 4 测试通过，包括图像二进制分片与任务加速度映射 PX4 参数；语法检查、diff 检查通过。dry-run 的 task/settings 配置预览在 artifacts/stage4/config-84-preview.json。实际 up 在创建场景/容器前被现有 uav-stage2-airsim-px4（容器 ID d64f85cbd011，owner dbb472e6edc54f5896747ca4bf1fe5a0）占用 UDP 14580 阻止；没有停止该实例，未创建新的 Stage 4 飞行 run。检查时本机 TCP 41451 无监听，因此本轮 8/4 飞行、倾角与 RPC 性能均未实测。待该实例按其原流程清理后，按 Hands-on 启动验证。

另读取到用户已完成的上一组 5/8 完整任务 run a3f51f2162e64fa09c36af9ad20b3d15：报告 79 次请求、334.24 秒、模型停止时估计目标距离 6.039 m、task_success=true、已 Disarmed、flight_collision=false。本条来自现存报告读取，不冒充本轮独立重跑，也不能替代新 8/4 配置验收。

## 源评估终止规则与源 UI 对齐（2026-10-18）

依据相邻 AeroVLA 当前工作区 closeloop_util.py / env_uav.py / assist.py 迁入独立 Evaluation，保留原阈值、比较符号、动作步计数与优先级：Oracle 是动作后距离严格小于 20 m 的粘滞标志，STOP 成功为≤20 m；卡住为 XY 位移<0.05 m 连续计数>15，首个动作后自比较计 1；距离最后十值非递减（含相等）触发；深度按原 clip/量化后≤1 像素占比>0.1 触发。独立 reason 区分深度近碰撞、卡住、距离不下降与物理碰撞，保留 legacy_collision 标志。API 契约优先于源评估器的远距离 STOP 继续行为：STOP 总是不执行伴随动作并降落，远于20 m 标记 early_end。固定动作测试不启用语义评估。所有位置规则仍用 PX4 估计，不引入真值控制。

为了实际覆盖原深度规则，Stage 4 设置补齐左/右/后相机，前/左/右/后/下五向 DepthPerspective 与双 RGB 同次 RPC 采样。图像类型值 2 已与本机 AirSim PythonClient enum 核对。全部帧及配对位姿遵守原 100 ms 时差约束；新增同步 depth topic 给控制节点，每步保存 fractions。缺失/非法深度不能当成无障碍，无法形成有效观测时沿用现有失流处理。该新增感知负载、深度效果和终止降落尚未实际仿真验证。

UI 直接复用旧 src/demo/dashboard.css，HTML 按其提示词→双图→输入位姿/动作→指标栏布局适配，不引入 NiceGUI 依赖；保留全屏与最终结果展示。模型观测的 PNG、位置、完整 XYZW 四元数和 prompt/动作绑定同 run/step，等待新请求时隐藏旧动作。两张图片都载入后才更新该帧内容，避免慢图响应造成混帧。HTTP 实测当前历史 run a3f51f2162e64fa09c36af9ad20b3d15 的 step=78：观测与响应同为78，两个 PNG 与对应 observations/78 文件逐字节相等；前视 SHA256 前缀 1720634fe850a58a、下视 ed7656cc16887ac3。HTML/CSS/PNG 端点均返回200。WebUI 已在原127.0.0.1:8080重启生效。尚未做真实浏览器布局截图验收。

PC 回归：28 项通过，另外3项 ROS 入口测试在 PC 显式跳过；这3项已在现有 ROS 镜像隔离容器内实际通过，另有6项纯评估边界测试在同镜像通过。控制入口测试覆盖评估终止后不提交新推理、最后动作先更新 Oracle 再判步数上限、UI 保存的 PNG/位姿与提交 API 数据一致。新增 Node 原生 DOM 模拟测试运行真实页面 JS，延迟两个图像响应，确认双图齐全前字段不提前更新，新观测等待时清除旧动作；通过。语法/diff检查通过。

当前 uav-stage2-airsim-px4 仍运行且占用飞控端口；没有停止它，没有启动新飞行或调用模型。故上述结果是规则/ROS入口/HTTP验证，不是完整新闭环验收。下一步按 Hands-on 重建实例，先检查七帧与估计时间配对，再逐项验证正常短程、深度近碰撞和评估终止后的真实降落及Disarmed。旧8/4配置也仍没有独立实飞证据。
