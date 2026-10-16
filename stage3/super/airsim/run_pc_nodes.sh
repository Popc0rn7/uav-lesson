#!/usr/bin/env bash
# 单个 PC Docker：PX4 + Agent + HIL 时钟 + 原始雷达；算法全部在 RoboPi。
set -eo pipefail
source /opt/ros/humble/setup.bash
source /opt/px4_ws/install/local_setup.bash
source /super_ws/install/local_setup.bash
export ROS_DOMAIN_ID=10 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOG_DIR=/run/airsim/pc-ros-logs PYTHONDONTWRITEBYTECODE=1
mkdir -p "$ROS_LOG_DIR" /run/airsim/pc-node-logs
if [ -f /run/airsim/profile.enabled ]; then
  export UAV_PROFILE_DIR=/run/airsim/profile
fi
pids=()
cleanup() { for pid in "${pids[@]}"; do kill -CONT "$pid" 2>/dev/null || true; kill -TERM "$pid" 2>/dev/null || true; done; wait || true; }
trap cleanup EXIT INT TERM
start() { local name=$1; shift; "$@" >"/run/airsim/pc-node-logs/$name.log" 2>&1 & pids+=("$!"); }
start agent MicroXRCEAgent udp4 -p 8888
start clock python3 /lesson-airsim/clock_bridge.py
start raw_lidar python3 /lesson-airsim/raw_lidar_bridge.py --ros-args -p task_config:=/run/airsim/task.json
start px4 bash /lesson-airsim/px4_start.sh
wait -n "${pids[@]}"
