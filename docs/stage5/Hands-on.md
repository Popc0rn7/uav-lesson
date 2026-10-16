# Stage 5：街区移动目标与自主任务

本版提供 Jev 跟随任务的 Gazebo 场景与初版飞行闭环：100 × 100 m 地面、12 栋建筑、环形道路和红色方块车。车头有浅黄色标记，车辆沿半径 24 m 的环路逆时针行驶，速度 2 m/s，一圈约 75.4 秒。世界名为 `stage5_street`，模型名为 `target_car`。

目标车使用 Gazebo 内置 VelocityControl，关闭重力、保持车身中心高度 0.65 m，直接执行模型局部 +X 的线速度和绕 Z 的角速度；这是理想运动目标，不模拟轮胎、发动机或道路交通。建筑与地面具有碰撞几何，道路和标线只用于显示。当前接入 SUPER 同款 `x500_experiment`（Stage 2 原始 RGBD＋MID-360S 模型），由 PX4 控制；已接入 DINO、深度/体素及 Jev；跟随入口见文末。

架构、Qwen/Jev职责、报告与历史、灯箱、代码入口及[当前关键问题](Agent.md#9-当前仍存在的关键问题)见 [Agent介绍](Agent.md)；逐轮实测见 [Validation](Validation.md)。本页集中说明准备、运行和恢复操作。

## 教师准备（PC）

需要 Python 3、可访问的 Docker daemon，以及已下载的 Gazebo Harmonic 镜像。当前复用 Stage 2 镜像，无需 API key 或插件编译。课前获取镜像：

```sh
docker pull px4io/px4-sitl-gazebo:latest
docker run --rm --network none --entrypoint gz px4io/px4-sitl-gazebo:latest sim --versions
```

应输出 Gazebo Sim 8.x。维护者记录镜像 ID，`latest` 不保证后续版本不变；可用入口的 `--image` 指定已固定的本地镜像标签。GUI 需要 PC 图形桌面的 `DISPLAY`、有效 `XAUTHORITY` 和 X11 socket；检测到 `/dev/dri/renderD128` 时挂载它用于渲染。

RGB/D 页面复用 Stage 2 展示程序，在现有 `uav-computer-ros-humble:local` 镜像内运行，需要 NumPy 和 Pillow。教师按 `develop/docker/Dockerfile` 准备镜像，或用 `camera --camera-image <本地镜像>` 指定具备这两个依赖的镜像。入口检查依赖且不自动下载。Server 使用 Ogre2/EGL 无桌面渲染，本轮使用 Radeon 780M，其他显卡另行验证。

## 学员操作（PC，仓库根目录）

```sh
python3 stage5/scene.py up
python3 stage5/scene.py view
python3 stage5/scene.py camera
python3 stage5/scene.py verify-camera
```

预期：打开街区全景窗口，红车先停在无人机前方，执行 `target-start` 后沿环路行驶；验收脚本读取 12 秒仿真时间的位姿，输出速度、半径误差、高度误差和 `PASS`。需要验证行驶时，先启动车辆（会离开当前相机视场）；完整一圈验证：

```sh
python3 stage5/scene.py target-start
python3 stage5/scene.py verify --seconds 80
python3 stage5/scene.py target-reset
```

浏览器打开 `http://127.0.0.1:8190` 查看实时 RGB 和深度。标准机起始位置 `(24,-8)`，机头沿世界 +Y，相机水平朝前。等待 `docker logs uav-stage5-gazebo` 出现 `Ready for takeoff!` 后，在 PC 执行：

```sh
python3 stage5/scene.py takeoff
python3 stage5/scene.py verify-camera
```

预期：PX4 起飞至默认约 2.5 m 后悬停，两路相机持续输出；相机验收报告帧率、有效深度比例与 `PASS`。单独 takeoff 只保持原位；启动 follow 后才跟随车辆。降落命令为 `python3 stage5/scene.py land`。起飞被拒绝时检查日志，不使用强制解锁。

当前相机配置：RGB 640×360、水平视场约 86°、量程 0.15～100 m；深度 640×400、水平视场约 91°、量程 0.15～20 m，两路约 30 Hz。深度超量程为无效值，显示黑色。RGB 和深度视场、分辨率不同，后续不能直接照搬框的像素坐标；20 m 深度量程为 10 m 后方跟随保留斜距余量。没有云台。

GUI 默认从无人机机体后方 4 m、上方 2 m 跟随观察。手动调整后，可在 PC 执行 `python3 stage5/scene.py view-follow` 恢复跟随。GUI 可暂停/继续世界。结束或从起点重新开始：

```sh
python3 stage5/scene.py down
python3 stage5/scene.py up
python3 stage5/scene.py view
```

`down` 只删除带本入口标签的Stage 5 场景、Gazebo GUI 和相机页面容器，重复执行无害。`up` 拒绝覆盖已有同名实例。复位采用重建实例，避免插件倒退时钟语义差异。

## 接口与排障

- 独立资源：容器 `uav-stage5-gazebo` / `uav-stage5-gazebo-view` / `uav-stage5-camera-view`，`GZ_PARTITION=uav-stage5`，不使用 Stage 3 的容器和分区。
- 世界坐标为右手 XYZ，Z 向上，长度 m、角度 rad；移动由仿真时钟驱动，暂停世界也暂停车。
- `/stage5/target/cmd_vel` 为 `gz.msgs.Twist`，线速度在模型局部坐标中表达；当前初值 `(2,0,0)`、角速度 `(0,0,2/24)`，修改会改变运动路线。
- `/model/target_car/pose` 为 `gz.msgs.Pose_V`，每个 pose 自带仿真时间戳。它是验收真值，后续视觉跟随不能直接把它当成感知结果。
- PX4 instance 为 5，DDS 域 15、XRCE 端口 8895；Offboard MAVLink 本地/远端端口为 14585/14545，GCS 本地端口 18575（远端 QGC 默认 14550）。当前未启动 DDS Agent，不把客户端运行当作 DDS 链路已连接。
- 原始 RGB/D HTTP 端口 8189，页面端口 8190，均绑定 localhost；入口拒绝占用已有端口。
- 相机无数据：检查 Docker 内 `/tmp/stage5-camera.log` 与 `/tmp/stage5-gazebo.log`；暂停世界会停止新帧。
- Docker 权限错误：先按 PC Docker 配置修复访问权限；入口不自动提权。缺镜像：回教师准备流程，启动不自动下载。
- 没有画面：检查桌面环境变量与 `docker logs uav-stage5-gazebo-view`。无需 GUI 时仍可 `up` 与 `verify`。
- 车不动或验证超时：检查 `docker logs uav-stage5-gazebo`、GUI 是否暂停。GUI 初始化可能暂停 server，`view` 会恢复时钟；手动暂停后需点击继续。
- 同名容器已存在：检查旧实例日志，再用 `down` 清理本入口实例。

场景几何由本仓库 `stage5/generate_world.py` 原创生成，`up` 会重建 `stage5/street.sdf`。速度、环路半径及布局在生成器中定义；修改布局或轨迹后重新验收。运行需要一个 Gazebo server，查看时增加一个 GUI；本轮仅在现有 PC 上验证，未做资源性能基准。

插件来源与接口：[Gazebo Harmonic VelocityControl 源码](https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/velocity_control/VelocityControl.cc)（Apache-2.0）。本仓库调用镜像自带插件，没有复制上游源码或外部模型。

## 临时 DINO client（PC）

初始化默认把车停在 `(24,0,0.65)`，无人机落地位置 `(24,-8)`、朝 +Y；起飞后约 2.5 m 高度，水平相距 8 m，车体在前向画面内。为了取图期间不跑出视野，默认车辆静止。开始/停止行驶：

```sh
python3 stage5/scene.py target-start
python3 stage5/scene.py target-stop
python3 stage5/scene.py target-reset
```

`target-stop` 停在当前位置；`target-reset` 停车并回到 `(24,0)`，不移动无人机。完整恢复无人机与车辆初始位置使用 `down` → `up` → 等待 Ready for takeoff → `takeoff`。相机页面与 Gazebo GUI 按前述命令重开。车辆开始移动后，当前悬停无人机仍不会跟随。

配置位于 `stage5/.env`，不提交 Git。新 clone 在 PC 复制模板：

```sh
cp stage5/.env.example stage5/.env
```

配置键：`DINO_DETECT_URL`、`DINO_TEXT`、`DINO_TIMEOUT`（秒）、`STAGE5_RGB_URL`。当前模板检测地址为 `http://127.0.0.1:18008/detect`，提示词 `a person. a car.`，RGB 来自 `http://127.0.0.1:8189/rgb`。环境变量优先于文件，CLI 参数优先于两者；文件按 KEY=value 读取，不执行 shell。

检测服务尚未启动时，先验证临时链路：

```sh
python3 stage5/dino_client.py --mock
```

服务启动后直接调用：

```sh
python3 stage5/dino_client.py
# 也支持用户示例中的本地图像：
python3 stage5/dino_client.py --image demo/demo3.png
```

client 无需第三方 Python 包，获取真实机载 RGB 编码为 PNG，以 multipart 的 `image` 和 `text` 字段 POST `/detect`。它拒绝超过 2 秒的旧相机帧，HTTP 默认超时 60 秒，不自动重试。响应按 `width`、`height`、`detections[].label/score/box_xyxy` 解析，保留原始 `timing_ms`。空 detections 是有效结果。

每次调用创建独立 `/tmp/stage5-dino-<ID>/`，或用 `--output <新目录>` 指定，不覆盖已有目录。包含输入图像、`capture.json`（真实图像尺寸、帧号与仿真时间）、原始 `detection.json`、`timing.json`、可用浏览器打开的自包含 `annotated.svg`。标注使用响应声明的图像尺寸；输入图像缩放到该坐标空间，不能把响应框直接视为 RGB 原始像素坐标。Detect 为 HTTP 请求耗时，E2E 还包含取帧和编码。

mock 使用用户提供的 812×538 固定示例框，只验证响应处理，框不会对应实际车体；capture 明确记录 `response_source=mock`，标注显示 MOCK。没有真实识别或推理延迟证据。服务未启动会报连接拒绝，并保留已经取得的图像和 `error.txt`；需要修改地址时编辑 `.env`，不由此入口启动检测服务。

## 检测框配合深度图（PC）

机载取帧现在默认同时获取 RGB 和深度，在提交检测之前保存两路快照，不用检测完成后的新深度去配旧框。沿用前述 `dino_client.py` 命令，额外输出 `depth.f32`（小端 float32，按 step 分行）、`depth_capture.json`、`calibration.json` 和 `targets.json`；SVG 标签增加距离或 `no depth`。本地图像 `--image` 自动禁用深度融合，`--no-depth` 可仅运行原 RGB 检测。

`.env` 新增 `STAGE5_DEPTH_URL=http://127.0.0.1:8189/depth`、`RGBD_MAX_SKEW_S=0.05` 和 `RGBD_MAX_AGE_S=0.5`。两帧仿真时间差需不超过 50 ms，无法配对时失败并报错；检测结束后保留观测年龄，超过 0.5 秒则标记不可用于控制。当前接收桥只有最新帧，这里是有限时间差配对，尚无严格同步队列。

标定从当前 `stage2/models/x500_experiment/model.sdf` 读取，要求两路传感器共光心、同朝向。先把检测响应框恢复到 RGB 原图坐标，再利用焦距和主点映射到深度图。方形像素的针孔内参为 `fx=fy=width/(2*tan(hfov/2))`、`cx=width/2`、`cy=height/2`，不能直接按分辨率比例把 RGB 框复制到深度图。换成实机、有不同光心或畸变时另行标定。

算法对映射后框中心 50% 的区域取有效深度中位数，排除 NaN、Inf 和量程之外值，要求至少 20 个有效像素且比例不低于 25%。用中位绝对偏差检查明显的混合深度；这仍是框内表面估计，没有目标分割。Gazebo Ogre2 的深度是相机前向分量，见 [上游深度图生成源码](https://github.com/gazebosim/gz-rendering/blob/gz-rendering8/ogre2/src/Ogre2DepthCamera.cc)。

`targets.json` 使用 `camera_flu`：X 向前、Y 向左、Z 向上，单位米，原点在相机光心，尚未换算到机体或世界坐标。每个目标包含标签、置信度、深度 ROI、有效比例、深度中位数、离散程度、`position_m`、欧氏斜距 `range_m` 和向右为正的水平角。`estimated_surface` 是框中心方向上可见表面的估计，不能当作车体中心位置。`insufficient_depth`、`mixed_depth` 或 `unsynchronized` 时不输出位置和距离。

mock 的固定示例框可能落在天空或建筑上，通常会输出 `insufficient_depth`；即使有深度，`response_source=mock` 也使 `usable_for_control=false`。只有 HTTP 响应、有合格深度、配对时间差及观测年龄均通过时才标记可用；该字段是观测有效性，不是飞行动作或避障许可。没有自动触发无人机移动。

当前本机 18008 服务已完成一次真实 DINO＋深度验证，结果见 [Validation](Validation.md#真实-dino深度2026-10-14)。此前 mock 示例仅作为离线格式检查保留。

## 粗体素局部场景（PC）

同一个 `python3 stage5/dino_client.py` 现在额外输出 `voxel_scene.json` 和 `voxels.ply`。体素不依赖检测框，所有可见表面都参与占据分析，包括目标自身及框内遮挡物；DINO 无目标时仍生成空间观测。PLY 保存相机 FLU 坐标、米制的占据体素中心点，可用支持 PLY 的点云软件打开。

第一版使用标准 Python 单帧射线采样，默认像素步长 8、体素边长 0.25 m；局部范围为前方 0～8 m、左右各 4 m、上下各 4 m。`.env` 中 `VOXEL_SIZE_M` 与 `VOXEL_PIXEL_STRIDE` 可调整。有效深度端点标占据，端点之前的射线标空闲，遮挡后方和未采样空间保留未知；占据优先于空闲。理想 Gazebo 的正无穷按“量程内无表面”处理，射线最多标记到量程之前，不把 NaN、负无穷或零深度当空闲。

候选动作包括前进 1 m、左前/右前移动（前进 1 m、侧移 0.75 m）、左移/右移 1 m、上移 1 m；只供决策选择，没有自动执行。机体以半径 0.45 m 的球近似，中心在相机坐标 `(-0.186,0,-0.025)`，沿候选线段形成扫掠体，并保守加上体素半对角线。起始机体包络假设已占空间，从新增扫掠空间中排除；换机体或相机安装位置时需修改参数。

候选扫掠体中存在占据体素即 `blocked`；无占据但有未知体素即 `unknown`；全部采样为空闲才 `clear`。同时输出各类体素数和空闲比例，让 Jev 看到程度差异。前向相机无法完整观察近身侧面，横移/上移经常为 unknown，不能改写成可通行。

检测框新增 `depth_evidence`：0.5 m 深度直方图合并相邻分箱形成粗距离簇，保留有限深度、超量程和无效比例。多个显著距离簇或近处表面与超量程混合时不合成单一目标位置。全框主要为正无穷且没有有限表面时输出 `too_far` 和量程下界；有少量有限表面时输出 `mostly_too_far`，保留距离簇，目标距离仍未知。所有候选都保留给上层，位置不可用不等于语义信息不存在。

当前为稀疏采样的粗几何观测，不维护世界坐标地图，不保证捕获细树叶或亚体素障碍；clear 是本采样模型的判断。`fresh` 记录构建结束时的观测年龄，超过 `.env` 的阈值不可执行。尚未接入 Jev 或自动避障控制。

PC 检查：

```sh
python3 -m py_compile stage5/*.py
.venv/bin/python -m unittest discover -s stage5/tests -v
```

## Jev 决策 client（PC）

`stage5/tactics.py` 改编自本机 `~/airos/robopi/jev-drone/tactics.py`（参考提交 `974b47378c14c6dcf7d11f7c813fba0f5f4d8b6a`），保留单 worker、单槽队列、限频、调用预算、场景指纹缓存和异步结果读取。MIT 版权与许可随 `stage5/LICENSE.jev-drone` 保存。当前使用官方 TypeSafe SDK，和 Stage 3 OpenRouter Jev 示例为不同入口。

教师准备（PC，仓库根目录）：

```sh
uv sync --extra stage5
```

成功判据：`.venv` 能导入 `typesafe_sdk`。当前锁定 typesafe-sdk 0.7.4；socksio 1.0.0 支持本机 SOCKS 代理。依赖安装在课前进行，不复制 MuJoCo 或参考项目虚拟环境。

本机已把参考目录的 Jev 密钥合并到忽略的 `stage5/.env`，文件权限 0600，未覆盖 DINO 配置。新 clone 需自行配置 `TYPESAFE_API_KEY` 或 `JEV_API_KEY`；可设置 `TYPESAFE_BASE_URL`。不要把密钥写进任务、状态或结果文件。其他配置：`JEV_MODEL=jev-latest`、`JEV_CALL_HZ=1`、`JEV_CALL_BUDGET=10`、`JEV_TIMEOUT=10`、`JEV_STALE_AFTER_S=1.5`。单轮异常也计入预算，SDK 自动重试关闭。

只检查接线，不调用 Jev（PC）：

```sh
.venv/bin/python stage5/jev_client.py --observe --dry-run
```

真实单轮调用（PC，需已有 Stage 5 场景与本地 DINO 服务）：

```sh
.venv/bin/python stage5/jev_client.py --observe
```

最多三轮观测与建议：

```sh
.venv/bin/python stage5/jev_client.py --observe --count 3
```

调用会向 TypeSafe 发送语义与几何摘要，使用对应 API 额度。默认只进行一轮，不无限运行。`--mission` 可以指定任务，默认“在车辆后方保持 10 米水平距离”。结果保存于新的 `/tmp/stage5-jev-<ID>/`，或指定 `--output <新目录>`：每轮感知子目录、`jev-001.state.json`、`jev-001.judgment.json` 和调用 `stats.json`。不同任务或目标不会复用旧缓存；缓存也不会因重复观测刷新原决策的时间。

Jev 输入保留所有 DINO 候选、框内距离簇、超量程状态、体素动作检查结果与观测年龄，省略原始图像、逐点数组和任何密钥。当前没有车辆运动方向、身份追踪或历史丢失时长，不编造这些字段。三种问题为行为 Choice、风险 Score、目标歧义 Noul；候选行为保持参考项目的 hold_course、gap_left、gap_right、climb、brake、reacquire。

输出为建议，不调用 PX4。需要移动的行为另检查对应候选路径必须 clear，blocked/unknown 时 `effective_maneuver=brake`，保留 Jev 原始选择和否决原因。`reacquire` 仅表示继续观察意图，不是盲目移动许可。结果年龄从源观测开始计算，超过 TTL 则 stale/actionable=false；这个标记不是完整飞行验收。

没有 SDK 或代理依赖时执行教师准备命令；缺密钥时补本地 `.env`。模型或网络异常输出 error_type，不把 SDK 异常正文写入日志；本轮建议降级，进程返回非零，保留本地结果。已有过期观测不会重新调用 Jev，可用 `--observation <感知目录> --dry-run` 检查它的状态结构；正常在线运行请使用 `--observe`。

## Jev 驱动车尾后上方跟随（PC）

先完成教师依赖准备 `uv sync --extra stage5`、本地 DINO 服务及 Jev 密钥配置。场景已运行并悬停时，直接执行：

```sh
python3 stage5/scene.py follow --seconds 60 --target-speed 0.7 --jev-budget 40
```

也可直接运行 `.venv/bin/python stage5/follow.py`，默认 60 秒。输出目录为新的 `/tmp/stage5-follow-<ID>/`，可用 `--output <新目录>` 指定。需要从初始场景开始时（PC，仓库根目录）：

```sh
python3 stage5/scene.py down
python3 stage5/scene.py up
python3 stage5/scene.py verify-camera
# 等待 PX4 日志出现 Ready for takeoff!
python3 stage5/scene.py takeoff
python3 stage5/scene.py camera
python3 stage5/scene.py view
python3 stage5/scene.py follow --seconds 60 --target-speed 0.7 --jev-budget 40
```

成功判据：终端出现 `FOLLOW RUNNING`，Jev 选择 hold_course，PX4 进入 Offboard，无人机朝向红车并随其沿环路运动；机载 RGB 页面中的红车基本保持可见。结束或 Ctrl+C/SIGTERM 后自动停车，并切回 PX4 Hold。当前仅支持本机 Stage 5、PX4 instance 5 / system ID 6；MAVLink UDP 本地监听 14545、飞控发送端 14585，未使用 DDS 控制链路。全局本机锁 `/tmp/uav-stage5-follow.lock` 防止多个执行器争用同一实例。

启动时先等待首个允许跟随的有效 Jev 决策，期间车辆保持停止。超时、网络错误、408、429、5xx 会停车悬停并有限重试：默认退避 1、2 秒，连续失败 3 次退出；429 同时遵守服务端 Retry-After。重试使用新的观测，仍计入总请求预算；不沿用失效决策。运行中决策过期也停车等待，最多等待恢复 15 秒；只有新的有效跟随许可和新鲜目标观测才能重新启动车辆。401/403、402、451 等明确拒绝会直接结束，报告异常类型、HTTP 状态、类别与脱敏的服务端说明。

独立线程以 50 Hz 发送 Offboard 速度与朝向，避免停车命令或网络操作阻塞发送；主循环超过 300 ms 未更新指令时，发送线程自动改为零速度并保持朝向。整个进程停止时仍由 PX4 的 Offboard 断流策略接管，线程不替代飞控保护。

HTTP 451 若说明 `Typesafe is not available in your region.`，表示当前访问出口被服务拒绝。检查服务可用地区与现有网络配置；若本机已有可用代理，可在本地 `stage5/.env` 显式设置 `JEV_PROXY=http://127.0.0.1:7897`（端口以实际代理为准），不依赖启动终端是否导出代理变量。不配置时沿用 SDK 的终端代理设置，不自动切换网络出口。

日志 `source=jev` 且 `fresh=true` 才表示新鲜的模型响应；服务错误不会被显示为模型选择 brake。`jev_stats.json` 记录成功调用、尝试和失败次数，`run.json` 保存退出原因；不记录完整响应正文、请求头或凭据。

任务定义：距**车尾可见表面**后方约 8 m 水平间距，并高于该表面约 2 m；不是三维斜距 8 m。首版车速 0.7 m/s，控制速度上限 1.2 m/s。Jev 在该入口约 0.5 Hz 选择行为，位置/速度反馈与 Offboard 指令以约 50 Hz 执行；调用预算默认 40，超时 10 秒，决策 TTL 3 秒。DINO、几何分析和 Jev 均不阻塞控制心跳。

感知先调用 DINO（提示词 `a red car. a red box.`）确认当前红色方块目标与颜色区域重叠，再使用 RGB 红色外观规则（R>60、R>1.6G、R>1.6B）结合配对深度高频跟踪。约每 3 秒再调用 DINO；当前确认身份保持到本次进程结束。此规则只适用本街区红色方块，**不是通用车辆跟踪器**，也没有使用仿真物体 ID 分割。车辆运动方向由视觉位置历史估计，启动时暂用机头方向。

车辆可见表面相对位置从 camera FLU 转为 body FRD，再结合 PX4 的 LOCAL_POSITION_NED 与 ATTITUDE_QUATERNION 进入本地 NED。计算目标后方 8 m、上方 2 m 的位置，用目标速度前馈和位置误差反馈生成 NED 速度，限制速度及变化率；航向持续指向视觉目标。车辆 Gazebo 位姿、轨迹参数和真值不进入此控制计算。

本入口对未知空间采用显式的**当前街区仿真限速策略**：保留体素 unknown，但前向通道没有测到近处阻挡时，允许 hold_course 以限速跟随；Jev 状态中明确说明该策略。blocked 始终否决，前向机体高度带内障碍小于 1.5 m 或 Jev risk≥1.7 时停止。通用 advisory client 仍要求 clear，不改变其 unknown 否决。gap_left/gap_right/climb 尚未实现为执行技能，本版只跟随、暂停、原位重新观察；没有完整绕障验收。

视觉更新超过 0.7 秒则停止速度目标，连续丢失 4 秒、PX4 数据陈旧、Offboard 状态丢失、越界或 Jev 预算耗尽后结束任务并停车悬停。飞行范围限制为距接管点水平 65 m 内、本地 NED Z 在 -6～-1 m；不强制解锁或抢占其他实例。

输出：`flight.json` 每 0.2 秒记录 PX4 位姿、视觉目标、目标点、速度和 Jev 决策；`jev_stats.json` 记录调用数；`run.json` 记录执行条件/结束状态；latest 文件保留最近 RGB、DINO、体素与 Jev 输入。密钥不写入结果。

只读真值评测单独在另一个 PC 终端启动：

```sh
docker exec uav-stage5-gazebo python3 /scene/follow_eval.py --seconds 68 --output /tmp/stage5-follow-eval.json
```

评测与跟随同时开始，真值只用于计算车尾后方、横向和高度误差。它的后半段统计是粗略稳定段评估，并非固定速度的标准算法对照；完整一圈、多轮成功率、复杂遮挡和精确正后方仍需另行验收。

## Qwen 任务闭环：规划、Jev 执行、阶段验收与总结

前置条件（PC）：Stage 5 已启动并起飞悬停，红车位于初始视野；DINO、Jev 和 Qwen 服务可用。原 `scene.py follow` 保留直接跟随模式，新 `mission` 使用任务运行器统一管理模型调用、计划与飞行连接。

本地 `stage5/.env`（不提交）配置示例：

```dotenv
QWEN_BASE_URL=http://127.0.0.1:18080/v1
QWEN_MODEL=qwen3.6-35b-a3b
QWEN_API_KEY=
QWEN_TIMEOUT=120
QWEN_SUMMARY_TIMEOUT=30
```

Qwen 请求显式发送 `enable_thinking=false`，关闭思考模式，适用于规划、阶段验收、总结及独立 planner；切换服务时需确认该参数兼容。云端响应耗时与飞行任务效果需分别验证。

换服务时核对模型名与鉴权。BASE_URL会追加 `/chat/completions`；Qwen 默认直连，不继承终端的 HTTP(S)_PROXY/ALL_PROXY，也不使用 JEV_PROXY。只有显式设置 QWEN_PROXY 才走代理；云端直连时保持该项为空，并确认终端没有同名覆盖。Jev 仍可独立使用 JEV_PROXY。板端 HTTP 正常但 PC 连接被拒绝时，按 Stage 1 文档核对显式目标的 HDC 转发，不能据此重启模型。示例设备需 PC18080→RoboPi8080，`/health` 应 ready、vision_enabled=true。

在 **PC，仓库根目录** 运行：

```sh
uv run stage5/scene.py mission --budget 10 --timeout 300 --seconds 60 \
  --task '先观察确认当前红色车辆，再在车尾后方8米、上方2米持续跟随60秒。'
```

只看计划可加 `--plan-only`，此模式不连接飞行接口，结束后同样请求一次总结。`--seconds` 是未写明时长时给规划者的缺省跟随时长，不再充当整任务超时；task内显式写的时长由Qwen拆入阶段。`--timeout` 才是总墙钟时间。`--output <新目录>` 可指定证据目录。

需要重建独立试验初态时，按前文 down/up 重建本任务场景，再 verify-camera、takeoff、camera、view。运行器不会为 redo 或 modify 自动复位飞机/车辆；这些操作从当前现场继续。若现场仍满足悬停、视野和服务条件，也可直接重复mission；完整重建用于需要固定初态的独立试验。不要同时启动直接follow或另一个mission，本机同一进程锁会拒绝争用。

预期：Qwen返回 version=2 的多阶段计划；终端出现 `STAGE START <id> attempt=... allocation=...`。Jev只判断 running/done/failed；有效跟随时间只累计估计水平误差≤1m、垂直误差≤0.5m的时段，接近时间另计enabled_follow_s。阶段结束后无人机悬停；Qwen请求期间仿真和车辆持续运动，无人机保持悬停，不自动暂停世界。Qwen依据精简报告、完整文字历史和最新RGB返回 accept、redo、modify_stage、modify_plan 或 abort。全部阶段被accept才出现TASK completed；失败或耗尽额度出现TASK failed。Qwen可能接受Jev的失败结果，是否真达成任务仍需检查证据，不能仅看completed字样。

当前技能只有 observe_target（原地观察确认红色车辆）、follow_red_vehicle（红车后上方跟随）。没有主动转向搜索、换观察点、绕障或通用目标跟踪；验收等待期间车可能离开视野，此时停止移动并将空候选、丢失时长和超量程等观测交给模型，不能假定仍能跟随。已知飞行边界和失联保护始终由执行层约束。

### 额度与时间

- `--budget` 只限制执行阶段Qwen请求次数，初始规划、验收、非法输出修复和请求重试都计数。每次执行前至少保留一次验收机会；最后一次验收的accept仍有效。
- 每次stage的Jev budget与timeout由Qwen的allocation分配；Jev请求失败/重试照常计入，所有attempt的实际消耗累计保留。DINO不纳入额度管理。
- redo继承已有进度，同时明确申请新增额度；改变目标、距离、高度或完成标准后按新要求记录新进度，历史观测和消耗不删除。
- task timeout包含规划、执行、等待和验收，不因redo/modify重置。到点立即禁止执行，迟到结果作废。
- 所有结束路径只额外请求Qwen总结一次，不计入budget，最多30秒，不再发动作/改计划；失败或超时则输出本地事实摘要。账本分别列出执行调用和总结调用，总Qwen调用可能是budget+1。

### 证据与故障检查

产物默认 `/tmp/stage5-mission-<ID>/`：task.json、plan.json及plan-<revision>.json、events.jsonl、ledger.json、terminal.json、summary.json；每个attempt保存阶段定义、flight.json、report.json、review.json与带时间的关键画面。Qwen每次输入/输出和图片单独保存，不含配置密钥或HTTP头。独立Gazebo真值评测仍按前文执行，真值不得放入模型输入。

`--plan <plan.json>` 可跳过初始规划，阶段验收仍由Qwen进行；旧version=1计划会显式适配为version=2，`--jev-budget`仅控制该旧计划的缺省额度，不限制在线Qwen分配。

- 阶段额度耗尽是可验收结果，Qwen可以accept或新增额度继续；它不等同于任务失败。
- 目标不可见时检查report里的tracking、semantic_targets、检测年龄与截图。深度too_far/mixed_depth仍保留；没有位置估计时不会平移。
- task budget耗尽后不再执行新阶段；总timeout、飞控失联或越界则停止任务并总结。
- Qwen返回非法JSON或未支持技能时不会执行该输出；可反馈错误修复，但每次修复也消耗额度。
- 只读总结失败可检查summary.json的local_fallback与error_type；不会为了总结重试或恢复运动。

纯测试（PC）：`.venv/bin/python -m unittest discover -s stage5/tests -q`。真实相机/DINO/PX4的受控协议测试需已起飞悬停，在PC执行 `.venv/bin/python stage5/tests/integration_agent.py`；它会实际移动本任务无人机，Qwen/Jev接口均为明确的本地模拟，不能作为真实模型能力验收。协议与生命周期说明见 [Agent](Agent.md)，各轮结果见 [Validation](Validation.md)。

## 任务灯箱 WebUI（PC，只读）

在仓库根目录、PC 新终端执行（仅使用 Python 标准库）：

```bash
python3 stage5/webui.py --port 8191
```

浏览器打开 `http://127.0.0.1:8191`。可以先开页面，再在满足前述仿真、起飞悬停与模型服务前提后，从另一 PC 终端启动任务：

```bash
uv run stage5/scene.py mission \
  --task '观察确认红车，然后在车尾后方8米、上方2米跟随10秒' \
  --seconds 10 --budget 10 --timeout 300
```

默认省略 `--run`，灯箱自动跟随本工作树最新启动的 mission（包含默认临时目录与自定义 `--output`），再次运行无需重启灯箱。若要固定查看历史任务，启动时加 `--run <任务输出目录>`。`--output` 如指定，必须是尚不存在的新目录；未指定时 mission 自动创建临时目录。WebUI 本身不会创建任务目录、起飞或调用模型，不要为看页面而启动真实任务。

预期：顶部 Qwen 在规划、阶段验收、总结时亮起，保留最近返回的决策；流水线按 Qwen 的实际 stages 展示，支持计划版本、attempt 与验收状态。右侧灯箱区分感知、DINO 请求、跟踪、Jev 请求、决策有效性及控制活动，仪表显示观测年龄、行为、风险、额度、进度和 NED 速度。实时 RGB 与 DINO 检测快照可切换，框只叠加到当次送检画面；下方显示配对实时深度伪彩图，红近蓝远，黑色为无效值。当前不提供三维体素视图、历史回放或任务控制按钮。

状态每约 0.5 秒落盘、页面每约 0.7 秒刷新；图片最多约每秒输出一组，由感知线程处理。图片输出会有额外 CPU/磁盘开销，当前只验证了链路运行，尚无独立开销基准。任务新增 `ui.json`、`preview.json` 为可覆盖快照，原有证据仍保留。只有新版本 mission 会产生这些快照，旧日志不会自动变成实时画面。

页面显示“数据已陈旧”时先检查 mission 进程与输出目录，陈旧状态不会继续点亮工作灯；任务结束显示最终结果。相机空白时检查仿真相机与感知错误字段，DINO 标签页要等待首次检测成功。端口占用可更换 `--port`；Ctrl+C 仅停止 WebUI，不停止 mission。服务只监听 PC 的 `127.0.0.1`，不向局域网公开任务数据。

验证范围：HTTP页面、资源、状态/图像同任务与自动切换已检查；真实任务链路见Validation。完整浏览器视觉回归尚未完成，不能把HTTP检查等同于视觉验收。

Qwen 顶部增加最近一次已完成请求的输入/输出 token 与历史轮数（请求进行中继续显示上次完成值）。实际请求文本与 API 用量分别在 `qwen-N-request.json`、`qwen-N-metrics.json`；本地 `qwen-N-input.json` 是完整诊断上下文，不等于线上传输内容。精简报告与完整文字历史的真实重跑记录见 [Validation](Validation.md#精简报告完整-qwen-文字历史重跑2026-10-15)：首次验收5.668s，但跟随未达标，最终abort；不要把耗时改善当作飞行任务验收通过。

mission 在 Qwen 规划、验收、总结及重试期间保持仿真连续运行，不再使用3秒后暂停策略。无人机等待时保持悬停，车辆继续运动，目标可能离开视野；模型提示词与额度建议已同步该事实。总任务超时仍按墙钟计时。云端 Qwen 已关闭思考，连续仿真的完整飞行效果仍待验收。

以下恢复命令仅用于历史版本或外部操作遗留的暂停；先确认没有正在运行的 mission：

```bash
docker exec uav-stage5-gazebo gz service \
  -s /world/stage5_street/control --reqtype gz.msgs.WorldControl \
  --reptype gz.msgs.Boolean --timeout 2000 --req 'pause: false'
```

成功响应包含 `data: true`，随后相机 sim_time 应重新增长。仅适用于当前 Stage 5 世界，不对其他场景发送控制。

历史3秒等待策略曾完成一次真实任务验证（不代表当前连续仿真配置通过）：观察＋跟随10秒两个阶段一次通过，累计有效跟随11.458s；真值达标区间水平8.062m、上方2.148m，仍有1.489m横向偏差。详情见 [Validation](Validation.md#qwen-3秒仿真窗口执行一致性验证2026-10-15)。暂停策略和协议测试通过不等于实机或通用跟踪能力验收。

灯箱自动跟随使用 `/tmp/uav-stage5-<工作树标识>-latest.json`，只记录任务目录和工作树路径，不含凭据。mission 启动时更新索引；灯箱刷新时重新选择，切换会清除旧画面。升级前已运行的默认 `/tmp/stage5-mission-*` 任务可自动发现；历史自定义目录仍可用 `--run` 固定查看。页面 `RUN` 行会标记“自动跟随”。
