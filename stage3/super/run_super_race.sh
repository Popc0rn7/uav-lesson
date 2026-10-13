#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source /super_ws/install/local_setup.bash
mkdir -p /tmp/stage3-super /tmp/stage3-fastlio /tmp/super-race
sim_pid= planner_pid=
cleanup() {
    trap - EXIT INT TERM
    [[ -z "$sim_pid" ]] || kill -TERM "$sim_pid" 2>/dev/null || true
    [[ -z "$planner_pid" ]] || kill -TERM "$planner_pid" 2>/dev/null || true
    wait || true
}
trap cleanup EXIT INT TERM
xvfb-run -a -s '-screen 0 1280x720x24' ros2 run perfect_drone_sim perfect_drone_node \
    --ros-args -p config_name:=corridor_medium_benchmark.yaml > /tmp/super-race/sim.log 2>&1 &
sim_pid=$!
ros2 run super_planner fsm_node --ros-args -p config_name:=/lesson/stage3/super/super_race.yaml \
    > /tmp/super-race/planner.log 2>&1 &
planner_pid=$!
wait -n "$sim_pid" "$planner_pid"
