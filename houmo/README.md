# 厚摩板端源码、编译与交付

本目录集中维护 Qwen、Grounding DINO 和 AeroVLA 的板端实现。源码和编译入口位于进入 Git 的 `src/`；`models/`、`deps/`、`build/`、`deploy/` 是忽略 Git 的本机资源或生成内容。PC 的上传、课程聊天和验收入口仍在 `stage1/`。

```text
houmo/
├── src/                         # 唯一源码维护位置，进 Git
│   ├── qwen/                    # C++、Python HTTP、启动器、客户端、测试
│   ├── dino/                    # C++、Python 前后处理/HTTP、客户端、测试
│   ├── aerovla/                 # Python TCIM 模型推理，不包含飞行编排
│   ├── stage1/                  # 课程 ROS 桥、启动与端口配置读取
│   └── compile/                 # 原生编译、导入 ELF、装配上传包的入口
├── models/                      # 独立复制的三模型、分词器及校验清单，不进 Git
├── deps/                        # modelzoo 公共源码快照、TCIM 头文件/库，不进 Git
├── build/                       # 不进 Git
│   ├── qwen/                    # 原生 ELF、lib/、CMake 缓存
│   ├── dino/                    # 原生 ELF、CMake 缓存
│   └── imported/                # 本次迁移保留的旧运行包，非维护入口
└── deploy/                      # 不进 Git；对应板端 /data/local/workspace/
    ├── stage1/
    │   ├── qwen_infer/          # ELF、运行 Python、lib、LICENSE、来源摘要
    │   ├── grounding_dino_infer/
    │   ├── aerovla_infer/
    │   ├── serve.sh / serve_dino.sh / ROS 桥等
    │   └── .env                 # 只包含三个 HTTP 端口
    └── models/                  # 链接本机模型缓存；上传时解引用
```

修改 Python、C++ 或启动脚本均修改 `src/`，不要编辑生成包。装配从这里复制运行文件；CMake、C++、测试、编译脚本、日志和根 `.env` 中的密钥都不会进入上传清单。模型实际文件集中在 `houmo/models/`，已从原机外部缓存复制成独立目录；通过 `deploy/models/` 链接这些仓库内文件，不再链接相邻模型仓库。不能把含主机绝对软链接的 deploy 直接打包给另一台 PC；换机先准备模型并重新装配。

## PC：复用已有原生产物

新 clone 需获取匹配版本的 OHOS ELF 和模型。以下在课程仓库根目录执行，不连接设备、不调用模型：

```sh
python3 houmo/src/compile/import_native.py --service qwen \
  --dist ../postmo-modelzoo/qwen_ohos_infer/dist
python3 stage1/prepare_dino.py \
  --source ../postmo-modelzoo/grounding_dino_ohos_infer
```

导入器只取目标 ELF 和 Qwen 两个 `.so` 到 `build/`，校验 AArch64 ELF 并记录摘要；已有不同产物拒绝覆盖。Python 和启动器始终使用本仓库 `src/`，不被外部 dist 改写。ELF 头检查不能证明 OHOS ABI 或源码/二进制匹配，需确认原生版本及运行库；修改 C++ 后必须重新编译，不应继续复用旧 ELF。

Qwen 模型按 [教师准备](../docs/AGENTS.md) 获取；DINO prepare 在首次准备时复制上游 360p 模型到 houmo/models。两者都保留完整模型相对结构。已有本机资源的集中复制入口如下，逐文件 SHA-256 校验且可中断重试：

```sh
python3 houmo/src/compile/copy_resources.py \
  --qwen-source ../models/Qwen3.6-35B-A3B \
  --dino-source ../postmo-modelzoo/grounding_dino_ohos_infer/360p \
  --modelzoo-source ../postmo-modelzoo
```

校验记录为 houmo/models/RESOURCES.json。这里只复制资源，不修改源缓存，不执行模型或联网下载；模型、SDK 和公共依赖快照不进 Git。

## PC：重新编译

原生编译遵循 [oh-houmo](../skills/oh-houmo/SKILL.md)，先核验 OHOS SDK、TCIM 头文件/目标库和依赖。根 `.env` 配置 OHOS_SDK、OHOS_TOOLCHAINS_DIR、TCIM_RUNTIME_PATH、HOUMO_MODELZOO_ROOT；build.sh 自动读取，环境变量优先。Native SDK 与 toolchains/hdc 所在目录是两个独立路径；toolchains 指向 ../version-…/ohos-sdk/linux/toolchains-…/toolchains，SDK 不复制进本仓库。下面是 Qwen/DINO 编译入口；本次复用这两个应用的原生 ELF，AeroVLA 私有 Python 绑定另行构建：

```sh
bash houmo/src/compile/build.sh qwen
bash houmo/src/compile/build.sh dino
```

