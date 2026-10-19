#!/system/bin/sh
# RoboPi：复用上游前台服务；驱动与依赖需已准备。
set -eu
app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
: "${DINO_MODEL_DIR:=/data/local/workspace/models/GroundingDINO-tiny-360p}"
: "${DINO_TOKENIZER:=$DINO_MODEL_DIR/tokenizer}"
: "${DINO_LIB_DIR:?请指定本次核实的 OHOS TCIM 库目录}"
: "${DINO_HAL_DIR:?请指定本次核实的 HAL 库目录}"
export DINO_MODEL_DIR DINO_TOKENIZER DINO_LIB_DIR DINO_HAL_DIR
dino_port=$(python3 -B "$app_dir/service_config.py" DINO_PORT)
exec sh "$app_dir/grounding_dino_infer/run.sh" --host 127.0.0.1 --port "$dino_port" "$@"
