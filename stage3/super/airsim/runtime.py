#!/usr/bin/env python3
"""PC Linux：统一管理宿主机 AirSim 与现有镜像中的 PX4 SITL。"""
import argparse
from contextlib import contextmanager, ExitStack
import errno
import codecs
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import selectors
import shutil
import socket
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LABEL = "io.uav-lesson.airsim.owner"


def command(*args, check=True, timeout=15):
    return subprocess.run(list(map(str, args)), capture_output=True, text=True,
                          check=check, timeout=timeout)


def streaming_command(*args, check=True, timeout=15):
    """边读取边显示 Docker 2 输出，仍保留原始结果供报告识别与复盘。"""
    argv=list(map(str,args));started=time.monotonic();parts=[]
    process=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    decoder=codecs.getincrementaldecoder('utf-8')(errors='replace')
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            while selector.get_map():
                remaining=timeout-(time.monotonic()-started)
                if remaining<=0:raise subprocess.TimeoutExpired(argv,timeout,output=''.join(parts))
                for key,_ in selector.select(min(.2,remaining)):
                    data=os.read(key.fileobj.fileno(),65536)
                    if not data:selector.unregister(key.fileobj);continue
                    chunk=decoder.decode(data);parts.append(chunk)
                    sys.stdout.write(chunk);sys.stdout.flush()
        tail=decoder.decode(b'',final=True)
        if tail:parts.append(tail);sys.stdout.write(tail);sys.stdout.flush()
        process.wait(timeout=max(.01,timeout-(time.monotonic()-started)))
    except BaseException:
        process.terminate()
        try:process.wait(timeout=2)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        raise
    finally:process.stdout.close()
    result=subprocess.CompletedProcess(argv,process.returncode,''.join(parts),'')
    if check:result.check_returncode()
    return result


def resolve(path, base):
    return (base / Path(path).expanduser()).resolve()


def load_config(path):
    config = json.loads(path.read_text())
    config["scene_dir"] = str(resolve(config["scene_dir"], path.parent))
    config["binary"] = str(resolve(config["binary"], Path(config["scene_dir"])))
    config["settings"] = str(resolve(config["settings"], path.parent))
    if config.get('super_task'):
        from task_config import load_task
        config['super_task'] = str(resolve(config['super_task'], path.parent))
        load_task(config['super_task'])
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]+', config['ros_container']):
            raise ValueError('ros_container 名称无效')
        if config['ros_container'] == config['container']:
            raise ValueError('两个 Docker 不能使用相同容器名')
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]+", config["container"]):
        raise ValueError("container 名称无效")
    if not isinstance(config["scene_args"], list) or not all(isinstance(x, str) for x in config["scene_args"]):
        raise ValueError("scene_args 必须是字符串数组")
    if any(x.lower().startswith("-settings") for x in config["scene_args"]):
        raise ValueError("scene_args 不应包含 -settings；由入口统一生成")
    if not 5 <= config["startup_timeout_s"] <= 600:
        raise ValueError("startup_timeout_s 必须为 5～600 秒")
    return config


def inspect_container(name):
    result = command("docker", "inspect", name, check=False)
    if result.returncode == 0:
        return json.loads(result.stdout)[0]
    if "no such object" in result.stderr.lower() or "no such container" in result.stderr.lower():
        return None
    raise RuntimeError(result.stderr.strip() or "无法查询 Docker 容器")


def start_ticks(pid):
    data = Path(f"/proc/{pid}/stat").read_text()
    tail = data[data.rfind(")") + 2:].split()
    if tail[0] == "Z":
        raise ProcessLookupError(pid)
    return tail[19]


