# Grounding DINO 板端交付与 serve 比较

## 当前接入范围

2026-10-18，吸纳 `postmo-modelzoo/grounding_dino_ohos_infer` 的 **tiny W8A8、360×640、2 cores** 运行产物，沿用 Qwen 的独立模型缓存、显式 HDC 目标、SHA-256 上传校验、相同文件跳过、不同文件拒绝覆盖。未接入 Stage 5 任务或 ROS，也未改变 Qwen 服务。

当前在本仓库 `houmo/src/dino/` 集中维护 C++、Python HTTP/前后处理、客户端和测试，编译与装配入口位于 `houmo/src/compile/`，均进入 Git。`houmo/build/` 和 `houmo/deploy/` 忽略 Git；上传内容集中于 `houmo/deploy/stage1/grounding_dino_infer/` 与 `houmo/deploy/models/`。唯一布局/编译/装配流程见 [厚摩交付](../../houmo/README.md)。

初始源码来自 modelzoo HEAD `9121ddac32d0d1a7317103a592b22f955d656050` 下尚未跟踪的 DINO 目录，初始快照摘要记录在 `houmo/src/dino/ORIGIN.json`；当前源码已吸纳到课程目录，不再依赖上游未跟踪 Python 文件。代码保留 Apache-2.0 LICENSE，模型发布来源与再分发许可仍需核实，不提供臆造公网下载地址。

## 固定端口

仓库根 `.env` 统一配置 `QWEN_PORT=8080`、`DINO_PORT=8083`、`AEROVLA_PORT=8084`，模板见 `.env.example`。这三个值是板端 HTTP 监听端口。部署入口仅提取这三个数字到板端 Stage 1 的 `.env`，不会上传根 `.env` 中的密钥。各启动入口、Qwen backend 和 PC 健康核验读取同一配置。缺少配置时兼容默认 8080/8083/8084；端口冲突或非法值会报错。修改后须重新部署配置并重启对应服务；已有不同板端配置仍按部署规则拒绝覆盖，需核实后更新。

PC 的 18080/18083 是独立的 HDC 本地转发端口，并非模型服务端口。下面的示例对应当前固定值。

## PC：课前准备与上传

前置：上游已构建并验证可复用的 OHOS dist，且该目录有 `360p/model.hmm`、`360p/tokenizer/tokenizer.json`。重新构建使用厚摩交付的本仓库编译入口，SDK 显式外部指定。以下均在课程仓库根目录执行：

```sh
python3 stage1/prepare_dino.py --source ../postmo-modelzoo/grounding_dino_ohos_infer
python3 stage1/deploy_dino.py --check-local
# 设备与 ABI、驱动、TCIM/HAL、Python 依赖按 HDC/Houmo skills 预检通过后：
python3 stage1/deploy_dino.py --target '<本次确认的connect-key>'
```

准备入口可以重复复用相同 ELF 与模型链接，拒绝覆盖不同的原生产物。已有模型由装配入口检查固定 HMM 摘要。模型在 houmo/models/ 中保存独立的真实文件；deploy 内仅链接到该仓库内的模型，上传时解引用。check-local 检查非空/LFS 指针、AArch64 ELF 头与模型摘要，不等于动态依赖或板端推理验收。

360p HMM：285448536 字节，SHA-256 `37170971fdd04800cc4b4dadda6d408e8eecb00e60542fae7b35ba1c59a7e4ea`。板端程序路径 `/data/local/workspace/stage1/grounding_dino_infer/`，模型路径 `/data/local/workspace/models/GroundingDINO-tiny-360p/`。只上传最小运行文件和 tokenizer，不传 golden/NPZ、转换参考代码、验证日志。上传失败保留输出，不自动停服务、加载驱动或安装依赖；已有不同文件需核实并备份后另行更新。

上游已有环境证据：OHOS AArch64、Linux 6.6.86、Python 3.12，xh2a v1.4.0、TCIM v2.5.0；NumPy 2.4.0、OpenCV 4.13.0、FastAPI 0.144.0、Uvicorn 0.54.0、Starlette 1.8.0。运行依赖见随包 requirements-board.txt；换设备重新核实，不直接安装 Linux wheels 或替换系统 libc++。

## RoboPi：前台启动

前置：驱动已就绪、Python 依赖及目标运行库已核验、8083 未被其他服务占用。路径按本次环境设置：

```sh
DINO_LIB_DIR='<TCIM库的绝对目录>' \
DINO_HAL_DIR='<HAL库的绝对目录>' \
sh /data/local/workspace/stage1/serve_dino.sh
```

