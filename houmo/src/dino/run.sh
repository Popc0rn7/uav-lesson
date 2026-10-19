#!/system/bin/sh
set -eu
app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
: "${DINO_MODEL_DIR:=$app_dir/bundle}"
: "${DINO_TOKENIZER:=$app_dir/tokenizer}"
: "${DINO_PYTHON:=python3}"
export LD_LIBRARY_PATH="$app_dir/lib${DINO_LIB_DIR:+:$DINO_LIB_DIR}${DINO_HAL_DIR:+:$DINO_HAL_DIR}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$DINO_PYTHON" "$app_dir/server.py" --model "$DINO_MODEL_DIR/model.hmm" --tokenizer "$DINO_TOKENIZER" "$@"
