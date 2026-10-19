#!/usr/bin/env bash
# Docker 2：XRCE Agent、同源时钟、RGBD ROS/内部HTTP；不启动实时图像网页。
set -eo pipefail
source /opt/ros/humble/setup.bash
source /opt/px4_ws/install/local_setup.bash
set -u
export PYTHONPATH=/lesson:${PYTHONPATH:-} PYTHONDONTWRITEBYTECODE=1
export ROS_DOMAIN_ID=15 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE=/lesson/stage5/airsim/fastdds.xml
export ROS_LOG_DIR=/run/stage5/ros-logs OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
mkdir -p "$ROS_LOG_DIR" /run/stage5/node-logs
pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  wait || true
}
trap cleanup EXIT INT TERM
start() { local name=$1; shift; "$@" >"/run/stage5/node-logs/$name.log" 2>&1 & pids+=("$!"); }
start agent MicroXRCEAgent udp4 -p 8895
start clock python3 /lesson/stage3/super/airsim/clock_bridge.py
start sensors python3 -m stage5.airsim.sensors
wait -n "${pids[@]}"
exit 1
