# RoboPi 环境准备流程

按实际环境准备；构建、部署和设备验证采用对应 HDC/ROS/Houmo 技能。课程目标见 [roadmap.md](roadmap.md)。

## 文件位置

- stage1/chat.py：PC 聊天入口。
- stage1/deploy.py：PC 固定部署入口，无命令行参数；必须显式填写本次设备 TARGET，留空会拒绝连接。
- stage1/download_model.py：PC 课前下载模型。
- stage1/robopi/：板端待传文件，内容对应 /data/local/workspace/stage1/。
- stage1/robopi/qwen_infer/：上游运行工具，忽略 Git；不在本仓库维护其源码。
- artifacts/models/：本机模型与 embedding 缓存，可以使用软链接。
- src/：仅供跨阶段通用代码使用，目前没有需要建立的内容。

## 1. PC：获取上游运行产物

PC 无原生 ROS 时，先按 [Hands-on：课前拉取 ROS Humble 镜像](stage1/Hands-on.md#pc课前拉取-ros-humble-镜像) 完成 Docker 镜像下载、自检并记录摘要。此步骤在教师准备阶段完成。

前置条件：上游已完成目标 OpenHarmony 构建并验证版本。本工作区来源为 ../postmo-modelzoo/qwen_ohos_infer/dist。
在课程仓库根目录执行：

```sh
mkdir -p stage1/robopi/qwen_infer
cp -a ../postmo-modelzoo/qwen_ohos_infer/dist/. stage1/robopi/qwen_infer/
cp ../postmo-modelzoo/LICENSE stage1/robopi/qwen_infer/LICENSE
```

应包含 qwen_ohos_infer、lib/、run.sh、run.py、models.json、server.py、vqa_client.py、requirements-server.txt 和 LICENSE。
这些 Python/启动脚本是上游工具的运行依赖，只随产物交付，不复制到 src 或另行维护。
2026-10-15 已将上游 VQA 修复同步到本工作树忽略的运行产物；上游旧发布归档仍是历史文本版，后续准备应使用更新并验证过的 dist。
当前 requirements-server.txt 要求 uvicorn==0.54.0；板端环境需匹配 Uvicorn/h11、TCIM/HAL 和系统库。
新 PC clone 后不会自动带有这些本地产物；缺少文件时部署脚本会停止。
需要重新编译或导出 embedding 时使用上游流程，不保存 main.cc、工具链、转换脚本副本。

## 2. PC：准备模型

已有模型链接：artifacts/models/Qwen3.6-35B-A3B → ../../../models/Qwen3.6-35B-A3B。
embedding 已在模型目录的 hmquant/quant_embedding.bin 中，不需要额外链接；不要修改共享缓存。
无缓存时，PC 需 ModelScope、发布方确认的固定版本和下载许可：

```sh
python3 stage1/download_model.py --revision '<固定版本>'
```

下载来源为 Houmo/xh2_qwen3.6_35b-a3b_256k。已有目录/链接拒绝覆盖。
模型卡声明 Apache License 2.0；具体发布版本及分发许可需核实，本机旧缓存没有固定版本记录。
若缺 FP16 embedding，按上游 prepare_embedding.py 生成，输出到所用模型目录的 hmquant/quant_embedding.bin。
文本推理所需图及 embedding 约 21.3 GB；VQA 还需要 *_visual_m*.hmm 动态视觉图，缺失时部署入口拒绝继续。部署传整个模型目录，按实际目录总大小预留空间。模型获取/转换放在课前，不提交 Git。

## 3. PC：部署

前置条件：明确目标设备；核对 HDC、目标镜像、ROS、驱动、HAL/TCIM、模型版本和空间。
HDC 不默认经以太网接入。板端根目录由 deploy.py 顶部常量确定：

```sh
python3 stage1/deploy.py
```

程序及板端脚本传到 /data/local/workspace/stage1/；模型传到
/data/local/workspace/models/qwen3.6-35b-a3b_w4a8_256_256k_b1_1chip_2cores/。
整个模型目录按原相对路径传输，包括图文件、hmquant 配置及其中的 embedding，不再单独收集文本图或 embedding。
脚本直接检查固定文件，没有打包脚本或 manifest 依赖；创建缺失的父目录。
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
新布局的 HTTP 文本与 VQA 已单独实测；文件重组后的完整 ROS 跨机聊天链路仍待重新验收，不能把 HTTP 验证当作 ROS 验收。VQA 的 PC 请求方式和兼容范围见 Stage 1 Hands-on。
