#!/bin/sh
# 仅本进程环境；基础前缀与 Stage 1 当前已记录镜像一致，部署预检重新核实。
unset LD_PRELOAD
export PATH=/sys_prod/robot/out/bin:/sys_prod/robot/install/bin:$PATH
export LD_LIBRARY_PATH=/sys_prod/robot/out/lib:/sys_prod/robot/install/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export PYTHONPATH=/sys_prod/robot/install/lib/python3.12/site-packages:/sys_prod/robot/out/lib/python3.12/site-packages:/sys_prod/robot/out/lib/python3.12${PYTHONPATH:+:$PYTHONPATH}
export COLCON_CURRENT_PREFIX=/sys_prod/robot/install
. /sys_prod/robot/install/local_setup.sh
unset COLCON_CURRENT_PREFIX
export ROS_DOMAIN_ID=10 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
