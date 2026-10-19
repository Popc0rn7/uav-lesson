# Stage 5 场景验证

## 当前结论与证据入口（2026-10-19）

用户已接受AirSim_Mountains Shipping包作为当前场景；默认入口为统一runtime，不再要求Editor Play。当前操作见[Hands-on](Hands-on.md)，架构见[Agent](Agent.md)，开发边界见[Development](Development.md)。本文后续按时间保留原记录，包括失败、撤回和更正；早期“未实现/未安装/通过”均只对应当时现场，不能独立当作当前状态。

| 范围 | 当前结论 | 主要证据 |
| --- | --- | --- |
| Shipping交付 | 用户接受当前包，41451/Drone1/PX4，固定包内UserDir与三车路线；文件/动态库检查通过 | 2026-10-19打包、残留清理与Shipping Saved路径修正记录；包ELF SHA256=169bdb150359530406a7b44534135c42a41a2c38caa19d53cc2b251754364177 |
| 统一生命周期 | 自动up到ready，重复up不增加实例，down/stop回收本轮场景和容器；任务占锁时恢复可用 | runs d7b186cbf6414a719ac814e6669b67af、fbedcb3c10f14633b20f4878b45815bc；各自lifecycle-check/super-alignment-check及scene/node/PX4日志 |
| 控制开发效果 | Editor轮曾达到约11.32秒有效跟随，最后被旧固定高度限制终止；限制已按用户要求移除 | run db27671822e74865a67837d34650658c；不将其记为完整任务成功 |
| 任务协议/展示 | action优先、本地验收绑定、持续跟随、验收overlap、原始记忆/深度层、取消恢复及只读快照均有离线回归 | 下文对应修改记录与tests；184项为整理前回归数，整理后结果见末尾 |
| 未验收 | 其他跟随方式、复杂遮挡/绕障效果、多轮完整任务成功率、长期Vulkan稳定性、板端及真实硬件 | 不因用户接受场景包、ready或单元测试标记完成 |

场景包、完整UE项目、Docker镜像、模型、ULog和artifacts均不是Git交付。换机需另行准备同一包及依赖；这里只保存证据索引，不把本机历史目录当可分发文件。日常命令只维护Hands-on；旧版本操作可从Git历史查阅。

## 历史验证记录


## AirSim相机与PX4接入代码（2026-10-18，待在线验证）

用户指定第一步迁移相机与PX4，参考Stage 2相机和SUPER AirSim接入。新增 `stage5/airsim/` Editor接入入口，保留Drone1／41461和交接出生点；PX4使用原镜像、instance5／sysid6、HIL TCP4565，独立AirSim控制UDP14546／14586，保留原执行器14545／14585。ROS域15／XRCE8895；时钟复用SUPER的SensorCombined桥。相机从Stage 2 SDF生成内外参，经PNG／DepthPlanar输出原HTTP协议与ROS图像／CameraInfo，页面复用Stage 2实现。完整命令仅维护在 [Hands-on](Hands-on.md)。

离线准备已生成 `artifacts/stage5-airsim/prepared/settings.json` 和标定，未写UE工程。Python语法、Shell语法及diff空白检查通过；新增离线测试覆盖身份／端口、图像颜色与深度、时间／尺寸错误、配置准备无副作用及容器归属，按用户要求留待后续运行，未宣称测试通过。

本轮早期仅检查已有本地镜像：ROS镜像 `sha256:c24f47188837b14600ec211bbc7d98f00c212aad7ff70cb4a446c02e8a1be894`，source ROS／px4_ws后rclpy、px4_msgs、msgpack、NumPy、Pillow及MicroXRCEAgent可用；PX4脚本确认HIL端口为4560＋instance，Offboard端口随instance分配。未改镜像。初次直接以Python entrypoint检查未source ROS而import rclpy失败，正确初始化后通过；不是缺ROS依赖。

**用户随后明确现场有竞争，本轮停止在线接入。** 未安装设置、未连接车队RPC、未启动持久PX4／ROS容器、未改变Editor Play、未解锁／起飞／启动车队。当前没有新链路run ID、在线传感器报告或ULog；既有Gazebo及SUPER成功记录不能替代本场景验收。

下一步在竞争解除后：安装已审阅设置→用户Play→up检查连续HIL／DDS／clock、定位与真实RGBD→verify-camera／snapshot→记录实际镜像／场景／源码及采集时间证据。之后再授权飞行验收；本次前向相机不覆盖正上方跟随，原mission仍会调用Gazebo车辆命令，不应在AirSim上直接执行。

### 2026-10-18 Editor 打开后的配置安装（尚未 Play）

用户恢复测试授权后，确认 UE4Editor PID891277 打开目标 `demo.uproject`／`LandscapeMap`，显式 `-settings=` 指向项目 `Config/AirSim/settings.json`；当时41461／4565／8189／8190均未监听，没有Stage 5飞行容器。原文件仍为SimpleFlight，随后使用 `install-settings` 备份并安装PX4＋RGBD配置，安装记录位于 `artifacts/stage5-airsim/prepared/installation.json`，文件内容核对与生成配置一致。

7项新增AirSim离线契约测试通过，Python／Shell语法检查通过。尚未进入Play，未启动PX4／ROS容器、未连接车队RPC、未解锁／起飞；下一步由用户正常Play后再验证HIL与真实传感器。本条更新前文“未安装／测试未运行”的状态，不代表在线接入已通过。

### 2026-10-18 首次 Editor Play：基础链路通过，发现相机机臂遮挡

运行ID `24731d48f1834d6e94a4948ff4feb9d4`，证据根目录 `artifacts/stage5-airsim/24731d48f1834d6e94a4948ff4feb9d4/`。Editor PID891277／原工程LandscapeMap，RPC41461／Drone1／PX4Multirotor，HIL TCP4565成功连接。PX4镜像 `sha256:70584c9eb1e928a9a621b939de0ebab0c91940860fb2f28848bd27f26a0432f4`、ROS镜像 `sha256:c24f47188837b14600ec211bbc7d98f00c212aad7ff70cb4a446c02e8a1be894`；源码和初始设置见 `identity.json`／`settings.json`。未调用模型、未解锁／起飞、未启动车队。

首次就绪检查缺少本地位置，原因是订阅无后缀话题，而实际发布为`/fmu/out/vehicle_local_position_v1`。修正后只重启本轮ROS容器，保留PX4／Editor连接，原up流程正常到`ready=true`。`preflight.log`为`Preflight check: OK`，GPS锁定、本地XY/Z有效、sysid6、nav_state4、armed=false。`Unsupported main mode`为既有组合已知警告，本次未改SYS_HITL或HIL开关。

`verify-camera`通过5秒窗口，RGB640×360／RGB_INT8、深度640×400／R_FLOAT32、实际约5.45帧/仿真秒，墙钟接收约5.53Hz，低于10Hz采样目标；两帧采集时间差约3ms，图像相对最近HIL样本误差小于1微秒，该次采集相对最新HIL滞后约54ms。深度有效比例0.36094，范围0.15063～19.98438m。证据为`camera-check/camera-verification.json`及原始画面；不能把这些内容／持续性检查当成几何精度或无遮挡验收。

独立ROS只读订阅5秒实际收到clock1256、位置250、RGB18、depth3、两路CameraInfo各26、vehicle10条，`/clock`推进5.016秒，标定K与各自尺寸／FOV一致。见`ros-verification.json`。已证明实际消息可收到；尤其深度大帧只收到3条，尚不能宣称ROS图像满速或无丢帧。HTTP图像约5.45Hz与DDS订阅计数属于不同链路，后续需单独核对大帧传输。

PC监听原Stage 5的14545端口5秒，实际收到system ID6的HEARTBEAT5、LOCAL_POSITION_NED150、ATTITUDE_QUATERNION251条，保持未解锁／Hold；见`mavlink-verification.json`。探针只接收，不发送控制。车队真实TCP status返回idle，三车available且速度0；仅status已验收，start／stop／reset未执行。

人工查看 `snapshot-1792306103405955118/rgb.png` 发现Stage 2原外参前方0.186m在AirSim默认机型内拍入机臂。随后仅通过`simSetCameraPose`临时把相机前移到0.5m，真实PNG确认原机臂遮挡消失，立即恢复0.186m；没有移动机体、暂停场景或使用真值控制。候选图及前后相机pose见`camera-clearance/`。当前配置输入已加入显式AirSim外参0.5m，生成新prepared设置，ROS标定／TF同步读取该配置；**尚未安装到UE，当前运行仍为0.186m旧外参**，下一轮Stop Play→安装→Play后必须复验。

8项离线契约测试、Python语法及diff检查通过。当前仅基础静止链路通过，外参修正后的RGBD／TF、ROS大图传输、起飞／悬停／降落、车队动态控制和三车跟随均未验收。下一步先完成相机外参切换及图像链路复验，再进行明确的低速飞行验证；不以ready或模型文字替代飞行结果。

### 按用户反馈改回AirSim内置相机安装（待重新Play）

源码确认默认1／2／3分别显示DepthVis／Segmentation／Scene，均引用内置`front_center`（别名空字符串／0／fpv）。此前没有新建相机，而是配置覆盖了内置相机的安装位置，导致遮挡。用户明确选择内置安装后，撤回0.186m覆盖及0.5m候选；`camera_mount=airsim_default`生成设置只配置CaptureSettings，不写安装位姿。RGB／DepthPlanar均90°FOV，CameraInfo同步使用fx=fy=320；外参未知时不发布先前Stage 2硬编码TF。8项离线测试和语法检查通过。

新prepared设置已生成，但未安装到正在Play的工程，当前运行状态不因删除配置字段而自动恢复。下一步Stop Play→安装→重新Play，再检查默认内置画面、两路图像与标定；原0.186m运行的结果仍仅代表当时配置。0.5m诊断图不再作为当前交付方案。

### 网页改为送检快照（2026-10-18，未重启现场）

按用户要求，AirSim ROS启动脚本不再启动Stage 2实时相机网页，移除viewer_port／8190的默认启动与端口占用检查。8189内部原始帧接口和后台感知继续工作。任务Perception不再每秒生成网页RGB／深度预览，仅在DINO送检时保存实际请求帧、配对深度，在返回时补同帧检测框；配置版本已过期的请求不覆盖新快照。Jev目前仍只传结构化观测，不声称网页图片已发给Jev，不改变模型输入契约。

灯箱改为“送检RGB”，预览接口使用ETag；快照无变化返回304，不重传base64图片正文。新增回归覆盖后台跟踪不刷新图片、送检图片一致性／旧配置拒绝及304后新快照更新。94项离线测试通过，Python／JavaScript／Shell语法和diff检查通过。初次全套测试因借用环境缺TypeSafe SDK有10项import错误；只读复用本机jev-drone的Python3.12包路径后全套通过，未安装或修改其他工作树依赖。没有真实模型调用或飞行。

当前旧ROS实例未为此改动重启，原8190网页可能仍在运行；下一次本入口重启后不再提供。未做浏览器视觉验收，也未宣称新AirSim内置安装配置已在Play中生效。

### Stage 5统一使用根环境配置及vLLM客户端（2026-10-18）

按用户要求同步`~/uav-lesson`的根环境配置格式，真实配置保存在忽略的根`.env`，示例密钥置空。Stage 5所有使用`dino_client.configuration()`的入口现在只读根`.env`，shell可覆盖服务配置，不读`stage5/.env`或`.env.example`；删除阶段目录模板，更新配置报错与操作说明。相机仍固定本机8189内部接口，与主仓库行为一致。

同步主仓库`decision_client.py`及离线协议回归，Tactician和问题定义接入统一客户端，实际使用`JEV_BACKEND=vllm`、18081/v1、jev-decision及同模型决策头／温度校准，不再要求本地vLLM提供TypeSafe密钥。新增根环境优先级／旧配置忽略及Tactician后端接线回归，102项离线测试通过，Python语法与diff检查通过。用禁止HTTP请求的mock检查本地真实配置可构造vLLM客户端，决策头／校准可读，DINO和Qwen配置可获取；没有发送推理请求、重启服务、操作飞控或改变Editor。该检查仅证明配置和客户端接线，不代表真实推理／飞行验收。

### 2026-10-18 Play立即崩溃：相机创建NaN，已修正配置、待重试Play

本轮最新崩溃PID1134132，原报告位于场景`Saved/Crashes/crashinfo-demo-pid-1134132-03EA1476982640679396BE9ABAB9E12E/`。日志07:53:45.977先报`SpawnActor failed ... transform (nan,nan,nan|...) is invalid`，随后SIGSEGV读取0x150。调用栈明确为`AActor::AttachToComponent`←`PawnSimApi::createCamerasFromSettings()`（PawnSimApi.cpp:139）←相机／车辆初始化，尚未到本轮PX4 HIL连接。查询时Stage 5容器已清理、运行记录stopped，没有相关端口监听；故障证据指向相机初始化，而非本轮模型调用或Docker控制。

此前“在Vehicles.Drone1.Cameras只写CaptureSettings、去掉位姿就会保留内置相机”的判断错误，现撤回。实际插件`setupCamerasFromSettings`先加载内置相机，再无条件创建每个车辆Cameras条目，即便名称是front_center；位置默认NaN使SpawnActor返回空指针，紧接的AttachToComponent没有判空。本仓库生成的配置触发了该缺陷。前一轮有限0.186m配置同样会创建替代相机，不能描述为仅调整原相机。

修复为只用**顶层CameraDefaults.CaptureSettings**，完全移除原生相机模式下的车辆Cameras条目。源码已核对：loadCameraSettings在无Cameras键时不生成条目；setupCamerasFromSettings会将camera_defaults应用于已有相机的采集组件，不经过额外创建分支。保留RGB640×360、DepthPlanar640×400、90°FOV、原生相机位置及原PX4连接。未修改或重编场景／插件。

8项离线契约测试通过，其中明确断言原生相机配置无车辆Cameras键，采集参数位于顶层CameraDefaults。修正配置已通过install-settings实际安装，原错误配置备份为`settings.json.stage5-a593aa54e063483d970d6e03e857e5b7.bak`；安装记录、崩溃日志／Diagnostics／CrashContext、修改前后设置与诊断归档于`artifacts/stage5-airsim/crash-20261018-camera-defaults/`，不提交Git。没有改动本轮其他开发者的模型／环境配置变更。

尚未重新Play，不能仅凭离线测试宣布UE崩溃已实测修复。下一步使用原Editor启动命令重新打开工程、正常Play；先检查不再出现NaN创建／空指针，再按Hands-on启动PX4／ROS并重新验收内置RGBD。无须重复安装或重建镜像。

### CameraDefaults修复后重新Play：内置相机与静止链路实测通过

运行ID `d7672e381b49434dbf3910b27d64200f`，Editor PID1150237，目标工程LandscapeMap，使用顶层CameraDefaults，无车辆Cameras条目。本轮Play正常，未再出现NaN创建／相机挂接崩溃，PX4 HIL连接、GPS和本地定位、正常预检均通过，保持sysid6／Hold／Disarmed。镜像沿用PX4 `sha256:70584c9eb1e928a9a621b939de0ebab0c91940860fb2f28848bd27f26a0432f4` 与ROS `sha256:c24f47188837b14600ec211bbc7d98f00c212aad7ff70cb4a446c02e8a1be894`，未重建镜像或插件。

实际RPC查询front_center、0和空字符串默认相机，pose与Scene投影矩阵完全一致；结合无Vehicles.Cameras的加载路径，确认采集使用内置相机。证据`native-camera-verification.json`；快照`snapshot-1792310383952712947/rgb.png`已人工查看，原机臂遮挡消失。查询pose属于AirSim本地参考坐标，未把它直接认作机体安装外参或用于飞行控制；机体→相机精确外参／TF仍待核实。

RGB640×360／90°与DepthPlanar640×400／90°真实采集通过；最终5秒HTTP窗口实际约5.33～5.35仿真Hz、墙钟接收约5.43Hz，深度有效比例0.23761、有效距离1.12598～19.98438m。RGB／深度采集时间差约3ms，最近HIL时钟偏差约1.2微秒，采集相对最新HIL滞后约51ms。均未把接收墙钟用作采集时间。见`camera-check/camera-verification.json`。

