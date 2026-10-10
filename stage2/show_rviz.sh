#!/usr/bin/env bash
# PC：独立 ROS Humble Docker 中运行点云/体素发布器与两个 RViz 窗口。
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
container=${STAGE2_CONTAINER:-uav-stage2-sitl}
image=${STAGE2_ROS_IMAGE:-osrf/ros:humble-desktop-jammy}
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  echo '用法：./stage2/show_rviz.sh [mid360s|depth]'
  echo '默认 MID-360S 点云/体素；depth 为深度相机对照。STAGE2_RVIZ_HEADLESS=1 仅发布数据。'
  exit 0
fi
(( $# <= 1 )) || { echo '用法：./stage2/show_rviz.sh [mid360s|depth]' >&2; exit 2; }
mode=${1:-mid360s}
case $mode in
  depth) default_topic=/depth_camera/points; default_port=8093; default_frame=stage2_depth; default_voxel=0.1; default_fps=5 ;;
  mid360s) default_topic=/mid360s/scan/points; default_port=8094; default_frame=mid360s_sensor; default_voxel=0.2; default_fps=10 ;;
  *) echo "未知点云模式：$mode" >&2; exit 1 ;;
esac
prefix=/stage2/$mode
port=${STAGE2_RVIZ_RAW_PORT:-$default_port}
headless=${STAGE2_RVIZ_HEADLESS:-0}
command -v docker >/dev/null
[[ $(docker inspect --format '{{.State.Running}}' "$container") == true ]] || { echo '请先启动仿真容器' >&2; exit 1; }
docker image inspect "$image" >/dev/null || { echo "教师准备：docker pull $image" >&2; exit 1; }
points=${STAGE2_POINTS_TOPIC:-$default_topic}
topics=$(docker exec "$container" gz topic -l)
printf '%s\n' "$topics" | grep -Fx -- "$points" >/dev/null || { echo "点云话题不存在：$points；可设置 STAGE2_POINTS_TOPIC" >&2; exit 1; }
mounts=(-v "$script_dir:/stage2:ro")
if [[ $headless != 1 ]]; then
  [[ -n ${DISPLAY:-} && -d /tmp/.X11-unix ]] || { echo '需要 PC 图形会话的 DISPLAY 与 X11 socket' >&2; exit 1; }
  auth=${XAUTHORITY:-$HOME/.Xauthority}
  [[ -r $auth ]] || { echo '请设置 XAUTHORITY 为当前图形会话的授权文件' >&2; exit 1; }
  mounts+=(-v /tmp/.X11-unix:/tmp/.X11-unix:ro -v "$auth:/tmp/rviz.xauth:ro" -e DISPLAY -e XAUTHORITY=/tmp/rviz.xauth -e QT_X11_NO_MITSHM=1)
fi
docker run --rm --network none --entrypoint bash "$image" -lc 'source /opt/ros/humble/setup.bash; command -v rviz2 >/dev/null; python3 -c "import rclpy; import numpy; from sensor_msgs.msg import PointCloud2; from visualization_msgs.msg import Marker"'
remote=$(docker exec "$container" mktemp -d /tmp/uav-stage2-cloud.XXXXXX)
ros_name="uav-stage2-cloud-${remote##*.}"
cleanup() {
  docker stop -t 5 "$ros_name" >/dev/null 2>&1 || true
  docker exec "$container" /bin/sh -c 'if [ -f "$1/pid" ]; then kill -TERM "$(cat "$1/pid")" 2>/dev/null || true; fi; rm -rf "$1"' sh "$remote" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker exec "$container" /usr/bin/python3 -c 'import socket,sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(("127.0.0.1",int(sys.argv[1]))); s.close()' "$port"
docker cp "$script_dir/sensor_receiver.py" "$container:$remote/sensor_receiver.py" >/dev/null
docker exec -d "$container" /bin/sh -c 'dir=$1; shift; echo $$ > "$dir/pid"; exec /usr/bin/python3 "$dir/sensor_receiver.py" "$@" > "$dir/receiver.log" 2>&1' sh "$remote" --points-only --points "$points" --port "$port"
docker exec "$container" /usr/bin/python3 -c 'import sys,time,pathlib; p=pathlib.Path(sys.argv[1])
for _ in range(50):
 text=p.read_text() if p.exists() else ""
 if "Raw receiver:" in text: break
 if "Traceback" in text: sys.exit(text)
 time.sleep(.1)
else: sys.exit("接收桥启动超时："+text)' "$remote/receiver.log"
echo "点云：$points；ROS $prefix/points、$prefix/voxels、$prefix/stats"
docker run --rm --init --name "$ros_name" --network host \
  -e ROS_DOMAIN_ID="${STAGE2_RVIZ_DOMAIN_ID:-10}" -e ROS_LOCALHOST_ONLY=1 \
  -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp -e HEADLESS="$headless" -e SOURCE="http://127.0.0.1:$port" \
  -e VOXEL_SIZE="${STAGE2_VOXEL_SIZE:-$default_voxel}" -e CLOUD_FPS="${STAGE2_CLOUD_FPS:-$default_fps}" \
  -e CLOUD_FRAME="$default_frame" -e CLOUD_PREFIX="$prefix" \
  "${mounts[@]}" --entrypoint bash "$image" -lc '
set -e
source /opt/ros/humble/setup.bash
python3 /stage2/rviz_cloud_config.py
if [[ $HEADLESS == 1 ]]; then exec python3 /stage2/rviz_cloud_bridge.py --source "$SOURCE" --voxel-size "$VOXEL_SIZE" --fps "$CLOUD_FPS" --frame "$CLOUD_FRAME" --topic-prefix "$CLOUD_PREFIX"; fi
python3 /stage2/rviz_cloud_bridge.py --source "$SOURCE" --voxel-size "$VOXEL_SIZE" --fps "$CLOUD_FPS" --frame "$CLOUD_FRAME" --topic-prefix "$CLOUD_PREFIX" &
bridge=$!
rviz2 -d /tmp/cloud_points.rviz &
points_view=$!
rviz2 -d /tmp/cloud_voxels.rviz &
voxels_view=$!
trap '\''kill -TERM "$bridge" "$points_view" "$voxels_view" 2>/dev/null || true; wait 2>/dev/null || true'\'' EXIT
wait -n "$bridge" "$points_view" "$voxels_view"
'
