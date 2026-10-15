#!/bin/sh
# Docker：Stage 5 自有 Gazebo server、PX4 instance 5 与 RGB/D 接收桥。
set -eu
export GZ_SIM_RESOURCE_PATH=/opt/px4-gazebo/share/gz/models:/opt/px4-gazebo/share/gz/worlds
export PX4_GZ_STANDALONE=1
gz sim --headless-rendering -r -s /scene/street.sdf > /tmp/stage5-gazebo.log 2>&1 &
python3 /lesson/stage3/super/gazebo_warmup.py > /tmp/stage5-warmup.log 2>&1 &
python3 /lesson/stage2/sensor_receiver.py \
  --rgb /world/stage5_street/model/x500_experiment_0/link/camera_link/sensor/orbbec_rgb/image \
  --depth /depth_camera --port 8189 > /tmp/stage5-camera.log 2>&1 &
mkdir -p /tmp/stage5-px4
ln -s /opt/px4-gazebo/etc /tmp/stage5-px4/etc
sed '/^uxrce_dds_client start/i param set UXRCE_DDS_SYNCT 0\nparam set UXRCE_DDS_DOM_ID 15\nparam set UXRCE_DDS_PRT 8895\nparam set COM_RC_IN_MODE 4\nparam set NAV_DLL_ACT 0\nparam set COM_DLL_EXCEPT 4\nparam set COM_OBL_RC_ACT 4\nparam set COM_OF_LOSS_T 0.5' \
  /opt/px4-gazebo/etc/init.d-posix/rcS > /tmp/stage5-rcS
# 指定模型名后 PX4 连接预先由本脚本生成的标准机，而非自动按 instance 改名。
attempt=0
until gz service -s /world/stage5_street/create --reqtype gz.msgs.EntityFactory \
  --reptype gz.msgs.Boolean --timeout 1000 --req \
  'name: "x500_experiment_0", allow_renaming: false, sdf: "<sdf version=\"1.9\"><include><uri>model://x500_experiment</uri><pose>24 -8 0.24 0 0 1.57079632679</pose></include></sdf>"' \
  > /tmp/stage5-spawn.log 2>&1 && grep -q 'data: true' /tmp/stage5-spawn.log; do
  attempt=$((attempt+1))
  if [ "$attempt" -ge 30 ]; then cat /tmp/stage5-spawn.log; exit 1; fi
  sleep 1
done
exec /opt/px4-gazebo/bin/px4 -i 5 -d /opt/px4-gazebo/etc -w /tmp/stage5-px4 -s /tmp/stage5-rcS
