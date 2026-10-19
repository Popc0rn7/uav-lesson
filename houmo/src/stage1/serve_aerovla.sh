#!/system/bin/sh
# RoboPi：模型服务前台运行；不启动仿真或执行模型输出。
set -eu
app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
: "${AEROVLA_MODEL_ROOT:=/data/local/workspace/models/AeroVLA}"
: "${TCIM_PYTHON_DIR:=$app_dir/aerovla_infer/tcim_python}"
: "${AEROVLA_LIB_DIR:?请指定本次核实的 OHOS TCIM 库目录}"
: "${AEROVLA_HAL_DIR:?请指定本次核实的 HAL 库目录}"
export AEROVLA_MODEL_ROOT TCIM_PYTHON_DIR
export LD_LIBRARY_PATH="$AEROVLA_LIB_DIR:$AEROVLA_HAL_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
port=$(python3 -B "$app_dir/service_config.py" AEROVLA_PORT)
exec python3 -B "$app_dir/aerovla_infer/service.py" --host 127.0.0.1 --port "$port" "$@"
