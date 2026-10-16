# SUPER 远目标裁剪返回值问题报告

当最终目标 B 超出 A* 搜索窗口，且裁剪后的局部目标 C 在搜索距离截止前被找到时，A* 返回 `REACH_GOAL`。调用方据此将原始 B 追加到局部路径末端，形成未经 A* 搜索的 C→B 线段。建议在成功裁剪后保留上下文，到达 C 返回 `REACH_HORIZON`，让已有滚动重规划继续朝 B 推进。

本问题可以在无 AirSim、无 PX4、无障碍物的真实 A* 测试中复现。它涉及搜索返回值的语义，不要求关闭或增大 `planning_horizon`。

## 代码来源与影响范围

已核对官方仓库的 [A* 实现](https://github.com/hku-mars/SUPER/blob/2ad3419c127a617c6d7df6925e81a14175a9c096/super_planner/src/super_core/astar.cpp)及 [SuperPlanner 实现](https://github.com/hku-mars/SUPER/blob/2ad3419c127a617c6d7df6925e81a14175a9c096/super_planner/src/super_core/super_planner.cpp)，基准提交为 `2ad3419c127a617c6d7df6925e81a14175a9c096`。2026-10-16 再次检查官方 master，相关控制流仍存在。本地仿真分支基于上述版本，修改前基线为 `61c1d6244ce2950dbf7052a1a3e8caeab0773088`；本地没有修改这几处分支的原始返回值语义。修复已独立提交为 `4461128ff139ab986c0229a6e29f7e17c060d4cf`（本地分支 `fix/clipped-goal-horizon`，尚未推送）。

影响条件是：B 在 A* 窗口外，裁剪/邻域调整成功，且搜索先到达 C，而非先达到搜索距离截止。不是每个远目标都会触发；窗口足够大或绕行距离较长时，可能先返回正常的 `REACH_HORIZON`。

## 最小例子

设 A=`[0,0,2]`，B=`[0,235,2]`，单位米，使用空局部地图并允许未知空间通行：

| 参数 | 值 |
| --- | --- |
| `astar.map_voxel_num` | `[200,200,80]`，内部调整为奇数网格 |
| 膨胀地图分辨率 | 0.2 m |
| A* 水平窗口半宽 | 约 20 m |
| 搜索距离 `searching_horizon` | 20 m |
| ROG 地图尺寸 | `[60,60,16]` m |

几何上，B 的投影与窗口边界相交于约 `[0,20,2]`，再向窗口内退 2.5 m，得到 C≈`[0,17.5,2]`。网格化后的实测路径末端为 `[0.1,17.5,2.1]`。

期望：搜索返回局部成功，输出 A→C；保留最终任务目标 B，后续继续重规划。

实际：返回 `REACH_GOAL`，上层追加 B，形成 A→C→B。C→B 约 217.5 m，没有经过本次 A* 搜索。

## 错误传播

1. `Astar::pointToPointPathSearch()` 检测到 `end_pt` 不在窗口中，改写 `local_end_pt`，但没有记录目标被裁剪。
2. `endPtr` 对应的是改写后的局部目标。搜到该网格时，无条件返回 `REACH_GOAL`；其后才是搜索距离截止分支。
3. `SuperPlanner::PathSearch()` 接受 `REACH_HORIZON` 和 `REACH_GOAL`，但仅在后者追加原始 `goal`。
4. `generateExpTraj()` 将得到的引导路径交给安全走廊生成，因此错误长线会进入下游。

本地另有引导路径分段补丁，会将长线插值成短段，但不会替这条线做避障搜索；这不是返回值问题的修复。走廊失败是本机场景中的表现，不能据此声称所有上游配置都会失败或碰撞。

## 最小修复

在每次 `pointToPointPathSearch()` 调用中新增局部布尔标记 `goal_clipped`，初始为 false；仅在窗口外目标成功裁剪、邻域调整通过后置为 true。搜到 `endPtr` 后选择返回值：

```cpp
return goal_clipped ? REACH_HORIZON : REACH_GOAL;
```

未裁剪的真实目标、原距离截止、搜索失败、超时和逃逸搜索保持既有处理；调用方无需修改。这里的 `REACH_HORIZON` 表示可执行的局部进展，不要求路径恰好长 20 m，现有探索边界分支也使用该返回值。

## 可重复验证

测试直接调用真实 A*，不模拟其返回值。测试源为 [astar_clipped_goal_test.cpp](../../submodules/SUPER/super_planner/test/astar_clipped_goal_test.cpp)，临时配置由 [run_astar_clipped_goal.py](../../submodules/SUPER/super_planner/test/run_astar_clipped_goal.py) 从仓库配置生成，不依赖历史飞行目录。

**执行位置：已准备好的 ROS 2 Humble 构建 Docker，`/super_ws`。** 前置为 SUPER 源码、ROG 与消息包可用，加载 Humble 和消息包环境：

```bash
source /opt/ros/humble/setup.bash
source /opt/px4_ws/install/local_setup.bash
colcon build --packages-up-to super_planner --executor sequential \
  --cmake-args -DCMAKE_BUILD_TYPE=Release -DSUPER_BUILD_PATH_SEARCH_TEST=ON
source install/local_setup.bash
ctest --test-dir build/super_planner -R astar_clipped_goal --output-on-failure
```

脚本使用隔离 DDS 域 191，关闭地图订阅、可视化与射线更新。期望 CTest 通过，真实目标返回 `REACH_GOAL`，裁剪目标返回 `REACH_HORIZON`。缺少 `rclcpp`、ROG、消息包或 PyYAML 时先补齐构建环境；不能用启动 AirSim 代替这些依赖。

2026-10-15 同一测试程序链接修改前与修改后 A* 的结果：

| 用例 | 修改前 | 修改后 |
| --- | --- | --- |
| 近目标 `[0,5,2]` | `REACH_GOAL` | `REACH_GOAL` |
| 裁剪目标 `[0,235,2]` | 错误返回 `REACH_GOAL`，负对照失败 | `REACH_HORIZON` |
| 裁剪目标 `[-37.57,231.76,6]` | 未继续执行，测试在上一项中止 | `REACH_HORIZON` |
| 窗口内但先到距离截止 `[19,19,2]` | 未继续执行 | `REACH_HORIZON` |
| 再次调用近目标 `[0,5,2]` | 未继续执行 | `REACH_GOAL` |

负对照仅替换 A* 编译对象，其余依赖和测试程序相同，确认测试能捕获原始错误。此测试没有覆盖障碍物、裁剪失败或动态飞行控制。

## 本地飞行结果与结论边界

20 m 规划距离、10 m/s 配置速度、相同出生点与最终 B 的单目标对照中，修复前起飞后连续走廊生成失败，最终规划超时降落；修复后初次规划与多次重规划成功，实际峰值约 9.62 m/s。随后在起点附近约 16 m 处碰撞树木，检查器中止，最终确认降落解除武装。

因此，隔离测试已证实并修正裁剪目标返回值问题；飞行证明原先初次规划阻塞已解除，**不代表 235 m 长任务完成，也不证明后续碰撞由该返回值问题引起**。飞行证据与 ULog 复盘见 [AirSim 实测记录](../../stage3/super/airsim/README.md#单目标裁剪返回值修复与-10-ab-实测2026-10-15)。原始记录保存在本机忽略 Git 的 `artifacts/airsim-diagnostics/clipped-goal-10-ab-20261015/` 和对应运行目录。
