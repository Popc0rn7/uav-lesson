#!/usr/bin/env bash
# Docker 2 专用诊断入口；不加载 SUPER、雷达桥或正常控制适配器。
set -eo pipefail
source /opt/ros/humble/setup.bash
source /opt/px4_ws/install/local_setup.bash
source /super_ws/install/local_setup.bash
export ROS_DOMAIN_ID=10 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export PYTHONDONTWRITEBYTECODE=1 ROS_LOG_DIR=/run/airsim/ros-logs
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
mkdir -p /run/airsim/node-logs "$ROS_LOG_DIR"
python3 - <<'PY'
import json
from pathlib import Path
task=json.loads(Path('/run/airsim/task.json').read_text())
Path('/run/airsim/response_profile.json').write_text(json.dumps(task['_diagnostics_response'],indent=2))
PY
pids=()
cleanup() { for pid in "${pids[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done; wait || true; }
trap cleanup EXIT INT TERM
start() { local name=$1; shift; "$@" >"/run/airsim/node-logs/$name.log" 2>&1 & pids+=("$!"); }
start agent MicroXRCEAgent udp4 -p 8888
start clock python3 /lesson/stage3/super/airsim/clock_bridge.py
start response python3 /lesson/stage3/super/airsim/diagnostics/response_node.py --ros-args -p use_sim_time:=true
wait -n "${pids[@]}"
