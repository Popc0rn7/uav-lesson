#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /opt/px4_ws/install/local_setup.bash
exec "$@"