本仓库维护两个应用的 main.cc/CMake；Qwen 公共 houmo_engine、qwen35 模型实现、tokenizer、Eigen、CMake 等已经复制成 `houmo/deps/modelzoo/` 独立快照，TCIM 头文件与库位于 `houmo/deps/tcim/`。默认 .env 指向这两处，编译不再读取相邻 modelzoo。依赖快照包含原始许可证，摘要在 RESOURCES.json；这些第三方快照不进入 Git，换机需按复制入口或发行包准备。应用初始源码身份仍见各自 ORIGIN.json，Qwen Python 保留课程原有 Uvicorn 实现，本次未升级为上游新版 FastAPI。

主机 `.board-work` 的通用核验流程和脚本维护在 [oh-ros2 工作区说明](../skills/oh-ros2/references/board-workspace.md)。根 `.env` 的 BOARD_WORK_DIR 指定当前项目缓存位置，OHOS_HOST_PYTHON 可显式复用已核验的现有 venv；不把 SDK、venv、旧日志或目标快照放进 skill。Stage 3 prepare.py 未显式传 --sdk/--host-python 时使用这些路径；已有构建配置不会被此整理偷偷改写。

## PC：装配、检查与上传

```sh
# 三个服务装配到同一上传根目录，可重复执行
python3 houmo/src/compile/package_runtime.py
# 或只装配一个：--service qwen / dino / aerovla
python3 stage1/deploy.py --check-local
python3 stage1/deploy_dino.py --check-local
# 设备及依赖预检通过后，显式选择本次目标：
python3 stage1/deploy.py --target '<connect-key>'
python3 stage1/deploy_dino.py --target '<connect-key>'
```

部署入口会先重新装配，并只从 `houmo/deploy/` 的显式清单上传，板端目的路径保持原值。相同文件跳过，不同文件拒绝覆盖；不自动停服务、装依赖或改驱动。生成包内 `SOURCE.json` 记录本次源码和 ELF 摘要。装配可更新已生成的运行文件，禁止手工往 deploy 存放需保留的源码。各服务不互相清空目录。

根 `.env` 中固定 `QWEN_PORT=8080`、`DINO_PORT=8083`、`AEROVLA_PORT=8084`，部署只提取这三项到 `deploy/stage1/.env`；启动入口、Qwen backend 和健康核验统一读取。PC HDC 转发端口是独立选择的本地端口。

板端 Qwen 启动仍为 `cd /data/local/workspace/stage1 && sh serve.sh`。DINO 启动、输入输出契约、依赖及性能边界见 [Grounding DINO](../docs/stage1/GroundingDINO.md)；课程操作与历史板端证据见 [Hands-on](../docs/stage1/Hands-on.md)。

## 验证范围（2026-10-19）

8 项装配回归、5 项 AeroVLA 服务回归通过；Qwen 46 / DINO 16 / AeroVLA 21 个本地运行文件检查通过，AeroVLA 加 smoke 后为 94 个文件。Python/shell 语法、9 个 AirSim runtime 的路径解析及环境覆盖、Git 忽略边界均已检查；没有启动 AirSim。

Qwen/DINO 本次完成源码迁移与本地交付检查，未对新生成包进行上板验收；历史结果不能替代新包验收。当前 PC 缺少 FastAPI/OpenCV，DINO HTTP 测试未能加载；Qwen 上游测试 28 项中 23 项通过、3 项依赖缺失跳过、2 项因沙箱 socket 限制报错，未记为全部通过。

Qwen、DINO 及公共依赖独立复制后逐文件 SHA-256 校验通过，记录在 houmo/models/RESOURCES.json。skill 主机环境核验记录在 .board-work/host-environment.json；SDK 26.0.1.45 Beta1，主机 Python 3.12.11 / NumPy 2.2.6。已有主机 venv 通过 .env 复用，没有搬移或重新安装。artifacts 的历史证据留待单独整理。

## AeroVLA 模型接入

推理源码、准备/上传/调用、固定端口和三图接收记录统一见 [AeroVLA](src/aerovla/README.md)。`package_runtime.py --service all` 现在包括 AeroVLA，三个 HMM 已接收并归档校验，当前可装配完整模型运行包；仍可显式选择 --service qwen / dino / aerovla。HF 参考权重与 golden 不默认上传。

## 统一部署入口

PC 使用 `python3 stage1/deploy.py --service qwen|dino|aerovla|all --target <本次设备>`；默认仍是 qwen。`--check-local` 仅装配检查，AeroVLA/all 可加 `--with-smoke` 上传验收数据。兼容的 deploy_dino.py/deploy_aerovla.py 委托同一实现。AeroVLA 私有 Python 绑定的构建、golden 和 HTTP 检查见其 README。

### AeroVLA 实际上板结果（2026-10-19）

统一部署和真实 HTTP smoke 已通过。Vision/prefill golden cosine 分别为 0.99855 / 0.99999962，HTTP 固定请求约 1.8 秒，实例复用、非法输入 400、忙时 503 与健康并发通过。服务保留运行于本次设备 192.168.2.100:8084；没有执行动作。经授权并核验 PC 副本后清理了板端 Qwen9B/SAM3，保留 35B 和 DINO。完整身份、证据及边界以 [AeroVLA 验收记录](src/aerovla/README.md#板端验收2026-10-19) 为准。
