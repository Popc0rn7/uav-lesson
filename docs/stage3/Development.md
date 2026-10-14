# Stage 3 开发交接

SUPER 相关代码统一放在 `stage3/super/`：包含运行入口、控制与传感器适配、场景与可视化配置、`ros_src/` 和 `tests/`。生成的 `models/`、`worlds/` 同样位于该目录并忽略 Git；核心源码位于 `submodules/SUPER/` 的 `feat/sim` 分支，`thirdparty/` 只保存编译产物与旧参考副本。Stage 3 根目录保留 Jev 文本示例和阶段环境检查。

操作只维护在 [Hands-on](Hands-on.md)，实测与失败边界维护在 [Validation](Validation.md)，上游来源与迁移边界见 [Bring-up](Bring-up.md)。

后续构建收敛：算力环境改为 `develop/docker/Dockerfile` 直接构建 `uav-computer-ros-humble:local`，不再依赖 `gcopter-humble`。新镜像、算法编译、离线依赖和只读 DDS 检查已通过；完整新实例飞行与故障测试尚未复验，历史飞行证据不自动转移到新镜像。

当前核心源码正在按源仓库精简，具体保留与回退项见 [SUPER 核心整理](SUPER-fork.md)。源码与补丁已更新，原 install 和历史飞行证据仍属于整理前版本；完成重新构建和 GNSS 飞行验收前，不将回退后配置标记为已验收。

## 当前交付

