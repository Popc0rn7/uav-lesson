#!/bin/sh
# RoboPi：初始化本次已验证的驱动与 ROS 环境，然后前台服务。
set -e
app_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
unset LD_PRELOAD
if [ -f "$app_dir/serve.pid" ]; then
    pid="$(cat "$app_dir/serve.pid")"
    case "$pid" in
        ''|*[!0-9]*) echo 'serve.pid 内容无效，请检查' >&2; exit 1 ;;
    esac
    if kill -0 "$pid" 2>/dev/null; then
        if [ "$(readlink "/proc/$pid/cwd")" = "$app_dir" ] && grep -q chat_node.py "/proc/$pid/cmdline"; then
            echo "ROS 推理服务已运行，PID=$pid"
            exit 0
        fi
        echo 'serve.pid 指向其他进程，请检查，不会覆盖' >&2
        exit 1
    fi
fi
if ! grep -q '^xh2a_drv ' /proc/modules; then
    driver=/data/local/houmo-sdk/xh2a_drv.ko
    expected=60a6ab2d7898fc319897122edf82b99a515a976eaaf3a62e0f949f335eb22159
    if [ "$(uname -r)" != 6.6.86 ] || [ "$(uname -m)" != aarch64 ]; then
        echo '当前镜像与已验证驱动不匹配，请重新核对内核和模块' >&2
        exit 1
    fi
    actual="$(sha256sum "$driver")" || exit 1
    if [ "${actual%% *}" != "$expected" ]; then
        echo '驱动文件与已验证版本不一致' >&2
        exit 1
    fi
    insmod "$driver" || exit 1
    grep -q '^xh2a_drv ' /proc/modules || exit 1
fi
. "$app_dir/ros_env.sh"
unset LD_PRELOAD
cd "$app_dir"
# 模型服务与 ROS 桥分开：HTTP 只监听本板，PC 仍通过 DDS 收发。
infer_dir="$app_dir/qwen_infer"
python3 -c 'import uvicorn, h11' || exit 1
status="$(sh "$infer_dir/run.sh" --status)" || exit 1
started=0
case "$status" in
    RUNNING*|FOREGROUND*) ;;
    *) sh "$infer_dir/run.sh" --serve --background --model qwen3.6-35b-a3b --host 127.0.0.1 --port 8080 || exit 1; started=1 ;;
esac
if ! python3 -B "$app_dir/backend.py"; then
    [ "$started" -eq 0 ] || sh "$infer_dir/run.sh" --stop
    exit 1
fi
echo $$ > "$app_dir/serve.pid"
exec python3 -B chat_node.py
