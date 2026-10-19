# AeroVLA 模型推理迁移

只处理模型推理：输入已预处理的图像张量及文本 token，输出文本、token ID、动作数值与停止提示，不启动 AirSim、不连接 PX4、不执行动作。不是标准 OpenVLA 的 7 维动作头接口。本次保留用户提供 runner 的双视觉→prefill→decode/KV 共享路径，加入独立路径配置、串行请求和输入校验；未重新量化或转换模型。

## 文件布局与身份

- `houmo/src/aerovla/`：受维护的 Python runner、HTTP 服务、客户端、离线 smoke、测试；初始来源摘要见 ORIGIN.json。
- `houmo/models/AeroVLA/assets/`：embedding、词表及推理配置的真实副本。
- `houmo/models/AeroVLA/golden/`：vision/prefill golden，供后续板端比较，不默认上传。
- `houmo/models/AeroVLA/reference_hf/`：合并 HF 权重及原始 processor/tokenizer，只作参考，不默认上传。不是可直接交给 TCIM 的 HMM。
- `houmo/models/AeroVLA/samples/request.json`：用户包内的一次预处理请求，用于协议复验，不是课程相机输入验收。
- `houmo/models/AeroVLA/models/`：vision/prefill/decode 三个 HMM 的独立真实副本。
- `houmo/deploy/stage1/aerovla_infer/` 与 `houmo/deploy/models/AeroVLA/`：装配生成的上传内容，忽略 Git。
- 用户原包保存在 `houmo/build/imported/aerovla_infer/`（忽略 Git），包括未吸纳的仿真编排器、调试文件及含原机路径的轨迹准备脚本，不作为源码维护入口。

原包没有给出许可证和转换版本，模型/源码分发许可需另行核实；没有套用 Qwen 或 modelzoo 的 LICENSE。HF 模型的合并日志不是 HMM 编译身份或数值精度证明。embedding 实际为 FP16 `[32064,4096]`，配置有效词表为 32001；runner 限制 greedy token 在有效词表内，保留图的 padding 行。

## 当前 HMM 与缺少的 JSON

用户已从 `ipads4090:/mnt/disk2/wqy/vla_out/hmm` 传回三个 HMM，迁入 `houmo/models/AeroVLA/models/`：

```text
aerovla_vision.hmm
aerovla_prefill.hmm
aerovla_decode.hmm
```

这三个图的原始接收副本归档在 `houmo/build/imported/aerovla-hmm-rsync/`。本地文件和模型目录副本逐文件 SHA-256 一致，摘要及大小在 RESOURCES.json。文件头均为 HMM0；这不等于图的 I/O、TCIM 版本或数值一致性验收。

本次 rsync 对三个 `*.codegen.json` 报远端 Permission denied，整体退出 23。当前 runner 和随包 TCIM Python 的 runtime.load 接口只加载 HMM，不读取这些 sidecar JSON，因此它们缺失不阻止本地运行包装配；这些 JSON 可用于补充编译信息，后续有权限时再归档。没有独立获取服务器原文件的 SHA-256，不能把本地复制一致写成远端逐字节认证。其后已完成三图板端加载、golden 和真实 HTTP 验收，说明当前运行链路无需这些 sidecar JSON。

## PC：准备和检查

以下在课程仓库根执行，不调用设备或模型：

```sh
# 本机资源已复制；重新准备可重复校验已有文件。
python3 stage1/prepare_aerovla.py \
  --source houmo/build/imported/aerovla_infer \
  --hf-source ../models/aerovla \
  --hmm-dir houmo/build/imported/aerovla-hmm-rsync
python3 stage1/deploy.py --service aerovla --check-local
# 也可通过统一入口：
python3 houmo/src/compile/package_runtime.py --service aerovla
```

准备脚本逐文件 SHA-256 校验，记录 RESOURCES.json；不复制训练、仿真和远程登录配置。HF 权重可省略 --hf-source；已有的参考权重不会被当成运行图。AeroVLA 使用匹配目标 Python ABI 的 tcim_lite，模型本身不需要另编 C++ worker，也不提供伪造的 HF→HMM 转换入口。当前板端全局 Python 包缺少 pytcim，已通过 SDK 源码构建应用私有绑定，编译入口为 houmo/src/compile/build_tcim_python.py；这与 HMM 编译是两件事。HMM 必须由已有转换流程提供，确认 vision、prefill、decode 属于同一模型/量化批次并共享兼容 cache。