- SUPER 的 ROS 2 Humble 核心、perfect_drone_sim 竞速入口，以及 PX4/Gazebo 实体走廊入口。
- AirSim 替换后端位于 `stage3/super/airsim/`：宿主机场景与原 PX4 镜像由统一入口管理。本机 AirSimNH 已验证传感器、RPC 往返、独立 MAVLink Offboard XYZ 及设定值停流降落；仍未接入 SUPER 规划器。AirSim 直接对接 ROS 2 Docker 由其他开发者负责，本轮仅处理 PX4 侧及合并接口，不改动该链路。操作、兼容问题、参数适用范围与证据统一见 [AirSim README](../../stage3/super/airsim/README.md#本机-airsimnhpx4-主线验收与合并接口2026-10-14)。
- AirSimNH 控制速度档：2 m 半径圆周的 1 m/s 两圈通过；2 m/s 实测峰值约 2.45 m/s，但跟踪误差超过 0.8 m 后中止并降落，3 m/s 未执行。动力学与控制调参按本轮约定暂不继续，不将未通过项写成已验收；后续合并仍需独立完成感知、时钟、DDS 和 SUPER 避障验证。
- 默认走廊为 PX4/GNSS 定位、无附加墙面标记；雷达点云经 PX4 位姿变换后由 ROG-Map 积累为局部占据体素图，另有规划使用的膨胀体素图。点云 RViz 单独展示实时回波，地图 RViz 同时展示占据体素与安全膨胀区域；Gazebo 是第三个窗口。
- Jev 文本示例保持原有状态；没有新增 Jev 飞行或付费 API 调用。

当前不算完成：多轮成功率、含悬空障碍的三维避障验收、SUPER 上板、GCOPTER 统一对照、目标识别/追踪。YOLOX＋ByteTrack 仍是候选，尚未复现。仿真运行不以实机雷达外参标定为当前验收前提；转向真实 MID-360 时另行核验安装外参和时间同步。

无墙面标记的原走廊在连续扫描角度与静止初始化先验试验中去程通过，回程发生纵向漂移，完整往返未通过；同代码有标记回归通过。详见 Validation。当前代码已移除固定 Z 投影及 1.4–2.2 m 中心高度带，完整传递 XYZ 位置/速度/加速度；墙体和柱子加高到 8 m，起飞仍为 1.95 m。场景保留宽范围安全边界与 ROG 虚拟地面/天花板；虚拟地面 −2.4 m 补偿膨胀和走廊半径余量，最低中心净空 1.4 m，无柱顶高度上限。新场景及 XYZ 执行已通过 2 m/s 一次冷启动往返；5 m/s 三维往返失败（横向边界拒绝后降落有墙体接触），保持待验证，详见 Validation。历史固定高度证据不自动适用。

## 文件职责与改动边界

| 工作区域 | 主要文件 | 交接约定 |
| --- | --- | --- |
| 统一运行入口 | develop/docker/、stage3/super/super_docker.py、super_gazebo_view.py、Dockerfile.race | 修改默认配置或运行方式时同步 Hands-on |
| AirSim 替换后端 | stage3/super/airsim/ | 保留现有 Gazebo 流程；PX4 控制验证不计为 SUPER 规划验收 |
| 场景与传感器 | generate_gazebo_corridor.py、corridor_layout.json、px4_start.sh、gazebo_warmup.py | 场景变化须独立标记评测条件 |
| LiDAR / IMU | ros_src/stage3_lidar/、super_imu.py、super_lidar.py | 维持时间、坐标系、外参、QoS 与失流语义 |
| SUPER / PX4 控制 | submodules/SUPER/、super_px4.py、super_*.yaml | 更改控制链后必须重新实际飞行验收 |
| 验收与诊断 | inspect_super.py、verify_super_*.py、check_*.py、gazebo_monitor.py、tests/ | 真值只用于评测，不能馈入定位或控制 |
| 独立竞速入口 | super_race.py、run_super_race.sh、super_race.* | perfect_drone_sim 结果不替代 PX4 动力学验收 |

stage3/super/models/、stage3/super/worlds/ 由生成器在启动时创建，忽略提交；它们没有被删除。模型来源为版本化的 Stage 2 输入与 Stage 3 生成器、场景 JSON。视场测试在临时目录生成自己的模型，不读取或改写正在运行的世界。

submodules/SUPER/ 保存核心源码，thirdparty/ 保存本机构建产物和旧参考检出，artifacts/ 保存模型缓存，均不提交。新 worktree 不会自动带有这些依赖；按教师准备流程准备，不能把另一个工作区的 Linux 产物直接视为板端产物。当前提交不包含临时日志、截图、轨迹或真实密钥。

## worktree 并行边界

各任务可从本轮最终提交建立独立 worktree；创建动作在主对话或维护者终端执行。优先按“板端迁移 / 视觉算法 / 仿真与评测”划分文件责任，公共 CLI、消息接口与文档变更需协调。每组提交自己的代码，避免直接修改其他组工作区。

源码隔离不等于仿真运行隔离。当前主 demo 固定使用以下共享资源：

| 资源 | 当前值 |
| --- | --- |
| 容器 | uav-stage3-ros、uav-stage3-sitl、uav-stage3-gazebo-view、uav-stage3-rviz-view、uav-stage3-rviz-map-view |
| ROS 域 / Gazebo 分区 | 10 / uav-stage3 |
| XRCE Agent UDP / 真值 HTTP | 8888 / 8096 |
| 镜像标签 | uav-computer-ros-humble:local（统一依赖镜像，算法在挂载工作区编译） |

当前脚本尚未参数化全部资源，因此同一 PC 上主 demo 由一组持有运行权。其他组可并行编辑、静态检查与运行不访问共享仿真的单元测试；需要同时跑多套时，另行实现容器名、域、分区、端口与评测 URL 的完整隔离。不要仅改容器名就并行启动，也不要从另一个 worktree 执行 down 关闭当前组的实例。

## 收束检查

本轮代码语法、模型 XML、Python 六项几何/视场测试与先前 C++ CTest 已通过。最终飞行与失流结果见 Validation。持续失流气压后备专项已按相同最终配置补测通过；没有进行板端部署或将其他配置写成已验收。

2026-10-13 提交前复核：Stage 3 Python 语法检查、六项几何/视场测试、原生 C++ 扫描方向测试，以及两个 RViz YAML 的解析和地图/点云话题分离检查均通过。现有仿真容器已停止，使用本地 Humble 镜像离线运行测试；没有重新飞行，三窗口往返证据沿用 Validation 中的 2026-10-12 记录。后续首先考虑完整 XYZ 轨迹执行与三维障碍验收，再推进板端和算法对照。
