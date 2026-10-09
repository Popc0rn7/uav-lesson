# Stage 1：ROS 2 常驻模型聊天

链路：PC ROS publish → 局域网 DDS → RoboPi ROS bridge → 本板 HTTP /infer → 常驻 C++ worker → NPU → ROS 回复。
HTTP 仅监听 127.0.0.1:8080，PC 仍通过 ROS 通信；模型启动时加载一次，每个问题创建独立上下文，无对话历史。

## 前置条件

- PC 与 RoboPi 使用 ROS 2 Humble，相同 ROS_DOMAIN_ID（默认 10）、ROS_LOCALHOST_ONLY=0。
- 板端已有适配 OpenHarmony 的 rclpy/std_msgs、Uvicorn 0.54.0、h11；依赖不能用 Linux 二进制替代。
- 程序与模型已按 [环境准备](../AGENTS.md) 放在 /data/local/workspace 下。
- 现有启动入口针对已验证的 AArch64、内核 6.6.86 和 Houmo xh2a_drv v1.4.0；换镜像需重新核对驱动。
- 实测局域网为 PC 192.168.99.115、RoboPi 192.168.99.145，通过 Wi-Fi。HDC 只用于部署和管理，不承载聊天消息。

## RoboPi：启动

```sh
cd /data/local/workspace/stage1
sh serve.sh
```

入口检查匹配驱动，初始化 ROS，启动 qwen_infer/run.sh --serve --background，等待模型 /health 就绪再启动 ROS 节点。
首次加载约 20 GB 模型，需要约 100 秒；看到“模型已就绪”后才运行 PC 客户端。
HTTP 服务后台运行，日志和进程身份保存在 qwen_infer/server.log、qwen_infer/server.pid。
ROS bridge 前台运行；重复启动时检查 serve.pid，已有本项目节点则提示并退出。
Ctrl+C 结束 ROS bridge，模型服务保留，重启 bridge 可复用模型。

RoboPi 另一个终端检查或停止模型服务：

```sh
cd /data/local/workspace/stage1/qwen_infer
sh run.sh --status
curl http://127.0.0.1:8080/health
# 确认无需继续处理请求后停止（会回收本服务 native worker）：
sh run.sh --stop
```

status 只证明进程存在，health 的 status=ready 才证明模型就绪。

## PC：聊天

PC 已安装并初始化 Humble 时，在仓库根目录运行：

```sh
export ROS_DOMAIN_ID=10
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
python3 stage1/chat.py
```

本机没有原生 ROS 时，使用课前已准备的镜像（Linux PC，仓库根目录）：

```sh
docker run --rm -it --network host \
  -v "$PWD:/course:ro" \
  -e ROS_DOMAIN_ID=10 -e ROS_LOCALHOST_ONLY=0 \
  -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  --entrypoint /bin/bash osrf/ros:humble-desktop-jammy \
  -lc 'source /opt/ros/humble/setup.bash && cd /course && python3 stage1/chat.py'
```

输入问题，显示纯模型文本；输入 /quit 退出。回复不再混入加载日志或性能统计。

## PC：自己 publish

在已初始化的 ROS 环境或上述 host 网络容器中，先开终端订阅回复：

```sh
ros2 topic echo /uav/robopi_01/chat/response std_msgs/msg/String
```

另一个 PC 终端发布：

```sh
ros2 topic pub --once /uav/robopi_01/chat/request std_msgs/msg/String \
  '{data: "{\"id\":\"manual-001\",\"prompt\":\"1+1等于几？只输出数字。\"}"}'
```

两端域均为 10，发布前确保订阅已开始。回复 id 对应 manual-001，status=ok，output 为模型文本。

## 接口与错误

| 项目 | 约定 |
| --- | --- |
| 请求/回复话题 | /uav/robopi_01/chat/request、/uav/robopi_01/chat/response |
| 消息/QoS | std_msgs/msg/String；reliable、volatile、depth=10 |
| 请求 | JSON：id（1–128 字符）、prompt（非空，最多 16 KiB UTF-8） |
| 成功回复 | id、status=ok、output；input_tokens/output_tokens/stop_reason，diagnostics 为这些指标的 JSON 字符串 |
| 失败回复 | id、status（invalid/busy/timeout/error）、error |
| 并发 | ROS 每板一个请求；HTTP 429 映射为 busy，不排队或自动重发 |
| 超时 | 模型启动最多 300 秒；入口等健康状态 330 秒；HTTP 推理 300 秒、桥等待 310 秒、PC 等回复 330 秒 |

节点不再写临时问题文件、启动或杀死每次请求的推理进程。HTTP 504 表示 worker 超时并已被模型服务终止，需检查日志后重启模型服务。
ROS 通信/客户端超时不代表 HTTP 已取消；不自动重发，以免重复推理。

模型没就绪：查看 qwen_infer/server.log、驱动和模型目录；入口拒绝复用其他部署占用的 8080 服务。
节点发现失败：检查域、RMW、实际网络接口、防火墙，确认模型加载已完成。
发现但收不到消息：核对 QoS 和双向 DDS 交付，topic list 不是验收。
HTTP 不可达：检查模型服务状态；不能回退到单次 CLI 隐藏故障。

## 验证记录

既有板端环境：Linux 6.6.86、AArch64、Python ABI cpython-312-aarch64-linux-ohos；
ROS 前缀 /sys_prod/robot/install、依赖前缀 /sys_prod/robot/out；Fast DDS RMW 为 rmw_fastrtps_cpp。
TCIM v2.5.0，PCI 0000:01:00.0 的 Houmo 1f6b:0c00，get_devices --num xh2 返回 1。

此前单次 CLI 的真实 ROS 推理两次成功，但每次约 104 秒；当前代码已删除该调用路径。
本次新版课程目录实测：

| 测试 | 结果 |
| --- | --- |
| 板端真实 ROS → HTTP → NPU：“1+1” | output=2，0.633 秒 |
| 同一链路：中国首都 | output=中国的首都是**北京**。，0.700 秒 |
| 常驻证据 | worker PID 5422，prefill/decode 图各加载一次 |
| ROS 节点重启 | 模型 worker 仍为 5422，立即健康就绪，无重新加载 |
| 输出与指标 | 纯模型文本，token 数和 stop_reason 独立返回 |

以上为单次观测，不是性能基准。模型加载时间只发生于启动；当前测试 MAX_NEW_TOKENS=32。
2026-10-08 测试使用此前的板端布局 stage1/ros_chat；本文操作命令已按新的平铺布局更新。
本次仅重组仓库，未迁移或重启板端服务；新布局尚未重新上板验证。

网络恢复后的新版跨机实测：PC 192.168.99.115 ↔ RoboPi 192.168.99.145，域 10、Fast DDS、PC Humble Docker host 网络。

| PC 发布问题 | ROS 跨机端到端结果 |
| --- | --- |
| 1+1 | 2，0.662 秒 |
| 中国首都 | 中国的首都是**北京**。，0.779 秒 |

两次 status=ok、请求 ID 匹配，worker 始终为 5422，模型图加载次数仍为 1；新版完整跨机常驻推理链路通过。
网络恢复后首次 DDS 发现仍超时；只重启 ROS bridge 后立即恢复，模型服务未重启。
切换网络后如有发现问题，可重启本项目 ROS bridge，使其重新绑定接口；无需重载模型。
这些结果属于 2026-10-08 实测，不代表当前板端进程状态。以上耗时为本次样本观测，不是正式性能基准。