运行资源应具备 vision 输入 `[1,6,224,224]`、视觉输出 `[1,256,4096]`、prefill chunk 512、32 层 KV cache `[1,32,1024,128]`。当前配置最多生成 8 个 token，99 档数值动作。实际 TCIM 元数据已核验：vision 1 core；prefill/decode 2 cores，prefill 输入 [1,512,4096]、decode [1,1,4096]，logits [1,1,32064]，K cache 为 INT8、V cache 为 FP16。原包 meta_info.json 中的 256 是旧记录，运行时以图接口为准，不修改原始资源。

## 上传与启动

HMM、本机清单和 HDC/Houmo 设备依赖预检通过后，在 PC：

```sh
python3 stage1/deploy.py --service aerovla --with-smoke --target '<本次确认的connect-key>'
```

复用已有 SHA-256 上传实现，显式设备，相同文件跳过、不同文件拒绝覆盖。普通部署传模型运行 Python、应用私有 TCIM Python 绑定、三张 HMM、四项运行 assets 及端口配置（21 个文件）；--with-smoke 额外传 golden、固定请求和 smoke.py（共 94 个文件）。不传 HF 权重或训练/仿真代码。板端模型根为 `/data/local/workspace/models/AeroVLA/`。

根 `.env` 使用 `AEROVLA_PORT=8084`，与 Qwen 8080、DINO 8083 分开；三个端口不能重复。上传 `.env` 只包含这三个数字。板端前台启动，库路径按本次设备核实：

```sh
AEROVLA_LIB_DIR='<OHOS TCIM lib目录>' \
AEROVLA_HAL_DIR='<OHOS HAL lib目录>' \
sh /data/local/workspace/stage1/serve_aerovla.sh
```

需已准备 NumPy、tcim_lite、NPU 驱动及匹配 TCIM/HAL。不安装 PyPI 同名包替代 SDK tcim_lite，不自动加载/替换驱动。入口追加运行库路径，默认使用应用自带的 tcim_python，不替换全局 TCIM/Python；若显式覆盖 TCIM_PYTHON_DIR，须重新核验 ABI。默认监听 127.0.0.1，前台退出即停止服务，未提供后台 status/stop，也未验证与 Qwen/DINO 同时加载时的资源。

## 调用契约

`GET /health` 返回 status=ready、model=aerovla、busy。`POST /infer` 接受：

- `input_ids`：非空整数列表，范围 `[0,32000]`。与视觉 256 token、生成预算合计不得超过 1024。
- `pixel_values_shape`：固定 `[1,6,224,224]`。
- `pixel_values_b64`：little-endian float32 张量字节的纯 Base64，禁止 NaN/Inf。不是 JPEG/PNG。

服务尚未提供任意文字 tokenization 或原始相机预处理；必须复用原模型 processor 的两套视觉预处理，不能只 resize/单套 normalize。输入校验错误 400、过大请求 413、模型忙 503、推理错误 500；请求体上限 4 MiB。一个模型实例串行推理，健康接口可并发；占用端口时不先加载第二份模型。

在服务就绪并建立 PC 18084→板端8084 HDC 映射后：

```sh
python3 houmo/src/aerovla/client.py \
  --url http://127.0.0.1:18084 \
  --request houmo/models/AeroVLA/samples/request.json \
  --output artifacts/aerovla/result.json
```

返回 `action: {fwd,down,yaw}`、should_stop、text、gen_ids。fwd 映射 `[0,5]`、down `[-5,5]`、yaw `[-1.1,1.1]`，是原模型数值语义，不是课程 PX4 速度接口；停止提示不是已执行降落。无动作解析能力或闭环效果验收保证。

## 板端验收（2026-10-19）

已在本次 USB 核实的 SysLong RoboPi（Linux 6.6.86 AArch64、Python 3.12.12 / SOABI cpython-312-aarch64-linux-ohos、NumPy 2.4.0、TCIM v2.5.0）完成实际部署和模型验收。应用私有 pytcim 已按目标头文件/libpython 交叉编译并通过真实 import，不替换板端全局库。默认全局 tcim_lite 缺少 pytcim 的首次预检失败已通过此私有依赖方案解决。

| 验收项 | 实际结果 |
| --- | --- |
| 三图及运行资源上传 | 94 个文件（含 --with-smoke）传输与 SHA-256 校验通过 |
| Vision golden | 输出 [1,256,4096]，cosine 0.9985496374，通过原门限 0.98 |
| Prefill golden | 68 个输入全部匹配，logits [1,1,32064]，cosine 0.9999996219，通过原门限 0.98 |
| HTTP 完整生成 | 两次固定请求结果一致，8 个生成 token，覆盖 vision→prefill→decode；约 1.86 / 1.82 秒 |
| 常驻复用 | pid、instance_id 在请求前后保持一致 |
| 错误/并发 | 非法输入 400；真实推理期间 health 返回 busy=true，约 53 ms；竞争推理 503，主请求 200 |
| 本机回归 | 8 项装配测试、5 项模型/严格 smoke 测试通过 |

