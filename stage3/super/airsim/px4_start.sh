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
if [[ ${AIRSIM_SUPER:-0} == 1 ]]; then
  # PX4 HIL clock is authoritative; DDS must not translate it to the Agent wall clock.
  sed '/^uxrce_dds_client start/i param set UXRCE_DDS_SYNCT 0\nparam set UXRCE_DDS_DOM_ID 10\nparam set COM_RC_IN_MODE 4\nparam set NAV_DLL_ACT 0\nparam set COM_DLL_EXCEPT 4\nparam set COM_OBL_RC_ACT 4\nparam set COM_OF_LOSS_T 0.5' \
    /opt/px4-gazebo/etc/init.d-posix/rcS > /tmp/airsim-rcS
  exec /opt/px4-gazebo/bin/px4 -d -s /tmp/airsim-rcS
fi
exec /opt/px4-gazebo/bin/px4 -d
