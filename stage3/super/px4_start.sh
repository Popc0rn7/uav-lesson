#!/bin/sh
set -eu
export GZ_SIM_RESOURCE_PATH=/opt/px4-gazebo/share/gz/models:/opt/px4-gazebo/share/gz/worlds${GZ_SIM_RESOURCE_PATH:+:$GZ_SIM_RESOURCE_PATH}
# Own one server explicitly. PX4's topic-list autodetection mistakes an early
# world-clock subscriber (or a retained GUI) for an already running server.
export PX4_GZ_STANDALONE=1
gz sim --verbose=1 -r -s "/opt/px4-gazebo/share/gz/worlds/${PX4_GZ_WORLD:-default}.sdf" > /tmp/stage3-gazebo-server.log 2>&1 &
python3 /lesson-stage3/gazebo_warmup.py > /tmp/stage3-barometer-warmup.log 2>&1 &
python3 /lesson-stage3/gazebo_monitor.py > /tmp/stage3-gazebo-monitor.log 2>&1 &
mkdir -p /tmp/stage3-px4
ln -s /opt/px4-gazebo/etc /tmp/stage3-px4/etc
# SITL only: shared simulator time, no RC, Offboard loss requests landing.
sed '/^uxrce_dds_client start/i param set UXRCE_DDS_SYNCT 0\nparam set UXRCE_DDS_DOM_ID 10\nparam set COM_RC_IN_MODE 4\nparam set NAV_DLL_ACT 0\nparam set COM_DLL_EXCEPT 4\nparam set COM_OBL_RC_ACT 4\nparam set COM_OF_LOSS_T 0.5' \
  /opt/px4-gazebo/etc/init.d-posix/rcS > /tmp/stage3-rcS
exec /opt/px4-gazebo/bin/px4 -d /opt/px4-gazebo/etc -w /tmp/stage3-px4 -s /tmp/stage3-rcS
