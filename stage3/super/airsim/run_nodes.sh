#!/usr/bin/env bash
# Docker 2：仅 AirSim 后端；默认启动后待命，PC 的 task 动作才请求起飞。
set -eo pipefail
source /opt/ros/humble/setup.bash
source /opt/px4_ws/install/local_setup.bash
source /super_ws/install/local_setup.bash
set -u
export ROS_DOMAIN_ID=10 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOG_DIR=/run/airsim/ros-logs PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
mkdir -p "$ROS_LOG_DIR" /run/airsim/node-logs
HERE=/lesson/stage3/super/airsim
TASK=/run/airsim/task.json
python3 "$HERE/planner_config.py" "$TASK" /run/airsim/planner.yaml
pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  wait || true
}
trap cleanup EXIT INT TERM
start() { local name=$1; shift; "$@" >"/run/airsim/node-logs/$name.log" 2>&1 & pids+=("$!"); }
start agent MicroXRCEAgent udp4 -p 8888
start clock python3 "$HERE/clock_bridge.py"
start px4 python3 /lesson/stage3/super/super_px4.py --ros-args -p use_sim_time:=true \
  -p lidar_height_required:=false -p airsim_task_config:="$TASK"
start lidar python3 "$HERE/lidar_bridge.py" --ros-args -p use_sim_time:=true -p task_config:="$TASK"
start planner ros2 run super_planner fsm_node --ros-args -p use_sim_time:=true -p config_name:=/run/airsim/planner.yaml
start mission python3 "$HERE/waypoint_task.py" --ros-args -p use_sim_time:=true -p task_config:="$TASK"
wait -n "${pids[@]}"
