# RoboPi 环境准备流程

按实际环境准备；构建、部署和设备验证采用对应 HDC/ROS/Houmo 技能。课程目标见 [roadmap.md](roadmap.md)。

## 文件位置

- stage1/chat.py：PC 聊天入口。
- stage1/deploy.py：PC 部署入口；实际部署必须显式传 `--target`，`--check-local` 仅检查本地文件。
- stage1/download_model.py：PC 课前下载模型。
- houmo/src/：Qwen、DINO、AeroVLA、课程板端 Python/启动脚本及编译入口，进 Git。
- houmo/build/：忽略 Git 的原生产物与编译缓存。
- houmo/deploy/：集中装配的上传内容，对应板端 /data/local/workspace/，忽略 Git。
- houmo/models/：本仓库内独立的模型与 embedding 文件，不依赖相邻工程的模型软链接；大文件忽略 Git。
- houmo/deps/：公共引擎源码快照与 TCIM 头文件/库，忽略 Git。
- src/：维护 Stage 1/3 共用的 HDC 远端退出码检查与 Fast DDS 接口配置。

## 1. PC：准备原生产物与上传包

源码、编译入口、依赖边界和唯一装配步骤见 [厚摩交付](../houmo/README.md)。
PC 无原生 ROS 时，先按 [Hands-on：课前拉取 ROS Humble 镜像](stage1/Hands-on.md#pc课前拉取-ros-humble-镜像) 准备 Docker。
本仓库维护 `houmo/src/` 中的 C++/Python/启动脚本。首次使用需按厚摩交付入口导入匹配的 OHOS ELF，或显式指定 根 .env 中的 SDK、TCIM 和本仓库 Qwen 公共依赖快照重新编译，输出到 `houmo/build/`。
随后从源码、ELF、模型缓存装配到 `houmo/deploy/`，不再从旧 `robopi/stage1/` 混合读取源码和运行产物。
2026-10-19 整理保留了课程 Qwen Python/Uvicorn 版本，requirements-server.txt 要求 uvicorn==0.54.0；未随整理升级上游 FastAPI 版。

## 2. PC：准备模型

模型实际文件位于 houmo/models/Qwen3.6-35B-A3B/；已从原模型缓存独立复制，来源和逐文件摘要见 houmo/models/RESOURCES.json。
embedding 已在模型目录的 hmquant/quant_embedding.bin 中，不需要额外链接；不要修改共享缓存。
无缓存时，PC 需 ModelScope、发布方确认的固定版本和下载许可：

```sh
python3 stage1/download_model.py --revision '<固定版本>'
```

下载来源为 Houmo/xh2_qwen3.6_35b-a3b_256k。已有目录/链接拒绝覆盖。
模型卡声明 Apache License 2.0；具体发布版本及分发许可需核实，本机旧缓存没有固定版本记录。
若缺 FP16 embedding，按 houmo/src/qwen/prepare_embedding.py 生成，输出到所用模型目录的 hmquant/quant_embedding.bin。
文本推理所需图及 embedding 约 21.3 GB；VQA 还需要 *_visual_m*.hmm 动态视觉图，缺失时部署入口拒绝继续。部署传整个模型目录，按实际目录总大小预留空间。模型获取/转换放在课前，不提交 Git。

## 3. PC：部署

前置条件：明确目标设备；核对 HDC、目标镜像、ROS、驱动、HAL/TCIM、模型版本和空间。
HDC 不默认经以太网接入。板端根目录由 deploy.py 顶部常量确定：

```sh
python3 stage1/deploy.py --check-local
python3 stage1/deploy.py --target '<本次确认的connect-key>'
```

程序及板端脚本传到 /data/local/workspace/stage1/；模型传到
/data/local/workspace/models/qwen3.6-35b-a3b_w4a8_256_256k_b1_1chip_2cores/。
整个模型目录按原相对路径传输，包括图文件、hmquant 配置及其中的 embedding，不再单独收集文本图或 embedding。
脚本先调用统一装配入口，再从 houmo/deploy/ 显式清单上传；创建缺失的父目录。
使用 SHA-256 校验传输，重复部署相同文件跳过；不同的已有文件会拒绝覆盖。
大模型摘要计算需要读完整文件，耗时属于教师准备。失败保留诊断输出，不自动删除板端文件或停止服务。
有不同旧版本时先检查、停止本项目进程并备份，再安排更新；不使用本脚本强行覆盖活动程序。

## 4. RoboPi：启动和验收

```sh
cd /data/local/workspace/stage1
sh serve.sh
```

入口核对匹配驱动，清除本进程的 LD_PRELOAD 导航库冲突，初始化 ROS 环境，
调用 qwen_infer/run.sh 显式选择 qwen3.6-35b-a3b 启动后台 HTTP 服务，等待 /health 就绪并确认模型名及 worker 身份后前台运行 ROS bridge，避免落入上游启动器的9B缺省模型。
模型首次加载约 100 秒；后续请求复用 worker。ROS 默认域 10，HTTP 仅绑定 127.0.0.1:8080。
Ctrl+C 退出 ROS bridge，模型服务保留；模型服务使用 qwen_infer/run.sh --status/--stop 管理。
PC 使用 stage1/chat.py 或自行 ROS publish，具体命令、回复字段与排障见 [Hands-on](stage1/Hands-on.md)。

既有兼容证据：Humble、rmw_fastrtps_cpp、OpenHarmony AArch64、Linux 6.6.86、Python 3.12 ABI，
驱动 xh2a_drv v1.4.0、TCIM v2.5.0；PC Humble Docker 使用 host 网络。
2026-10-08 旧布局真实跨机常驻推理返回 2/北京，0.662/0.779 秒，同一 worker，模型图各加载一次。
2026-10-16 新布局完整部署与真实以太网 ROS 聊天、桥重启常驻复用、并发拒绝及单图 VQA 已通过，证据见 Stage 1 Hands-on；HTTP 与 ROS 分别验收。VQA 的 PC 请求方式和兼容范围见 Stage 1 Hands-on。

## Grounding DINO 360p

独立检测服务的课前准备、上传、调用和 serve 比较统一见 [Grounding DINO](stage1/GroundingDINO.md)。入口为 `stage1/prepare_dino.py`、`stage1/deploy_dino.py`；源码位于 `houmo/src/dino/`，上传包位于忽略 Git 的 `houmo/deploy/stage1/grounding_dino_infer/`，模型缓存独立于 Qwen。当前只完成本地交付检查，课程固定路径未上板验收；使用独立常驻 HTTP 服务。

Stage 1 三个 HTTP 服务的板端端口统一在根 `.env` 配置：`QWEN_PORT=8080`、`DINO_PORT=8083`、`AEROVLA_PORT=8084`（模板 `.env.example`）。部署只提取端口白名单到板端 `.env`，不传根配置中的密钥；启动入口和 Qwen backend 同步读取。

本机 SDK/toolchains、主机 Python、BOARD_WORK_DIR 和 AIRSIM_SCENE_DIR 在根 `.env` 配置。工作区通用流程见 [oh-ros2 工作区](../skills/oh-ros2/references/board-workspace.md)，skill 只保存流程和脚本。AirSim 场景本体本次未复制。

## AeroVLA 模型

仅模型推理迁移，流程和验收边界见 [AeroVLA](../houmo/src/aerovla/README.md)。源码位于 houmo/src/aerovla，模型资源位于忽略 Git 的 houmo/models/AeroVLA；prepare_aerovla.py / deploy_aerovla.py 为 PC 入口。根 .env 的 AEROVLA_PORT 固定为 8084。三个 HMM 已接收、归档并完成本地复制校验；codegen.json 因服务器权限缺失，现有模型运行入口不读取它们。完整包已通过下述上板验收；未启动仿真或执行模型动作。

2026-10-19 AeroVLA 已在 RoboPi 完成应用私有 TCIM Python 绑定、94 文件部署、vision/prefill golden 和真实 HTTP 推理/并发验收。统一 PC 部署入口为 stage1/deploy.py --service aerovla --with-smoke，HTTP 验收为 stage1/verify_aerovla.py --url <本次地址> --concurrency；细节与遗留状态只维护在 AeroVLA README。
