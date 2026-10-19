# Stage 5 开发交接

当前处于“AirSim替换Gazebo”层，用户已接受AirSim_Mountains Shipping包作为日常场景。默认runtime统一管理Shipping、PX4和ROS Docker；不要重新从Gazebo或Editor接入复现，也不要在没有新输入时重复验证已经通过的静止链路。

当前操作唯一入口：[Hands-on](Hands-on.md)；职责与边界：[Agent](Agent.md)；实际证据：[Validation](Validation.md)。旧版本操作可从Git历史查阅；历史失败及更正以Validation为准。

## 阅读与修改顺序

| 改动层 | 阅读入口 | 必要验证 |
| --- | --- | --- |
| 包地址/生命周期 | .env.example → airsim/config.py → runtime.py → scene_process.py | dry-run、归属/锁回归；确需时静止up/status/down，不自动飞行 |
| PX4/相机/时钟 | airsim/px4_start.sh、run_nodes.sh、sensors.py、frames.py、geometry.py | 双向消息、实际RGBD/采集位姿/时钟、配置与ULog；仅ready不算飞行 |
| 感知/记忆 | airsim/perception.py、observation_memory.py → depth_fusion.py | 空帧/超量程/混合层/采集位姿与记忆；保留原始审计 |
| 任务/模型协议 | airsim/task.py、mission_runtime.py → agent_contracts.py、task_runner.py → tactics.py、decision_client.py | action优先、上下文绑定、预算、取消/恢复与延迟；真实模型调用单独记录 |
| 控制 | agent_runtime.py、follow.py、airsim/geometry.py | 合法动作、速度/坐标、阶段切换、失流/人工降落；再做授权低速任务 |
| 展示/诊断 | webui.py、webui/、latency.py | 只读HTTP、图像/状态同任务、快照时机；不把旧模型选择当执行授权 |

## 必须保留的已确认决策

- AIRSIM_MOUNTAINS为Shipping ELF地址，根.env统一配置，Shell优先；包内settings/UserDir/三车路线必须一致，不回退到其他项目的SimpleFlight配置。
- 先悬停，再开车；阶段切换保持Offboard但清空感知历史。默认持续跟随，Jev判断结果，Qwen调度与验收；不重新添加10秒完成、固定搜索一圈或旧框IoU门槛。
- DINO阈值0.7，最大深度层估计目标，too_far按正常超量程参考接近；其他层作为潜在遮挡事实保留。无效深度与无采集位姿不伪造几何。
- 水平3m/s、垂直1m/s，感知1秒；无固定高度/65m中止。budget、阶段/总timeout、15秒无决策及现有速度估计过滤保留。
- action优先，忽略多余参数并留证；redo缺allocation复用配置、不退还消耗；验收对象由本地绑定，模型漏填不重复耗预算。
- 成功阶段验收期间用实时观测继续执行；独立land/stop持久取消任务，不能再切回Offboard或用Hold覆盖Land。

## 外部场景与仓库边界

Git交付Python/Shell/XML/JSON、测试、文档与airsim/scene中的修复补丁。已接受Shipping包、完整UE项目/资产、三车SaveGames、Docker镜像、模型和运行日志不是Git源码；新机器必须另行取得相同交付包。包二进制SHA256、实际配置、镜像身份和静止生命周期run索引见Validation；不要用本机绝对路径或缺失的历史artifacts当换机前置。

scene下补丁记录停车控制器修复、未接PX4时停止Play恢复、禁用SteamVR、隐藏路线调试图形。它们不是完整场景构建源；修改C++/蓝图/地图后才涉及UE编译/cook/打包，修改Python、prompt或模型配置不需要重打包。包清单校验、动态库解析和启动成功均不能替代车队路线实际加载或完整飞行。

## 当前后续验收

优先记录Shipping上完整任务、多轮遮挡恢复与成功率，区分模型选择、执行器拦截和真实机体运动。次要方向是确认误检、视觉运动方向和实际运动方向的路径检查；不能无证据增加新的隐藏终止条件。其他两种跟随方式、复杂绕障、板端与真实硬件保持未验收。

整理/合并前检查源码语法、Stage 5离线回归、Shell/前端语法、依赖锁一致性与diff空白；不调用云端、不启动模型/飞行来做静态整理。不要提交.env、artifacts、包、模型、缓存或长日志。主线同步和合并冲突由合并阶段处理，整理不改写分支或替换其他阶段源码。
