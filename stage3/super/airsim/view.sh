#!/usr/bin/env bash
# Docker 2：同一算法容器中的 RViz；退出不影响飞行节点。
set -eo pipefail
source /opt/ros/humble/setup.bash
source /super_ws/install/local_setup.bash
test -n "${DISPLAY:-}"
exec 9>/run/airsim/rviz.lock
flock -n 9 || exit 0
export LIBGL_ALWAYS_SOFTWARE=1 QT_X11_NO_MITSHM=1
exec rviz2 -d /lesson/stage3/super/airsim/super.rviz --ros-args -p use_sim_time:=true \
  >/run/airsim/rviz.log 2>&1