首次独立5秒ROS探针收到RGB25、Depth0，CameraInfo／clock／PX4位置正常，说明HTTP相机通过不能替代DDS深度大帧验收。原共享内存段约537KiB，小于单帧深度载荷1024000字节，socket默认收发缓冲212992字节、内核最大10MiB；未更改内核参数。参考[Fast DDS共享内存文档](https://fast-dds.docs.eprosima.com/en/2.6.x/fastdds/transport/shared_memory/shared_memory.html)关于segment不足的说明，新增显式本机DDS配置：SHM段8MiB、UDP收发各4MiB，仅重启本轮ROS容器，不断开PX4／Editor。两个独立5秒窗口随后分别收到RGB／Depth25／25、27／27，两路CameraInfo计数一致，修正后本轮大帧消息到达通过。SHM和UDP缓冲同时变化，尚未分别隔离其贡献，不声称已证明唯一根因或跨机问题修复。

最终可复现入口`runtime.py verify-ros`检查通过：clock1255、位置248、RGB／深度各27、CameraInfo各27、状态10，时钟推进5.013秒，CameraInfo的fx=fy=320、主点RGB(320,180)／深度(320,200)，实际编码rgb8／32FC1及载荷长度正确。见`ros-verification-before-transport-fix.json`和`ros-verification.json`。MAVLink14545只读5秒收到sysid6心跳5、LOCAL_POSITION_NED150、ATTITUDE_QUATERNION250，保持未解锁／Hold，见`mavlink-verification.json`。8190无监听，未启动实时图像网页。

本轮证据位于`artifacts/stage5-airsim/d7672e381b49434dbf3910b27d64200f/`；启动输入与源码／镜像身份、原始报告、节点日志、Docker日志和现场快照已保存，ULog为`px4-logs/2026-10-18/07_59_25.ulg`（实例仍运行，非完整飞行日志）。初始identity为DDS调整前版本，调整后XML／脚本及源码摘要另存，保留两者。8项离线契约测试与Python／Shell／XML／diff检查通过。

当前静止接入通过并保留运行现场，飞机未解锁、三车idle／静止，无模型请求、无起飞／悬停／降落动作。尚未验证10Hz目标、长时传输稳定性、精确安装外参、飞行控制与动态车辆跟随；下一步为独立低速起飞／悬停／降落，再接车队任务，不以本次ready代替飞行验收。

### 同一轮后续运行崩溃：Vulkan设备丢失，稳定性未通过

运行`d7672e381b49434dbf3910b27d64200f`／Editor PID1150237后续在08:06:51（日志前缀时基）崩溃。本次Play开始日志为07:59:01，约7分50秒后出现`VK_ERROR_DEVICE_LOST`／VkResult=-4，首个检测点是`VulkanMemory.cpp:4765`的`vkGetFenceStatus`，调用栈经过`VulkanViewport::Present`和RHIThread。随后SIGSEGV是Fatal处理路径的一部分，未再出现此前NaN相机创建栈。上述短时接口验收结果仍有效，但**本场景持续运行稳定性未通过，不能作为稳定交付**。

实际本机为Intel i9-14900K／RTX4090（24564MiB）／NVIDIA595.99.02，UE4.27.2使用Vulkan。不能沿用旧Gazebo记录中的AMD780M环境说明。本轮崩溃后GPU可查询，当前GPU Recovery Action=None，显存约1280MiB、温度40℃，但这是UE退出后的状态，不能据此排除崩溃前显存压力或驱动异常。未获得崩溃时的NVIDIA Xid／内核事件：普通journal无系统权限、dmesg拒绝，免密码sudo也失败，已请求用户提供对应时间窗口。暂不能将具体根因归为驱动重置、显存不足、图像采集或某个RHI线程缺陷。

崩溃前接收1721对有效RGBD；随后RPC拒绝连接、HIL／位置／状态均陈旧，sensors healthy=false，属于场景退出后的链路失效。未尝试靠修改相机位置、关闭深度或放宽健康检查恢复。已保存新CrashContext／Diagnostics／UE日志、断流状态、GPU崩溃后快照和PX4状态于本轮`crash-vulkan-device-lost/`，归档Docker／节点日志及ULog。核对PX4 arming_state1、armed_time0、takeoff_time0后正常down，仅清理本轮两个容器；未停止其他模型服务、改驱动、重置GPU或改场景参数。运行记录现为stopped。

下一步先取得内核NVRM／Xid／GPU reset事件，与UE设备丢失时间对齐，再选择单因素对照；当前没有新的稳定性修复或成功复验，不重复宣称相机配置修复解决所有UE崩溃。

### 用户补充内核证据：同PID的Xid109上下文切换超时

用户提供特权journal输出：`Oct 18 16:06:44 ... NVRM: Xid (PCI:0000:01:00): 109, pid=1150237, name=UE4Editor, channel 0x0000000d, errorString CTX SWITCH TIMEOUT, Info 0x21c00e`。PID与本轮UE一致；按该机UE日志UTC前缀与内核本地时间偏移对齐，GPU超时约7秒后UE报告Device Lost。[NVIDIA官方Xid目录](https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html)将109定义为Context Switch Timeout Error。现已确认GPU执行上下文切换超时这条故障路径，但不能进一步认定为特定驱动版本缺陷、硬件故障、RPC采集或RHI并发的唯一问题，也不等于已观察到整卡reset。

原始用户提供行和后续诊断保存为本轮`crash-vulkan-device-lost/kernel-xid-user-provided.txt`、`xid-followup.json`，保留先前“无权限读取”的原始诊断时间点。下一轮准备单因素`-norhithread`对照；本机UE4.27源码已确认该选项控制GUseRHIThread_InternalUseOnly，保持Vulkan／驱动和其他输入不变，先做至少15分钟静止连续观测。候选启动命令只维护在Hands-on，目前尚未执行、没有成功结论；本轮容器已正常清理，无需再等待Land。

### 后续已运行实例复核（run ee2ac54558224348bda7f1b41a911bd3）

用户重新Play并执行up／verify-camera／verify-ros／snapshot后，接续检查发现本轮已ready，因此复用这些输入未变的验收报告，没有重复启动容器。Editor PID1184786，实际启动参数含`-norhithread`；按用户要求暂缓GPU问题排查，未为该问题继续改驱动、参数或安排长期实验，也不据此宣称Xid已修复。

HTTP相机窗口约3.00仿真Hz、墙钟接收约2.95Hz，RGB640×360／DepthPlanar640×400，时间／格式与有效深度检查通过。ROS5秒收到RGB／深度及各自CameraInfo均15条，clock1254、位置251、状态10，时钟推进5.010秒，两路fx=fy=320。本轮帧率低于10Hz目标，也低于上一轮约5.3Hz；启动线程选项与现场资源条件不同，不能把差异直接归因于其中一个因素。

随后只读MAVLink5秒收到sysid6的HEARTBEAT5、LOCAL_POSITION_NED150、ATTITUDE_QUATERNION251，保持未解锁／Hold；即时commander check通过。真实车队status为idle，三车速度0；front_center与空字符串默认相机实际pose／投影一致。未发送飞行指令、启动车队或调用模型。现场保留运行，尚未做独立起降或动态跟随。

证据根目录为`artifacts/stage5-airsim/ee2ac54558224348bda7f1b41a911bd3/`：`camera-check/camera-verification.json`、`ros-verification.json`、`mavlink-verification.json`、`preflight-recheck.log`、`native-camera-recheck.json`、`convoy-recheck.json`、`latest-review.json`、`snapshot-1792311382458701728/`及原始identity／配置／节点日志。短时静止链路复核通过；下一步独立低速起飞、悬停、降落，不能沿用旧Gazebo飞行证据或把本轮ready写成飞行通过。

### Dashboard不可见：启动8191并接入只读AirSim状态卡

查询时8191无监听，运行中的8189为内部取帧接口，8190按用户要求未启动。原webui只从mission文件读取任务状态，即使场景ready、没有mission时也不会显示飞控。新增独立AirSim状态卡，读取当前运行记录与传感器快照，显示PX4解锁／nav_state、本地定位、NED位置、RGBD计数及新鲜度；过期或停止不报就绪。没有把场景状态伪装为模型任务，也没有重新开启实时图片。

已在PC启动`python3 -u stage5/webui.py --port 8191`，仅绑定127.0.0.1。实际HTTP页面／api/state可访问，返回本轮`ee2ac54558224348bda7f1b41a911bd3`、scene_live=true、armed=false，任务为等待mission；preview无图片，带相同ETag查询返回304且无正文。验证保存于`artifacts/stage5-dashboard/http-verification.json`。3项相关离线测试及Python／JavaScript语法通过，覆盖场景陈旧／停止与快照缓存。没有浏览器截图验收：本机未发现可用Playwright／Chrome，未为此安装额外浏览器。未调用模型、未发送飞行动作，未重启ROS或Editor。

## Gazebo历史验证

2026-10-14，本机 PC：x86_64、AMD Ryzen 7 8745HS / Radeon 780M，Docker 29.1.5，Gazebo Sim 8.15.0。镜像 `px4io/px4-sitl-gazebo:latest`，本次镜像 ID：`sha256:70584c9eb1e928a9a621b939de0ebab0c91940860fb2f28848bd27f26a0432f4`。

场景为生成器初版，半径 24 m、2 m/s、物理步长 0.004 s、目标车中心高度 0.65 m。两个容器使用 host 网络与独立 `GZ_PARTITION=uav-stage5`，未启动 PX4、ROS、板端或付费 API。

已完成：

- 三个 Python 文件语法检查通过。
- 场景在实际 Gazebo server 中加载，内置 Physics、VelocityControl、PosePublisher 正常运行。
- `python3 stage5/scene.py verify --seconds 80` 通过：80.028 s 仿真时间，1540 个位姿样本，累计移动 160.056 m，平均速度 2.0000 m/s，最大半径误差 0.0040 m，最大高度误差 0。覆盖超过一圈。
- Gazebo GUI 正常打开，内置截图经人工图像检查：建筑、环路、标线和红车显示正常；截图保存在临时目录，未提交。
- GUI 初始化暂停时钟的问题已在入口加入恢复请求。初次验证另发现 Pose_V 的时间戳位于每个 pose 的 header，已修正后完成上述 80 秒实际验证。

尚未验证：新 PC 复现、其他镜像与显卡兼容、资源性能基准、无人机与相机传感器接入、DINO/深度感知和 Jev 决策跟随。此记录只证明街区与移动目标场景可运行，不代表 jev-drone 已复现。

操作、预期现象与排障统一见 [Hands-on](Hands-on.md)。

## 标准机与相机接入（2026-10-14）

沿用上述 PC 与 Gazebo 镜像，加载仓库 Stage 2 的 `x500_experiment` 与 `mid360s`，GUI 同样挂载这两个目录。补齐 Sensors/Ogre2、IMU、气压、GNSS 和磁力计世界插件以及 ENU 地理原点。PX4 git `61907962c9220437ec01a98fa26bfbf5cbb254b5`，版本输出 1.18.0；实例 5 连接预生成模型 `x500_experiment_0`。DDS 域 15、UDP 8895，未运行 Agent，客户端状态为 disconnected。

实际验证：

- PX4 启动成功，气压/GNSS/磁力计 warmup 通过，出现 `Ready for takeoff!`。
- 地面 RGB 640×360、RGB_INT8，深度 640×400、R_FLOAT32，两路约 30.3 Hz；RGB 实际快照能看到街区、道路和红色目标车，深度有效像素约 47.8%。
- `takeoff` 实际起飞后进入 Hold，无 failsafe；本地 NED 高度 `z=-2.50329 m`，速度约 `(0.00696,-0.00607,-0.00943) m/s`，heading_good_for_control=True。
- 空中 `verify-camera` 通过，两路约 30.3 Hz，深度有效比例 24.0%，有效距离 4.326～9.551 m。原始图像长度、格式、时间戳增长、新帧计数与陈旧检查均通过。
- 复用 Stage 2 WebUI 于 `http://127.0.0.1:8190`；实际 `/api/status`、`/rgb.jpg`、`/depth.jpg` 返回正常，两路 error=null，页面输出约 20 Hz，图像年龄约 20 ms。查看器镜像 `uav-computer-ros-humble:local`，NumPy 1.21.5、Pillow 9.0.1。
- 加入无人机后车辆 12.012 s 回归通过，速度 2.000 m/s、半径误差 0.0024 m、高度误差 0。
- Python 语法与 shell 语法检查通过。

调试中曾尝试在运行期停止/重启 DDS 客户端，PX4 进程随后以 139 退出，具体原因未定位。最终入口通过 `PX4_UXRCE_DDS_PORT=8895` 在启动期设置端口，重建实例后完成上述起飞、悬停和相机验证；日常流程不包含运行期重启 DDS。

本轮没有验证降落动作、新 PC、DDS 控制链路、自动跟随、RGB/深度像素配准或 10 m 跟随测距。相机水平朝前且深度上限为 10 m，这些原始配置未修改。

## 可见目标初始化与临时检测 client（2026-10-14）

默认车辆改为静止等待，初始位置 `(24,0,0.65)`；标准机落地位置改为 `(24,-8)`、朝 +Y，起飞约 2.5 m。6 m 间距试验中车体底部在画面边缘被裁切，因此最终使用 8 m。

- 最终配置冷启动、RGB/D 检查与真实起飞通过；末次 PX4 为 Armed/Hold、无 failsafe。
- client 从真实机载 RGB 获取 PNG，人工检查 640×360 画面：红车完整位于画面中下部，没有被边缘裁切。默认车辆等待期间可重复取帧。
- `target-start` 后 12.012 s 车辆回归通过：速度 2 m/s，最大半径误差 0.0034 m，高度误差 0。`target-reset` 成功把车停回初始位置；随后真实相机取帧与 mock client 再次通过。
- 临时 HTTP 协议替身（随机本地端口、测试结束关闭）确认 `/detect` multipart 字段 `image`、`text`，上传载荷为 PNG，服务示例 JSON 原样回传。没有启动占用 8000 的假服务。
- `--mock` 用用户提供的 812×538 示例响应，保存原始图像、响应、取帧元数据、耗时和自包含 SVG；mock 来源和图内标记明确。示例框不对应实际车体，只用于接口格式验证。
- `stage5/.env` 已写入本地服务配置，确认被 Git 忽略；`.env.example` 提供无密钥模板。Python 与 shell 语法检查、diff 空白检查通过。

用户说明真实 DINO 服务尚未启动；没有验证真实模型识别、框准确率或推理耗时。机载 RGB → client 的真实链路已验证，client → 检测 API 仅验证协议替身。

## RGB 框与深度融合（2026-10-14）

- 真实机载 RGB 与深度配对成功，实测两帧仿真时间均为 837.940 s，时间差 0。深度快照在检测之前保存，后续融合使用该快照。
- 固定用户 mock 框映射到当前场景背景，ROI 无有效深度，正确输出 `insufficient_depth`，位置/距离 null，`usable_for_control=false`。
- 在同一真实 RGB 快照中人工圈定车体（仅测距验证，非模型识别），中心 ROI 1147 个深度像素全部有效：前向深度中位数 6.6003 m、MAD 0.0078 m、表面斜距 6.8533 m；相机 FLU 位置约 `(6.6003,0.1731,-1.8368)` m。车后表面比车体中心更近，不能直接与 8 m 中心水平间距混用。人工框结果标记 `manual_validation`，不用于控制。
- 五项几何/失效测试通过：中心测距、不同响应尺寸与光线映射、坐标方向、无效/超量程深度、帧时间差与 mock 禁用、尺寸与标定不符；Python 语法检查通过。

真实 DINO 尚未启动，未验证真实模型框与深度的完整在线链路、运动目标时的同步误差、多目标或复杂遮挡。当前只有相机坐标下表面估计，未估计车辆行进方向、车中心或世界位置，也未接 Jev。

## 真实 DINO＋深度（2026-10-14）

用户启动本机 `http://127.0.0.1:18008/detect` 后，将 `stage5/.env` 指向此服务，实际运行 `python3 stage5/dino_client.py`。这次使用真实机载 RGB、真实深度与 HTTP 模型响应，没有启用 mock。模型服务具体版本与权重未核实。

- RGB 和深度快照仿真时间均为 1084.516 s，时间差 0；RGB 输入 640×360。
- 红车框 `[267.2383,236.7549,335.5664,316.0979]`，标签 `a car`，置信度 0.369998，人工核对真实输入图像后确认覆盖红车。
- 深度 ROI 1184 个有效像素，有效比例 100%；前向中位深度 6.57117 m、MAD 0.00975 m。
- 可见表面在相机 FLU 坐标约 `[6.57117,0.35613,-1.84648]` m，斜距 6.83495 m，水平角为左偏 3.102°。
- 检测请求耗时 0.34322 s，总取图/检测/融合耗时 0.38174 s；处理后的观测年龄 0.37430 s，在当前 0.5 s 阈值内。
- 同一帧另有一个置信度 0.396185 的 `a car` 框覆盖右侧建筑，属误检；该 ROI 无量程内有效深度，输出 `insufficient_depth`，位置和距离 null。本次深度筛选排除了这个候选，但不能据此认为深度可以识别所有语义误检。

输入、原始响应、深度快照、标注和融合结果保存于本机 `/tmp/stage5-dino-live-18008/`，没有提交运行产物。当前证明静止目标单帧真实 DINO＋深度链路可运行；运动目标、多帧稳定性、目标身份和 Jev 控制仍未验证。


## 深度量程扩展至 20 m（2026-10-14）

共享 `x500_experiment` 深度 clip/far 从 10 改为 20 m；RGB、视场、分辨率、频率和近裁剪保持不变。Stage 5 显示与验收从同一 SDF 读取量程，融合本身已使用该配置。Stage 2 文档注明这是仿真任务配置扩展，不代表真实 Orbbec 测距能力；历史 10 m 记录保留。

实际重建 Stage 5 后，地面相机验证读到 17.611 m 有效深度，起飞期间读到 19.343 m，RGB/D 仍约 30.3 Hz。初次验证发现 Docker 内标定路径错误，已改为挂载工作区 `/lesson/stage2/models/x500_experiment/model.sdf`，修正后验证通过。

悬停时重新调用真实 DINO：单个红车框置信度 0.37915，前向表面深度 6.61108 m、斜距 6.84844 m，ROI 有效比例 100%，RGB/D 时间差 0；请求耗时 0.097 s，总耗时 0.133 s。PX4 为 Armed/Hold，无 failsafe。结果保存于 `/tmp/stage5-dino-depth20-air/`。本次没有出现先前建筑误检，不能据此认为量程修改解决了语义误检。

Python 语法、五项融合测试与 diff 检查通过。Stage 2 与 Stage 3 共用该模型，扩大深度量程后的这些阶段尚未重新实际验收。


## 粗体素场景分析（2026-10-14）

- 真实机载深度与本机 DINO 联合运行：体素 0.25 m、像素采样步长 8，共 4000 条射线（1647 条有限深度、2353 条超量程），局部得到 374 个占据体素、16487 个空闲体素。构建结束观测年龄约 0.393 s，总 client 耗时约 0.416 s；本机单次结果，不是性能基准。
- 原场景前进候选新增扫掠体素 72 空闲、24 未知，无占据，正确标 unknown（空闲比例 75%），没有因为中心方向无障碍就认定整机体积可通行。横移/上移未知比例更高。
- 此帧 DINO 只返回一个建筑误检框，框内约 99.5% 超量程及 0.5% 有限表面；新增证据会保留超量程与少量有限距离簇，不把这些信息删除。模型语义误检仍存在。
- 实际 Gazebo 中，在悬停无人机前方约 1.2 m 临时创建 0.3×0.3×0.6 m 实体障碍。深度体素最近表面约 1.073 m；前进候选扫掠体检测到 8 个占据体素，输出 blocked。验证后已删除临时障碍，未发出移动指令。记录保存在 `/tmp/stage5-voxel-obstacle-check.json`。
- 11 项测试通过：原有映射/失效测试，新增混合深度、超量程信息保留、射线前后空间、NaN 与正无穷区别、机体扫掠碰撞与低处地面不误挡。Python 语法通过。

本版仅交付深度几何表示与候选动作分析。没有验证真实树叶遮挡、多帧融合、实际执行这些动作或 Jev 选择；前向相机盲区与稀疏采样可能使动作不可确认或漏掉细障碍，结果不能等同于完整避障系统。


## Jev 异步 client 接入（2026-10-14）

参考 jev-drone tactics（提交 `974b47378c14c6dcf7d11f7c813fba0f5f4d8b6a`），调整为本仓库 DINO＋深度＋体素状态；保留 MIT 许可证。最初参考目录没有 `.env`，用户补充后已合并 TYPESAFE_API_KEY 到本地 stage5/.env，权限 0600、Git 忽略，未输出密钥。依赖通过 uv 锁定 TypeSafe SDK 0.7.4 与 socksio 1.0.0。

- 使用真实感知进行 dry-run 接线检查成功，状态包含语义候选与空间摘要，不含占据点数组或凭据。
- SDK 初始化发现当前 SOCKS 代理缺 socksio，补齐后成功。
- 真实 `--observe` 单轮调用 TypeSafe 成功：模型 jev-latest，行为 reacquire，confidence 0.86，risk 1.02，target_ambiguous 0.95，选择概率 reacquire 0.88/brake 0.12。请求耗时 0.8343 s，返回时观测年龄 1.3701 s（TTL 1.5 s 内），使用 2488 tokens。calls=1、attempts=1、errors=0。
- 结果仅保存为建议，未发布飞行命令。reacquire 是重新确认目标的意图，不意味着该轮成功跟随。
- 本次线上产物在 `/tmp/stage5-jev-live-ready/`，未提交。
- Python 语法与 16 项测试通过；新增测试覆盖预算/缓存、同场景失败恢复、过期响应、未知路径否决和缓存不刷新观测时间。

尚未接入飞行执行、目标身份及运动方向估计；没有验证连续 Jev 控制飞行、避障或 10 米后方跟随。一次真实调用不代表多轮任务已验收。


## Jev 驱动真实 PX4 后上方跟随（2026-10-14）

执行入口 `follow.py`，使用 PX4 system ID 6、MAVLink UDP 14545。运行前无人机已在 Hold 悬停；先发送50 Hz零速度流，然后切换 Offboard。DINO 初始提示词 `a red car. a red box.` 确认目标，当前红色外观/RGBD跟踪提供连续相对位置；PX4自身位置/姿态用于坐标变换。没有将车辆仿真位姿、模型 ID 分割或预设圆周位置传入控制器。

条件：车辆0.7 m/s，目标是车尾可见表面后方约8 m水平间距、上方2 m；速度上限1.2 m/s；Jev约0.5 Hz，TTL3 s，线程不阻塞控制心跳。unknown保留并按显式街区仿真限速策略处理，blocked与近处障碍否决。实际未验证绕行或复杂障碍飞行。

- 第一轮35秒：无人机实际移动约22.90 m，视觉测得目标斜距后段约8.0 m，Jev19次调用全部成功。产物 `/tmp/stage5-follow-first/`。第一轮真值记录启动较晚、车辆已停止，因此不把该记录当作运动跟随误差证据。
- 第二轮60秒与独立68秒真值记录同时启动：真值603个样本，车辆实际移动39.312 m。评测后半段水平距离中位数7.9187 m，车尾后方投影中位数7.7899 m，横向绝对偏差中位数1.4236 m，高于车尾中位数2.1575 m，最大后段水平距离误差0.11365 m。68秒记录包括启动与结束停车，后半段仅作粗略稳定段统计，不是多轮成功率。
- 第二轮Jev31次请求/31次成功/0错误，持续选择hold_course并实际使能跟随速度。证据 `/tmp/stage5-follow-validated/flight.json`、`jev_stats.json`、`evaluation.json`，均不提交。
- 跟随结束后停车，PX4回到Armed/Hold，无failsafe。
- 最终执行器SIGTERM实际中断验证通过：进入FOLLOW RUNNING并发出跟随速度后中断，保存run/flight文件，车辆停止，PX4回到Hold且无failsafe。证据 `/tmp/stage5-follow-stop-check/`。
- 20项测试与Python语法通过，包含相机FLU→机体FRD→NED符号/旋转、实际红色图像与深度跟踪、Jev暂停/陈旧/高风险/近障碍否决；进程锁避免同一实例并行控制。

当前完成PC单目标初版闭环，存在约1.42 m横向偏差，不能标为严格正后方对准；通用车辆/动物、复杂遮挡、完整一圈、多轮成功率、未知空间的实机安全性、板端迁移均未验收。后续可先改进方向估计和目标表面位置偏差，再增加绕障技能。

## API 故障处理与近距离跟随视角（2026-10-15）

用户失败记录 `/tmp/stage5-follow-w1zrgby0/` 实际为 attempts=11、errors=11、calls=0；日志里的 brake 来自错误回退，并非模型选择。旧版 fresh 只检查缓存年龄，错误响应也可能显示 true；历史未保存 HTTP 状态，无法追溯这 11 次请求的确切外部失败原因。同一状态随后请求真实 API 成功，不能据此认为历史服务问题已被定位。

- 修正为取得首个允许跟随的有效决策后才启动车辆；API 错误明确报告异常类型、HTTP 状态与类别，停车悬停并退出。终端保留 source/effective_maneuver，fresh 仅对实际 Jev 响应为真，入口不再追加重复的 subprocess traceback。
- 本地 HTTP 503 故障注入使用临时假凭据，仅替代决策服务；DINO、相机与 PX4 仍为实际链路。程序在车辆启动前退出 1，原因保存为 `TypeSafeInternalServerError HTTP=503 category=server`，没有进入 FOLLOW RUNNING。证据 `/tmp/stage5-follow-api-fault-fixed/`。不把这次人为 503 当作历史请求失败原因。
- 恢复真实 Jev 后完成 30 秒跟随，17 次请求全部成功，车辆运动约 19.56 m。独立 35 秒真值评测后半段水平距离中位数 7.941 m、后方投影 7.895 m、上方 2.133 m、横向绝对偏差 0.805 m；记录包括停车阶段，不是多轮成功率。证据 `/tmp/stage5-follow-fixed/`。
- GUI 默认切到机体后方 4 m、上方 2 m，读取 `/gui/currently_tracked` 确认 FOLLOW 状态，并实际截图确认；可用 `scene.py view-follow` 恢复该视角。
- 21 项测试通过，新增 HTTP 故障诊断回归测试；模型控制能力和复杂避障的既有限制保持不变。

## HTTP 451 原因定位与故障恢复（2026-10-15）

用户连续两次启动返回 451。使用不带凭据的 HTTP GET 对同一服务根地址对比：本机直连得到 Cloudflare HTTP 451，正文 `{"title":"Typesafe is not available in your region.","status":451}`；沿用本终端代理时得到根路径 404。随后同一失败状态经代理调用真实决策 API 成功。证据说明直连出口被服务地区策略拒绝；不能把 451 归为普通超时，也不能据此追溯早先缺状态码的 11 次失败。

增加 `.env` 的显式 `JEV_PROXY` 配置，并将本机已有可用代理配置到忽略的本地文件。清空大小写 HTTP/HTTPS/ALL_PROXY 环境后，实际完成 20 秒跟随，12 次真实 Jev 请求全部成功，视觉斜距约 8 m；证据 `/tmp/stage5-follow-ripow_5l/`。此项验证在独立发送线程改动之前完成。

临时错误增加指数退避、Retry-After、连续失败上限、总预算及恢复等待期限；451 等明确拒绝不盲目重试。记录有长度限制、脱敏后的服务端说明。故障注入发现同步车辆命令可能阻塞控制流，首次运行阶段测试因 PX4 Offboard 退出而失败；修正为独立 50 Hz 发送线程，主循环超过 300 ms 不更新时只发送零速度。

修正后的本地协议模拟测试在第 1、4 次请求返回 503，其余请求返回固定的跟随许可；DINO、相机、PX4 与车辆均为实际仿真链路。启动阶段保持车辆停止并重试，飞行中停车悬停，取得新鲜有效决策后继续，16 秒任务完成，10 次请求中 2 次人为错误。证据 `/tmp/stage5-follow-recovery-stream-fixed/`。这些固定许可只用于故障恢复测试，不作为真实 Jev 决策质量证据。

最终补充在故障分支立即清零主循环命令缓存，避免停车调用返回后重新发送之前速度的减速斜坡。重复相同 16 秒注入验证通过，错误期间所有保存的速度命令为零、恢复后继续运动；证据 `/tmp/stage5-follow-recovery-verified/`。

## Qwen 规划与 Jev 单阶段执行接线（2026-10-15）

新增 planner.py、mission.py 与 scene.py mission 入口。规划器读取真实 RGB 图片，调用配置的视觉模型，输出一个 stage；DINO text、水平距离、高度、持续时间从计划传递到跟随器。Jev 增加 stage_status 判断，只有新鲜的 completed 且累计有效跟随时间达到计划要求才标记成功；blocked/needs_replan 禁止移动，后者结束并保存现场。本版不实现多阶段推进、目标搜索或自动重新规划。

- 本地 HTTP 协议模拟了 Qwen 和 Jev 两个接口，真实相机、DINO、PX4 和车辆实际运行。模拟规划输出后方8.5 m、上方2.5 m、持续5秒，参数出现在 Jev 每次状态和 run.json 中，区别于原固定8 m/2 m。启动仅一次规划请求；6次 Jev 模拟响应，先 running、后 completed，实际累计有效跟随6.778秒后结束，车辆停止且 PX4回Hold。证据 `/tmp/stage5-mission-7er1qu5m/`。几何误差未同步做真值评测，不能将参数传递验证当作精度验收。
- 模拟服务还检查规划请求确实包含 PNG 图片。模型使用 protocol-test-vlm/protocol-test-jev，仅为接口与执行闭环测试，不代表真实模型的规划或阶段判定能力。
- 此轮接线时尚未配置 QWEN_BASE_URL 与 QWEN_MODEL，真实模型联合验收见下节。缺配置时明确退出、不调用飞行执行器，也不自动伪造计划。
- 30项测试通过，新增计划结构/执行边界拒绝、图片请求、缺配置失败，以及阶段完成时禁止运动等检查；Python语法与diff检查通过。

26 项测试通过，覆盖地区拒绝停止、重试退避及上限、错误说明脱敏、主循环阻塞时持续发送及零速度看门狗。最初一次故障注入还遇到目标不在可用视野而未进入决策阶段，重建标准初始场景后继续验证；通用目标重捕获仍未实现。

## 真实 Qwen VLM→DINO→Jev→PX4 单阶段验收（2026-10-15）

用户部署 Qwen3.6-35B-A3B 后，通过本地 `http://127.0.0.1:18080/v1/models` 确认 API 模型名 `qwen3.6-35b-a3b`；`/health` 返回 ready、vision_enabled=true、worker_pid=3086。本地忽略的 `.env` 已配置地址、模型名和120秒超时，未更改推理服务或板端文件。

先使用当前 RGB 图片进行真实 plan-only 调用成功，生成一个跟随 stage：DINO text 为 `a red car. a red box.`、后方8 m、上方2 m、持续15秒。证据 `/tmp/stage5-mission-4757h2wv/`。这只证明带图请求可用，不作为视觉理解准确率评测。

随后重建标准街区、相机验证通过并起飞悬停，执行：

```sh
# PC，仓库根目录；真实本地Qwen、DINO及远端Jev可用
.venv/bin/python stage5/scene.py mission --seconds 60 \
  --task '跟随红色车辆，在车尾后方8米、上方2米持续跟随60秒。'
```

- Qwen 启动时基于真实 RGB 与任务生成一个 stage，计划通过校验后执行；未复用外部计划，也未使用模拟 Qwen/Jev 服务。
- DINO 使用该计划的检测提示词；Jev共32次请求、32次成功、0错误。运行中持续返回 running/hold_course，最后返回 completed；累计有效跟随60.949秒，run.outcome=completed、stage_status=completed。没有用计时器单独宣布任务完成。
- 同时独立记录85秒仿真真值，751个样本，车辆行驶43.599 m。按相机/Gazebo仿真时间筛选运动后半段（67.156～97.616秒，267样本）：水平距离中位数7.9526 m、车尾后方投影7.8781 m、高于车尾2.1071 m、横向绝对偏差1.0609 m。真值只用于评测，不参与控制；该统计来自一次运行，不代表成功率或严格正后方精度。
- 结束后车辆停车，PX4 Armed/Hold、无failsafe。30项测试、Python语法与diff检查通过。
- 完整证据 `/tmp/stage5-mission-h_z2i3t7/`：planner_rgb.png、plan.json、planning.json、follow/flight.json、follow/run.json、follow/jev_stats.json、evaluation.json、demo_summary.json。运行产物不提交。

本次完成已在视野内红色车辆的单阶段真实分层demo；目标搜索、多阶段推进、自动重新规划、通用目标、复杂障碍和多轮稳定性仍未验收。

## Qwen验收闭环、预算与计划修订（2026-10-15）

任务入口现使用version=2多阶段运行器。Qwen初始规划、阶段验收和计划修订计入task budget；每个stage由Qwen分配Jev额度与本次timeout。done/failed/额度耗尽均提交Qwen，accept、redo、modify_stage、modify_plan统一处理。所有结束路径额外请求一次只读总结，最多30秒，失败输出本地事实摘要；总结不计入budget。运行器跨阶段保持同一飞行连接，车辆在验收期间继续运动。

### 板端服务恢复

本机18080连接被拒绝时，通过hdc-master与oh-houmo预检确认目标USB设备 `d62903433941363131137f1d31cb9c00`，HDC 3.2.0g、Linux 6.6.86 AArch64，Stage1路径、现有runtime库和模型目录可读。初次沙箱内HDC shell超时；用户明确授权提升权限后预检通过。板端uptime约9370秒，驱动xh2a_drv已加载，server PID3085、worker PID3086，与此前部署身份一致；/health为ready、vision_enabled=true。未发现重启证据，也未重启服务或加载/替换驱动。

实际故障是HDC fport列表为空。只恢复PC18080→板端8080映射后，PC健康检查和真实视觉请求恢复。该映射保留供demo使用。没有改动板端文件、模型、ROS服务或其他映射。

### 协议与故障验证

- 55项单元测试通过，覆盖四种验收操作、失败结果仍可accept、redo继承进度、改要求后新统计、已接受前缀不可覆盖、预算与deadline、迟到结果丢弃、最终总结不重试、控制硬故障、旧阶段决策不能移动、旧检测配置响应丢弃、空跟踪保留too_far证据。单元测试隔离进程锁，不与真实任务争用。
- 本地Qwen/Jev协议模拟配合真实相机、DINO与PX4完成五次stage执行，依次覆盖accept、redo、modify_stage、modify_plan、accept，产生4个计划revision；6次预算内Qwen调用和1次预算外总结。证据 `/tmp/stage5-agent-protocol-qq3bkh_j/`。模拟模型固定输出，不作为模型能力证据。
- 初次协议运行发现阶段切换复用旧Offboard心跳会误报模式丢失，已增加新的Hold与Offboard心跳确认；失败记录 `/tmp/stage5-agent-protocol-u8yu3cyc/` 保留。
- 初次真实多阶段运行中Qwen拒绝Jev的done并分配redo，最终因目标远离在120秒task deadline结束并生成总结，证据 `/tmp/stage5-agent-live-closed-loop/`。此轮发现“技能启用时间”被误当达标时长，现分离enabled_follow_s与valid_follow_s；后者仅累计感知估计水平目标点误差≤1m、垂直误差≤0.5m的时段，并提供全程、末段及最新误差供Qwen验收。
- 随后一轮模型闭环完成，但独立真值显示车辆行驶0m，只能作为静态目标联调，证据 `/tmp/stage5-agent-qualified-live/`。定位到单次gz topic发布可能未生效，车辆命令现等待插件订阅连接并重复发布；独立发送线程继续维持飞控心跳。
- 首次plan-only总结误返回accept，已将总结系统提示词与规划/验收提示词分离；只读总结不接受action。后续真实总结成功。

### 真实动态两阶段验收

标准场景重建、相机验证及起飞悬停后，在PC仓库根目录执行：

```sh
.venv/bin/python stage5/scene.py mission --budget 8 --timeout 180 --seconds 10 \
  --task '先观察确认当前红色车辆，再在车尾后方8米、上方2米持续跟随10秒。接近车辆的时间不算有效跟随，请为接近留出执行时间。' \
  --output /tmp/stage5-agent-moving-live
```

真实Qwen3.6-35B-A3B生成observe_target→follow_red_vehicle；两个阶段均由真实Jev报告done，再由Qwen分别accept。3次预算内Qwen请求（初始规划+两次验收）、1次预算外总结；Jev共20次请求，20次成功、0错误。观察阶段3.751秒、Jev1次；跟随阶段38.514秒、Jev19次，技能启用35.541秒，其中达标跟随11.991秒。执行部分约93.238秒，总结及结束处理后总进程约121.639秒，task outcome=completed。

独立150秒真值记录1326个样本，含规划、执行、两次验收及总结等待，车辆实际行驶75.174m。只筛选有效跟随对应的仿真时间区间，107个真值样本的水平距离中位数8.0455m、车尾后方投影7.9168m、高于车尾2.1427m、横向绝对偏差1.5706m；仍不能标为严格正后方对准。

两次Qwen验收分别耗时11.859秒与25.524秒，期间车辆分别行驶8.229m、17.800m；飞机端点位移分别0.049m、0.651m，后者包括跟随结束后的制动。证明验收期间没有暂停车辆，也没有继续跟随来掩盖等待成本。整段记录后半段包含大量悬停等待，不能用其整体距离中位数代替有效跟随精度。

最终车辆停止、PX4 Armed/Hold、无failsafe。证据 `/tmp/stage5-agent-moving-live/` 包含版本化计划、每次Qwen输入/输出与图片、两次stage报告/验收、请求账本、terminal/summary、完整flight、独立evaluation.json及demo_summary.json。运行产物不提交；真实模型仍可错误验收或重复重做，当前没有搜索/绕障技能，多轮成功率、复杂场景和板端控制迁移未验收。

### 恢复连接后的重复运行（失败）

再次恢复 PC18080→板端8080 转发后，健康检查为 ready、worker PID3086、视觉启用；55项单元测试再次通过。真实图像规划验证成功，证据 `/tmp/stage5-mission-4qp00x5c/`；该轮仅规划，不发送飞行动作。

重建场景、起飞后，以相同两阶段10秒任务、Qwen budget8、总timeout180秒运行，证据 `/tmp/stage5-mission-01vtpcu7/`。观察阶段完成并获验收；Qwen为首次跟随分配12次Jev调用、40秒，调用额度先耗尽，有效跟随累计0秒。Qwen拒绝验收并多次redo，但验收等待期间车辆继续运动，随后目标丢失，现有技能无法主动搜索恢复。最终在180秒总期限退出，仅接受观察阶段，Qwen执行调用7次、Jev调用17次；预算外总结调用1次遇到QwenHTTPError，使用本地事实总结。结束时PX4 Armed/Hold、无failsafe。此轮证明预算与失败闭环生效，同时说明模型资源分配和丢失后的重做策略仍不健壮，不能据此前单次成功宣称稳定完成任务。

### 执行成本提示改进

新增execution_guidance，将请求周期、实际速度上限、接近时间估计、剩余达标时长和预算公式传给Qwen；验收同时可见已返回模型请求耗时。系统提示明确接近与启动开销、丢失后无主动搜索能力、重复增加额度无法恢复目标。60项单元测试通过，包含缺测保守估算、按相对速度估算、无法追赶、继承进度、规划/验收数据传递与提示词边界；Python语法及diff空白检查通过。

真实Qwen视觉plan-only验证证据 `/tmp/stage5-mission-v155abmd/`：仍拆成观察→跟随，为10秒跟随分配budget31、timeout55秒，与缺测时成本建议一致，并完成只读总结。本轮没有执行飞行动作，只验证规划链路和预算输出；改进后的动态跟随成功率、丢失后的实际修订策略仍未复验。

## 精简报告＋完整 Qwen 文字历史重跑（2026-10-15）

真实任务：`观察确认红车，然后跟随10秒`，Qwen budget=10、总timeout=300s，真实本地 Qwen3.6-35B-A3B 与 Jev，车速0.7m/s。沿用运行中的场景与悬停无人机；准备阶段让车沿原环路驶回视野并停车（先2m/s、再0.7m/s调整到约7.1m相机前向距离），未传送/复位模型。没有启用 KV cache，没有改动板端推理服务。

代码使用精简阶段报告、完整 Qwen 文字输入/输出历史，每次仅最新一张 RGB。旧的实时检测、深度、体素与 Jev 逐次历史仅保留本地。原始上下文仍落在 `qwen-N-input.json`；实际发送文本看 `qwen-N-request.json`，API token 用量看 `qwen-N-metrics.json`。证据目录：`/tmp/stage5-report-history-20261015-01/`，板端新增日志只读保存为 `server-timings.log`，逐次 usage 与 profiler 数量核对一致，汇总在 `token-timing-report.json`。

| 请求 | 历史轮数 | 输入 token（含图片展开） | 输出 token | Prefill/s | Decode/s | HTTP/s |
|---|---:|---:|---:|---:|---:|---:|
| 初始规划 | 0 | 1778 | 383 | 2.175 | 15.101 | 18.022 |
| 首次验收 | 1 | 2689 | 38 | 3.492 | 1.509 | 5.668 |
| 第二次验收 | 2 | 3417 | 75 | 4.424 | 2.966 | 8.090 |
| 第三次验收 | 3 | 4202 | 91 | 5.590 | 4.452 | 10.796 |
| 第四次验收 | 4 | 4922 | 91 | 6.592 | 3.639 | 10.920 |
| 第五次验收 | 5 | 5661 | 99 | 7.622 | 4.791 | 13.093 |
| 第六次验收 | 6 | 6426 | 72 | 8.658 | 2.882 | 12.221 |
| 最终总结 | 7 | 6059 | 116 | 8.177 | 4.598 | 13.467 |

每次vision编码约0.28s；prefill/decode是对应阶段子项总和，不包含vision，不重复计入日志括号中的avg值。共35154输入token、965输出token；7次预算内Qwen执行请求＋1次额外总结。此前 `/tmp/stage5-webui-next` 首次验收为7168输入token、71输出token、HTTP14.128s，本次为2689/38、5.668s，输入减少约62.5%、耗时减少约59.9%。两轮现场、阶段结果、模型输出长度及图片数不同，不是严格固定输入的性能基准。保留完整文字历史仍使后续prefill增长；本次summary使用专用短系统提示，输入token不必大于上一轮验收。

任务结果 **failed / qwen_aborted**，总用时120.56s（执行106.45s＋总结/结束14.11s）。观察阶段done并获accept；跟随尝试5次均由Jev返回failed，有效跟随0s，启用跟随累计12.78s。Jev共13次真实请求，全部成功、0错误。最后Qwen返回abort，明确无主动搜索能力、目标丢失后重复追加额度无效。任务退出后PX4仍armed、mode4（Hold），遥测速度约0.014m/s；未降落。

剩余问题：Jev在接近过程中较早判failed；Qwen一次把真实`jev_failed`描述成“额度耗尽”，之后多次追加额度重做，不能据此认为失败推理已可靠。最终模型总结把观察＋跟随共6个attempt误称为6次跟随，实际只有5次跟随。该轮无独立真值距离评测，不能宣称跟随达标或以模型文字替代执行指标。

验证：Python/JavaScript语法、67项单元测试通过；真实相机、DINO/Jev、Qwen、PX4链路执行，WebUI状态接口可读。新增回归覆盖精简输入不泄入感知大JSON、完整文字历史不递归重复、保留Qwen原始输出、API token记录及只发送最新一张图。未做浏览器视觉验收。

## Qwen 3秒仿真窗口＋执行一致性验证（2026-10-15）

先用延迟模拟模型、真实Gazebo/PX4验证暂停协议，未调用付费模型、未执行飞行stage：证据 `/tmp/stage5-pause-smoke-mj419_c6/`，两次请求在相机sim_time分别推进3.000s、3.036s时发出暂停请求，均恢复并确认时钟继续推进，未触发PX4遥测陈旧故障。暂停命令异步确认有额外开销，不能把触发时间当成硬实时停表时间。

随后真实Qwen＋DINO＋Jev＋PX4运行任务：`观察确认红车，然后在车尾后方8米、上方2米有效跟随10秒`，seconds=10、Qwen budget=10、task timeout=300s、车速0.7m/s。沿用现场，无人机不复位，准备阶段仅让车辆沿现有环路驶回视野并调整到约7.2m前向距离。使用既有板端worker3086，未修改推理服务、模型或KV cache。

证据：`/tmp/stage5-paused-mission-20261015-01/`。结果 **completed**，两个stage各执行一次，无redo。规划返回duration_s=10；观察阶段done并获accept，跟随阶段23.89s墙钟后done，累计有效跟随11.458s、启用跟随21.446s。跟随误差估计：全程水平目标点误差中位数0.781m、末段0.375m、最新0.144m；垂直全程中位数0.0126m、末段0.0110m。Jev共13次真实请求（观察1、跟随12），全部成功、0错误。本轮未出现接近阶段过早failed；失败/完成证据拦截的异常路径由单元测试验证。

Qwen预算内3次＋额外总结1次：

| 请求 | 输入/输出token | HTTP/s | 触发暂停时的仿真推进/s |
|---|---:|---:|---:|
| 规划 | 1881 / 377 | 17.836 | 3.036 |
| 观察验收 | 2797 / 44 | 5.908 | 3.000 |
| 跟随验收 | 3542 / 86 | 8.656 | 3.100 |
| 总结 | 2998 / 98 | 8.533 | 3.100 |

四次暂停均在请求返回后恢复，未出现恢复失败或遥测故障。总墙钟70.11s，其中执行60.60s、最终总结/结束9.51s；总deadline未因暂停延长。完成后PX4 mode4（Hold）、仍armed，速度约0.036m/s，未降落；UI finalized=true、simulation_paused=false。

独立真值：Gazebo侧`follow_eval.py`记录120s，保存为同目录`truth.json`。其默认末半段摘要包含任务结束后的悬停，不代表有效跟随间距。按PC与Docker共享单调时钟，将真值时间戳匹配到flight.json里valid_follow_s增长的区间，得到103个样本（`qualified-truth.json`）：水平间距中位数8.062m，车尾后方投影7.928m，上方2.148m，横向绝对偏差中位数1.489m；水平间距范围7.990～8.901m。未把真值提供给感知、Qwen、Jev或控制器。仍存在约1.49m横向偏差，不宣称已验证精确车尾中心线跟随、通用目标或复杂绕障。

代码校验：78项单元测试、Python/JavaScript语法通过。新增覆盖3秒按仿真时间触发、短请求不暂停、暂停确认失败后的恢复所有权、模型异常恢复、主动暂停下的预期遥测停更、恢复后陈旧故障、明确10秒与60秒矛盾、modify_stage时长漂移、缺失败事实的failed和未达标done拦截。后续收紧（修改计划继续核对原任务时长、缺失净空不当作实际阻挡、总结恢复失败不得维持completed）仅做单元回归；真实成功轮次中对应输入为10秒且净空有效，不触发这些分支。未做浏览器视觉验收。

## 文档与代码整理（2026-10-15）

`Agent.md`改为按当前实现组织的统一介绍，包含职责、报告/完整文字历史、预算、3秒仿真窗口、代码入口、证据文件和单独的关键问题章节；历史实测仍保留本页，不将整理当作新的飞行验证。

整理前故障补记：`/tmp/stage5-webui-next/`为interrupted，43次Jev请求均成功、零请求错误、有效跟随0秒；观察阶段反复耗尽额度或超时，Qwen验收等待期间车辆远离，跟随阶段Jev多次failed，之后空stages终止尝试触发协议修复，最终总结HTTP失败回退本地。后续已新增abort、精简报告与3秒暂停策略，各自实测见上文。

代码整理抽出共用FatalControl，避免执行器和仿真控制依赖任务运行器模块；统一单写者JSON快照的原子替换；保留关闭资源前后的最终UI发布，删除重复赋值；灯箱拆分文件/事件读取、数据组装与HTTP响应，容忍事件流正在追加的半行，不再因此清空已有事件。整理仅涉及模块边界与证据/展示读写，不改变控制参数、任务协议或模型提示词。

验证：83项单元测试、Python/JavaScript语法通过；新增回归覆盖无效数据/替换失败保留旧证据、临时文件清理、半行事件不隐藏已有事件。未调用真实模型、未重新执行飞行，暂停/飞行效果仍以前述真实任务证据为准。

## 2026-10-18：Jev 双后端与环境配置（离线回归）

Stage 5 增加统一 HTTP 决策适配，TypeSafe 使用原生 `/v1/systemone`，JEV-9B vLLM 使用 `/v1/completions` 的 System 1 LoRA、token logprobs、head bias 和校准温度。Qwen 继续使用 Chat Completions。配置和服务前提统一见 [Hands-on](Hands-on.md#jev-决策-clientpc)。RGB/depth 固定本机 8189，不再从环境变量选择来源。

本轮 `.venv/bin/python -m unittest discover -s stage5/tests -q`：89 项通过，含 6 项新增适配测试；语法和 diff 检查通过。模拟响应验证 TypeSafe 原生请求、vLLM token 约束/概率还原/校准、三档风险期望、缺 logprobs 拒绝、HTTP 错误状态及固定 RGBD 来源。未连接真实 JEV-9B 服务、未调用 TypeSafe 付费 API、未启动仿真或飞行。没有生成新 run ID / ULog；历史 TypeSafe 飞行证据不作为新 HTTP 适配或 JEV-9B 的验收。下一步先验证同一输入下两后端的实际消息、延迟和决策输出，再独立验收低速任务；本地三档风险的 Choice 映射需单独评估，不能宣称与原生 Score 效果等价。

## vLLM JEV-9B 4090 实测（2026-10-18）

使用同模型、同四组构造样例；没有修改飞行链路。确认 vLLM 0.31.0 可加载 `Qwen3_5ForCausalLM` 和 `adapter_vllm` 的 `jev-decision`，真实 `/v1/completions` 返回受限候选token的logprobs，经发布方bias/温度恢复概率。`/health` HTTP200、`/v1/models`同时列出主干和适配器；只看到主干并不作为成功判据。服务保持在 `127.0.0.1:18081`，未接入TypeSafe SDK或Tactician。

模型来源 `autotrust/JEV-9B`，本地 `/mnt/disk1/wqy/JEV-9B`。身份：模型commit `7ac669b8fb476ba926491e3d1c39f9330d68dbed`；Python3.12.3、vLLM0.31.0、torch2.13.0+cu130、transformers5.17.0、Triton3.7.1，4090、BF16、无量化。环境 `/tmp/jev9b-venv`，数据盘缓存 `/mnt/disk1/wqy/jev9b-runtime/uv-cache`；国内镜像55.48秒完成包准备，不更改其他项目依赖。本轮只停止自己启动的Transformers/eager测试服务，不结束其他仿真。其他GPU进程在测量期间有变化，测末只见vLLM计算进程和远程桌面；因此与上一轮属于相同输入的本机实测对比，不是固定背景负载、独占GPU的严格性能实验。

共同参数：`max_model_len=4096`、`max_num_seqs=4`、`max_num_batched_tokens=2048`、`gpu_memory_utilization=0.80`、LoRA rank上限32、`logprobs_mode=processed_logprobs`，**关闭prefix caching**。实际使用Triton/FLA GDN prefill、FlashAttention2和Punica LoRA。分别验证eager与编译模式；编译模式保留默认torch.compile，仅把CUDA Graph捕获规模限为[1,2,4]，不能认为292～665token的prefill均命中图，也不能将全部收益单独归因于CUDA Graph。

编译模式启动到API就绪约95秒（14:34:40～14:36:15），torch.compile21.67秒、engine初始化80.83秒，测后进程显存20460MiB；首次请求581.554ms。eager首次请求见其summary。每种模式四情形×三次重复×串行/并发，共48轮、169次推理请求（含首请求），两种模式合计338次全部成功。预热统计不含各自首请求；单问题统计取串行组84次，各次输入token数与上一轮完全一致（292～665）。

| 指标 | 上轮Transformers基础实现 | vLLM eager | vLLM编译模式 |
| --- | --- | --- | --- |
| 单问题中位数 / P95 | 137.064 / 188.693ms | 97.178 / 134.913ms | 69.241 / 97.781ms |
| 跟随3问串行，中位数 / P95 | 412.923 / 416.928ms | 306.215 / 350.264ms | 229.870 / 290.306ms |
| 跟随3问并发，中位数 / P95 | 408.904 / 420.951ms | 251.058 / 254.977ms | 172.993 / 194.426ms |
| mission4问串行，中位数 / P95 | 527.964 / 556.811ms | 383.480 / 412.350ms | 272.614 / 311.411ms |
| mission4问并发，中位数 / P95 | 517.640 / 557.659ms | 308.119 / 329.891ms | 214.096 / 235.481ms |

编译模式相对上轮中位数：单问题1.98倍、三问并发2.36倍、四问并发2.42倍；不能把并发整轮结果直接当作现有串行调用时延。两后端还存在torch/transformers版本、融合内核与LoRA实现差异，不把以上作为单一优化的因果归因。

概率核对：每种vLLM模式与上轮对齐168个非首请求、768个概率值。eager平均绝对差0.001139、最大0.014085；编译模式平均0.001060、最大0.008045。两种模式各有1次top1变化，均为持续丢失mission的maneuver在reacquire与brake之间变化；两候选接近，按当前课程语义均保持位置。不能声称逐次输出完全一致或通用决策质量已验收。其余阶段状态等选项在本样本中一致；本轮仍为构造情形，不是真实传感器回放或飞行。

操作唯一入口：Hands-on的“本地JEV-9B：vLLM服务与时延测试”。证据位于 `artifacts/jev9b-benchmark/`：`vllm-eager-run-01/`、`vllm-compiled-run-01/`（各自summary、requests、cases）、`vllm-eager-server.log`、`vllm-compiled-server.log`、`vllm-eager-comparison.json`、`vllm-compiled-comparison.json`、`vllm-models.json`、`vllm-requirements-frozen.txt`。运行产物忽略Git。此次复用已实现的benchmark，没有修改控制代码；`git diff --check`通过。下一步如需用于真实Stage5，仍须明确SDK响应与score尺度映射、回放真实状态，再验收控制链路。

### 本地入口整理（2026-10-18）

按用户要求只维护vLLM：移除临时Transformers/PEFT服务代码及benchmark的后端切换分支，删除本次专用 `/tmp/jev9b-torch` 环境；操作文档统一为vLLM安装、启动、检查和测试。vLLM自身需要的torch/transformers等传递依赖保留。上表保留已测得的历史基础实现对比及其本地证据，不再提供该实现的代码、安装或运行流程。

构造样例取自 `follow.py:follow_questions` 的三问跟随和四问mission定义：稳定跟随、持续丢失、0.8m近障碍、valid_follow_s=11.458的10秒跟随完成；不是历史传感器录制。原基础实现比较证据仍在忽略目录 `artifacts/jev9b-benchmark/transformers-run-01/`，不随clone分发。

清理后验证：Python语法和 `git diff --check` 通过；纯vLLM入口以四情形各重复1次完成16轮、57次实际推理请求，全部成功，证据 `artifacts/jev9b-benchmark/vllm-only-smoke-01/`。vLLM服务保持在线。

### 无 AirSim Python SDK 的车队客户端（2026-10-18）

新增 `stage5/airsim/convoy_client.py`，复用现有 MessagePack RPC 传输，仅依赖 msgpack；配置读取 Stage5 runtime，保留四个车队方法及 status/start/stop/reset CLI。UE 工程内原 SDK 客户端不修改，无人机仍由 PX4 接管。

当前 Play 现场实际执行新入口 status，返回 ok=true、state=idle、三车 available=true 且速度均0，仿真时间1207.940秒。只读查询通过；未执行 start/stop/reset，未起飞或调用模型。Python 语法、CLI help、git diff --check 通过。操作入口见 Hands-on。

### AirSim SDK 与任务开发契约（2026-10-18）

用户确认后续以手动 Editor Play 代替 bin 启动，runtime 管健康就绪，task 同时编排起飞与开车，起飞完成后再进入 plan/Jev。目标接口及当前实现差距记录在 Agent 的“AirSim 迁移后的开发契约”；尚未实现完整 AirSim mission，不调用旧 Gazebo 红车执行器冒充迁移。

按要求在本仓库 `.venv`（Python3.12.13）手动安装 airsim1.8.1、pymavlink2.4.50。AirSim setup.py 构建时直接导入依赖，首次隔离构建缺numpy；预装 setuptools、numpy、msgpack-rpc-python、opencv-contrib-python、pymavlink，另补 backports.ssl-match-hostname 后，`uv pip install --python .venv/bin/python --no-build-isolation airsim==1.8.1` 成功。其旧传输依赖 msgpack-rpc-python0.4.1、msgpack-python0.5.6、tornado4.5.3，opencv-contrib-python5.0.0.93；与项目已有 msgpack 分发共享导入名，不能只看包元数据宣称使用了现代 msgpack，也不能假定未来 uv sync 会保留这次手动环境。

SDK导入及本机临时假RPC服务的真实TCP ping往返通过；现有轻量RPC所需packb/Unpacker编码自检通过。尝试当前场景41461时返回ECONNREFUSED，未验证此轮SDK与真实场景通信，未启动场景、解锁、起飞、开车或调用模型；不追查历史GPU问题。后续仍需单独固定SDK/现代msgpack依赖共存方式，再验收真实任务。

### 起飞前模型服务检查与显存现状（2026-10-18 16:50）

用户确认本轮“实机”指当前 AirSim＋PX4 仿真，并授权一次云端截图视觉测试。未解锁、未起飞、未启动车队。

- DINO `http://127.0.0.1:8000/health` 返回200/ready/cuda/fp32；用历史AirSim截图真实调用 `/detect` 成功，客户端耗时0.168秒，返回1个候选（white truck，score0.3778）。这仅验证检测接口和数据格式，未人工确认目标身份，不能作为识别正确率或实时跟踪验收。
- 云端 `.env` 的 qwen3.8-flash：一次无场景数据文本请求200，0.608秒；用户明确同意上传一张截图后，单次视觉请求200，1.273秒，返回场景描述，usage含222 image tokens。图像来自历史run的snapshot，非当前画面，未做真实plan/Jev闭环。自动审批最初拒绝截图上传，收到用户明确同意后才执行。
- Jev本机18080及旧配置18081的health/models均连接被拒绝，没有成功推理。`.env`当前DINO仍为18008、Jev为18081，本轮未擅自将Jev配置切到不可达服务。
- runtime status：旧run ee2ac54558224348bda7f1b41a911bd3的PX4/ROS仍运行，但RGBD及遥测失流约796秒，RPC连接拒绝，ready=false；旧phase=ready不代表当前链路可用。未重启Editor或回收实例。
- 当前4090总24564MiB，已用5803MiB、剩18281MiB；UE4Editor1123MiB、DINO3054MiB、远程桌面725MiB，当前无Jev推理进程。历史vLLM编译轮日志记录model loading16.93GiB、KV cache2.11GiB、实际CUDA graph pool0.04GiB；历史完整进程约20460MiB。说明BF16 JEV与当前图形/DINO负载存在显存容量冲突，但本轮没有拿到新的OOM退出日志，不能断言18080服务退出原因已确认。gpu_memory_utilization限制总执行器预算，不会压缩BF16权重。

证据：`artifacts/stage5-service-check/20261018-165015/summary.json`、`dino-response.json`、`qwen-vision.json`；历史显存分解见 `artifacts/jev9b-benchmark/vllm-compiled-server.log`。继续条件：先解决Jev服务共存与实际端口，恢复Play/HIL/新鲜RGBD，再完成AirSim任务执行后端迁移；当前不能宣布完整任务已可运行。

### TypeSafe API 与显式代理验收（2026-10-18 16:55）

用户修改的是相邻 `/home/wqy/uav-lesson/.env`，实际执行工作树 `/home/wqy/uav-lesson-stage5/.env` 仍为vLLM。本轮仅将用户更新的Jev后端、地址、模型及密钥同步到当前工作树，其他服务配置保留；密钥不输出、不写入报告。发现终端已有本机7890代理及监听后，为当前Jev显式设置 `JEV_PROXY=http://127.0.0.1:7890`，因为现有客户端session.trust_env=False，不继承终端代理。

通过当前项目 `.venv` 与实际 `DecisionClient`，使用 typesafe / jev-latest 调用一次 System One，单次请求包含 Choice/Score/Noul 三类问题。输入为“目标不可见、跟踪不可用”的合成事实，不上传图像或真实遥测。代理调用0.870秒成功，三类答案结构均可解析：brake概率1.0、risk1.01、target_ambiguous0.98，usage为486输入token/68输出token。验证了当前凭据、显式代理、API协议及现有统一客户端，不证明实际跟踪/控制闭环效果；未对直连作成败断言。

证据：`artifacts/stage5-service-check/typesafe-20261018-165535/summary.json`（无凭据）。未解锁、未起飞、未启动车队；本地18080/18081的JEV服务不再是本次所选后端的依赖。此前AirSim失流及任务后端尚待迁移的结论不因API成功而撤销。

### 再次 Vulkan 崩溃与 AirSim task 开发候选（2026-10-18）

用户重新Play后，本地16:58:49再次崩溃：UE日志记录VulkanMemory.cpp4765、VkResult=-4、VK_ERROR_DEVICE_LOST，栈为FFenceManager检查→VulkanViewport::Present→RenderThread，随后错误处理触发SIGSEGV0x3。Editor仍为PID1184786、带-norhithread，因此该启动参数未消除复现；与早期相机NaN创建崩溃不同。本轮没有本地JEV-9B进程，崩后GPU已用4594MiB；不能据崩后占用推断崩前峰值，不能将其归因为已经确证的显存OOM。未取得本轮内核Xid，确切触发原因仍未知，未改驱动或图形配置、未反复启动Editor。

PX4 listener显示arming_state1、armed_time0、takeoff_time0，未实际解锁或起飞。完整UE崩溃目录及demo.log归档在run `ee2ac54558224348bda7f1b41a911bd3/crash-20261018-165849/`。按run标签与容器ID核验后正常down，仅回收本项目旧PX4/ROS容器，其他模型/桌面服务保持原状；不把失流的仿真时间下listener日志年龄当墙钟新鲜度证据。

新增 `stage5/airsim/task.py`、`preflight.py`、`mission_runtime.py`、`perception.py`、`geometry.py`：runtime health委托task check；run读取固定prompt，模型与现场检查→静止相机相对外参测量→SDK/PX4起飞和独立车队启动→PX4实际悬停屏障→沿用TaskRunner计划/阶段/验收/总结。SDK后端源码getTakeoffZ固定-3米，因此本入口不提供虚假的可变起飞高度；悬停还要求新鲜PX4估计、速度<0.3m/s、误差≤0.4m、AUTO/LOITER(main4/sub3)连续2秒，并且SDK Future成功。请求接受不是屏障通过。

任务不调用Gazebo target_command或红色掩膜；候选控制使用DINO/RGBD与IoU关联。桥新增VehicleAttitude订阅，实际镜像消息MESSAGE_VERSION=0，对应无后缀话题；RGBD metadata附采集时刻附近（≤50ms）的PX4位置/姿态，缺失即不给可执行跟踪，不以最新位姿或仿真真值代替。相机静止相对测量及新元数据尚未在线验收。近似车顶是框上部光线/中值表面深度，不是车顶中心真值；运动方向不足时不授权跟随。默认仅开放Pickup rear_above，保持原1.2m/s水平/0.5m/s垂直、65米半径与NED Z(-6,-1)短任务限制，侧向/正上方入口明确拒绝。

崩溃后实际执行新runtime health：ready=false、transport_ready=false，在模型调用与飞行前退出，证据 `ee2ac54558224348bda7f1b41a911bd3/task-863889444f1842a58095cbdb17235300/health.json`。本地临时假RPC服务器验证安装SDK先同步ping、再从线程等待takeoffAsync Future的真实TCP往返成功；这不是对真实PX4起飞的验证。

最终117项单元测试通过，包含新任务的部分启动异常补偿、拒绝接管现有车队、未完成/未稳定/陈旧估计/非Loiter状态不通过悬停屏障、停止车队失败仍关闭飞行资源、外参参考系/四元数、固定任务参数与目标不被改写、丢失关联不自动换车等。Python语法、bash语法与git diff --check通过。离线报告、源码SHA256与测试输出在 `artifacts/stage5-airsim/task-development-20261018/`；源码沿用当前未提交工作树，PX4/ROS镜像身份及原配置见父run。实际环境Python3.12.13、AirSim1.8.1、pymavlink2.4.50、numpy2.5.3、Pillow13.0.0；手动SDK依赖尚未固定为uv sync交付。

未执行task run、未开车、未调用新任务的真实模型规划，也未重新调用云端截图。下一步先恢复稳定Editor/Play与HIL，up加载新桥，验证采集时刻PX4位姿和静止相机外参，再完成低速起飞/悬停/降落及Pickup短任务；不能以模型API就绪或117项静态/隔离回归宣布真实任务通过。唯一命令入口见Hands-on的“AirSim task开发候选”。

### 快速真实联调：起飞/开车通过，视野无Pickup而中止（2026-10-18）

按用户要求缩短空跑时间：新Editor/Play后自动接入up，run ID `8d4071fdb14c41d387456d230d689cdb`。早先一次由代理启动Editor时漏带桌面DISPLAY，回退llvmpipe/OpenGL并触发OpenGL3.h断言，记录在 `/tmp/stage5-editor-retry.log`；这是本轮启动环境错误，不归入Vulkan设备丢失。随后实际使用的Editor PID1409637由桌面启动、同工程与设置，用户确认Play。未修改驱动或渲染参数。

先后修正两项真实链路错误，均保留失败证据：

- `task-03d42519ce844d32b429c8ce32b37dcd` 在解锁前停于相机外参检查。原实现混用getMultirotorState的PX4估计朝向和物理相机姿态，测出约7.5°假安装旋转。改为落地时simGetVehiclePose与simGetCameraInfo的同一物理参考系相对测量，getMultirotorState只用于落地/静止检查；飞行时仍只使用采集时刻PX4估计。实际安装FRD为[0.46,0,0]、相对旋转单位阵，不再把AirSim局部Z或估计yaw偏差当外参。此前“由kinematics_estimated直接相减即可测得外参”的实现已撤回。
- `task-bb68d184ce9d4e0680d1ff6bd66c9c1a` SDK arm失败，PX4明确记录 `ignoring CMD with same SYS/COMP (6/1) ID`。当前设置VehicleSysID6是AirSim API发送端身份，与PX4飞控6/1冲突，不能把此字段当作PX4目标ID配置。未关闭预检；本轮改为独立PX4 commander正常解锁/起飞，AirSim继续提供动力学/传感器/车队RPC。SDK起飞候选撤回，SDK只保留可选诊断用途；若今后恢复SDK控制，应先修正发送端身份、Stop Play后重新安装设置并重验，不能直接沿用此配置。

实际任务 `task-afa4fa1406464523952d0a893fd7db51`：所有模型及当前链路/外参检查通过；PX4预检OK，MIS_TAKEOFF_ALT3m、MPC_TKO_SPEED0.5m/s。任务墙钟2.591秒派发takeoff、2.627秒车队start受理；20.674秒悬停屏障通过，PX4本地Z=-2.848m、速度约0.069m/s，随后进入Qwen任务。模型预算3、模型墙钟上限60秒；实际2次Qwen执行（plan/review）加1次总结，5次TypeSafe Jev全部成功、无错误，模型段约17.637秒。

实际前视图片为山坡树林，没有Pickup；DINO候选始终为空、perception_error为空。约8秒连续无可用跟踪后stage以tracking_unavailable结束，Qwen abort，任务failed/qwen_aborted；有效跟随、观察和跟随授权时间均0。没有真实跟随运动，不把“模型闭环已调用”写成“跟随通过”。车队在任务墙钟36.435秒停止，无人机Hold。

随后独立runtime land，实际确认新鲜遥测armed=false；车队stopped，Pickup约0.00048m/s、另两车0。本项目两个容器已正常down，未复位车辆或操作其他服务；通知用户Stop Play避免空跑。全轮未报告Vulkan新崩溃，但不能据短轮宣布稳定性修复。

ULog `px4-logs/2026-10-18/09_21_36.ulg` 已读取，沿用Stage3 analyse_ulog生成 `quick-flight.review.json`：解锁区间仿真时间1792315490.132～1792315557.153秒（包含起飞、Hold、等待与降落，不能当模型执行时间），末arming_state1；本地最高高度2.976m，最大水平半径0.093m。完整内环复盘数据在该JSON，不据本轮调PID。解除解锁与车队证据 `quick-task-recovery.json`；任务内有health/calibration/source-identity/bootstrap、Qwen输入输出、Jev报告、截图与ledger。

现场修复后AirSim专项14项回归通过（含命令派发后未到高度不能提前Hold中断爬升）；git diff --check通过。操作入口已更新为原生PX4起飞和60秒窗口。下一轮先调整出生朝向与车距，让Pickup进入前向视野及20米深度量程，再复验跟踪和10秒跟随；不新增主动搜索或继续长时间原地等目标。

### 初始180度转向与Jev原地环视（2026-10-18，离线验证）

用户明确要求一开始转180度，并将原地环视寻找加入决策。本轮只改这两项及其所需协议/验证，未启动Editor、未解锁/开车、未调用真实模型。

新增yaw_search.py：任务完成起飞悬停屏障后，在模型plan之前，以20°/s原地顺时针转180度；按PX4实测航向累计进度，跨±π正确展开，指令最多领先实测15度；确认到位并回到AUTO/LOITER才进入plan。初始转向单独限时30秒，异常仍按启动失败停止本任务车队并请求降落。此固定初始动作不是由模型猜测目标方向，也不使用车辆真值。

AirSim阶段向Jev新增scan_yaw可选动作，Qwen初始计划/修改必须保留；旧Gazebo阶段不开放该执行能力。目标不可见时Jev可选择原地偏航，单阶段累计最多360度、30秒主动扫描；进度来自实际航向，暂停/居中转向不冒充搜索覆盖。出现语义候选即停扫确认，图像或决策陈旧/错误、阶段不匹配或预算耗尽时不扫描，扫描期间平移指令为零。重进扫描可清除旧框关联以重新获取目标候选，没有通用重识别保证。reacquire仍为原地等待，不混称为环视。

为使环视实际有时间发生，用户此次新增能力对应AirSim开放scan_yaw阶段无跟踪门限由8秒改为35秒；原Gazebo/未开放扫描的阶段维持8秒。完成一圈仍无可执行跟踪、阶段额度或task总timeout到期均终结，不自动延长预算。原来“没有目标方向就把所有Jev响应都标不可用”的门控已调整为只禁止跟随平移，不阻止有效的保持/搜索决策。状态、提示词与执行成本提示同步报告搜索能力及剩余额度，飞行行记录增加yaw指令和扫描进度，bootstrap记录初始转向事件。

最终126项离线回归通过；新增验证静止反馈不会假报转完、航向跨界/暂停不虚增覆盖、初始半圈零平移并实际到位、Jev在无跟踪超过旧8秒时仍可选扫描、候选出现/图像或模型过期即停、单圈预算耗尽终结，以及Tactician能力/预算/新鲜度授权门控。Python语法与git diff --check通过。证据 `artifacts/stage5-airsim/yaw-search-development-20261018/` 含测试输出和源码SHA256。新增旋转与搜索均未实飞，不把上一轮不具搜索能力时的结果沿用为本轮通过；下次仍沿Hands-on同一task run入口做短轮。

### 初始朝向改为出生Yaw180度（2026-10-18）

按用户纠正，固定180度方向调整改为场景初始化：runtime.demo.json的spawn_yaw_deg由0改180，生成Vehicles.Drone1.Yaw=180。删除task中起飞后的固定半圈动作、initial_half_turn实现及对应专用测试，起飞悬停后直接进入plan；Jev的scan_yaw原地环视能力和边界保留。模型提示与操作入口同步，不再说“已在空中转过180度”。

安装器允许已知生成配置只改变Yaw，并保持原车辆名/XYZ校验、Play端口拒绝及备份；Yaw不同且混有未知配置修改时拒绝覆盖。126项回归通过，包含Yaw0→180安装/备份与拒绝未知修改，git diff --check通过。

当前只生成prepared/settings.json；检查时Editor的41461/4565仍占用，未覆盖场景实际settings，尚未安装生效、未新飞行。待用户Stop Play后执行install-settings，再Play/up；无需重启Editor。当前旧Play仍为原来的0度，不能据新源码配置宣称场景已转向。

### 2026-10-18：纠正环视策略职责

按用户架构纠正候选实现：Qwen先决定策略并以stage语言指示Jev，scan_yaw仅为可选偏航动作。撤回强制开放偏航、目标不可见必须扫描、候选即停、一圈/30秒及35秒无跟踪结束规则；AirSim阶段由Qwen分配的allocation及任务总timeout约束。保留图像/决策失效保持与可靠几何平移约束。此次为离线回归，不调用模型、不连接仿真，不代表环视策略或出生180度已实飞通过。

离线回归：`python -m unittest discover -s stage5/tests -q`，128项通过。覆盖Qwen可不开放偏航、Jev可在未找到目标时停止、候选出现不越过Jev自行停转、超过一圈/30秒仍遵循当前指示，以及图像/决策陈旧时保持。

### 2026-10-18：连续跟踪第3帧的JSON类型修复

用户运行`0e510222822f4ab69bff9f46ee346446/task-9439e319608e4fb892e143e4ff62126f`在Jev开始偏航后以TypeError结束；原证据只存异常类型，未保存调用栈，不能直接确认异常行。离线重现发现AirSim感知第3帧起的direction_confirmed产生numpy.bool，无法JSON序列化，可解释现场时序。改为原生bool，增加连续3帧感知输出JSON回归；旧代码回归失败，修复后全量129项通过、语法检查通过。同时将后续任务异常栈保存为runtime-error.txt/bootstrap-error.txt，便于定位后续错误。未连接场景、未重跑飞行，本轮修复仍待用户现场复验。

### 2026-10-18：寻找阶段与起飞视野调整，车辆驶离道路待定位

用户反馈上述run中Pickup启动后驶出桥/路边掉落，并非静止穿透地面。bootstrap与UE日志只确认正常start/stop，无自动复位记录；本项目未修改车辆物理、路线或转向。UE现有桥面修正记录仅验过起点静止落稳，不能代替行驶验收。当前RPC状态无位置/路线误差，缺少掉落前轨迹与具体路段，不能宣称已定位或修复；后续需在相同PX4/Play条件下复验车队路线，记录掉落路段及路线误差，再判断录制路线、转向控制或物理因素。

Qwen原提示示例为单跟随阶段，现场照抄示例。改为按当前证据规划：目标未可靠确认时先独立observe_target寻找确认再follow_vehicle，使用两阶段示例；已有确认可直接跟随。策略仍由Qwen以语言指示Jev，不在执行器写死环视流程。

起飞入口增加--takeoff-height（默认5米、范围2～5米，相对起飞点），实际MIS_TAKEOFF_ALT和悬停屏障均使用该参数；原固定3米撤回。任务的车顶上方2米保持原要求。Hands-on短任务预算更新为120秒/6次Qwen，起飞45秒，给寻找及验收留时间。129项离线测试和语法检查通过；未调用模型、未操作Editor，5米视野改善及新规划行为尚未现场验收。

### 2026-10-18：定位停车后皮卡失控，场景修复与分环节延迟

用户Play/up后，在runtime `4ee2d2e819c4460eac662926622706be`执行仅车辆复现：`convoy-probe-20261018-190318`保存30秒车辆RPC位姿/速度，无解锁、无模型调用。行驶期Pickup到约25米，按UE日志中的世界原点(68209,18550,13076)厘米及PickupConvoy3Route01.sav计算，最大三维路线偏差0.203535米。最初据stop回包误称停车正常，已撤回：后续parked.json显示装甲/白车速度为0，Pickup仍0.790316m/s，位置NED(-26.557,-15.674,12.925)m，已驶离道路掉落。stop回包不等于实际停车。

源码解释与现象一致：CarRouteManager.ReleaseControl销毁临时SpawnedController；PhysX WheeledVehicleMovementComponent.UpdateState在无本地Controller时复用ReplicatedState旧输入，后续ConvoyDriver.Park设置Raw输入无效。此外bReverseAsBrake=true会忽略直接RawBrakeInput。修复ConvoyDriver.Park：缺Controller时创建并持有本地AI Controller，使用直接刹车模式。场景源码及备份位于原工程；可分发补丁/UE回归在stage5/airsim/scene/convoy-parking.patch。未改录制路线、地图、车辆物理资产。

本机demoEditor Development编译成功（clang11、Linux x86_64），证据`artifacts/stage5-airsim/parking-development-20261018/build.log`和identity.json保存场景源码/原文件/模块SHA256。独立无渲染自动化Demo.Convoy.ParkingController通过，0失败、1带既有Pickup输入映射警告；检查stop后的本地Controller、直接制动与重复停车控制器复用。报告automation/index.json，退出码0。完整道路停车及5米任务仍待重新打开Editor后验收，不能用该无渲染回归替代。

本轮Editor于本地19:05:52再次VK_ERROR_DEVICE_LOST退出（未执行无人机飞行），后续编译/自动化不使用Vulkan。新的convoy_probe持有执行锁，停止后额外采样10秒，避免再次只看stop回包。

新增latency.jsonl及latency-summary.json（并输出LATENCY终端日志）：同机单调墙钟，记录取图、DINO、后处理、图像接收到感知、Jev请求/状态提交至结果/图像接收到结果、控制设定值提交、图像接收到控制提交、Qwen请求、车队启动RPC和起飞至悬停。统计count/min/median/P95/max，单位毫秒，Jev/Qwen失败标注success=false；不把sim_time相减当延迟，不声称测得曝光到执行器物理响应。写日志不自动调用模型。

旧任务0e510222822f4ab69bff9f46ee346446/task-9439e319608e4fb892e143e4ff62126f离线重建：Qwen HTTP 2452ms（1次），flight.json可见的2次Jev为852.393/300.050ms（中位576.222ms），车队start RPC约15.791ms，takeoff派发到hover约18080.508ms。旧任务没有DINO逐帧延迟，保持缺失。汇总已写其latency-summary.json；历史Jev去重仅覆盖采样到的调用。131项Python离线测试通过，包括并发延迟写入、单位/P95和历史缺测不推算；相关Python语法检查通过。

### 2026-10-18：车队改为悬停确认后启动

按用户要求撤回起飞与开车并行编排：task先正常起飞并通过现有实际高度/速度/Loiter悬停屏障，再请求车队start，随后进入Qwen任务；起飞异常/悬停超时不发车。车队启动失败仍沿用停止本任务车辆及请求降落的恢复。takeoff_to_hover延迟现在不包含车队start RPC等待。操作入口与架构说明同步。132项离线测试通过，覆盖悬停确认先于车队请求以及悬停失败不启动车队；未连接场景、未实飞。

### 2026-10-18：Editor停止Play时未响应，PX4未连接的accept取消修复

现场Editor PID1731077，本地19:38:07进入Play，19:38:22最后日志Disconnecting mavlink vehicle后冻结；41461已无监听，4565仍监听，PX4/ROS runtime停止，GPU约6017MiB/24564MiB、利用率0%，本轮日志无Vulkan错误。普通gdb被ptrace限制，sudo免密码不可用，未获取用户态完整栈；/proc线程等待显示主线程futex、连接线程1731967在inet_csk_accept。源码MavLinkMultirotorApi析构close后join连接线程，而MavLinkCom关闭未取消accept。仅对已核实正在退出且无PX4的监听做一次本地TCP连接并关闭，19:41:05现场立即恢复并完成BeginTearingDown/CleanupWorld；该操作不作为正常HIL探测方法。

项目内AirSim插件增加析构标记与accept进行中原子标记，析构时仅唤醒尚未完成的本机accept，线程检查取消后不继续连接；处理标记设置先于bind的竞态。补丁为stage5/airsim/scene/px4-stop-before-connect.patch，原头文件有.orig备份，demoEditor Linux Development编译成功（clang11/x86_64），44.17秒；源码/备份/插件模块SHA256保存于artifacts/stage5-airsim/editor-hang-20261018/identity.json。当前交互Editor仍须重开加载新模块。

真实隔离Editor黑盒回归：同LandscapeMap、PX4Multirotor、SteppableClock，以临时配置使用TCP4566、RPC41462，-nullrhi避免Vulkan，未运行PX4/传感器桥/模型。通过ExecCmds执行scene/verify_stop_without_px4.py，Play并等待2秒后请求Stop，返回编辑状态耗时0.047082秒，ok=true，测试进程正常退出码0。stop-without-px4.json、test-settings.json、stop-test-console.log及stop-test_2.log记录结果；首轮命令引号解析导致仅执行空py命令，已停止该独立测试进程，第二轮才是有效回归。此结果证明未接PX4的Stop路径恢复，不代表Vulkan故障已修复或完整飞行通过。现场恢复日志为scene-hang-recovered.log。

### 2026-10-18：提高寻找起飞高度及模型额度候选

按用户要求快速调整：task默认起飞8米（允许2～8米）、起飞超时60秒、Qwen执行预算10次、模型任务timeout180秒；Qwen提示给寻找阶段约60秒/36次Jev、跟随约75秒/41次Jev的分配参考，仍由Qwen按剩余时间决定。车队仍在悬停确认后启动，跟随要求的车顶上方2米不变。未增加自主升高动作；本轮通过入口起飞高度验证视野收益。AirSim垂直边界随实际起飞高度配置为起飞点Z减max(6,高度+2)至-1米，避免8米起飞被旧-6米门限拒绝；Gazebo保持原门限。133项离线测试通过，包含8米允许/超出-10米拒绝回归；语法检查通过，未实飞验证。


### 2026-10-18：Dashboard 聚焦 DINO 与 Jev 选择

按当前界面需求移除仿真／飞控状态卡，感知区仅显示DINO检测图与检测框，移除RGB切换、深度图与执行遥测仪表。Jev选择题从实际问题定义随judgment输出，每组横排，选中项绿灯并显示“已选择”，不影响执行policy。Qwen任务、阶段与事件保留。旧mission没有choice_groups时显示等待选择，需更新后的mission生成新快照。

11项tactics与3项preview测试通过；Python／JavaScript语法、前端模拟DOM渲染（两组选项及选择灯、无送检RGB回退）和diff检查通过。没有调用模型、启动任务或发送飞行动作；尚未进行真实浏览器视觉验收。

### 2026-10-18：环视中皮卡可见但无跟踪，补观察历史与检测审计

用户指出环视可能扫过皮卡。run9831d55c5bab4db38a57e097c9cfe7e2/task-1ea2732130024c26abe8adc32573aaa7保存的attempt-001/frame-2.png确有皮卡；只向本机8000 DINO重放同一原图，原提示a pickup truck.检出0.936938，框[85.39,178.84,164.89,207.37]，请求107ms。双提示a car. a pickup truck.分别返回pickup0.638056和car0.366703，证据dino-visible-pickup-replay.json。不据重放结果声称原请求当时返回相同结果；旧记录未保留逐帧审计，无法确认深度拒绝还是Jev采样漏过。该轮257次DINO、28次Jev均正常，264条控制采样无可用跟踪，260条选择scan_yaw/searching。

新增逐帧perception-audit.jsonl，包含原始候选、筛选/融合状态及是否具备采集位姿/跟踪；同时提供最近4秒、最多16帧候选历史给Jev（带age_s），供其决定是否停转复查，不自动改变环视策略、不用历史框授权平移。阶段切换清空历史，历史过期移除；日志写失败不改变控制。133项离线回归与语法检查通过，尚未实飞。

注意本轮task-input实际仍为Qwen budget3/timeout60秒，起飞8米/超时30秒，覆盖了新默认10/180/60；Qwen规划寻找60秒，任务总超时先到，未进入跟随或验收。后续采用Hands-on当前参数或直接省略旧覆盖参数使用默认值。

### 2026-10-18：明确超量程目标使用20米接近代理

按用户授权实现：too_far仅来自原深度融合的明确超量程证据；保留原始测量未知和distance_lower_bound_m=20，AirSim控制适配按框中心光线/采集位姿构造20米截断代理，明确标注control_proxy和distance_source。NaN、mostly_too_far、混合深度、不同步及缺位姿不套用代理。新增可选Jev基础动作approach_target（observe_target/follow_vehicle均可开放）：按当前语言指示选择，最大0.5m/s水平接近、保持高度，沿用路径阻挡/未知空间限速策略、风险及图像/决策时效约束；不逐步请求Qwen决定接近。

代理可以支持视觉“已找到”判断，但不积累运动方向历史、不推断车顶、不计算跟随误差或有效跟随时间；有效深度恢复后代理动作不再授权，切回实测/运动方向条件下的正常跟随。正常跟随入口也显式拒绝control_proxy。Qwen/Jev提示与操作契约同步；Gazebo未开放新动作。

136项离线测试通过：明确超量程投影且原测量保持未知、无效/混合/不同步拒绝代理、无需车辆运动方向可接近且垂直速度为零、代理不计跟随达标、实测恢复后旧代理决策失效，以及新动作的阶段权限/新鲜度/障碍约束。仅离线测试，无模型调用、无飞行验收。


Dashboard快照保持补充：DINO请求中保留上次检测图与框，Jev请求中、错误或网页连接中断保留上次选择和绿灯，新模型结果返回后替换；切换mission重置缓存。前端模拟验证覆盖等待／错误／断连保持、新选择替换及跨任务重置，JavaScript语法与diff检查通过，未调用模型或操作飞行。

### 2026-10-18：按Actor2新位置调整出生点

用户将Actor2移到UE厘米(68500,14500,13000)。无渲染Python命令进程只读加载已保存LandscapeMap并射线查询，中心命中Landscape地面Z12728.367cm（不是路面）；最近录制路线点约(67658.758,15224.396,13195.255)cm，水平距离11.10米。机体出生XY采用Actor2，Z取当地地面+30cm，保持Yaw180；按已有AirSim基准Pawn原点(68209.03125,18550.0078125,13076.107421875)cm换算NED为(2.9096875,-40.500078125,3.17740234375)m。未解锁机体先自然落稳，默认8米起飞后预计悬停在附近路面上方约3米多，实际高度/视野尚待复验。未修改地图/Actor2/道路/路线文件。

已更新runtime.demo.json并通过install-settings安装到项目Config/AirSim/settings.json，安装前端口空闲，原配置有备份。安装保护允许明确调整位置/朝向，但原配置须匹配本入口已知配置，未知改动仍拒绝覆盖；137项Python测试通过，包含位置变更备份/未知改动拒绝。检查与坐标换算保存在artifacts/stage5-airsim/spawn-development-20261018/inspection.json、conversion.json、inspection.log；命令进程不进入Play、不调用模型、不启动飞行。

### 2026-10-18：接近动作拒绝实测目标、寻找完成瞬时漏检阻塞修复

用户反馈新出生点已识别但迟迟不接近。run2c6da83fe8934fbeafc8456d682fefb4/task-6346024172f94f95bbdc23c128df4acd：find161条控制采样、3条可用跟踪、0条平移；其中75条Jev approach_target/done被stage done刹停，而当前帧短暂无跟踪导致运行器拒绝完成。follow247条采样、64条跟踪、仅16条平移，首次平移在该阶段36.110秒；27条接近选择被通用guard拒绝，13.9秒起明确存在estimated_surface/方向已确认/clearance20m，却仍被approach仅接受control_proxy的旧限制拒绝。因此不是完全不移动，也不能统称为障碍阻挡；旧guard文本过于笼统。

修复：approach_target接受已确认的超量程代理或实测目标，按实测距离接近到阶段水平间距（observe默认8米）后停止，仍保持高度/最高0.5m/s/不累计跟随达标；正常跟随仍须方向确认。细分接近动作未放行原因（无目标、阶段未授权、图像过期、感知错误、路径约束）。observe完成允许同阶段最近4秒内有可用跟踪的事实，不再因恰好当前帧漏检而反复卡住，但必须Jev主动done且判断有效，不自动触发完成。

用户指定三车目标细化至固定convoy_prompts.json：yellow pickup、grey-green六轮装甲车、white van；保留原任务ID和跟随参数，Qwen示例DINO提示改为a yellow pickup truck.，AirSim候选词支持van。139项离线测试通过（新增实测目标无方向也可接近、短时漏检仍可验收寻找的回归），语法检查通过。未启动仿真或调用模型，现场效果待复验。

### 2026-10-18：阶段结果绑定Jev实际判断帧

按用户纠正，撤回“最近4秒任一有效跟踪可用于完成”的临时实现。Jev队列提交时深拷贝请求状态，返回判断由本地附上该请求的decision_evidence：观测时间、采集接收时间、跟踪确认/快照、有效跟随累计时长及失败事实。执行器对done/failed只核对这份证据，仍检查阶段标签/判断时效；当前新帧仅影响后续控制有效性，不追溯否决或补齐旧判断。最近4秒历史仍可供Jev参考，但不单独作为运行器的完成凭据。

140项离线回归通过：判断帧已确认而当前帧漏检仍可完成、判断帧未确认而当前帧才出现不能补齐完成，以及提交后状态修改不改变绑定证据。三车prompt去掉six-wheeled，仅保留grey-green armored vehicle；未运行仿真/模型，尚待现场验证。

### 2026-10-18：DINO阈值与白车高分误报分析（未调参）

分析run02f89e1ffb5f4d4b95286b13a132a870/task-575583120d8f468f957d25ec50f66d0e。实际本机8000服务PID1319675，入口/home/wqy/GroundingDINO/scripts/serve.py，默认box_threshold0.35、text_threshold0.25；Stage5客户端不传这两个字段，因此使用服务默认，实际DINO_MIN_SCORE未配置，客户端二次过滤0.35。HF本机processing_grounding_dino.py以sigmoid后文本token最大值为box score，再以text_threshold解码短语；score并非完整“yellow pickup”身份正确概率。

attempt-002/frame-2.png主体实际为白色尾车，右侧另有装甲车。仅对已保存图像调用本机DINO：单提示a yellow pickup truck.把白车检为yellow pickup，score0.809350；三类同图提示产生white van0.657779（仅驾驶室）、armored0.692056（右车），同时对白车整车返回混合短语yellow pickup + armored0.498923。证据dino-white-van-false-positive-replay.json。提高阈值到0.5/0.7仍不能消除单提示高分误报；多类提示有帮助，但必须拒绝混合/歧义短语，并进一步验证目标身份。未修改阈值、检测服务或运行中的任务。

卡住不只是误报：attempt-001的270条控制采样中137条approach_target+stage done、94条approach target unavailable，仅2条有效跟踪（score约0.38、too_far）；Jev完成判断的绑定当前观测未确认时，执行器正确拒绝done，但Jev非running阶段状态又使动作归零，形成反复等待。attempt-002误报白车被当作已找到，Qwen图像验收指出当前只见白车并多次redo。需分别处理类别身份误报与Jev动作/阶段状态组合不一致，不能仅靠加budget或提高单一score门限归因。

### 2026-10-18：按用户要求提高候选接受阈值至0.5

本机.env与.env.example设置DINO_MIN_SCORE=0.5，AirSim任务/后端缺省同步0.5，task-input.json记录实际门限；DINO服务原始box0.35/text0.25保持不变，低于0.5的候选在Stage5拒绝，原始审计仍保留。Gazebo后端代码缺省0.35不变（显式.env覆盖仍生效）。

用户指出第一次approaching不一定是白车。重新核对同run attempt-001：首次approach_target控制采样在5.727秒，该判断绑定tracking_confirmed=false、tracking={}，实际actionable=false、guard_reason=approach target unavailable。没有该判断对应的精确RGB原图，不能认定其对象为白车；之前白车误报证据仅适用于attempt-002/frame-2.png，不能外推到首次接近。

### 2026-10-18：明确Jev实际输入并新增逐请求审计

核对调用链agent_runtime.step→Tactician.offer深拷贝/队列→DecisionClient.system_one：TypeSafe实际HTTP JSON仅含model/state/questions，无原始RGB、深度图片或Qwen完整聊天。state的mission为当前stage.goal，含当前stage完整契约、进度、plan_revision/stage_id/attempt、当前融合候选与tracking、局部运动候选、年龄/错误、最近4秒历史、execution_health。questions同时有maneuver Choice、risk Score、stage_reason Choice、stage_status Choice，并非模型自由生成行动文本。

首次接近请求的精确capture_received_monotonic=632349.664695255与perception-audit匹配：该帧raw_detections/detections/semantic_targets为空、tracking不可用，采集位姿存在。之前0.740080秒的历史候选score0.350705，框[2.257,71.590,637.564,357.713]几乎覆盖图像，mixed_depth，非明确too_far。原轮未记录完整HTTP正文，不能把执行器latest_jev_state或事后拼装内容声称为当次完整输入；Jev仍选approach的心理原因无法从结果证明。

为后续核对，在DecisionClient实际post前将完整请求body（不含headers/key）写到对应attempt/jev-request-NNNN.json；日志保存失败不影响控制。140项离线测试及语法检查通过，没有调用模型或启动场景。

### 2026-10-18：按用户指定形式提供记忆

不采用自动分类/关联式历史摘要。内部4秒窗口保留全部有效检测帧用于计数，Jev输入target_memory按顺序先给summary：“Recent 4s: 15 out of 16 frames had no accepted detection.”，再提供candidate_observations，仅保留至少一个accepted候选的原始观测，加age_s，不修改原始框/分数/深度状态。不发送空帧原始条目，也不添加single_frame/continuous等判断。accepted为当前阈值过滤后接受的候选，避免将低于0.5的被拒记录计为目标出现；过期、未来、其他阶段帧不计数。145项离线测试通过，包含15/16空帧强调、仅发送候选、拒绝候选不计出现、原始字段保留与输入不变；尚未现场复验。


Dashboard视觉整理：统一深色背景、卡片边框、字号与留白，任务标题强化层级，DINO与Jev采用响应式双栏，选择项保留绿色灯及文字标识，每组保持单行并支持横向滚动；窄屏改为上下排列。快照保持行为沿用。JavaScript语法和diff检查通过，本机8191返回的CSS与工作区文件一致。Firefox截图因Snap临时配置目录不可见未完成，尚未进行浏览器截图视觉验收。

### 2026-10-18：阈值0.7、环视关联和首次目标决策时机修复

用户反馈黄车出现但未接近，分析run9258210c159842c39be33805ea1dbf87/task-24abf9299a9b47e79fbdb183e609d866（实际阈值0.5）。14.49/14.81秒出现score0.798824/too_far跟踪，但当时Jev仍为前次reacquire。审计显示其后0.242/0.465/0.701秒连续检出0.8095/0.7956/0.8009、仍too_far、位姿存在，却tracking=false：环视导致前后框IoU为0，旧像素框关联拒绝；旧超时代码仅清空速度历史，未清previous框，形成持续卡死。15.85秒实际Jev请求已是mostly_too_far而无tracking，常规定时采样错过前面的可用窗口。

按用户要求，本机.env、示例、AirSim后端/任务默认DINO_MIN_SCORE改0.7；服务原始box0.35/text0.25不变。修复旋转关联：按RGB内参和两帧采集姿态/相机旋转外参投影旧框，再检查IoU；投影落到相机后方时拒绝关联。超过1秒未更新实际清除旧框/旧姿态和速度历史，允许按现有唯一候选规则重新选择。审计保存association_reference_box。该补偿不解决平移/复杂遮挡/通用身份识别。

AirSim有效tracking从无到有时，允许提前提交Jev，保留在途单请求和预算上限；持续可用时仍周期限频，不自动停止环视或授权接近。147项离线测试通过，新增旋转使旧框零IoU而补偿后可关联、相机后方投影拒绝、首次目标立即请求/持续目标不绕过限频。Python语法检查通过，未启动飞行或调用模型。

仍观察到黄车后续部分帧为mostly_too_far（如超量程比例99.87%但含少量有限表面）；本轮未改变混合/部分有限深度的代理适用规则，不能据此宣称整个接近链已经通过。

### 2026-10-18：按用户要求精简AirSim执行层门槛

用户明确不需要旧框像素关联，并要求提供充分信息、信任Jev判断。撤回IoU关联、旋转补偿及旧框锁定代码，删除候选分差0.1拒绝；当前帧中具有可用几何的候选取最高分，同时将全部候选/分数/选择规则、运动估计假设交给Jev。没有新增身份跟踪保证；tracking.confirmed保留兼容字段，并以geometry_available/confirmation_scope明确只是检测候选具备控制几何，身份由Jev/Qwen判断。

AirSim的Jev done/failed不再由执行器以跟踪状态或阈值重复驳回，直接交Qwen验收；真实有效跟随时长、误差和绑定判断帧的decision_evidence仍保存，不把模型done自动写成整个任务成功。去掉AirSim执行器重复risk<1.7/clearance数值判断；动作层的明确路径阻挡、阶段权限、指令时效、可用坐标、速度/范围及PX4失流处理保留。Gazebo原语义核对/控制基线不变。

hold_course在相对跟随几何尚未形成（无运动方向或仅有量程代理）时按当前目标水平接近、保持高度；不伪算车后方位置或累计有效跟随。approach水平上限从0.5提高到既有1.2m/s，避免低于约1m/s车速而必然落后；该上限不保证追赶成功。0.7候选阈值及用户指定的“空帧比例强调+仅候选原始记忆”保留。147项离线测试通过，覆盖当前帧选择不受旧框/分差拒绝、Jev阶段结果交Qwen、缺方向的跟随请求先接近且不累计达标；语法检查通过，无模型/飞行测试。


### 2026-10-18：AirSim 最大深度层策略

AirSim 现在信任检测框，按框内像素数最大的距离层确定目标距离；有限深度按相邻 0.5 m 桶合并成层、取所选层实测中位数，超量程作为独立正常距离层参与比较，选中后沿用 20 m 接近参考。无效像素不参与，平票取近层。Gazebo 保持原策略。

`depth_evidence` 向 Jev 提供全部层的距离、占比、深度图像素包围框，以及 `selected_layer`／`other_layers`。小层保留为潜在遮挡或背景，原深度点云路径检查仍保留；这些是距离层，并非物体分割，也不保证选中层确为车辆。当前只有接近／偏航等已实现动作，没有新增平移绕障技能。新建 task 生效，不需要重启 Editor。单元验证不代表树木遮挡场景实飞通过。

验证：150 项 Stage 5 单元测试通过，相关 Python 语法检查及 git diff --check 通过。未调用模型或启动飞行，实际树木遮挡与接近效果待验证。


### 2026-10-18：持续跟随与 Qwen 验收 overlap

默认三车英文 prompt 改为持续跟随，使用 `continuous=true`，取消固定 10 秒要求；`follow_vehicle` 持续模式无需 `duration_s`，有效跟随时间仍记录为诊断，由 Jev 根据任务与实时观测判断阶段结果。原有总 Qwen budget、分配的 Jev budget、阶段及总 timeout 保持有效，不能无限执行。旧的显式定时任务协议仍兼容。

跟随阶段已有实测目标位置与运动方向时，`approach_target` 与 `hold_course` 都驱动后上方相对目标控制及速度前馈；几何尚未形成时才仅水平接近。Jev 收到水平距离、运动方向是否可用、接近与完整跟随的区别；`unknown+cautious` 不等于已知阻挡。终端同时显示原始 maneuver、effective_maneuver 和 block_reason，区分模型主动刹车与执行器拦截。

AirSim 成功阶段 `done` 后立即形成验收快照，Qwen 请求期间继续读取实时感知并调用 Jev 执行上一阶段，忽略重复 done 的阶段切换请求但保留动作合法性检查；不循环重放旧速度。失败、Jev 预算耗尽或阶段超时停止 overlap，Qwen 返回后关闭旧阶段，再切换、重做或结束。验收继续调用消耗原阶段 Jev 额度及总时间，新增调用计入任务账本，轨迹和统计覆盖整个 continuation。阶段快照报告与 `attempt-*/review-continuation.json` 分别保留验收开始和继续执行结束的证据。新建 task 生效，不需要重启 Editor。

依据：run b11f3890ba9c468eb71aa19eb49bb532 / task-c660654b36ba4938aa9bdfe173bd2515，存在 Jev 主动 brake、接近被路径/目标检查改为 brake，以及接近动作停在间距边界三类现象。155 项单元测试通过，覆盖持续模式协议、接近接入完整跟随、验收期间使用实时观测、目标消失归零、失败/预算耗尽、异步验收继续服务及额外调用计账；语法与 diff 检查通过。未调用付费模型或启动新飞行，实际跟随和验收耗时改善待复验。


### 2026-10-18：持续跟随被固定高度边界终止

证据 run `db27671822e74865a67837d34650658c` / task `f99d3a35bd3443e68bcf6be3742f3b1f`：任务约82.92秒因 `control_fault: 飞行边界越界` 结束；终态PX4 NED Z=-10.0043029785m，触发任务入口按起飞8m配置的固定-10m上限。水平位置约(-17.43,-3.95)m，未触发65m水平限制。结束前有效跟随累计11.32秒，最新水平/垂直目标误差0.507/0.241m，不能归因为跟随丢失。固定出生点高度限制与随道路起伏的车顶相对高度目标不兼容，尚未修改边界策略。

本次仅改善错误证据：边界异常包含实际水平距离、Z和限制值；stage report保留FatalControl原因，避免仅写task_stopped。UE日志在22:24:01.325（UTC14:24）停车成功处中断，当前Editor进程已退出，无新增Saved/Crashes或/var/crash的UE报告；内核日志无读取权限。不能证明任务停止导致UE退出，也不能认定为已知Vulkan Xid109重现。


Qwen与阶段灯箱语义调整：请求期间增强紫色背景、边框及Q图标光亮，退出请求立即发布熄灯状态；ui.json新增qwen_stage_id绑定验收对象，前端验收高亮优先使用该字段（旧快照回退runtime.tag.stage_id），总结时不提前点亮下一阶段。移除Qwen活动标题中硬编码的仿真3秒说明。24项TaskRunner测试通过，新增回归覆盖stage one验收→redo→再次验收→accept→stage two；前端模拟验证序号指向下一阶段时仍锁定验收对象，accept后再推进。语法及diff检查通过，未运行真实模型／飞行。


### 2026-10-18：移除 AirSim 固定高度中止

按用户授权移除 Stage 5 AirSim 执行器相对本地 NED 原点的固定高度上下限；任务入口不再设置 AIRSIM_MIN_NED_Z，旧环境值亦不生效。-10m 原为起飞8m+2m余量，不是GNSS海拔或离地高度。PX4 本地位置估计继续用于控制，车顶相对高度目标不变；没有增加GNSS真值或地形真值输入。65m水平范围、遥测新鲜度、位置/姿态有限性、解锁及Offboard检查保留。Gazebo 的原高度边界不变。新建task生效，无需重启Editor。16项执行器单元测试通过，含跨旧高度上下限、水平范围和Gazebo回归；语法与diff检查通过。未复飞，UE退出问题未因本次修改得到验证或修复。


### 2026-10-18：用户确认的 AirSim 限制调整

Stage 5 AirSim 水平速度上限调整为3m/s、垂直1m/s（仍保留速度渐变）；移除65m固定水平范围，固定高度范围亦已移除。感知生成控制几何、执行器接收观测和Jev动作前置检查的新鲜度统一为1秒；Jev判断TTL仍为3秒。阶段结束发送零速度但不退出Offboard，新阶段若已在Offboard直接复用，否则直接请求Offboard，不再先请求Hold。每次stage仍更新感知generation，清空候选/运动估计/4秒记忆并重新检测，以防目标改变。任务最终结束与控制异常的Hold保留。总/阶段budget、timeout、15秒无可用决策时限及原速度估计阈值保持不变。Gazebo原速度、范围和模式切换行为不变。

新建task生效，无需重启Editor。实飞和UE退出原因未在本轮验证。

验证：160项Stage 5单元测试通过，包含跨旧65m范围、阶段保持Offboard并切换感知generation、0.85s观测仍可控制、水平速度达到3m/s及旧高度用例更新；语法和diff检查通过。


### 2026-10-18：遮挡恢复调度与验收对象绑定

AirSim Qwen 提示明确：临时遮挡或 Jev 当前阶段 tracking_lost 不等于整个任务不可恢复；结合剩余时间/预算和现场事实，恢复可行时通过 modify_plan 插入新的 observe_target（可用 scan_yaw、有几何时 approach_target），然后继续原 follow_vehicle。不是执行器写死的重试流程，也不强制恢复次数；资源不足或恢复确实不可行才 abort。

协议明确 redo 仅重做当前阶段并带 allocation，插入子任务使用 modify_plan+stages；恢复阶段 id 不能与已接受前缀冲突。验收输出新增 reviewed_stage_id、reviewed_attempt，必须绑定当前阶段与本轮报告；不允许将历史 find 成功串用成当前 follow 完成。Qwen 当前输入补充实时检测/跟踪可用性、丢失时长、近期无检出计数和实际搜索能力，不把结束时快照当当前状态。

证据：run e93b40bea55849bd80765d556b1e0bb5 / task-2cc43e514d4845c589667fda5bdc31bb。follow约17.30秒Jev报告tracking_lost，结束时lost_for_s约12.22秒、近期15/15帧无检测。Qwen第三次回复建议重新寻找再跟随，但错误输出redo+stages且缺allocation；协议修正后第四次回复复述旧find成功，被接受到failed follow，终态错误标completed、总结却说跟随失败。本轮修复协议对象与提示，不将这一历史结果计为成功。未调用真实模型或复飞。

验证：162项Stage 5测试通过；补充当前观测摘要后4项Qwen测试复验通过，语法及diff检查通过。新建task使用新协议，无需重启Editor；真实模型恢复调度仍待验证。


### 2026-10-18：action 优先调度

验收严格按action选择操作：accept/abort忽略stage、stages、allocation；redo只使用allocation，省略时复用当前阶段额度配置；modify_stage只使用stage；modify_plan只使用stages。其他多余字段删除并在ignored_fields及events.jsonl的qwen_ignored_fields事件中记录，不因此再调用Qwen。必要参数缺失、显式无效或未知action仍请求修正。redo重新获得一次配置额度，但历史消耗、总Qwen预算和总deadline不会重置；验收stage/attempt绑定仍保留。覆盖此前拒绝redo+stages的规定：现在执行redo并忽略stages。新建task生效。

验证：164项Stage 5测试通过，覆盖redo+stages忽略、复用原allocation且不额外修正/不退还消耗、多余无效参数忽略、必要参数缺失/显式无效拒绝；语法及diff检查通过。未调用真实模型或复飞。


### 2026-10-18：验收绑定字段漏填导致预算耗尽——修复

run 23ee81e21bd34e6d958872a8e56b0bf1 / task-1f8539b218f04a90a630c4729ff2bf84 在约31秒因budget_exhausted结束，Qwen总额度6次：1次规划+5次find验收；模型每次均accept但漏填reviewed_stage_id/attempt，被新增硬校验全部拒绝，follow未启动。这是新增协议要求引入的回归，不是模型拒绝继续、飞行越界或Jev失败。

修复：阶段和attempt由本地请求上下文绑定，模型无需复述；漏填不触发修正、不额外耗预算。模型显式返回错误阶段/attempt仍拒绝。保持action优先规则。覆盖此前“模型必须返回绑定字段”的说明。全套164项测试通过，新增完整plan→find→review→follow→review回归后20项AirSim任务测试通过，验证无绑定字段仍在3次预算内推进两阶段、不产生invalid_qwen_result；未调用真实模型或复飞。新建task生效，无需重启Editor。


### 2026-10-18：RPC 统一 41451 与打包前光照

当前 Stage 5 RPC 已统一为 AirSim 默认41451，runtime.demo.json、ConvoyClient默认端口、UE工程Config/AirSim/settings.json一致；历史run快照和旧验证记录保留原41461。外部settings已在原目录备份为settings.json.before-port-41451-20261018-230655，只改ApiServerPort。没有热切换当前进程，也没有停止现场任务。任务结束后执行runtime down，Stop Play再Play，再runtime up重建state；不要复用旧41461运行快照。30项AirSim相关单元测试、prepare生成及diff检查通过；新端口真实RPC/PX4链路尚未复验。

光照操作位置为PC UE4.27.2 Editor：Stop Play，打开LandscapeMap，Save All；检查静态/Stationary灯光及World Settings未开启Force No Precomputed Lighting，移动的车辆和无人机不改成Static。放置或调整Lightmass Importance Volume覆盖路线、飞行区域与附近环境，不无谓包住整个远景。Build下拉选择Lighting Quality=Preview，执行Build Lighting Only，先确认流程成功；完成后再选Production执行最终烘焙。查看Message Log的Lighting Results，处理错误及重要的UV/光照贴图警告，Save All保存地图及BuiltData，然后再打包。全动态照明项目不应盲目启用静态烘焙，先确认灯光Mobility。Linux本机已存在Engine/Binaries/Linux/UnrealLightmass；未实际启动烘焙，耗时/结果待现场确认。


### 2026-10-19：Linux 打包 OpenVR 链接错误

Linux Development 首次打包在 libopenvr_api.so 的 GLIBCXX_3.4.20 符号失败；当前UE使用自带clang11/libc++，SteamVR插件默认启用引入该预编译库，工程没有直接VR依赖。已备份外部demo.uproject并添加SteamVR Enabled=false，修改复现见stage5/airsim/scene/disable-steamvr.patch。未替换系统C++库，未添加忽略未解析符号的链接选项，未重建光照。增量Build.sh demo Linux Development已启动，新demo.response确认不再包含OpenVR/SteamVR；链接结果见后续补充。

Editor重启以加载插件变更；已有地图和BuiltData保留。Development游戏目标链接通过后仍需从File→Package Project→Linux重新执行完整cook/stage/package，构建成功不等于最终包验收。

补充验证：禁用SteamVR后的Build.sh demo Linux Development正常退出（exit 0），完成游戏目标链接及元数据；日志artifacts/stage5-airsim/packaging-openvr-20261019/build.log。不代表cook/stage/package或包内RPC任务已经通过。


### 2026-10-19：打包启动 settings 缺失与 RPC 空指针

包位于 `/mnt/disk1/wqy/demo3-scene/demo/Packages/LinuxNoEditor`。首次启动未包含 demo/Config/AirSim/settings.json，项目StartupModule未找到项目配置，转而使用~/Documents/AirSim/settings.json，创建其他项目的drone_1/SimpleFlight。addr2line对游戏构建debug文件解析0x350e63a落在ASimModeBase::getImageCapture的getVehicleSimApi(vehicle_name)->getImageCapture空指针路径；前三个CameraDirector/Teleport/Weather警告不是此次已定位的崩溃地址。插件不存在车辆的图像RPC缺少空值检查仍未修复，不应向错配场景调用车辆API。

已将当前41451/Drone1/PX4 settings复制至包内demo/Config/AirSim/settings.json，并安装LinuxNoEditor/run-stage5.sh（显式-settings）；维护模板为stage5/airsim/scene/run-stage5.sh。runtime允许同工程Packages/LinuxNoEditor/demo/Binaries/Linux/demo作为HIL监听持有者，保留车辆和完整settings核对。30项AirSim测试、语法与diff检查通过；打包真实启动/RPC/PX4闭环尚未复验。

PC先runtime down清理旧runtime，终端1启动：

```sh
/mnt/disk1/wqy/demo3-scene/demo/Packages/LinuxNoEditor/run-stage5.sh -log
```

终端2在仓库根目录执行`.venv/bin/python -m stage5.airsim.runtime up`。PX4版本场景在HIL等待期间可能没有RPC，不能用TCP探连4565。启动日志应显示Drone1及PX4/TCP4565；不要使用默认用户目录的drone_1配置。不再需要Editor Play；无需重新烘焙或重打包。以后重新打包需补齐外部settings及启动脚本，不假设普通JSON会被自动cook/stage。


### 2026-10-19：打包车队路线存档交付

run 474d8d4ea32c4753995f392bf99ee38c / task-5b2869f4247b4ec488578a853182a55a 起飞约27.96秒后正常悬停，随后simStartConvoy因包内缺Saved/SaveGames/PickupConvoy3Route01.sav失败，引发bootstrap异常恢复降落，未进入模型任务。外部包已补入原工程PickupConvoy3Route01.sav、ArmoredConvoy3Route01.sav、VanConvoy3Route01.sav，均校验一致；无需重新cook或烘焙。启动脚本增加三份路线文件存在且非空检查。之后打包交付必须同时带settings和三份路线，不能只复制二进制/pak。任务日志新增convoy_start_response，RuntimeError显示车队真实原因。20项AirSim任务测试、语法与diff检查通过，未实际启动新车队或起飞。

当前失败场景落地后先执行`.venv/bin/python -m stage5.airsim.convoy_client reset`清理fault并回到路线起点，确认重置完成后重跑task；如果重启场景，则down→run-stage5.sh→up正常初始化即可。


### 2026-10-19：隐藏路线调试绘制

CarRouteManager原bDrawRoute=true会在Development包绘制路线线段和起终点球。新增控制台变量demo.Convoy.DrawRoute默认0，统一关闭上述图形，保留路线存档、跟车及原有文字状态。显式排错可在Development控制台执行`demo.Convoy.DrawRoute 1`，关闭为0。修改模板stage5/airsim/scene/hide-route-debug.patch。此为C++显示逻辑变更，不需重新烘焙或cook地图；增量构建成功后更新游戏可执行文件，重启包生效。

验证：Linux Development游戏目标增量编译/链接通过，日志artifacts/stage5-airsim/hide-route-debug-20261019/build.log；已原子更新现有包可执行文件并备份旧版，当前进程不受替换影响，下次启动生效。尚未重启场景进行画面确认。


### 2026-10-19：Shipping 包交付核对

原Packages/LinuxNoEditor已生成demo-Linux-Shipping，构建receipt确认Shipping；同目录仍残留旧demo Development二进制，不删除。run-stage5.sh已改为优先Shipping、不存在才回退Development，runtime HIL进程核验支持两个可执行文件名。包内settings为41451/Drone1/PX4且与原工程一致，三份路线与源存档逐字节一致。Shipping SHA256=169bdb150359530406a7b44534135c42a41a2c38caa19d53cc2b251754364177。30项AirSim测试、语法和diff检查通过；未启动Shipping或验证其RPC/PX4闭环，不声称已完成任务验收。启动入口仍为包根run-stage5.sh，然后仓库runtime up，再task run。Shipping可能不输出与Development相同的日志；以up健康状态为准。


### 2026-10-19：Shipping 传输目录去残留

已按Manifest_NonUFSFiles_Linux.txt核对并将包内非交付文件移到工程TransferBackups/shipping-cleanup-20261019-115940，含旧Development程序及备份、旧PhysX PROFILE库、历史日志/崩溃及机器缓存；保留Shipping及清单依赖、pak、41451 settings、三份路线、启动脚本，以及当前Epic GameUserSettings。移出349729410字节，清理后包含SHA256SUMS共951181742字节（约907MiB）。清单18文件逐项SHA256校验通过，启动脚本语法通过，ldd无not found且PhysX依赖解析到包内。没有启动新实例或飞行。清理报告artifacts/stage5-airsim/shipping-cleanup-20261019/report.json。

传输只复制Packages/LinuxNoEditor整个目录，不带TransferBackups；接收方在包根目录执行`sha256sum -c SHA256SUMS`，使用`./run-stage5.sh`启动。运行后日志/缓存会重新生成，SHA256SUMS对应清理时交付快照，画质配置若被运行程序改写可能使该文件校验变化。重新打包会覆盖或混入文件，需要重新核对交付清单。


### 2026-10-19：Shipping Saved 路径修正

run cee9290285fc4f2da7947cc7cc2f9fa0/task-726726a44aaa41758726d2bb8d329d27 再次在车队启动时因No valid saved route失败。遗漏的是Shipping默认FApp::IsInstalled=true，FPaths::ProjectUserDir映射~/.config/Epic/demo/，SaveGames读该目录Saved，而非包内目录。此前仅核对包内文件和ldd不足以证明实际路线读取成功。

run-stage5.sh新增显式-UserDir="$package_root/demo/"，确保FPaths::ProjectSavedDir位于包内demo/Saved，与路线及Epic画质设置一致。未复制到或覆盖机器用户目录。已更新现有包脚本和SHA256SUMS；脚本语法及使用带空格路径的真实shell参数回归通过。必须关闭旧场景、down，重新run-stage5.sh并up，旧进程不会热切换存档路径。不需重新cook/烘焙或打包；实际Shipping路线启动仍未验收，不把参数回归当实飞通过。传输时以更新后的整个LinuxNoEditor为准。


### 2026-10-19：Shipping 统一 runtime 生命周期

用户接受Shipping包后，默认runtime改为自管场景＋PX4／ROS，原Editor手动模式仅显式兼容。新增scene_process.py校验包文件并以显式settings/UserDir启动，保存PID/启动时刻/二进制/参数身份，仅回收本轮进程；status将场景存活纳入ready，重复up复用健康同配置实例，down确认Disarmed后回收场景及容器。保留原land/force恢复入口及任务独立起飞逻辑。配置可用STAGE5_PACKAGE_DIR覆盖，不依赖原UE源码/uproject路径。根run-stage5.sh改为runtime入口，操作已收束到Hands-on最前面的当前默认章节。

静止实测run `d7b186cbf6414a719ac814e6669b67af`：由runtime自动启动Shipping PID3853714，HIL/RPC/PX4/ROS/RGBD均ready；PX4 armed=false、system6、nav4、XY/Z有效。重复up保留同run/PID；down移除本轮两个容器，确认scene alive=false。证据`startup.json`、`scene.json`、`scene.log`、`lifecycle-check.json`、`lifecycle-status.txt`／`lifecycle-up.txt`／`lifecycle-down.txt`、node-logs和px4-logs。Shipping SHA256 `169bdb150359530406a7b44534135c42a41a2c38caa19d53cc2b251754364177`，UE4.27.2 Linux；PX4镜像`sha256:70584c9eb1e928a9a621b939de0ebab0c91940860fb2f28848bd27f26a0432f4`，ROS镜像`sha256:c24f47188837b14600ec211bbc7d98f00c212aad7ff70cb4a446c02e8a1be894`；包文件身份和本轮实际配置均已保存。

此前工具环境无DISPLAY导致启动即退出，失败run `1f191882a8ee4d92bd7339c228520ab6`已通过down回收；使用用户桌面DISPLAY=:1及既有Xauthority路径后通过，未改系统显示配置/驱动。launch现给出缺少桌面环境的明确错误。173项单元测试通过，新增8项覆盖PID复用/外部程序不误杀、场景退出影响ready、缺路线提前拒绝、up幂等、部分启动失败可down、停止失败保留stopping状态与包路径迁移；语法和diff检查通过。未调用模型、未解锁、未行驶，未验证Shipping完整任务或长期GPU稳定性。现场验证结束已全部down。


### 2026-10-19：对齐 Stage 3 SUPER runtime 操作与恢复

对照stage3/super/airsim/runtime.py及README，Stage 5统一支持up/task/status/land/stop/down，stop=down --force；新增up --dry-run（无外部访问）、--image（本地PX4镜像覆盖）。runtime task同进程转发既有任务参数及退出码；根run-stage5.sh同样转发。任务/普通生命周期使用runtime.lock，独立recovery.lock允许任务占锁时status/land/stop/down --force执行，但不并发接管正在创建资源的up；直接旧task入口也受同一锁保护。新增land.request.json持久取消，覆盖预起飞、悬停、开车前及任务控制；人工降落后不再被freeze的Hold覆盖，任务Ctrl+C请求降落。保留Stage 5相机/车队/模型契约，不移植SUPER的规划器/雷达/板端选项。

182项测试通过，新增命令转发、dry-run无连接、任务/恢复锁互斥、取消先于降落、取消起飞和不覆盖Land、Ctrl+C恢复路径等回归；语法和diff检查通过。实际静止验收run `fbedcb3c10f14633b20f4878b45815bc`：统一up正常ready，持有任务锁时独立status正常、stop回收Shipping和两个本轮容器；确认场景不存活、取消标记存在，未影响其他容器。证据`startup.json`、`scene.json`、`super-alignment-check.json`、`super-aligned-status.txt`／`super-aligned-stop.txt`及原节点日志/ULog路径。Shipping与镜像身份同上一节，实际配置/源码身份保存在本轮identity/config快照。未调用付费模型、未解锁或开车；取消中的真实飞行及Shipping完整任务仍待后续用户验证。现场已停止。


### 2026-10-19：AirSim_Mountains 地址并入根环境配置

.env.example新增AIRSIM_MOUNTAINS，沿用AIRSIM_NH/TOWN05/RACE的ELF路径约定；Stage 5 runtime默认JSON改为binary_env=AIRSIM_MOUNTAINS，不再携带本机绝对包路径。config.load读取根.env并以Shell覆盖，相对环境路径以仓库根解析，支持空格/波浪线；不读取.env.example。按ELF推导包根和项目名，场景settings/UserDir/路线路径与该项目保持一致。STAGE5_PACKAGE_DIR保留兼容优先级，旧显式JSON package_dir仍可作无环境地址时的回退。当前本机.env仅添加此场景路径，不输出或修改其他私有键，不提交.env。手册当前入口已收束到这一配置方式。

仅做配置/脚本回归和dry-run，没有启动场景、容器、模型或飞行；原已验收包未修改。

验证：184项测试通过，新增根.env读取、Shell优先、相对及空格路径、示例不作为运行回退、无地址与误填sh报错；dry-run及当前包文件校验通过，语法与diff检查通过。


### 2026-10-19：本分支开发整理检查

本轮整理并提交当前分支，不同步主线、不merge/rebase或push。Hands-on收束到Shipping统一runtime和根.env；不交付重复历史归档及一次性benchmark/诊断脚本；Agent重写为当前职责/协议/限制，新增Development导航，README/路线图/AGENTS与当前状态对齐。保留历史证据和失败更正，不将用户接受场景包或静止ready改写为完整任务稳定性通过。

依赖整理：NumPy保留在阶段extra，不扩大基础依赖；Stage 5 extra补齐Pillow并离线更新uv.lock。示例模型路径使用占位地址，补充显式代理说明；没有修改实际.env密钥。未更改仿真控制策略或已接受场景包。

检查通过：184项Stage 5回归、Python语法、Shell语法、前端JavaScript语法、离线锁一致性及stage5安装计划dry-run、修改文档本地链接、diff空白；共用Stage 3 RPC以本机临时TCP验证自定义端点、分片响应、远端错误及默认41451契约。待提交内容无实际.env密钥值匹配、无超过1MiB文件，无artifacts/虚拟环境/模型/打包产物。检查摘要在忽略的artifacts/stage5-repository-cleanup-20261019/checks.json。未执行uv sync安装、启动真实场景/容器、调用模型、解锁或开车；未验证新机器环境、真实云端或完整飞行。

## 2026-10-19：Stage 5 重放到 Houmo 整理后的主线

解决 rebase 冲突，保留主线 Houmo 交付说明、板端服务端口与工具链环境变量、Stage 2/4 更新，以及双方历史验证记录。Stage 5 沿用已确认的根 `.env`、示例 vLLM 和 DINO 8000 配置，不再读取旧阶段 `.env`；保留双后端说明与 Stage 4/5 Pillow 依赖。

本次 184 项 Stage 5 离线测试、变更 Python/Shell/JavaScript 语法、离线锁一致性和 diff 空白检查通过（排除 `.patch` 必需的空行上下文前缀）。未修改本机 `.env`，未运行设备、模型、仿真或飞行；不产生新飞行 run ID/ULog，不作为 Houmo 与 Stage 5 联合链路验收。
