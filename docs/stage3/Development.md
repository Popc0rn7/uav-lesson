# Stage 3 开发交接

2026-10-12 收束：本轮停止扩展功能，以当前通过验收的 PC demo 为提交基线。操作只维护在 [Hands-on](Hands-on.md)，实测与失败边界维护在 [Validation](Validation.md)，上游来源与迁移边界见 [Bring-up](Bring-up.md)。

## 当前交付

- SUPER 的 ROS 2 Humble 核心、perfect_drone_sim 竞速入口，以及 PX4/Gazebo 实体走廊入口。
- 默认走廊为 FAST-LIO2＋可选墙面标记；约 30 Hz 配准点云、200 Hz IMU 传播状态，关闭 GNSS 融合，飞控保留气压高度。2 m/s、100 m 往返、双窗口与一次恢复数据后的失流降落已实测。
- 旧 PX4 定位、宽视场与其他传感器配置作为显式对照保留，各配置不能混用验证记录。
- Jev 文本示例保持原有状态；没有新增 Jev 飞行或付费 API 调用。

当前不算完成：原赛道纯 LIO、LIO 5 档、持续失流直至落地、多轮成功率、实机雷达校准、SUPER 上板、GCOPTER 统一对照、目标识别/追踪。YOLOX＋ByteTrack 仍是候选，尚未复现。

## 文件职责与改动边界

| 工作区域 | 主要文件 | 交接约定 |
| --- | --- | --- |
| 统一运行入口 | stage3/super_docker.py、super_gazebo_view.py、Dockerfile.* | 修改默认配置或运行方式时同步 Hands-on |
| 场景与传感器 | generate_gazebo_corridor.py、corridor_layout.json、lio_landmarks.json、px4_start.sh、gazebo_warmup.py | 场景变化须独立标记评测条件 |
| LiDAR / IMU / LIO | ros_src/stage3_lidar/、super_imu.py、prepare_lio.py、patch_lio_forward.py、fast_lio_gazebo.yaml、lio_bridge.py、lio_geometry.py | 维持时间、坐标系、外参、QoS 与失流语义 |
| SUPER / PX4 控制 | prepare_super.py、patch_super_height.py、super_px4.py、super_*.yaml | 更改控制链后必须重新实际飞行验收 |
| 验收与诊断 | inspect_super.py、verify_super_*.py、check_*.py、gazebo_monitor.py、tests/ | 真值只用于评测，不能馈入定位或控制 |
| 独立竞速入口 | super_race.py、run_super_race.sh、super_race.* | perfect_drone_sim 结果不替代 PX4 动力学验收 |

stage3/models/、stage3/worlds/ 由生成器在启动时创建，忽略提交；它们没有被删除。模型来源为版本化的 Stage 2 输入与 Stage 3 生成器、场景 JSON。视场测试在临时目录生成自己的模型，不读取或改写正在运行的世界。

thirdparty/ 保存上游检出、消息包和 build/install，artifacts/ 保存模型缓存，均不提交。新 worktree 不会自动带有这些依赖；按教师准备流程准备，不能把另一个工作区的 Linux 产物直接视为板端产物。当前提交不包含临时日志、截图、轨迹或真实密钥。

## worktree 并行边界

各任务可从本轮最终提交建立独立 worktree；创建动作在主对话或维护者终端执行。优先按“板端迁移 / 视觉算法 / 仿真与评测”划分文件责任，公共 CLI、消息接口与文档变更需协调。每组提交自己的代码，避免直接修改其他组工作区。

源码隔离不等于仿真运行隔离。当前主 demo 固定使用以下共享资源：

| 资源 | 当前值 |
| --- | --- |
| 容器 | uav-stage3-ros、uav-stage3-sitl、uav-stage3-gazebo-view、uav-stage3-rviz-view |
| ROS 域 / Gazebo 分区 | 10 / uav-stage3 |
| XRCE Agent UDP / 真值 HTTP | 8888 / 8096 |
| 镜像标签 | uav-stage3-ros:local、uav-stage3-lio:local |

当前脚本尚未参数化全部资源，因此同一 PC 上主 demo 由一组持有运行权。其他组可并行编辑、静态检查与运行不访问共享仿真的单元测试；需要同时跑多套时，另行实现容器名、域、分区、端口与评测 URL 的完整隔离。不要仅改容器名就并行启动，也不要从另一个 worktree 执行 down 关闭当前组的实例。

## 收束检查

本轮代码语法、模型 XML、Python 六项几何/视场测试与先前 C++ CTest 已通过。最终飞行与失流结果见 Validation。没有在收束过程中新增飞行、板端部署或扩大验证声明；持续失流后备专项留给后续任务。