耗时为 PC 固定已预处理张量经以太网请求到 JSON 回复的 smoke 记录，包含 HTTP/序列化及模型执行，不含相机采集、原始图像预处理或文本 tokenization，不是吞吐基准。模型输出文本为 `96▁49▁48`，解析 fwd≈4.89796、down=0、yaw≈-0.02245、should_stop=false；输出只保存，没有执行任何飞行或仿真动作。

按用户授权，清理前逐文件核对了 PC Qwen9B 副本（27 文件全部匹配）、SAM3 模型副本，并收回 SAM3 推理代码备份；随后删除板端 Qwen9B 模型及 SAM3 模型/推理目录。共享 Qwen 推理工具仍供 35B 使用，35B 模型保留，DINO 服务保持 ready。本次结束 /data 可用约 4.8 GiB。

当前 AeroVLA 服务保留运行于 `http://192.168.2.100:8084`（本次设备地址，不写死为其他设备的默认值）。板端日志 `/data/local/workspace/stage1/aerovla_infer/http-20261019.log`，进程身份记录 `http-20261019.pid.json`；本次 PID 14964 仅为历史索引，后续停止或重启必须重新核对 /proc 的 start_ticks 和 service.py 路径，不按旧 PID 操作。

证据 run ID 为 `board-http-20261019`，本机报告目录为 `artifacts/aerovla/board-http-20261019/`：run-identity.json 汇总源码提交/dirty 状态、实际模型/绑定身份与报告；deploy.log、vision/prefill/decode-model-info.txt、vision/prefill-smoke.log、golden-smoke.json、http-smoke-unified.json、final-snapshot.json 分别记录部署、图接口、数值结果、HTTP 与残留状态；authorized-cleanup.json 和 backup-check 报告记录清理及可恢复副本。日志/二进制不进 Git，不随 clone 分发。

后续仍需验证更多输入、原始图像/任意文本的预处理、长期资源稳定性、Qwen35B 与 AeroVLA 并行加载。导航/飞行闭环完全不在本次验收范围。

## 统一部署与上板验收入口

PC 统一入口为 `stage1/deploy.py --service qwen|dino|aerovla|all`，旧 deploy_dino.py/deploy_aerovla.py 只作兼容委托。`--with-smoke` 用于 AeroVLA 或 all，`--check-local` 不连接设备。当前板端全局 tcim_lite 缺少原生扩展，私有绑定复用 SDK pytcim.cc，链接当前目标 libpython3.12.so.1.0；不能将 Linux Python 扩展改名后上板。

PC 构建私有绑定（前置：当前设备 ABI 与目标头文件/库快照已核验，依赖预检通过）：

```sh
python3 houmo/src/compile/build_tcim_python.py \
  --python-include artifacts/robopi-stage3/target/deps/out/include/python3.12 \
  --pybind11-include artifacts/robopi-stage3/target/deps/install/include/moveit/python
```

输出为忽略 Git 的 houmo/build/aerovla/tcim_python，含 Python 3.12 OHOS AArch64 扩展和 BUILD.json。板端 smoke（模型和 --with-smoke 数据已上传，库目录按本次核实值设置）：

```sh
TCIM_PYTHON_DIR=/data/local/workspace/stage1/aerovla_infer/tcim_python \
LD_LIBRARY_PATH='<TCIM lib>:<HAL lib>:<板端Python运行库目录>' \
python3 -B /data/local/workspace/stage1/aerovla_infer/smoke.py \
  --model-root /data/local/workspace/models/AeroVLA \
  --report /data/local/workspace/stage1/aerovla_infer/golden-smoke.json
```

smoke 要求所有图输入唯一匹配、形状一致，不忽略未匹配的 golden，也不会把 NaN/Inf 归零后通过。vision/prefill cosine 门限仍为 0.98；完整视觉→prefill→decode 由 HTTP 固定请求另验。服务启动后 PC：

```sh
python3 stage1/verify_aerovla.py \
  --url http://'<本板地址>':8084 --concurrency \
  --report artifacts/aerovla/http-smoke.json
```

这项 HTTP 检查发送非法请求和两次真实模型请求，--concurrency 再增加一次主请求及一次竞争请求验证 503，核验健康响应、输出字段和 pid/instance_id 常驻复用；记录实际输出，不执行动作。默认服务只监听本板回环，若直接以太网测试需在启动命令末尾显式指定 `--host '<本板地址>'`；也可保持回环并使用 HDC fport。
