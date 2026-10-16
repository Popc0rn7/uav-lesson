#!/bin/sh
# PX4's Noble ELF and libraries remain isolated from ROS Humble's Jammy process.
# Preserve symlink-dispatched module names such as px4-commander and px4-listener.
set -eu
unset LD_PRELOAD
exec /opt/px4-runtime/ld-linux-x86-64.so.2 \
    --library-path /opt/px4-runtime --argv0 "${0##*/}" \
    /opt/px4-gazebo/bin/px4.native "$@"
