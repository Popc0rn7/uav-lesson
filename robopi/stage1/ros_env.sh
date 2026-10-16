#!/bin/sh
# RoboPi：source 本文件，仅初始化本板已确认的 ROS Humble 环境。
unset LD_PRELOAD
export PATH=/sys_prod/robot/out/bin:/sys_prod/robot/install/bin:$PATH
export LD_LIBRARY_PATH=/sys_prod/robot/out/lib:/sys_prod/robot/install/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export PYTHONPATH=/sys_prod/robot/install/lib/python3.12/site-packages:/sys_prod/robot/out/lib/python3.12/site-packages:/sys_prod/robot/out/lib/python3.12${PYTHONPATH:+:$PYTHONPATH}
export COLCON_CURRENT_PREFIX=/sys_prod/robot/install
. /sys_prod/robot/install/local_setup.sh
unset COLCON_CURRENT_PREFIX
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-10}
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}
