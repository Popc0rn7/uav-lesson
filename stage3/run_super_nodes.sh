#!/bin/bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source /gcopter_install/local_setup.bash
if [[ -f /lio_ws/install/local_setup.bash ]]; then source /lio_ws/install/local_setup.bash; fi
source /super_ws/install/local_setup.bash
if [[ -f /super_ws/install-prefilter/local_setup.bash ]]; then source /super_ws/install-prefilter/local_setup.bash; fi
export LD_LIBRARY_PATH=/gcopter_install/xrce_agent/lib:${LD_LIBRARY_PATH:-}
export PYTHONDONTWRITEBYTECODE=1
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOG_DIR=/tmp/stage3-ros-logs
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
mkdir -p /tmp/stage3-node-logs
pids=()
cleanup() { for pid in "${pids[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done; wait || true; }
trap cleanup EXIT INT TERM
start() { local name=$1; shift; "$@" > "/tmp/stage3-node-logs/$name.log" 2>&1 & pids+=("$!"); }
start agent /gcopter_install/xrce_agent/bin/MicroXRCEAgent udp4 -p 8888
if [[ ${STAGE3_CORRIDOR:-false} == true ]]; then
  start imu ros2 run ros_gz_bridge parameter_bridge '/world/corridor/model/x500_experiment_0/link/super_fcu_imu_link/sensor/super_fcu_imu/imu@sensor_msgs/msg/Imu[gz.msgs.IMU' --ros-args -r /world/corridor/model/x500_experiment_0/link/super_fcu_imu_link/sensor/super_fcu_imu/imu:=/stage3/uav1/imu_raw
  start imu_clean python3 /lesson/stage3/super_imu.py --ros-args -p use_sim_time:=true
  start sensors ros2 run ros_gz_bridge parameter_bridge '/world/corridor/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock' \
    --ros-args -r /world/corridor/clock:=/clock
else
  start sensors ros2 run ros_gz_bridge parameter_bridge '/world/default/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock' \
    '/mid360s/scan/points@sensor_msgs/msg/PointCloud2[gz.msgs.PointCloudPacked' \
    --ros-args -r /world/default/clock:=/clock
fi
height_required=true
if [[ ${STAGE3_HEIGHT_SOURCE:-lidar} != lidar ]]; then height_required=false; fi
use_lio=false
if [[ ${STAGE3_LOCALIZATION:-px4} == fastlio ]]; then use_lio=true; fi
start px4 python3 /lesson/stage3/super_px4.py --ros-args -p use_sim_time:=true -p corridor:=${STAGE3_CORRIDOR:-false} -p speed:=${STAGE3_SPEED:-2.0} -p lidar_height_required:=$height_required -p use_lio:=$use_lio
input_topic=/mid360s/scan/points
if [[ ${STAGE3_CORRIDOR:-false} == true ]]; then
  pattern=false
  if [[ ${STAGE3_LIDAR:-super360} == mid360 ]]; then pattern=true; fi
  if [[ $use_lio == true ]]; then
    start timed_lidar ros2 run stage3_lidar timed_lidar --ros-args -p use_sim_time:=true -p sensor_z:=${STAGE3_SENSOR_Z:-.335} -p self_filter:=${STAGE3_SELF_FILTER:-true}
    start fastlio ros2 run fast_lio fastlio_mapping --ros-args --params-file /lesson/stage3/fast_lio_gazebo.yaml -p mapping.extrinsic_T:="[0.0, 0.0, ${STAGE3_SENSOR_Z:-.335}]" -r /Odometry:=/stage3/lio/odom -r /Odometry_propagated:=/stage3/lio/odom_propagated -r /cloud_registered:=/stage3/lio/cloud
    start lio_bridge python3 /lesson/stage3/lio_bridge.py --ros-args -p use_sim_time:=true
  else
  start prefilter ros2 run stage3_lidar prefilter --ros-args -p use_sim_time:=true -p range_max:=${STAGE3_LIDAR_RANGE:-69.9} -p mid360_pattern:=$pattern -p self_filter:=${STAGE3_SELF_FILTER:-true} -p sensor_z:=${STAGE3_SENSOR_Z:-.135}
  if [[ $height_required == true ]]; then
  start height python3 /lesson/stage3/super_height.py --ros-args -p use_sim_time:=true -p sensor_z:=${STAGE3_SENSOR_Z:-.135}
  fi
  fi
  input_topic=/stage3/lidar/filtered
fi
if [[ $use_lio == false ]]; then
start lidar python3 /lesson/stage3/super_lidar.py --ros-args -p use_sim_time:=true -p range_max:=${STAGE3_LIDAR_RANGE:-39.9} -p input_topic:=$input_topic -p sensor_z:=${STAGE3_SENSOR_Z:-.135}
fi
start planner ros2 run super_planner fsm_node --ros-args -p use_sim_time:=true \
  -p config_name:=${STAGE3_CONFIG:-/lesson/stage3/super_gazebo.yaml}
wait -n "${pids[@]}"
