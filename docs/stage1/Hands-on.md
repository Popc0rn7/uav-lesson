# Stage 1：ROS 2 常驻模型聊天

链路：PC ROS publish → 局域网 DDS → RoboPi ROS bridge → 本板 HTTP /infer → 常驻 C++ worker → NPU → ROS 回复。
HTTP 仅监听 127.0.0.1:8080，PC 仍通过 ROS 通信；模型启动时加载一次，每个问题创建独立上下文，无对话历史。

## 前置条件

- PC 与 RoboPi 使用 ROS 2 Humble，相同 ROS_DOMAIN_ID（默认 10）、ROS_LOCALHOST_ONLY=0。
- 板端已有适配 OpenHarmony 的 rclpy/std_msgs、Uvicorn 0.54.0、h11；依赖不能用 Linux 二进制替代。
- 程序与模型已按 [环境准备](../AGENTS.md) 放在 /data/local/workspace 下。
- 现有启动入口针对已验证的 AArch64、内核 6.6.86 和 Houmo xh2a_drv v1.4.0；换镜像需重新核对驱动。
- 实测局域网为 PC 192.168.99.115、RoboPi 192.168.99.145，通过 Wi-Fi。HDC 只用于部署和管理，不承载聊天消息。

## PC：课前拉取 ROS Humble 镜像