def host_alive(state):
    try:
        pid = state["pid"]
        return (start_ticks(pid) == state["start_ticks"]
                and Path(f"/proc/{pid}/exe").resolve() == Path(state["binary"])
                and f"-settings={state['runtime_settings']}".encode()
                in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0"))
    except (OSError, KeyError, ProcessLookupError):
        return False


def owned_container(state):
    info = inspect_container(state["container"])
    if info and ((state.get("container_id") and info["Id"] != state["container_id"])
                 or (info["Config"].get("Labels") or {}).get(LABEL) != state["owner"]):
        raise RuntimeError("同名容器不属于本次运行，拒绝操作")
    return info


def write_state(directory, state):
    temporary = directory / "state.json.tmp"
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    temporary.replace(directory / "state.json")


@contextmanager
def management_lock(directory, action, force=False):
    """任务互斥；只读状态/急救请求不被整轮任务及复盘阻塞。"""
    if action=='dashboard':
        yield
        return
    recovery = action in ('land', 'stop') or (action == 'down' and force)
    with ExitStack() as stack:
        if recovery:
            recovery_lock = stack.enter_context((directory/'recovery.lock').open('a'))
            try:
                fcntl.flock(recovery_lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('另一个恢复命令正在执行；可用 status 查看状态') from exc
        lock = stack.enter_context((directory/'runtime.lock').open('a'))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            if not (recovery or action == 'status'):
                raise RuntimeError('任务/管理命令正在执行；仍可 status、land 或 stop（仿真急停）') from exc
            if recovery:
                state_file = directory/'state.json'
                state = json.loads(state_file.read_text()) if state_file.exists() else {}
                if state.get('phase') not in ('ready', 'stopping', 'stopped'):
                    raise RuntimeError('实例正在初始化，先中断 up，再 stop；不与创建资源并行操作') from exc
        yield


def request_land(state):
    """发送请求并明确区分“已发命令”和“实际落地”。"""
    info = owned_container(state)
    if not info or not info['State']['Running']:
        raise RuntimeError('本次 PX4 未运行；需要回收剩余资源可使用 stop')
    if state.get('ros_container'):
        owned_ros(state)
        # 持久取消任务，避免尚处 prestream/takeoff 时又切回 Offboard。
        marker = Path(state['run_dir'])/'land.request.json'
        temporary = marker.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(owner=state['owner'], requested_at=time.time())))
        temporary.replace(marker)
    result = px4(state, 'commander', 'land')
    if result.returncode:
        raise RuntimeError('降落命令未确认：'+result.stdout+result.stderr+'；仿真失控可使用 stop')
    print('已发送降落请求并中止任务；不代表已落地。用 status 检查；碰撞/卡住时使用 stop 回收仿真。')


def listen_owned(pid, port):
    """只查监听，不连接 4560，避免消耗 AirSim 的单次 accept。"""
    inodes = set()
    try:
        for fd in Path(f"/proc/{pid}/fd").iterdir():
            try:
                link = os.readlink(fd)
                if link.startswith("socket:["):
                    inodes.add(link[8:-1])
            except OSError:
                pass
        for row in Path("/proc/net/tcp").read_text().splitlines()[1:]:
            fields = row.split()
            if int(fields[1].split(":")[1], 16) == port and fields[3] == "0A" and fields[9] in inodes:
                return True
    except OSError:
        pass
    return False


def tcp_states(port):
    """读取本网络命名空间的 TCP 状态，不建立探测连接。"""
    states = []
    for name in ("tcp", "tcp6"):
        for row in Path(f"/proc/net/{name}").read_text().splitlines()[1:]:
            fields = row.split()
            if int(fields[1].split(":")[1], 16) == port:
                states.append(fields[3])
    return states


