#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source /opt/px4_ws/install/local_setup.bash
set -u
ln -s /run/airsim /run/stage4
export PYTHONPATH=/lesson:${PYTHONPATH:-} ROS_DOMAIN_ID=10 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOG_DIR=/run/stage4/ros-logs PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
mkdir -p "$ROS_LOG_DIR" /run/stage4/node-logs
pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  wait || true
}
trap cleanup EXIT INT TERM
start() { local name=$1; shift; "$@" >"/run/stage4/node-logs/$name.log" 2>&1 & pids+=("$!"); }
start agent MicroXRCEAgent udp4 -p 8888
start clock python3 /lesson/stage3/super/airsim/clock_bridge.py
start sensors python3 -m stage4.sensors --ros-args -p use_sim_time:=true
start control python3 -m stage4.control --ros-args -p use_sim_time:=true
wait -n "${pids[@]}"
exit 1  # Any node exit terminates the stack; PX4 Offboard-loss fallback remains active.
