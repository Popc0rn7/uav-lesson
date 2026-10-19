#!/usr/bin/env bash
# Docker 1：instance 5 / sysid 6；外部 AirSim HIL，无 Gazebo。
set -euo pipefail
export PX4_SIM_MODEL=none_iris PX4_SYS_AUTOSTART=10016
export ROS_DOMAIN_ID=15 PX4_UXRCE_DDS_PORT=8895 PX4_UXRCE_DDS_NS=''
unset PX4_SIMULATOR PX4_SIM_HOST_ADDR PX4_SIM_HOSTNAME
mkdir -p /tmp/stage5-airsim/fs /flight-logs
cd /tmp/stage5-airsim
ln -s /opt/px4-gazebo/etc etc
ln -s /flight-logs fs/log
sed '/^uxrce_dds_client start/i param set UXRCE_DDS_SYNCT 0\nparam set COM_RC_IN_MODE 4\nparam set NAV_DLL_ACT 0\nparam set COM_DLL_EXCEPT 4\nparam set COM_OBL_RC_ACT 4\nparam set COM_OF_LOSS_T 0.5' \
  /opt/px4-gazebo/etc/init.d-posix/rcS > /tmp/stage5-airsim-rcS
# 独立 AirSim API/MAVLink 链路，保留原 Stage 5 Offboard 14585→14545。
echo 'mavlink start -x -u 14586 -o 14546 -r 4000000 -m onboard' >> /tmp/stage5-airsim-rcS
exec /opt/px4-gazebo/bin/px4 -i 5 -d -s /tmp/stage5-airsim-rcS
