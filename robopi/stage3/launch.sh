#!/bin/sh
set -e
release=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$release/ros_env.sh"
set -u
export AMENT_PREFIX_PATH="$release/install${AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}"
export LD_LIBRARY_PATH="$release/install/lib:$LD_LIBRARY_PATH"
export PYTHONPATH="$release/install/lib/python3.12/site-packages:$release/app:$PYTHONPATH"
export FASTRTPS_DEFAULT_PROFILES_FILE="$1/dds.xml"
export ROS_LOG_DIR="$1/ros-logs"
cd "$1"
exec python3 -B "$release/manage.py" run "$1"
