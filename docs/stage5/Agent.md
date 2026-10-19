# Stage 5：Qwen—Jev 车队语义跟随

当前默认是PC上的AirSim_Mountains Shipping场景、PX4 Docker和ROS RGBD Docker。Qwen规划与验收、DINO感知、Jev选动作，执行器通过PX4 MAVLink Offboard控制。RoboPi与真实硬件尚未迁移。操作统一见[Hands-on](Hands-on.md)，开发入口见[Development](Development.md)，实测结论见[Validation](Validation.md)。

## 1. 当前能力与验证结果

| 层 | 当前能力 | 验证边界 |
| --- | --- | --- |
| 场景与runtime | Shipping窗口＋PX4／ROS统一up/status/land/stop/down；进程及容器所有权校验 | 静止ready、重复up、完整回收、任务锁占用时急停通过；长期GPU稳定性未确认 |
| 感知 | 内置front_center RGB与DepthPlanar、DINO候选、最大深度层、短期原始记忆 | 高分候选仍可能误检，无通用身份关联或实例分割 |
| 任务 | observe_target寻找/确认；follow_vehicle后上方持续跟随 | 当前只开放黄皮卡rear_above；用户接受当前场景包及开发效果，未做多轮完整任务统计 |
| 模型决策 | Qwen阶段计划/验收/修订；Jev偏航、接近、跟随、保持及阶段结果 | 协议回归通过，不保证任意自然语言任务理解或复杂遮挡恢复成功 |

Gazebo红色目标的35/60秒及两阶段实飞结论保留在Validation，不作为Shipping任务验收。三种英文prompt都已保存，但左侧伴随、正上方跟随尚未开放。

## 2. 流程与职责

1. **runtime up**检查包及端口，显式settings/UserDir启动Shipping，等待本轮HIL监听，再启动PX4／ROS。验证图像、定位和预检，不调用模型、不起飞、不启动车队。
2. **runtime task**取得任务锁，检查现场与DINO/Jev/Qwen，PX4 commander起飞；确认高度、低速和Loiter稳定后才启动车队。准备阶段单独记账，起飞失败不进入模型任务。
3. **Qwen**根据当前图像和任务规划阶段。目标未确认时先寻找，再跟随；是否偏航/接近由阶段语言和Jev决定，不写死一圈搜索流程。
4. **Jev**读取当前阶段、感知、记忆、几何、进度和执行健康，选择动作并报告running/done/failed。Jev收到结构化信息，没有实时图像输入。
5. **执行器**做合法性、数据新鲜度、坐标及路径检查，再发送速度/偏航设定值；不通过旧像素框IoU或重复语义验收否决Jev阶段结果。
6. **Qwen验收**决定接受、重做、改阶段/后续计划或中止。成功阶段验收期间仍用实时感知和Jev继续上一阶段；失败、预算耗尽、超时不继续移动。最终总结仅描述事实。

车队在模型请求期间持续运动，不暂停或复位世界。场景退出、遥测异常、预算结束都不是任务成功；runtime ready也不是模型或飞行验收。

## 3. 感知与执行

- 相机为AirSim原生front_center，RGB640×360、DepthPlanar640×400，90°水平FOV。20m外是正常的超量程距离信息，20m控制参考用于接近，不是目标消失或精确测量。
- DINO默认阈值0.7，保留完整筛选审计。当前最高分且有可用几何的候选提供控制参考，不声称完成身份跟踪；候选全部给Jev判断。
- 检测框内按有效像素数最多的距离层估计距离，相邻0.5m桶合并。超量程层同等参与；其他层的距离、占比和像素包围框保留为潜在遮挡/背景，不因mixed直接抹掉目标。层不是物体分割，包围框不是掩膜。
- 世界投影使用采集时刻PX4估计与相机外参，不用仿真车辆真值控制。NaN、不同步或无采集位姿仍不能伪造几何。
- 记忆保留最近4秒的观测统计，先给“多少帧无候选/总帧数”，再附有候选的原始记录与年龄；不人为标注连续确认、不把历史候选冒充当前可见。
- 感知有效期1秒，Jev判断TTL3秒，调用间隔2秒；无可用判断15秒结束阶段。阶段切换保留Offboard但清空候选、运动估计与记忆，避免目标变化后沿用旧信息。
- 水平速度上限3m/s、垂直1m/s，保留设定值渐变。AirSim没有固定高度或65m水平中止；遥测、有限数值、解锁和Offboard状态仍检查。
- 有实测位置及运动方向时，approach_target/hold_course均可朝指定后上方目标点移动并持续跟随；方向尚未形成或超量程时先水平接近、保持高度。当前方向估计仍有低速/跳变过滤，不提供真实车头朝向。

路径检查保留已知阻挡否决；near-frustum unknown按现有谨慎仿真策略处理，不等于clear。当前没有左右绕行或主动爬升技能，不能仅通过更换提示词实现绕树。

## 4. 计划、验收与进度

计划version=2，阶段包括id、goal、skill、dino_text、完成/失败标准、allowed_skills及allocation。持续跟随使用continuous=true，不要求duration_s；valid_follow_s仅为诊断，不是固定10秒门槛。旧Gazebo定时协议仍兼容。

| action | 行为与参数 |
| --- | --- |
| accept | 接受当前阶段，推进；最后一个接受即结束 |
| redo | 重做当前阶段；allocation省略时复用当前配置，历史消耗不退还 |
| modify_stage | 使用stage替换当前阶段，保留后续和当前id |
| modify_plan | 使用stages替换当前及后续，已接受前缀不能改写或重复id |
| abort | 记录assessment并结束为失败 |