def check_port(kind, port, time_wait_timeout_s=75):
    deadline = time.monotonic() + time_wait_timeout_s
    announced = False
    protocol = "TCP" if kind == socket.SOCK_STREAM else "UDP"
    while True:
        with socket.socket(socket.AF_INET, kind) as sock:
            try:
                if kind == socket.SOCK_STREAM:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
                if kind == socket.SOCK_STREAM:
                    sock.listen(1)
                return
            except OSError as exc:
                if exc.errno != errno.EADDRINUSE:
                    raise RuntimeError(f"无法检查 {protocol} 端口 {port}：{exc}") from exc
                states = tcp_states(port) if kind == socket.SOCK_STREAM else []
                if not states or any(state != "06" for state in states):
                    raise RuntimeError(f"{protocol} 端口 {port} 已占用；先确认现有实例用途") from exc
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"TCP 端口 {port} 的 TIME_WAIT 尚未释放，等待超时；稍后重试") from exc
                if not announced:
                    print(f"TCP {port} 仅有 TIME_WAIT 残留，自动等待释放（最多 {time_wait_timeout_s} 秒）…", flush=True)
                    announced = True
        time.sleep(.5)


def check_ports():
    for kind, ports in [(socket.SOCK_STREAM, [4560, 41451]),
                        (socket.SOCK_DGRAM, [14540, 14580, 18570, 14280, 13030])]:
        for port in ports:
            check_port(kind, port)


def runtime_settings(config, task=None):
    settings = json.loads(Path(config["settings"]).read_text())
    vehicles = settings.get("Vehicles", {})
    if list(vehicles) != ["PX4"] or vehicles["PX4"].get("VehicleType") != "PX4Multirotor":
        raise ValueError("当前入口需要唯一的 PX4 / PX4Multirotor，无多机支持")
    settings.update(SimMode="Multirotor", RpcEnabled=True, ApiServerPort=41451,
                    LocalHostIp="127.0.0.1")
    vehicles["PX4"].update(UseSerial=False, UseTcp=True, LockStep=True,
                           LocalHostIp="127.0.0.1", ControlIp="127.0.0.1",
                           TcpPort=4560, ControlPortLocal=14540, ControlPortRemote=14580)
    if config.get('super_task'):
        from task_config import apply_settings, load_task
        apply_settings(settings, task if task is not None else load_task(config['super_task']))
    return settings


def owned_ros(state):
    if not state.get('ros_container'):
        return None
    info = inspect_container(state['ros_container'])
    if info and ((state.get('ros_container_id') and info['Id'] != state['ros_container_id'])
                 or (info['Config'].get('Labels') or {}).get(LABEL) != state['owner']):
        raise RuntimeError('算法容器不属于本次运行，拒绝操作')
    return info


def ros_action(state, action, check=True, *, stream=False, dashboard='auto'):
    info = owned_ros(state)
    if not info or not info['State']['Running']:
        raise RuntimeError('算法容器未运行，检查 node-logs')
    mode=dashboard if dashboard!='auto' else ('ansi' if sys.stdout.isatty() and os.environ.get('TERM')!='dumb' else 'plain')
    display_args=f' --dashboard {mode} --dashboard-width {shutil.get_terminal_size((88,24)).columns}' if stream else ''
    runner=streaming_command if stream else command
    try:
        result = runner('docker', 'exec', state['ros_container'], 'bash', '-lc',
                   'source /opt/ros/humble/setup.bash; source /opt/px4_ws/install/local_setup.bash; '
                   'source /super_ws/install/local_setup.bash; '
                   f'python3 -u /lesson/stage3/super/airsim/verify_stack.py {action}{display_args}',
                   timeout=86400 if action.startswith('dashboard') else state['config'].get('mission_wall_timeout_s', 2000) if action.startswith(('fly','fault')) else 40,
                   check=False)
    finally:
        if stream and mode=='ansi':print('\x1b[?25h\x1b[?1049l',end='',flush=True)
    displayed_length=len(result.stdout) if stream else 0
    if action.startswith(('fly', 'fault')):
        # 成败都复盘；分析失败不得覆盖飞行结果。只接受本次运行目录内的报告。
        report_found = False
        for line in result.stdout.splitlines():
            if line.startswith('报告：/run/airsim/'):
                name = line.removeprefix('报告：/run/airsim/')
                if Path(name).name != name or not name.endswith('.json'):
                    continue
                report_found = True
                try:
                    review = command(sys.executable, HERE/'review_flight.py',
                                     Path(state['run_dir'])/name, check=False, timeout=180)
                    result.stdout += '\n'+review.stdout
                    if review.returncode:
                        result.stdout += '\n复盘失败（不改变飞行结果）：'+review.stderr[-2000:]
                except (OSError, subprocess.TimeoutExpired) as exc:
                    result.stdout += '\n复盘失败（不改变飞行结果）：'+str(exc)
                break
        if not report_found:
            result.stdout += '\n未获得任务报告，无法自动对齐本轮窗口；保留节点日志与 ULog，不能视为已完成飞控复盘。\n'
    if stream:
        print(result.stdout[displayed_length:],end='',flush=True)
        result.streamed=True
    if check:
        try:
            result.check_returncode()
        except subprocess.CalledProcessError as exc:
            exc.streamed = stream
            raise
    return result


