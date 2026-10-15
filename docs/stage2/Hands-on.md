# Stage 2：标准机仿真、飞行与传感器展示

目标：在同一台 Linux PC 上启动 PX4 SITL + Gazebo，通过 QGroundControl（QGC）完成起飞、悬停、改变高度、降落与重新开始。链路为 **PC QGC ↔ MAVLink UDP ↔ Docker 内 PX4 ↔ Gazebo**；飞行练习在 PC 完成，不使用 RoboPi/HDC；点云与体素展示使用另一个 ROS Humble Docker。

课程标准机为 **`x500_experiment`：X500＋RGBD＋MID-360S 规则扫描近似**，后续阶段继续使用该机型。用户已确认四图展示可用；改装后的完整飞行和新 PC 复现待验收。实测与历史诊断见 [Validation](Validation.md)，雷达规格和拟合边界见 [MID-360S](MID-360S.md)。

## 1. 教师课前准备（PC）

### 环境与版本

优先复用教师已有的 `px4io/px4-sitl-gazebo`。它是包含预编译 PX4、Gazebo Harmonic 与模型的运行镜像，见 [PX4 预编译包说明](https://docs.px4.io/main/en/simulation/px4_sitl_prebuilt_packages)。本节不执行 `docker build`、不编译 PX4、不挂载源码，保留镜像自带入口。

| 项目 | 课程基线（换 PC/镜像需复验） |
| --- | --- |
| PC | Linux x86_64、桌面会话，Docker Engine 使用 host 网络；本机 Fedora，Ubuntu 安装命令仅为教师参考 |
| 镜像 | 教师本地 `px4io/px4-sitl-gazebo`，实际 tag、摘要与内置版本课前记录 |
| 飞行器/场景 | `gz_x500_experiment`，`baylands` 户外场景，单实例，显示 Gazebo 三维窗口 |
| QGC | [v4.4.3 发布页](https://github.com/mavlink/qgroundcontrol/releases/tag/v4.4.3)的 Linux AppImage，和现有镜像的兼容性待实测 |
| 资源 | 教师建议起点：4 核 CPU、16 GB RAM；磁盘占用与实时率待测 |

### 选择已有镜像并固定本次使用版本

**PC** 执行，前置条件是 `docker info` 正常：

```sh
docker image ls px4io/px4-sitl-gazebo
# 将下面的 latest 替换为本地已有 tag；不要为了本练习更新已有镜像。
stage2_image_ref=px4io/px4-sitl-gazebo:latest
docker image inspect "$stage2_image_ref" \
  --format '{{.Id}} {{.Os}}/{{.Architecture}} {{json .RepoDigests}}'
export STAGE2_IMAGE=$(docker image inspect "$stage2_image_ref" --format '{{.Id}}')
```

成功判据：inspect 输出镜像 ID、架构和可用摘要。后续命令用本地镜像 ID，避免 tag 在练习中变动。不同终端需重新设置 `STAGE2_IMAGE`，或使用教师记录的完整 ID。新 PC 没有镜像时才拉取教师验收过的 `px4io/px4-sitl-gazebo@sha256:…`，不要默认拉取最新构建。

**PC** 检查镜像内依赖，命令在 **Docker** 内执行：

```sh
docker run --rm --entrypoint /bin/sh "$STAGE2_IMAGE" -c \
  'command -v px4-gazebo && gz sim --versions && dpkg-query -W "px4*"'
```

记录实际 PX4/Gazebo 版本，运行后还可在 `pxh>` 输入 `ver all` 获取固件信息。若旧镜像布局不同，以该 tag 的入口和工具为准，先排查，不直接套用源码构建命令。镜像版本、来源及许可证需随验收记录保存；分发时核对镜像及内置模型、依赖的许可与通知要求。

### 挂载解决什么问题

[Docker bind mount](https://docs.docker.com/engine/storage/bind-mounts/)适合把 PC 文件提供给容器：后续赛道、模型和配置可只读挂载，日志输出目录可写挂载。挂载不安装 Gazebo 或系统依赖；Linux 二进制仍须匹配容器的架构与运行库。

本节使用镜像自带 Baylands 场景，并只读挂载仓库的 `x500_experiment` 与 `mid360s` 两个模型目录。实验飞机 include 镜像内 X500 和独立雷达，RGBD 配置位于实验飞机 SDF，雷达参数位于独立雷达 SDF。两个目录缺一不可。后续有实际赛道文件时，再核实此镜像的资源路径并设置 `GZ_SIM_RESOURCE_PATH`，追加挂载目录且保留镜像原有搜索路径；不要把整个源码目录挂到镜像程序目录而遮蔽预编译产物。只有确实需要修改 PX4 或增加系统依赖时，才评估源码编译或派生镜像。

### 安装 QGC

在上述固定发布页下载 Linux AppImage，保存到 **PC** 的 `~/Applications/QGroundControl-v4.4.3.AppImage`。以下以 Ubuntu 22.04 为准，运行库安装依据 [QGC 官方安装说明](https://docs.qgroundcontrol.com/Stable_V5.0/en/qgc-user-guide/getting_started/download_and_install.html)：

```sh
sudo apt-get update
sudo apt-get install -y libfuse2 libxcb-xinerama0 libxkbcommon-x11-0 \
  libxcb-cursor0 gstreamer1.0-plugins-bad gstreamer1.0-libav gstreamer1.0-gl
chmod +x ~/Applications/QGroundControl-v4.4.3.AppImage
sha256sum ~/Applications/QGroundControl-v4.4.3.AppImage
~/Applications/QGroundControl-v4.4.3.AppImage
```

成功判据：QGC 主窗口正常出现，About 页面版本为 4.4.3。保存下载文件摘要。本练习用 UDP，不需要配置串口权限或移除 ModemManager。更换 QGC 版本时重新核实界面与飞行操作。

## 2. 学员：启动单机仿真（PC）

前置条件：教师已在此 PC 选择镜像、设置 `STAGE2_IMAGE` 并准备 QGC；PC 已配置 X11/XWayland，`DISPLAY` 非空，存在 `/tmp/.X11-unix`，安装了 `xhost`；只运行本练习的一架仿真机和一个 QGC。**PC 仓库根目录，终端 A** 执行：

直接使用镜像原有启动入口。气压计问题已由用户确认解决，当前流程无需额外订阅脚本。

```sh
xhost +si:localuser:root
docker run --rm -it --init --name uav-stage2-sitl --network host \
  --mount "type=bind,source=$PWD/stage2/models/x500_experiment,target=/opt/px4-gazebo/share/gz/models/x500_experiment,readonly" \
  --mount "type=bind,source=$PWD/stage2/models/mid360s,target=/opt/px4-gazebo/share/gz/models/mid360s,readonly" \
  -e DISPLAY -e QT_X11_NO_MITSHM=1 -e GZ_PARTITION=uav-stage2 \
  --device /dev/dri/renderD128 \
  -v /tmp/.X11-unix:/tmp/.X11-unix:ro \
  -e PX4_SYS_AUTOSTART=4001 -e PX4_SIM_MODEL=gz_x500_experiment \
  -e PX4_GZ_WORLD=baylands -e PX4_GZ_NO_FOLLOW=1 \
  "$STAGE2_IMAGE"
```

这是前台运行容器，保留终端用于观察 PX4 日志。仿真由镜像自带入口启动标准实验机与 Baylands 户外场景，不设置 `HEADLESS`。预期出现 Gazebo 三维窗口和 `pxh>` 提示符，仿真时间前进，无持续仿真连接错误。当前 PC 已验证 AMD 核显硬件加速，使用 render 节点，不设置 `LIBGL_ALWAYS_SOFTWARE=1`；实际 Gazebo 流畅度需验收。其他 PC 先按下节核实设备。

**PC 终端 B** 启动 QGC：

```sh
~/Applications/QGroundControl-v4.4.3.AppImage
```

进入 Fly（飞行）页面，等待遥测与位置就绪。成功判据：仅出现一架 PX4 多旋翼，姿态、高度、GPS/位置状态持续更新，初始为地面、未解锁。

### 未自动连接时配置 UDP

同机 host 网络采用下列约定：

| 项目 | 端点/意义 |
| --- | --- |
| QGC | UDP 14550，地面站监听端口 |
| PX4 第 0 实例 | GCS 本地端口常见为 UDP 18570，以实际 `mavlink status` 为准 |
| 地址 | 同一台 PC 的 `127.0.0.1`，容器使用 host 网络 |
| MAVLink system ID | 预期为 1，在 QGC MAVLink Inspector 中核实 |

本练习 QGC 使用 14550；在容器前台 `pxh>` 输入 `mavlink status` 核实飞控 GCS 链路本地端口。14540 属于 Offboard/API 链路。

如果 30 秒内未出现飞机，在 QGC **Application Settings → Comm Links** 添加名为 `Stage2-SITL` 的 UDP 链路：Listening Port 为 `14550`，Target Hosts 添加 `127.0.0.1:18570`（若 `mavlink status` 显示其他 GCS 本地端口则替换），保存后 Connect。若已有自动 UDP 链路占用 14550，先在 AutoConnect 中关闭 UDP 自动连接，再连接手动链路；不同时创建两个监听同端口的链路。

成功判据是状态持续更新且后续指令生效；仅显示 Connected 不算飞行验收。

若 PC 的 `ss -lunp 'sport = :14550'` 显示同一个 QGC 有两个监听 socket，先断开手动链路并关闭 UDP AutoConnect，再只连接一条手动链路。必要时正常退出并重新打开 QGC。PX4 `mavlink status` 的 GCS 实例出现 `GCS heartbeat valid`、partner IP 和非零 rx，证明已收到地面站消息；仍需在 QGC 核实飞机显示与遥测。

## 3. 学员：QGC 控制飞行（PC GUI）

前置条件：位置估计已就绪，QGC 未显示阻止起飞的错误。将 QGC 高度/距离显示单位设为米。这里的 5 m、8 m 均为相对起飞点高度，不是海拔；不输入 NED 坐标。本练习不需要手柄。

本节采用 QGC Takeoff/Hold/Land 指令，先在 **PC** 设置当前仿真为无摇杆输入：

```sh
docker exec uav-stage2-sitl /opt/px4-gazebo/bin/px4-param set COM_RC_IN_MODE 4
docker exec uav-stage2-sitl /opt/px4-gazebo/bin/px4-param show COM_RC_IN_MODE
```

成功判据：显示值为 4。容器使用 --rm，每次新建后重新设置。此设置仅适用于本节纯自动指令的 SITL 仿真；后续使用 JoyCan、实体/虚拟摇杆时需重新选择输入模式并验收持续输入。值 1 表示 Joystick only，会检查持续摇杆输入，不是“关闭输入检查”。含义见 [PX4 Manual Control](https://docs.px4.io/main/zh/config/manual_control)。不通过关闭全部 failsafe 或强制解锁处理起飞问题。

操作依据 [QGC 飞行页面](https://docs.qgroundcontrol.com/Stable_V5.0/en/qgc-user-guide/fly_view/hud.html)，4.4.3 的菜单位置以实际界面为准：

| 步骤 | 操作 | 预期现象与课堂成功判据 |
| --- | --- | --- |
| 起飞 | Fly 页面点击 Takeoff，设高度为 5 m，滑动确认 | 自动解锁并爬升；60 秒内到达 5±1 m |
| 悬停 | 到达目标高度后保持 10 秒；若未进入 Hold，通过飞行模式菜单选 Hold | 高度保持在 5±1 m，水平速度接近 0，无持续漂移或告警 |
| 改变高度 | Actions → Change Altitude，设为 8 m，确认 | 60 秒内到达 8±1 m，然后保持 10 秒 |
| 降落 | 点击 Land，确认 | 高度逐渐下降；60 秒内落地，随后自动解除解锁，状态显示 Disarmed |

上述时限和容差是课程验收规则，尚不是实测性能。起飞后高度、姿态与速度应随飞行改变；可在 MAVLink Inspector 查看 `ATTITUDE`、`GLOBAL_POSITION_INT` 等消息。QGC 地图底图下载失败不等于 MAVLink 断开，用遥测判定连接。

发生拒绝起飞、超时或模式异常时，记录 QGC 消息和终端输出，按排障表处理，不反复提交指令。飞行仍有响应时先 Land；无法恢复时按下一节停止本练习容器并重新开始。

## 4. 停止与重置（PC）

正常结束先在 QGC 降落，确认 Disarmed。在 **PC 终端 B** 执行：

```sh
docker stop -t 10 uav-stage2-sitl
xhost -si:localuser:root
```

仅停止本练习命名的容器；`--rm` 会移除它。再执行第 2 节的 `docker run`，PX4 参数、任务、位置和仿真状态在未挂载持久化状态目录时从镜像初始状态开始，等待 QGC 重新连接后再飞一次。不要只点 Gazebo 的 Reset：飞控状态需要同时重置。

容器未挂载运行目录，日志也会随移除消失。失败时在停止前，**PC** 将诊断保存到仓库外：

```sh
stage2_diag_dir=$(mktemp -d /tmp/uav-stage2-diag.XXXXXX)
docker logs uav-stage2-sitl > "$stage2_diag_dir/sitl.log" 2>&1
docker inspect uav-stage2-sitl > "$stage2_diag_dir/container.json"
# 查看实际运行数据位置，再按该镜像布局保存需要的目录：
docker exec uav-stage2-sitl /bin/sh -c 'pwd; printenv XDG_DATA_HOME; ls -la /root/.local/share'
```

同时截图或记录 QGC 状态消息；日志不提交 Git。容器已经移除时无法补取其中日志。

## 5. Gazebo 三维窗口检查

第 2 节已默认显示三维窗口。成功判据：窗口显示 Baylands 户外场景与 X500，仿真时间前进，QGC 起飞时模型同步升高。QGC 地图底图与 Gazebo 三维场景是两个独立显示。

若镜像找不到 `baylands`，先检查已有镜像是否包含该 world，不自动拉取最新镜像或回退到空场景。若窗口无法显示，按下表排查 X11/XWayland 与图形环境。本节显示授权针对以 root 运行的容器，实际镜像使用其他用户时需按该用户调整授权；运行结束后撤销授权。

### 核显加速与性能观察

本机 2026-10-09 检查：Fedora 内核 `7.1.3-101.fc43.x86_64`、AMD Radeon 780M（HawkPoint1）、`amdgpu` 驱动，render 节点 `/dev/dri/renderD128`。现有镜像包含 Mesa `radeonsi`；一次性容器映射此节点后 `glxinfo -B` 返回 `direct rendering: Yes`、`Accelerated: yes`、AMD Radeon 780M、OpenGL 4.6。容器 Mesa 25.2.8。这验证容器 OpenGL 硬件加速，尚不是 Gazebo 飞行性能验收。

本节启动命令映射该 render 节点，并移除强制软件渲染变量。其他 PC 需先核实实际节点与驱动；不要求 NVIDIA Toolkit，也不挂载宿主图形库。若使用非 root 容器用户，检查 render 设备组权限。

**PC** 可在正式启动前检查（需有上文 X11 授权）：

```sh
docker run --rm --network none --device /dev/dri/renderD128 \
  --entrypoint glxinfo -e DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix:ro \
  "$STAGE2_IMAGE" -B
```

预期 renderer 显示真实 AMD GPU 且 `Accelerated: yes`；若显示 llvmpipe，仍在软件渲染。保留日志中的驱动告警；本机检查出现 `os_same_file_description` 提示，但 OpenGL context 成功创建，实际长期稳定性仍需确认。

Gazebo 右上角插件菜单添加 **Camera FPS** 观察 GUI 渲染帧率；底部 **RTF** 或 **World Stats** 观察仿真实时率。RTF=1 为实时，0.1 为十倍慢；传感器 SDF 的 30 Hz 是仿真时间频率，不等于墙钟输出频率。

**PC** 读取实时率：

```sh
docker exec uav-stage2-sitl gz topic -e -t /world/baylands/stats
docker stats --no-stream uav-stage2-sitl
```

复杂场景的 RTF/FPS 需单独实测，静态场景的近 10 Hz 雷达链路不能替代飞行性能验收。鼠标缩放可用右键拖动；需关闭自动跟随时，在启动命令加 `-e PX4_GZ_NO_FOLLOW=1`。

## 6. 四图展示与数据验收（PC）

教师课前准备：PC 安装 uv/Python 3.12+，在仓库根目录执行 `uv sync --extra stage2`；准备已验收 ROS 镜像 `osrf/ros:humble-desktop-jammy`（下载属于课前准备）。RGB/D 处理依赖在 PC，Gazebo Python 绑定使用仿真容器自带环境，ROS/RViz 在另一个容器内运行。运行前先按第 2 节启动标准机，等待 Baylands 加载完成并恢复播放。

### 相机基线：Orbbec Gemini 2 几何近似

依据 [官方产品页](https://www.orbbec.com/products/structured-light-camera/gemini-2/) 和 [官方规格书 v1.0](https://www.orbbec.com/wp-content/uploads/2023/04/ORBBEC_Datasheet_Gemini-2.pdf)（2026-10-10 核对），采用 RGB 640×360 / 30 Hz、水平 86°，深度 640×400 / 30 Hz、水平 91°，原始近似范围 0.15–10 m（官方最佳范围 0.2–5 m）；2026-10-14 为 Stage 5 跟随实验将共享模型的仿真深度上限扩展至 20 m，不代表真实 Gemini 2 的测距能力。模式支持更高分辨率，课堂选择低分辨率以控制负载。

Gazebo 针孔由水平视场和宽高比推导垂直视场：RGB 约 55.4°、深度约 64.9°；官方标称分别约 55°/66°，并非精确实机内参。机壳用 90×25×30 mm 盒体、98 g 质量，均匀盒体惯量近似，取消 OakD-Lite 网格。camera_link 相对 base_link 位于 `(0.17,0,0.025)` m，共用传感器原点再向前 0.016 m，坐标轴沿用 Gazebo +X 前、+Y 左、+Z 上；这不是 ROS optical frame，也不是已标定的 RGB/IR 外参。

该实现提供理想 RGB 和几何深度，不模拟主动双目投影、匹配误差、畸变、日照失效或真实深度噪声；两路共光心是课程近似，仍不保证时间同步。官方适用环境为室内/半室外，Baylands 理想深度可见不代表硬件强光下可靠。实际安装、外参和改装飞行须复验；Orbbec SDK、USB 驱动和硬件未接入。修改后按第 4 节重启仿真，再启动两个展示入口。

### 文件与运行位置

| 文件 | 运行位置与职责 |
| --- | --- |
| `show_sensors.sh` | PC WebUI 入口：启动接收桥、本地图像服务，退出时清理 |
| `show_rviz.sh [mid360s\|depth]` | PC RViz 入口：默认雷达，可选深度对照；启动 ROS 容器与接收桥 |
| `sensor_receiver.py` | 仿真 Docker 内订阅 Gazebo，只缓存最新原始帧并提供本机 HTTP |
| `sensor_web.py` / `.html` | PC 编码 RGB/深度 JPEG、提供网页 |
| `rviz_cloud_bridge.py` | ROS Docker 内转换原始点云、生成表面体素与指标 |
| `rviz_cloud_config.py` / `cloud_*.rviz` | ROS Docker 内按来源生成两个 RViz 窗口配置 |

两个展示入口按需启动各自接收桥，不需要手工运行 `sensor_receiver.py`。接收桥把 Gazebo 绑定留在仿真容器中，PC 无需安装 Gazebo Python 库。

### 课堂主入口

**PC 仓库根目录，终端 C**：

```bash
./stage2/show_sensors.sh
```

浏览器打开 <http://127.0.0.1:8090>，RGB 和 D 两图持续更新。RGB 为 640×360，深度为 640×400、单位米；Stage 2 展示默认色标仍为 0.15–10 m，可用 `--far 20` 显示共享模型当前 20 m 仿真量程。深度伪彩色 JPEG 仅用于展示，算法使用原始浮点深度。两路未做时间同步或 RGBD 光学对齐。

**PC 仓库根目录，终端 D**：

```bash
./stage2/show_rviz.sh
```

打开两个 RViz 窗口：MID-360S 近似雷达点云、同帧表面体素。固定坐标系 `mid360s_sensor`，XYZ 数值保留 Gazebo 传感器局部坐标，没有 world TF。雷达独立产生点云，无需深度相机；体素每帧替换，不是 SLAM 融合地图，也不能将未观测区域视为空闲。

| 图像/数据 | 来源 | 展示出口 |
| --- | --- | --- |
| RGB | 标准机 Orbbec Gemini 2 近似 RGB 相机 | WebUI RGB |
| D | `/depth_camera`，浮点米制深度 | WebUI 深度伪彩色 |
| 点云 | `/mid360s/scan/points`，Gazebo 原生 GPU LiDAR | ROS `/stage2/mid360s/points` |
| Voxel | 同帧有效雷达 XYZ，默认 0.2 m 格网 | ROS `/stage2/mid360s/voxels` |
| 指标 | 源尺寸、有效点/体素数、消息载荷、接收/发布频率、处理耗时 | ROS `/stage2/mid360s/stats`，JSON |

WebUI 默认最高每路 20 Hz 编码，接收桥只保留最新帧；ROS 雷达展示最高 10 Hz。仿真时间频率与墙钟频率不同，应同时观察 RTF。数据仅绑定本机，ROS 默认域 10、`ROS_LOCALHOST_ONLY=1`，尚未作为 RoboPi 网络接口验收。

| 服务 | 默认本机端口 |
| --- | --- |
| RGB/D 原始 HTTP 桥 | 8089 |
| WebUI | 8090 |
| 雷达原始 HTTP 桥 | 8094 |
| 深度点云对照桥 | 8093 |

### 验收与停止

**PC** 检查飞控与话题：

```bash
docker exec uav-stage2-sitl /opt/px4-gazebo/bin/px4-commander check
docker exec uav-stage2-sitl gz topic -l
```

成功判据：实验飞机生成，IMU/陀螺仪/气压计等没有当前数据缺失告警；RGB/D 时间递增，点云与体素持续更新，两个 RViz 没有红色数据/坐标系错误，墙等几何在两窗口对应。持续输出的有效点数取决于场景，没有回波的方向不会被填充。QGC 起飞另按第 3 节验收。

关闭展示时，分别在 C/D 终端 Ctrl+C。脚本只清理本次接收器、Web 服务和 ROS 容器，仿真继续运行。再运行相同入口，应能正常启动，无端口占用；要重置仿真，先关闭展示，再按第 4 节停止/启动，最后重新打开展示。

### 调参和补充实验

**PC 课前调雷达**，参数集中写入 `stage2/models/mid360s/model.sdf`，停止并重新启动仿真生效，无需重建 Docker 镜像：

```bash
python3 stage2/configure_mid360s.py --preset light     # 256×16，5 Hz
python3 stage2/configure_mid360s.py --preset balanced  # 默认 512×16，10 Hz
python3 stage2/configure_mid360s.py --preset detail    # 512×32，10 Hz
```

默认范围 0.1–40 m；可用 `--range` 调整几何截止距离，不能视为真实反射率模型。默认视场 360°、−7°～52°；水平安装飞得较高时，地面可能超出覆盖范围。完整模型尺寸、重量、扫描分辨率、预算与误差见 [MID-360S](MID-360S.md#7-已实现的规则扫描近似)。

**PC** 仅调整展示负载，不改传感器：

```bash
STAGE2_CLOUD_FPS=5 STAGE2_VOXEL_SIZE=0.3 ./stage2/show_rviz.sh
```

**PC** 可选入口：

- `./stage2/show_rviz.sh depth`：深度相机点云/体素对照，默认 5 Hz、0.1 m；与雷达的视场、坐标原点不同，未融合。
- `STAGE2_RVIZ_HEADLESS=1 ./stage2/show_rviz.sh`：只发布 ROS 点云/体素，不打开图形窗口，供数据诊断。

环境变量：`STAGE2_CONTAINER` 选择仿真容器；RGB/D 话题使用 `STAGE2_RGB_TOPIC` / `STAGE2_DEPTH_TOPIC`，雷达点云使用 `STAGE2_POINTS_TOPIC`。原始桥/Web 端口分别用 `STAGE2_RAW_PORT` / `STAGE2_WEB_PORT`，RViz 原始桥端口用 `STAGE2_RVIZ_RAW_PORT`；ROS 镜像和域使用 `STAGE2_ROS_IMAGE` / `STAGE2_RVIZ_DOMAIN_ID`。多个实例时必须显式选择并分配独立话题/端口，当前模型固定深度和雷达话题仍只作为单机基线。

## 7. 常见失败与恢复

| 现象 | 检查与恢复 |
| --- | --- |
| `Unable to find uri[model://mid360s]`，随后关节断图 | 启动缺少雷达模型挂载；使用第 2 节完整命令重建容器，两个目录都需存在 |
| 飞机未生成但 PX4 打印启动成功 | PX4 启动日志不能代替模型加载成功；查看 Gazebo 错误、实际模型与连续传感器帧 |
| IMU/气压计等无数据 | 先确认模型成功生成、仿真正在播放、时间前进；不要关闭检查掩盖模型加载失败 |
| QGC 没有飞机 | 核对 host 网络、14550/18570 与 UDP 链路，关闭重复监听，检查当前 GCS heartbeat |
| 起飞后 Hold/RTL | 核对 QGC 消息和实际 failsafe；纯 Takeoff/Hold/Land 流程使用第 3 节 COM_RC_IN_MODE=4；Joystick only 要持续输入 |
| WebUI 等待/原始传输错误 | 确认实验机及接收器运行、未暂停、话题正确；仿真重启后重启展示 |
| 端口被占用 | 退出自己的旧展示进程或调整对应端口，不结束无关服务 |
| RViz 无图形会话 | 检查 DISPLAY、X11 socket、XAUTHORITY；无界面数据诊断用 headless |
| 雷达稀疏/看不到地面 | 检查有效回波、视场、安装高度与裁剪距离；档位影响远处细目标，大点尺寸不能补回波 |
| 更新慢 | 检查 Gazebo RTF、GPU 渲染与 CPU/内存；降低展示频率或传感器档位，分别记录影响 |
| Docker/Gazebo 图形失败 | 先确认 docker info、render 节点、驱动与 X11 授权；保存诊断后再重置 |

若需保留当前容器临时修复缺失雷达，**PC 仓库根目录**执行：

```bash
docker cp stage2/models/mid360s uav-stage2-sitl:/opt/px4-gazebo/share/gz/models/mid360s
docker restart uav-stage2-sitl
```

该复制随容器删除而消失，正式流程仍使用两个只读挂载。历史诊断、具体版本及性能证据见 [Validation](Validation.md)；QGC 消息历史不等于当前故障，以本次实时状态为准。

## 相机配置验证（2026-10-10）

独立无界面 Gazebo 静态墙场景实测：RGB 640×360、深度 640×400，接收桥与 Web JPEG 尺寸正确，连续帧时间递增；深度 256000 有效像素、约 4.664 m，与已知墙面距离一致。SDF 校验及深度点云 640×400 连续两帧验证通过。Python/Bash 语法检查通过；未自动验收图形、改装飞行、Orbbec SDK 或真实硬件，先前展示确认对应改相机前版本。
