# Houmo M50 on RoboPi — historical platform reference

Extracted intact from the former robopi-hdc reference on 2026-10-08. Hardware IDs, kernel, package layout, and workaround describe that platform; verify current vendor documentation and target state before applying them.

Use this order: hardware enumeration, driver compatibility, driver load, HAL/runtime smoke test, example inference, then application integration. Do not begin with a large LLM model.

## Known hardware and software identity

On the validated RoboPi/OpenHarmony image:

- The external M50/xh2 PCIe endpoint enumerates as vendor/device `1f6b:0c00`, class `0x058000`.
- The board kernel is `6.6.86` on `aarch64`.
- The supplied `houmo-sdk.tar.gz` contains `houmo-sdk/xh2a_drv.ko`, HAL libraries, `pcie_test`, and other utilities.
- The supplied kernel module reports driver version `v1.4.0`, alias `pci:v00001F6Bd00000C00...`, and vermagic `6.6.86 SMP mod_unload aarch64`.
- The supplied `houmo.tar.gz` contains the TCIM runtime, including `libtcim_runtime_lite.so` and `bin/get_devices`.
- The supplied executables are ARM64 OpenHarmony/musl binaries.

Re-check all identities after changing the system image or vendor packages. Do not assume a `.ko` remains compatible merely because its architecture matches; compare complete `uname -r` and module `vermagic` before `insmod`.

## Stage 1: enumerate without changing state

```sh
hdc -t '<target>' shell 'lspci; cat /sys/bus/pci/devices/0000:01:00.0/vendor; cat /sys/bus/pci/devices/0000:01:00.0/device; readlink /sys/bus/pci/devices/0000:01:00.0/driver'
```

The minimal success condition is `0x1f6b` and `0x0c00`. An empty driver symlink means the endpoint is visible but no kernel driver is bound.

The RoboPi `lspci` is a minimal implementation: options such as `-s` or `-vv` may be unsupported, and a missing `/usr/share/misc/pci.ids` only removes friendly names.

## Stage 2: inspect packages on the host

Inspect archives before deploying:

```sh
tar -tzf houmo-sdk.tar.gz
tar -tzf houmo.tar.gz
modinfo '<extracted-path>/houmo-sdk/xh2a_drv.ko'
file '<extracted-path>/houmo-sdk/xh2a_drv.ko'
sha256sum houmo-sdk.tar.gz houmo.tar.gz
```

Treat the deployment-path table in `OpenHarmony 部署及示例编译方法 （外发版）.md` cautiously: its two recommended paths appear swapped relative to later commands. Use these consistent paths unless the package's own release notes say otherwise:

- Driver/HAL package `houmo-sdk` → `/data/local/houmo-sdk`
- TCIM runtime package `houmo` → `/data/local/houmo`
- Models and examples → `/data/houmo/`

## Stage 3: deploy and load the driver

Transfer versioned archives or extracted directories, verify them, then load `xh2a_drv.ko`. `insmod` changes live kernel state and requires explicit user approval. Capture output and immediately verify:

```sh
lsmod | grep xh2a_drv
readlink /sys/bus/pci/devices/0000:01:00.0/driver
dmesg | tail -n 200
```

Do not configure automatic boot loading until manual loading and recovery have been tested. If `insmod` fails, record its exact error and the bounded kernel log; do not force-load an incompatible module.

## Stage 4: smoke-test before inference

Set `LD_LIBRARY_PATH` to the deployed TCIM and HAL library directories. Run the smallest vendor checks first:

1. `houmo-sdk/utility/pcie_test` or a read-only system-info utility.
2. `houmo/bin/get_devices`.
3. A small vendor sample that does not require a multi-gigabyte model.

Confirm device discovery, stable kernel logs, and repeatability across multiple runs. Only then deploy an `.hmm` model and `houmo-examples-xh2`.

## Stage 5: inference and compilation

For the documented Qwen example, deploy the prefill/decode `.hmm` files, tokenizer JSON, quantized embedding, and `houmo-examples-xh2`; source its OpenHarmony environment and run the demo with explicit absolute paths.

Cross-compile on x86 Linux using the OpenHarmony native SDK, `OHOS_ARCH=arm64-v8a`, `HOUMO_TARGET=xh2`, and library paths from the exact deployed vendor package version. Keep the SDK/image ABI aligned. The source document targets OpenHarmony 6.0.x while the validated workstation SDK/image may be newer, so verify rather than assume compatibility.

When old Eigen code fails with `invalid output constraint '+g,w'`, define `EIGEN_NO_OPTIMIZATION_BARRIER` for the OHOS build as documented. Treat this as a source compatibility workaround, not a runtime or NPU fault.

## Acceptance gates

Advance only when the current gate passes:

1. PCIe: endpoint `1f6b:0c00` is present.
2. Kernel: module vermagic matches and driver binds to the endpoint.
3. Runtime: `get_devices` reports the accelerator and vendor smoke tests pass.
4. Model: sample inference produces correct output without kernel errors.
5. Integration: a locally cross-compiled minimal C++ program links, deploys, and repeats the same result.

## 后续故障证据（2026-10-16）

同为内核 6.6.86、驱动 v1.4.0 且模块 SHA 匹配的一次启动，模块成功加载，但 PCIe 未绑定；内核报 `dma_alloc_coherent failed for wr channel 7`、`hdma_init failed -12`，CMA 请求 512 pages 失败。`get_devices --num xh2` 返回 0，模型启动器拒绝加载图。该镜像 CmaTotal 为 8 MiB；MemAvailable 仍约 6.6 GiB，不能据总空闲内存推断连续 DMA 分配一定可用。当前内核没有 `/proc/sys/vm/compact_memory`，不得假定 compaction 接口存在。

此时先核对是否真实绑定、实际工具帮助和 bounded kernel log，不把“模块在 lsmod 中”记作 runtime ready，不反复加载大模型。重启或更改内核/CMA/启动配置分别需要当前任务对具体动作的授权；重启后早期加载是否解决须重新实测。本次仍待复验，不能写成恢复方案已通过。

当前 get_devices 帮助要求后端参数，可用 `--num xh2`；直接无参数返回 usage。运行独立厂商诊断时清理本进程的导航 `LD_PRELOAD`，再设置其实际 HAL/TCIM 库路径，避免把无关导航库解析失败误判为 NPU 故障。

2026-10-16 后续复验：经用户明确授权重启后，在 uptime 147 秒先加载同一个已核验模块，PCI 成功绑定 `houmo,xh2a`，`get_devices --num xh2` 返回 1。随后 Qwen ready、两次 ROS 文本及单图 VQA 通过。内核仍有部分 CMA 分配警告，故不能仅凭警告行判断 probe 失败；结合 PCI 绑定、runtime 枚举和真实推理判断。未修改内核、CMA 启动参数或系统库。