def px4(state, module, *args):
    return command("docker", "exec", state["container"],
                   f"/opt/px4-gazebo/bin/px4-{module}", *args, check=False, timeout=6)


def ready(state):
    if not host_alive(state):
        return False
    info = owned_container(state)
    if not info or not info["State"]["Running"]:
        return False
    if state.get('ros_container') and state.get('phase') == 'ready':
        ros = owned_ros(state)
        if not ros or not ros['State']['Running']:
            return False
    result = px4(state, "listener", "sensor_combined", "-n", "2")
    stamps = re.findall(r"^    timestamp: (\d+)", result.stdout, re.M)
    if result.returncode or len(stamps) != 2 or int(stamps[1]) <= int(stamps[0]):
        return False
    position = px4(state, "listener", "vehicle_local_position").stdout
    health = px4(state, "commander", "check").stdout
    if not ("xy_valid: True" in position and "z_valid: True" in position
            and "Preflight check: OK" in health):
        return False
    from rpc_client import rpc
    try:
        return bool(rpc("ping", timeout=2)) and rpc("listVehicles", timeout=2) == ["PX4"]
    except (OSError, RuntimeError):
        return False


def stop_host(state):
    if not host_alive(state):
        return
    os.killpg(state["pid"], signal.SIGTERM)
    deadline = time.monotonic() + 5
    while host_alive(state) and time.monotonic() < deadline:
        time.sleep(.2)
    if host_alive(state):
        os.killpg(state["pid"], signal.SIGKILL)


def shutdown(state, directory, force=False):
    info = owned_container(state)
    ros = owned_ros(state)
    if info and info["State"]["Running"] and not force:
        if "arming_state: 1" not in px4(state, "listener", "vehicle_status").stdout:
            raise RuntimeError("未确认 PX4 已解除解锁；正常降落用 land，碰撞/卡住用 stop（等同 down --force）；保留日志")
    elif host_alive(state) and not force:
        from rpc_client import rpc
        if rpc("getMultirotorState", "PX4", timeout=3)["landed_state"] != 0:
            raise RuntimeError("未确认落地，拒绝停止场景")
    state['phase'] = 'stopping'
    write_state(directory, state)
    errors = []
    def attempt(operation):
        try:
            operation()
        except Exception as exc:
            if not force:
                raise
            errors.append(str(exc))
    def remove_container(info, logfile):
        identity = info['Id']
        if info['State']['Running']:
            attempt(lambda: command('docker', 'stop', '-t', '5', identity, timeout=12))
        def save_console():
            result = command('docker', 'logs', identity, check=False)
            (Path(state['run_dir'])/logfile).write_text(result.stdout+result.stderr)
        attempt(save_console)
        # 急停允许强制移除已核实身份的容器；日志保存失败不能阻断其他资源回收。
        attempt(lambda: command('docker', 'rm', *(['-f'] if force else []), identity))
    if ros:
        remove_container(ros,'ros-console.log')
    # 先停止场景，让仍连接的仿真循环处理正常退出，避免断连后 lockstep 卡住。
    attempt(lambda: stop_host(state))
    if info:
        remove_container(info,'px4-console.log')
    remaining = bool(host_alive(state) or owned_container(state) or owned_ros(state))
    state["phase"] = "stopping" if remaining else "stopped"
    write_state(directory, state)
    if errors or remaining:
        raise RuntimeError('资源回收状态：'+state['phase']+'；'+ '; '.join(errors))


