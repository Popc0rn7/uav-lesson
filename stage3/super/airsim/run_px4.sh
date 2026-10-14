#!/usr/bin/env bash
# PC Linux：旧命令兼容入口，统一启动宿主机 AirSim 和 PX4 Docker。
set -euo pipefail
entry_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
extra=()
if [[ -n "${AIRSIM_PX4_IMAGE:-}" ]]; then
  extra+=(--image "$AIRSIM_PX4_IMAGE")
fi
exec "${AIRSIM_PYTHON:-python3}" "$entry_dir/runtime.py" up "${extra[@]}" "$@"
