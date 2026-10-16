# Stage 3 SUPER 工作流

核心源码唯一来源为 submodules/SUPER，远程仓库 https://github.com/Popc0rn7/SUPER-sim.git，开发分支 feat/sim。旧 thirdparty 工作副本及 /tmp 备份仅作迁移参照，不作为后续修改或 prepare 的源码来源。

## AirSim 后续修复

AirSim 集成继续使用同一核心来源；新增静止末端等待重规划（默认关闭）及 A* 裁剪目标返回 `REACH_HORIZON` 的修复。裁剪返回值问题及可独立运行的 CTest 入口见 [上游问题报告](SUPER-astar-clipped-goal-report.md)。运行产物、原交接包和诊断日志均不入库；本地提交以课程主仓库 gitlink 为准，下面保留初次迁移记录。

## 本轮迁入内容

仅迁入三个核心包所需的 ROS 2 构建/编译兼容、仿真时钟与绝对 YAML 路径、最终目标静止保持、初次规划失败限频重试、路径分段、课程中心高度约束和 /tmp 日志路径。必要新增头文件与终点测试一并迁入。未迁入旧 ProjectAirSim、森林配置、搜索后备实验、诊断回放工具或无关脚本；源仓库原有文件保持原样。

课程接口和核心扩展说明位于 submodule 的 STAGE3.md。雷达/PX4 适配、配置、场景、Docker 和验收仍在 stage3/super/。

## 构建与版本

prepare 只初始化/检查 submodule；build 将其只读挂载到 /super_ws/src，构建产物写到 thirdparty/super_gazebo_ws。运行容器同样挂载 submodule 和产物，不复制源码、不动态打补丁。

新用户 clone --recurse-submodules；课程仓库的 gitlink 固定核心 commit。开发者在 feat/sim 完成核心修改、验证、提交和推送，再由课程仓库更新 gitlink。本轮核心修改已提交为 `a2cdc03`（feat/sim），未推送；课程 gitlink 已更新并暂存。正式工作区旧 install 尚未更新，飞行需重新验收。

## 迁移验证

245 个核心源码/构建文件与精简样本一致，未迁入 ROS1 适配改动。使用正式嵌套挂载方式，三个核心包在 Humble 镜像内隔离构建通过（4 min 12 s，单线程；有上游编译警告）。终点保持 C++ 测试、课程 Python 6 项测试、入口 dry-run 和空白检查通过。构建日志位于 PC `/tmp/super-submodule-build.log`，产物位于 `/tmp/uav-thirdparty-cleanup-20261013/super_submodule_check/`。未启动仿真或执行飞行。

工作区 src 已链接到 ../../submodules/SUPER，prepare 会创建或检查此链接。旧源码已移到 /tmp/uav-thirdparty-cleanup-20261013/backups/super_gazebo_before_submodule/；现有构建产物保留。符号链接在 PC 和现有 Docker 嵌套挂载方式中均验证可读。

thirdparty 已清理，只保留 super_gazebo_ws。旧工作区、弃用定位依赖、独立验证产物和备份移到 PC /tmp/uav-thirdparty-cleanup-20261013/；旧 SUPER/GCOPTER 链接移除，目标源码未改动。

源码布局改为 super_gazebo_ws/src 直接链接 ../../submodules/SUPER，容器路径为 /super_ws/src。旧 build/install 因 CMake 缓存绑定旧 src/SUPER 路径，已备份至 /tmp/uav-thirdparty-cleanup-20261013/super_old_source_layout/，下一次 build 重新生成。build-prefilter/install-prefilter 保留。
