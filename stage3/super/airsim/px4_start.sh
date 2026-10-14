#!/usr/bin/env bash
# Docker：外部 AirSim 的 PX4 SITL 入口，无 Gazebo。
set -euo pipefail
test -x /opt/px4-gazebo/bin/px4-simulator_mavlink
test -f /opt/px4-gazebo/etc/init.d-posix/airframes/10016_none_iris
export PX4_SIM_MODEL=none_iris PX4_SYS_AUTOSTART=10016
unset PX4_SIMULATOR PX4_SIM_HOST_ADDR PX4_SIM_HOSTNAME
mkdir -p /tmp/airsim-px4/fs /flight-logs
cd /tmp/airsim-px4
ln -s /opt/px4-gazebo/etc etc
ln -s /flight-logs fs/log
exec /opt/px4-gazebo/bin/px4 -d