def up(config, directory, *, ros_entrypoint=None, ros_check=None):
    if config.get('diagnostics') and ros_entrypoint is None:
        raise RuntimeError('诊断配置只能由 diagnostics/diagnose.py response-up 启动，不加载正常 SUPER 控制器')
    task = None
    if config.get('super_task'):
        from task_config import load_task
        task = load_task(config['super_task'])
    settings = runtime_settings(config, task)
    inputs = [config, settings] + ([task] if task is not None else [])
    fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    state_file = directory / "state.json"
    if state_file.exists():
        old = json.loads(state_file.read_text())
        if old["phase"] != "stopped":
            if old["fingerprint"] == fingerprint and ready(old):
                print("当前实例已就绪，无需重复启动")
                return
            raise RuntimeError("已有运行记录未正常停止；先 status / down，不自动接管或覆盖")
    binary = Path(config["binary"])
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f"场景二进制不存在或不可执行：{binary}")
    with binary.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise RuntimeError("binary 必须是 Linux 原生场景二进制，不能使用另带 -settings 的 .sh 包装器")
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("需要从 PC 图形桌面会话启动；NoDisplay 仍需要图形环境")
    command("docker", "image", "inspect", config["image"])
    if config.get('super_task'):
        command('docker', 'image', 'inspect', config['ros_image'])
        if inspect_container(config['ros_container']):
            raise RuntimeError('同名算法容器已存在，拒绝接管')
        if not (ROOT / 'thirdparty/super_gazebo_ws/install/local_setup.bash').is_file():
            raise RuntimeError('SUPER 尚未编译；先执行 super_docker.py prepare / build')
        check_port(socket.SOCK_DGRAM, 8888)
    if inspect_container(config["container"]):
        raise RuntimeError("同名容器已存在，拒绝接管；先检查并停止已知旧实例")
    check_ports()
    owner = uuid.uuid4().hex
    run_dir = directory / owner
    run_dir.mkdir()
    (run_dir / "px4-logs").mkdir()
    settings_path = run_dir / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2))
    state = dict(owner=owner, fingerprint=fingerprint, container=config["container"],
                 binary=str(binary), runtime_settings=str(settings_path), run_dir=str(run_dir),
                 config=config, phase="starting", container_id=None)
    if config.get('super_task'):
        (run_dir / 'task.json').write_text(json.dumps(task, indent=2))
        state.update(ros_container=config['ros_container'], ros_container_id=None)
    log = (run_dir / "airsim-console.log").open("w")
    process = subprocess.Popen([str(binary), *config["scene_args"], f"-settings={settings_path}"],
                               cwd=config["scene_dir"], stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=True)
    log.close()
    try:
        state.update(pid=process.pid, start_ticks=start_ticks(process.pid))
    except (OSError, ProcessLookupError) as exc:
        raise RuntimeError(f"场景启动即退出；查看 {run_dir}/airsim-console.log") from exc
    write_state(directory, state)
    deadline = time.monotonic() + config["startup_timeout_s"]
    try:
        print(f"AirSim PID={process.pid}，等待监听 TCP 4560…", flush=True)
        while not listen_owned(process.pid, 4560):
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"AirSim 未进入监听；查看 {run_dir}/airsim-console.log")
            time.sleep(.3)
        print("AirSim 已监听，启动 PX4 容器…", flush=True)
        result = command("docker", "run", "-d", "--init", "--name", config["container"],
                         "--network", "host", "--label", f"{LABEL}={owner}",
                         "--mount", f"type=bind,source={HERE},target=/lesson-airsim,readonly",
                         "--mount", f"type=bind,source={run_dir}/px4-logs,target=/flight-logs",
                         '-e', f'AIRSIM_SUPER={int(bool(config.get("super_task")))}',
                         "--entrypoint", "/bin/bash", config["image"],
                         "/lesson-airsim/px4_start.sh", timeout=30)
        state["container_id"] = result.stdout.strip()
        write_state(directory, state)
        while True:
            try:
                if ready(state):
                    break
            except subprocess.TimeoutExpired:
                pass
            if not host_alive(state) or time.monotonic() > deadline:
                raise RuntimeError("PX4 未就绪；查看本次运行日志")
            time.sleep(1)
        if config.get('super_task'):
            gui = []
            if Path('/tmp/.X11-unix').is_dir():
                gui.extend(['--mount', 'type=bind,source=/tmp/.X11-unix,target=/tmp/.X11-unix,readonly'])
            if os.environ.get('DISPLAY'):
                gui.extend(['-e', 'DISPLAY='+os.environ['DISPLAY']])
            authority = os.environ.get('XAUTHORITY')
            if authority and Path(authority).is_file():
                gui.extend(['--mount', f'type=bind,source={authority},target=/tmp/airsim.xauth,readonly',
                            '-e', 'XAUTHORITY=/tmp/airsim.xauth'])
            result = command('docker', 'run', '-d', '--init', '--name', config['ros_container'],
                             '--network', 'host', '--label', f'{LABEL}={owner}',
                             '--mount', f'type=bind,source={ROOT},target=/lesson,readonly',
                             '--mount', f'type=bind,source={ROOT}/thirdparty/super_gazebo_ws,target=/super_ws,readonly',
                             '--mount', f'type=bind,source={ROOT}/submodules/SUPER,target=/super_ws/src,readonly',
                             '--mount', f'type=bind,source={run_dir},target=/run/airsim',
                             '-e', 'FASTRTPS_DEFAULT_PROFILES_FILE=/lesson/stage3/super/race_view_dds.xml',
                             *gui,
                             config['ros_image'], 'bash', ros_entrypoint or '/lesson/stage3/super/airsim/run_nodes.sh', timeout=30)
            state['ros_container_id'] = result.stdout.strip()
            write_state(directory, state)
            result = ros_check(state) if ros_check else ros_action(state, 'inspect', check=False)
            (run_dir / 'startup-inspect.log').write_text(result.stdout + result.stderr)
            result.check_returncode()
        state["phase"] = "ready"
        write_state(directory, state)
        print(f"已就绪：AirSim ↔ PX4；日志 {run_dir}")
    except BaseException:
        try:
            shutdown(state, directory, force=True)
        except Exception as cleanup:
            stop_host(state)
            print(f"启动清理失败：{cleanup}；保留状态 {directory}", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog='land：请求降落；stop：仿真急停，等同 down --force，保留日志。任务执行中仍可 status/land/stop。')
    parser.add_argument("action", choices=["up", "status", "down", "stop", "task", "land", "inspect", "view", "fault", "snapshot", "dashboard"])
    parser.add_argument('--case', choices=['lidar','planner','clock'])
    parser.add_argument("--config", type=Path, default=HERE / "runtime.forest10.json")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "artifacts/airsim-runtime")
    parser.add_argument("--image", help="up：覆盖配置中的本地 PX4 镜像")
    parser.add_argument("--force", action="store_true", help="down：显式停止本入口拥有的仿真资源，即使无法确认落地")
    parser.add_argument('--dashboard',choices=['auto','ansi','plain','off'],default='auto',help='task/fault/dashboard：终端仪表盘，自动识别交互终端')
    parser.add_argument('--seconds',type=int,default=0,help='dashboard：观察秒数，0表示持续；Ctrl+C只退出观察')
    args = parser.parse_args()
    if args.action == 'fault' and not args.case:
        parser.error('fault 需要 --case')
    if args.force and args.action != "down":
        parser.error("--force 只适用于 down")
    if args.image and args.action != "up":
        parser.error("--image 只适用于 up")
    if args.seconds<0 or (args.seconds and args.action!='dashboard'):parser.error('--seconds 只用于 dashboard，必须非负')
    directory = args.state_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with management_lock(directory,args.action,args.force):
        if args.action == "up":
            config = load_config(args.config.resolve())
            if args.image:
                config["image"] = args.image
            up(config, directory)
            return
        state_file = directory / "state.json"
        if not state_file.exists():
            if args.action in ["status", "down", "stop"]:
                print("尚无本入口管理的运行实例")
                return
            raise RuntimeError("请先 up")
        state = json.loads(state_file.read_text())
        if args.action in ("down", "stop"):
            if state["phase"] != "stopped":
                shutdown(state, directory, args.force or args.action == 'stop')
            print("仿真急停完成；资源已停止，诊断日志保留（不代表正常降落）" if args.force or args.action=='stop'
                  else "已停止；诊断日志保留")
        elif args.action == 'land' and state.get('ros_container'):
            request_land(state)
        elif args.action == "status":
            info = owned_container(state)
            print(json.dumps(dict(phase=state["phase"], airsim_alive=host_alive(state),
                                  px4_running=bool(info and info["State"]["Running"]),
                                  container=state["container"], run_dir=state["run_dir"]),
                             ensure_ascii=False, indent=2))
            if info and info["State"]["Running"]:
                print(px4(state, "commander", "status").stdout)
            ros = owned_ros(state)
            if state.get('ros_container'):
                print('算法容器运行：', bool(ros and ros['State']['Running']))
        elif args.action == 'inspect':
            print(ros_action(state, 'inspect').stdout)
        elif args.action == 'dashboard':
            if state['phase']!='ready':raise RuntimeError('实例未就绪，无法观察实时遥测')
            marker=Path(state['run_dir'])/('dashboard-stop-'+uuid.uuid4().hex)
            try:
                ros_action(state,f'dashboard --seconds {args.seconds} --stop-file /run/airsim/{marker.name}',stream=True,dashboard=args.dashboard)
            except KeyboardInterrupt:pass
            finally:marker.touch()
        elif args.action == 'view':
            info = owned_ros(state)
            if not info or not info['State']['Running']:
                raise RuntimeError('算法容器未运行')
            command('docker', 'exec', '-d', state['ros_container'], 'bash',
                    '/lesson/stage3/super/airsim/view.sh')
            print('已请求启动 RViz；检查本次运行目录 rviz.log')
        elif args.action == 'snapshot':
            info = owned_ros(state)
            if not info or not info['State']['Running']:
                raise RuntimeError('算法容器未运行')
            print(command('docker', 'exec', state['ros_container'], 'python3',
                          '/lesson/stage3/super/airsim/camera_snapshot.py', timeout=15).stdout)
        else:
            if state.get('ros_container'):
                if state['config'].get('diagnostics'):
                    raise RuntimeError('此实例为隔离响应测试；使用 diagnostics/diagnose.py response-run，不能执行正常 task/fault')
                if (Path(state['run_dir'])/'land.request.json').exists():
                    raise RuntimeError('本轮已手动中止；确认落地后 down/up，再开始新任务')
                try:
                    result=ros_action(state, f'fault --case {args.case}' if args.action == 'fault' else 'fly',stream=True,dashboard=args.dashboard)
                    if not getattr(result,'streamed',False):print(result.stdout)
                except (KeyboardInterrupt, subprocess.TimeoutExpired):
                    request_land(state)
                    raise
                return
            from round_trip import run_task, land
            if args.action == "land":
                info = owned_container(state)
                if not host_alive(state) or not info or not info["State"]["Running"]:
                    raise RuntimeError("场景或飞控未运行，无法发送降落请求")
                land(state)
            else:
                if state["phase"] != "ready" or not ready(state):
                    raise RuntimeError("当前实例未就绪，请先 status")
                run_task(state)


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and not getattr(exc, 'streamed', False):
            print((exc.stderr or exc.stdout or "")[-2000:], file=sys.stderr)
        raise SystemExit(1)