教师在课前完成下载；学员 PC 没有原生 ROS 时使用此镜像。前置条件：Linux PC 已安装 Docker、当前用户可访问 Docker daemon，网络可访问 Docker Hub，磁盘有足够空间。
镜像使用现有聊天命令对应的 `osrf/ros:humble-desktop-jammy`，上游构建定义见 [OSRF Dockerfile](https://github.com/osrf/docker_images/blob/master/ros/humble/ubuntu/jammy/desktop/Dockerfile)。这是 PC 的 Linux ROS 环境；板端仍需适配 OpenHarmony 的 ROS 产物。

在 **PC** 执行：

```sh
docker info
docker pull osrf/ros:humble-desktop-jammy
docker image inspect osrf/ros:humble-desktop-jammy \
  --format '{{.Os}}/{{.Architecture}} {{json .RepoDigests}}'
```

成功判据：pull 正常结束，inspect 输出镜像架构和 `sha256` 摘要。教师记录实际摘要与 PC 架构；标签可能更新，后续授课可将本文运行命令中的镜像替换为记录的 `osrf/ros@sha256:…`，使用同一构建。

在 **PC** 启动一次性容器，以下检查在 **Docker** 内执行：

```sh
docker run --rm --entrypoint /bin/bash osrf/ros:humble-desktop-jammy \
  -lc 'source /opt/ros/humble/setup.bash && python3 -c "import rclpy; import std_msgs.msg; from rclpy.utilities import get_available_rmw_implementations; assert \"rmw_fastrtps_cpp\" in get_available_rmw_implementations(); print(\"ROS Humble / rclpy / std_msgs / Fast DDS OK\")"'
```

预期输出 `ROS Humble / rclpy / std_msgs / Fast DDS OK` 并正常退出；这只验证 PC 容器依赖，跨机聊天仍按后续步骤验收。

常见失败与恢复：

- Docker socket `permission denied`：按 PC 的 Docker 安装方式修复访问权限；`Cannot connect to the Docker daemon`：启动对应 daemon 后重试 `docker info`。
- 拉取超时或连接失败：检查 PC 网络、Docker daemon 代理和 Docker Hub 可达性，再执行同一 pull；已有镜像层可复用。
- `no matching manifest` 或 `exec format error`：检查 PC 架构与镜像支持的平台，改用已验收的匹配环境；换平台后重新验收。
- 磁盘不足：检查 Docker 数据目录所在磁盘的剩余空间，确认可删除内容后清理，再重试。

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

本机没有原生 ROS 时，使用上述课前已拉取并自检的镜像（Linux PC，仓库根目录）：

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

## PC：OpenAI/vLLM 风格的 VQA 请求

2026-10-15 起，Stage 1 使用更新后的上游 qwen_ohos_infer 运行包，模型显式选择 qwen3.6-35b-a3b。原 ROS 聊天仍通过文本 /infer 工作；同一个常驻 worker 新增图片接口。模型目录必须包含 *_visual_m*.hmm；/health 应包含 status=ready、model=qwen3.6-35b-a3b、vision_enabled=true。

前置条件：按环境准备取得新的上游 dist（不能使用历史文本版归档），板端模型服务已就绪，PC 有 PNG/JPEG 图片。以下命令在 **PC，仓库根目录** 执行。先用 `hdc list targets -v` 确认设备，再检查已有转发：

```sh
hdc -t '<connect-key>' fport ls
# 只有不存在该映射时建立：PC 18080 → RoboPi 8080
hdc -t '<connect-key>' fport tcp:18080 tcp:8080
curl --noproxy '*' http://127.0.0.1:18080/health
curl --noproxy '*' http://127.0.0.1:18080/v1/models
python3 robopi/stage1/qwen_infer/vqa_client.py \
  --image /path/on/pc/image.png --prompt '请描述图片中的主要物体。'
```

成功判据：健康状态及模型名正确，客户端打印与图片内容一致的回答。把同一问题分别用于两张内容不同的图片做对照；HTTP 200 本身不能证明模型实际看了图片。HDC 映射仅用于这条 HTTP 验证，ROS 聊天仍使用原 DDS 链路。

请求协议采用 OpenAI Chat Completions 的 messages/content/image_url 结构，兼容 vLLM 常用的 base64 图片模式，格式参考 [OpenAI 图片输入](https://developers.openai.com/api/docs/guides/images-vision?api-mode=chat) 和 [vLLM 多模态输入](https://docs.vllm.ai/en/latest/features/multimodal_inputs/#image-inputs_1)。**PC 已有 openai Python SDK 时**也可这样调用（示例不调用 OpenAI 云端）：

```python
import base64
from pathlib import Path
from openai import OpenAI

data = base64.b64encode(Path('/path/on/pc/image.png').read_bytes()).decode()
client = OpenAI(base_url='http://127.0.0.1:18080/v1', api_key='EMPTY')
reply = client.chat.completions.create(
    model='qwen3.6-35b-a3b', temperature=0, max_tokens=128,
    messages=[{'role': 'user', 'content': [
        {'type': 'text', 'text': '这张图片中有什么？'},
        {'type': 'image_url', 'image_url': {
            'url': f'data:image/png;base64,{data}', 'detail': 'auto'}},
    ]}],
)
print(reply.choices[0].message.content)
```

当前兼容范围：单轮 user（可带 system）、按输入顺序交错的文本和最多4张 PNG/JPEG 图片、temperature=0、top_p=1、n=1、非流式响应；max_tokens 或 max_completion_tokens 二选一。图片使用 data URL，整个 JSON 不超过1 MiB、单图不超过1600万像素。暂不支持远程图片 URL、多轮历史、SSE、tools、response_format、detail=low/high、其他采样参数；不支持的设置明确报错，不作为完整 OpenAI/vLLM 实现宣称。

响应保留 choices[0].message.content、finish_reason 和 usage；prompt_tokens 使用包含视觉展开的实际输入 token 数。Chat Completions 错误返回 error.message/type/param/code；原 /infer 的回复结构继续兼容 ROS backend。

常见失败：404 表示运行的是旧 HTTP 包或路由错误；vision_enabled=false 表示没有加载视觉图；400 可检查图片 base64、模型名及不支持的选项；413 表示整个请求超过1 MiB；429 表示同一 worker 正忙。更新时先停止本项目服务、备份再替换，部署脚本继续拒绝覆盖不同的已有文件。更新后 /health 缺少 model 或模型不符时，Stage 1 backend 会拒绝复用该服务。

实现分工：上游 main.cc 加载视觉图、绑定图片上下文和视觉 token；上游 server.py 解码标准消息、管理图片临时文件、转换 OpenAI 响应；课程 stage1/deploy.py 只收集运行产物及整套模型，serve.sh 显式选择模型。课程不维护上游 C++ 工程副本。

### 2026-10-15 生产目录更新验证

- 同步了上游源码/dist、本工作树忽略的运行包与板端 `/data/local/workspace/stage1/qwen_infer`，逐文件SHA-256一致。补齐部署清单的run.py/models.json/vqa_client.py；Stage 1入口显式选择35B，backend核对健康接口的模型名和worker可执行文件。实际backend就绪检查返回0，通过backend.infer调用“1+1”返回2，文本接口回归通过。
- 既有21 GB级模型和运行库没有重传；使用板上已有Qwen3.6-35B-A3B、驱动v1.4.0、TCIM v2.5.0。当前工作树没有模型缓存，本次没有执行整套模型部署。
- PC通过18080→8080转发发送两张448×448矩形图片，同一句问题，红图回答red（0.868秒）、蓝图回答blue（0.815秒）；prompt_tokens均240，包含视觉展开。
- 交错双图请求使用max_completion_tokens：正序红/蓝回答red,blue（2.231秒），交换图片后回答blue,red（1.415秒），prompt_tokens均456。非零temperature返回400及OpenAI风格error对象。
- 运行课程本地包的vqa_client.py识别Gazebo画面中的红立方体（3.426秒、64输出tokens达到长度上限）；同时把路面黄色标记猜成支撑结构/阴影，说明语义回答仍会出错，不能当作可靠几何或物体身份判定。
- 25项主机测试通过，3项因主机未安装Uvicorn跳过；板端实际Uvicorn启动和真实HTTP/VQA分别验证。Python语法、Shell语法、diff检查通过。当前平铺布局的完整ROS跨机聊天没有重跑。
- 更新前的板端小文件备份位于 `/data/local/workspace/stage1/.backup-vqa-prod-sync-20261015/`，保留原服务控制入口。不自动配置开机启动。

## 新目录部署回归（2026-10-16）

**PC 仓库根目录**，先按教师准备流程取得匹配的上游 dist、整个模型目录及许可证。实际部署显式指定 HDC 目标，不再修改源码 TARGET；本地检查不连接设备：

```bash
python3 stage1/deploy.py --check-local
python3 stage1/deploy.py --target '<本次确认的connect-key>'
```

成功判据：本地所有必需文件存在且不是 LFS 指针；部署逐文件 SHA-256 校验完成。重复部署相同文件跳过，遇到不同已有文件停止。先检查服务与文件、备份旧版本，再安排更新，不用本入口强行覆盖活动程序。

**RoboPi shell**，完成模型/驱动/ROS 预检后，沿用前文 `cd /data/local/workspace/stage1; sh serve.sh` 启动。**PC 仓库根目录**，已有本地 ROS 镜像、以太网 DDS 可达、板端 ROS bridge 与模型 ready 后执行：

```bash
python3 stage1/verify.py --target '<本次确认的connect-key>' \
  --image '<已准备的Humble镜像摘要>'
```

回归入口使用 HDC 读取本板 HTTP health及worker身份，在临时 PC ROS容器中顺序发出两次文本请求和一次空请求，再确认同一 worker PID及启动时刻；预期前两次status=ok且输出非空、空请求status=invalid。报告位于忽略Git的 `artifacts/stage1-validation/result.json`。它不会启动模型、重启ROS桥、自动拉镜像或调用付费API；回复内容需结合报告核对。忙碌、ROS桥退出重启和VQA另按前文章节验证，不能仅凭本入口通过就扩展验收范围。

2026-10-16 实测：43 个交付文件完整部署及 SHA-256 核验通过，已有大模型未重传。首次加载驱动因 DMA/CMA 内存不足而 probe 失败；经用户授权重启后先加载相同驱动，PCI 绑定及 runtime 枚举 1 个 NPU 通过。等待健康接口 ready 后，PC 经实际以太网 DDS 发出的“1+1”和首都问题分别收到“2”“北京”，耗时 0.55/0.50 秒；空请求 0.003 秒返回 invalid。前后 worker PID=2226、start_ticks=16973 一致，确认常驻复用。报告为 `artifacts/stage1-validation/post-reboot-ready.json`；第一次在模型加载期间执行的健康检查超时单独保留，未记为通过。HDC 18080→8080 下，VQA 对 turtlesim humble 乌龟图回答“乌龟”（0.651 秒），这是单图回归，不扩展为通用视觉准确率验收。以太网临时地址及源策略路由须在每次重启后恢复，配置见 AirSim README 的板端通信说明。

同日附加回归：仅停止并重启已核实身份的本项目 ROS bridge，两次文本和空请求再次通过；worker 仍为 PID 2226/start_ticks 16973。真实并发推理测试中，首请求返回 200，健康接口观测 busy=true 时提交的第二请求返回 429，完成后恢复 ready。证据分别为 `artifacts/stage1-validation/bridge-restart.json`、`busy-post-reboot.json`；没有杀死其他服务或调用付费 API。

同日 Stage 3 飞行测试结束后已恢复本项目服务，worker PID=7368/start_ticks=754599；以太网 ROS 两次文本（0.59/0.50 秒）和空请求再次通过，前后 worker 一致。当前健康 ready，HDC 本次 18080→8080 映射可用；证据 `artifacts/stage1-validation/restored-after-flight.json`。该临时网络/转发与服务状态不等于开机自动恢复配置。

后续 Stage 3 profile 结束及 USB/以太网恢复后，再次恢复模型/桥，worker PID=8714/start_ticks=1433105；健康 ready、以太网 ROS 两次文本约 0.60/0.50 秒、空请求拒绝与常驻复用通过，证据 `artifacts/stage1-validation/restored-after-profile.json`。HDC 18080→8080 本次映射已恢复。