默认只监听 `127.0.0.1:8083`。上游 worker 仅对 native 子进程清空 LD_PRELOAD，课程入口不全局修改 Python 的环境。出现 `Application startup complete` 后检查 `/health` 的 ready、busy、worker_pid。Ctrl+C 结束该前台 HTTP 服务及其 worker；本入口尚无 Qwen 的后台 status/stop 管理。勿重复启动加载第二份模型；健康接口没有部署身份和模型摘要，不能只凭 ready 自动复用其他部署。

## PC：调用

在 PC 确认目标后建立管理端口转发（HDC 不代替 DDS）：

```sh
hdc -t '<本次确认的connect-key>' fport tcp:18083 tcp:8083
curl --noproxy '*' http://127.0.0.1:18083/health
python3 houmo/src/dino/client.py \
  --url http://127.0.0.1:18083 --image /path/to/image.jpg \
  --prompt 'person. car. truck.' --threshold 0.35 \
  --output artifacts/dino/result
```

客户端只需标准库，只保存 result.json；本板业务调用 `http://127.0.0.1:8083`。HTTP 不通分别检查进程日志与转发，重连后重新核实映射。需要直接以太网 HTTP 时，可在启动命令后显式加 `--host '<本板实际地址>'`。

`POST /detect` 接收 image_base64（JPEG/PNG，无 data URL 前缀）、prompt、threshold。返回原图 width/height、detections、prompt、elapsed_ms；框为原图像素 xyxy，query_id 不是跟踪 ID，不做 NMS，不输出掩码或叠加图。空检测返回空数组。默认框阈值 0.35，token 阈值固定 0.25；输入错误 400，忙时 503，推理错误 500，请求体最多 16 MiB。不要无限排队或无条件自动重试。elapsed_ms 不代表完整取图到检测时延。

## HTTP 服务方式

| 项目 | Qwen 当前课程入口 | DINO 上游及本次入口 |
| --- | --- | --- |
| HTTP / 推理进程 | Uvicorn + 常驻 native worker | FastAPI/Uvicorn + 常驻 C++/TCIM worker |
| 生命周期 | run.sh 后台启动、status/stop；ROS 桥退出后模型保留 | run.sh 前台运行；退出时关闭 worker |
| 业务接入 | ROS 桥调用本板 HTTP；PC 用 DDS，VQA 亦可 HTTP | 本板 HTTP 或 PC 经 HDC/以太网 HTTP |
| 并发 | 模型串行，忙时 429 | 模型串行，忙时 503；健康检查可并发 |
| 身份检查 | 课程 backend 校验模型名、worker 可执行文件 | health 只有 ready/busy/worker_pid，未实现部署身份核验 |
| 数据 | 文本或视觉请求 | Base64 图片 JSON → 框 JSON |

采用独立 HTTP 服务与常驻 worker，并通过统一的 `stage1/deploy.py --service qwen|dino|aerovla|all` 装配和上传。业务方通过 HTTP 调用模型；本次未接入 Qwen 任务调度或 ROS 图像桥。DINO 仍以前台启动为主，后台启动/status/stop、部署身份检查及日志管理属于后续工作。

连续相机接入时建议调用方只保留一个推理请求和最新待处理帧；这是后续调度设计，本次未实现。上游 USB 360p 仅框历史统计：端到端平均 236.8 ms、P95 266.5 ms，纯 NPU 约 132 ms；不含相机采集/JPEG 编码，不能当作持续飞行帧率或 Qwen 与 DINO 同时运行的性能。二者同时占用 NPU 的资源、时延和稳定性尚未验证，不默认并行推理。

## 验证记录与下一步

本次只完成课程本地交付：源码归档、完整上传包装配、模型摘要与 AArch64 文件检查、Python 语法、shell 语法、本地部署清单检查；没有连接设备、上传或启动新服务。Qwen 的部署上传实现抽为共用函数，原交付清单与目的路径保持原值。

上游证据见 modelzoo 的 HANDOFF.md、REPORT_360P.md、FASTAPI_MIGRATION.md；三组样例检测可用、连续 worker 复用、健康并发及 busy 拒绝已验证，**严格 golden 逐元素比较未通过**，不能写为数据集精度通过。历史 verification 文件未复制，不随课程 clone 分发。

下一步验收：在课程固定路径实际上传校验 → health 与 worker 身份 → 正负样例及原图框坐标 → 连续请求复用/忙时拒绝/服务退出 → Qwen 同板加载与串行调用资源测试。通过后再接 Stage 5 的相机与任务链，不能沿用上游临时目录结果宣布课程链路通过。
