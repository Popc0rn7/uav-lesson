#!/usr/bin/env bash
# PC：容器仅接收原始图像；当前 uv 环境运行处理与 WebUI。
set -euo pipefail
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  echo '用法：./stage2/show_sensors.sh [--fps N] [--near M] [--far M]'
  echo 'PC WebUI 固定显示 RGB/D；点云和体素另开 show_rviz.sh。'
  exit 0
fi
container=${STAGE2_CONTAINER:-uav-stage2-sitl}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python=${STAGE2_PYTHON:-$script_dir/../.venv/bin/python}
"$python" -c 'import numpy; import PIL' || {
  echo '本地依赖缺失：在仓库根目录执行 uv sync --extra stage2' >&2; exit 1;
}
[[ $(docker inspect --format '{{.State.Running}}' "$container") == true ]] || {
  echo "请先启动仿真容器 $container" >&2; exit 1;
}
rgb=${STAGE2_RGB_TOPIC:-}
if [[ -z $rgb ]]; then
  topics=$(docker exec "$container" gz topic -l)
  mapfile -t candidates < <(printf '%s\n' "$topics" | sed -n '\|/sensor/IMX214/image$|p')
  if (( ${#candidates[@]} != 1 )); then
    printf '无法唯一选择 RGB，请设置 STAGE2_RGB_TOPIC。话题：\n%s\n' "$topics" >&2; exit 1;
  fi
  rgb=${candidates[0]}
fi
port=${STAGE2_RAW_PORT:-8089}
remote=$(docker exec "$container" mktemp -d /tmp/uav-stage2-receiver.XXXXXX)
web_pid=
cleanup() {
  if [[ -n $web_pid ]]; then kill -TERM "$web_pid" 2>/dev/null || true; wait "$web_pid" 2>/dev/null || true; fi
  docker exec "$container" /bin/sh -c 'if [ -f "$1/pid" ]; then kill -TERM "$(cat "$1/pid")" 2>/dev/null || true; fi; rm -rf "$1"' sh "$remote" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker cp "$script_dir/sensor_receiver.py" "$container:$remote/sensor_receiver.py" >/dev/null
# 与 ThreadingHTTPServer 一样启用地址复用：允许正常关闭后的 TIME_WAIT，
# 仍拒绝正在监听的服务，不清理未知进程。
docker exec "$container" /usr/bin/python3 -c 'import socket,sys
s=socket.socket()
s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
try:
 s.bind(("127.0.0.1",int(sys.argv[1])))
except OSError as exc:
 sys.exit(f"接收桥端口 {sys.argv[1]} 无法绑定：{exc}。请检查已有服务，或设置 STAGE2_RAW_PORT。")
finally:
 s.close()' "$port"
docker exec -d "$container" /bin/sh -c 'dir=$1; shift; echo $$ > "$dir/pid"; exec /usr/bin/python3 "$dir/sensor_receiver.py" "$@" > "$dir/receiver.log" 2>&1' sh "$remote" \
  --rgb "$rgb" --depth "${STAGE2_DEPTH_TOPIC:-/depth_camera}" --port "$port"
# 确认接收桥完成启动；不要求传感器已产生首帧。
docker exec "$container" /usr/bin/python3 -c 'import sys,time,pathlib; p=pathlib.Path(sys.argv[1]);
for _ in range(50):
 text=p.read_text() if p.exists() else ""
 if "Raw receiver:" in text: break
 if "Traceback" in text: sys.exit(text)
 time.sleep(.1)
else: sys.exit("接收桥启动超时："+text)' "$remote/receiver.log"
"$python" "$script_dir/sensor_web.py" --source "http://127.0.0.1:$port" --port "${STAGE2_WEB_PORT:-8090}" "$@" &
web_pid=$!
wait "$web_pid"