**action优先**，无关字段忽略并记录，不因此重试。缺必要参数、非法数值/技能或未知action才修正。阶段/attempt由本地请求上下文绑定，模型漏填不额外耗预算；显式错配仍报错。

临时遮挡或当前阶段failed不等于整个任务不可恢复。Qwen在资源允许时可插入新的寻找/确认阶段，再恢复原跟随；不是固定重试流程，也不因一次丢失自动中止。协议正确仍不保证模型选择了正确策略。

## 5. Qwen实际看到什么

Qwen接收原任务、当前阶段、计划概要、报告、预算与剩余时间、实时观测摘要、完整文字历史和本轮最新RGB。历史图片不反复发送；结束时tracking与当前画面明确区分。真实请求见qwen-N-request.json，本地完整诊断上下文qwen-N-input.json不等于线上文字输入。

Jev的实际请求保存在attempt-*/jev-request-NNNN.json，不包含HTTP认证头；模型本地或云端由根.env决定。WebUI图像仅在DINO送检/模型请求时更新，不是持续视频，也不表示Jev收到图片。

## 6. Qwen等待期间持续运行仿真

成功阶段done后立即形成验收快照，保留本阶段执行器继续读取新观测/请求Jev；重复done不重复切换，其他动作约束不放开。Qwen返回后关闭旧阶段，按action切换或结束。继续执行仍消耗原阶段Jev额度和总时间；报告快照与review-continuation.json分别记录两个时刻，不能用旧速度无限续飞。

人工land/stop写入取消标记，起飞/开车前与任务控制均检查。降落后不能又被任务切回Offboard或Hold。取消本轮后重新执行需要down/up。正常任务结束保持，起飞编排失败请求降落；请求受理不等于落地。

## 7. 预算、时间与结束状态

| 资源 | 当前默认及范围 |
| --- | --- |
| Qwen执行budget | 默认10；初始规划、验收、修正和重试计数 |
| 模型任务timeout | AirSim默认180秒，从悬停/开车后的模型任务开始，含规划、执行、验收 |
| 阶段Jev budget/timeout | Qwen分配；在途请求、失败和验收continuation按同一配置计账 |
| 起飞屏障 | 独立timeout默认60秒，需真实悬停，不以API回包代替 |
| 最终总结 | 预算外最多1次，最长30秒，不发动作或修改计划 |

DINO不计Jev/Qwen额度；任务前就绪探针与起飞单独记录，不伪装成模型任务执行耗时。不能相减异机单调时间或混用ROS墙钟日志与仿真时钟。latency.jsonl记录请求及控制提交，不能直接等同于机体响应。

## 8. 灯箱、证据与代码入口

| 代码 | 职责 |
| --- | --- |
| stage5/airsim/runtime.py、scene_process.py、config.py | 生命周期、所有权、包路径和飞控/传感器配置 |
| stage5/airsim/task.py、mission_runtime.py | 健康、起飞屏障、车队编排与AirSim模型协议 |
| stage5/airsim/sensors.py、frames.py、geometry.py | 采集、时钟/位姿配对、坐标转换 |
| stage5/airsim/perception.py、observation_memory.py | 当前帧候选、最大深度层、原始短期记忆 |
| stage5/task_runner.py、agent_contracts.py | 阶段路由、预算、进度、action参数与上下文 |
| stage5/qwen_agent.py、qwen_report.py、tactics.py、decision_client.py | Qwen/Jev调用、历史、协议与TTL |
| stage5/agent_runtime.py、follow.py、depth_fusion.py、voxel_scene.py | 共用控制、几何、确定性执行 |
| stage5/webui.py、webui/、mission_registry.py | 只读状态、送检快照与工作树任务索引 |
| stage5/latency.py、tests/、airsim/scene/ | 延迟汇总、回归、外部UE场景补丁 |

本轮run目录保留scene.log、scene.json、源码/镜像/配置身份、node-logs、PX4日志与startup；任务目录保留plan、events/ledger、terminal/summary、每次attempt报告/轨迹、模型请求/用量及latency。它们位于忽略的artifacts，不随clone分发。场景包也是外部运行产物，补丁不是完整UE项目源码。

## 9. 当前仍存在的关键问题

| 问题 | 边界 |
| --- | --- |
| 模型任务语义 | Qwen仍可能错误accept失败报告或误判目标；action协议与上下文绑定不能保证语义正确 |
| 身份与深度 | DINO高分仍可能把白van/装甲车当黄皮卡；最大深度层可能属于背景，当前没有重识别或分割 |
| 遮挡恢复 | 已有偏航与子任务调度能力，但复杂树木遮挡恢复、多轮成功率及绕障执行未验收 |
| 控制与路径 | 视觉运动方向/近似车顶有误差；当前主要检查相机正前方候选，不能宣称完整三维规划与碰撞保证 |
| 场景稳定性 | 历史Vulkan/Xid109根因尚未隔离；Shipping包接受不等于长期稳定性通过 |
| 交付范围 | 非PC迁移、其他两种跟随方式、真实硬件均未验收；不把Gazebo结果替代Shipping结果 |

## 10. 如何验证后续修改

先跑离线协议/控制回归，再按改动验证实际链路：配置/import→双向消息→静止传感器→低速短程→完整任务和故障恢复。模型调用、飞行、车队运行分开授权与记录，不能为了检查文档默认发付费请求。每轮保留实际源码/镜像/配置、run ID、日志及验证边界；操作只维护Hands-on，历史结论按Validation的后续更正阅读。
