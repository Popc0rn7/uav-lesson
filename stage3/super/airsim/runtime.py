#!/usr/bin/env python3
"""PC Linux：统一管理宿主机 AirSim 与现有镜像中的 PX4 SITL。"""
import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
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


def resolve(path, base):
    return (base / path).resolve()


def load_config(path):
    config = json.loads(path.read_text())
    config["scene_dir"] = str(resolve(config["scene_dir"], path.parent))
    config["binary"] = str(resolve(config["binary"], Path(config["scene_dir"])))
    config["settings"] = str(resolve(config["settings"], path.parent))
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


def check_ports():
    for kind, ports in [(socket.SOCK_STREAM, [4560, 41451]),
                        (socket.SOCK_DGRAM, [14540, 14580, 18570, 14280, 13030])]:
        for port in ports:
            with socket.socket(socket.AF_INET, kind) as sock:
                try:
                    if kind == socket.SOCK_STREAM:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(("0.0.0.0", port))
                    if kind == socket.SOCK_STREAM:
                        sock.listen(1)
                except OSError as exc:
                    protocol = "TCP" if kind == socket.SOCK_STREAM else "UDP"
                    if exc.errno == errno.EADDRINUSE:
                        raise RuntimeError(f"{protocol} 端口 {port} 已占用；先确认现有实例用途") from exc
                    raise RuntimeError(f"无法检查 {protocol} 端口 {port}：{exc}") from exc


def runtime_settings(config):
    settings = json.loads(Path(config["settings"]).read_text())
    vehicles = settings.get("Vehicles", {})
    if list(vehicles) != ["PX4"] or vehicles["PX4"].get("VehicleType") != "PX4Multirotor":
        raise ValueError("当前入口需要唯一的 PX4 / PX4Multirotor，无多机支持")
    settings.update(SimMode="Multirotor", RpcEnabled=True, ApiServerPort=41451,
                    LocalHostIp="127.0.0.1")
    vehicles["PX4"].update(UseSerial=False, UseTcp=True, LockStep=True,
                           LocalHostIp="127.0.0.1", ControlIp="127.0.0.1",
                           TcpPort=4560, ControlPortLocal=14540, ControlPortRemote=14580)
    return settings


def px4(state, module, *args):
    return command("docker", "exec", state["container"],
                   f"/opt/px4-gazebo/bin/px4-{module}", *args, check=False, timeout=6)


def ready(state):
    if not host_alive(state):
        return False
    info = owned_container(state)
    if not info or not info["State"]["Running"]:
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
    if info and info["State"]["Running"] and not force:
        if "arming_state: 1" not in px4(state, "listener", "vehicle_status").stdout:
            raise RuntimeError("未确认 PX4 已解除解锁，先执行 land；保留实例与日志")
    elif host_alive(state) and not force:
        from rpc_client import rpc
        if rpc("getMultirotorState", "PX4", timeout=3)["landed_state"] != 0:
            raise RuntimeError("未确认落地，拒绝停止场景")
    # 先停止场景，让仍连接的仿真循环处理正常退出，避免断连后 lockstep 卡住。
    stop_host(state)
    if info:
        if info["State"]["Running"]:
            command("docker", "stop", "-t", "5", state["container"], timeout=12)
        result = command("docker", "logs", state["container"], check=False)
        (Path(state["run_dir"]) / "px4-console.log").write_text(result.stdout + result.stderr)
        command("docker", "rm", state["container"])
    state["phase"] = "stopped"
    write_state(directory, state)


def up(config, directory):
    settings = runtime_settings(config)
    fingerprint = hashlib.sha256(json.dumps([config, settings], sort_keys=True).encode()).hexdigest()
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "status", "down", "task", "land"])
    parser.add_argument("--config", type=Path, default=HERE / "runtime.example.json")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "artifacts/airsim-runtime")
    parser.add_argument("--image", help="up：覆盖配置中的本地 PX4 镜像")
    parser.add_argument("--force", action="store_true", help="down：显式停止本入口拥有的仿真资源，即使无法确认落地")
    args = parser.parse_args()
    if args.force and args.action != "down":
        parser.error("--force 只适用于 down")
    if args.image and args.action != "up":
        parser.error("--image 只适用于 up")
    directory = args.state_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "runtime.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("其他管理命令正在执行；task 中 Ctrl+C 会尝试降落") from exc
        if args.action == "up":
            config = load_config(args.config.resolve())
            if args.image:
                config["image"] = args.image
            up(config, directory)
            return
        state_file = directory / "state.json"
        if not state_file.exists():
            if args.action in ["status", "down"]:
                print("尚无本入口管理的运行实例")
                return
            raise RuntimeError("请先 up")
        state = json.loads(state_file.read_text())
        if args.action == "down":
            if state["phase"] != "stopped":
                shutdown(state, directory, args.force)
            print("已停止；诊断日志保留")
        elif args.action == "status":
            info = owned_container(state)
            print(json.dumps(dict(phase=state["phase"], airsim_alive=host_alive(state),
                                  px4_running=bool(info and info["State"]["Running"]),
                                  container=state["container"], run_dir=state["run_dir"]),
                             ensure_ascii=False, indent=2))
            if info and info["State"]["Running"]:
                print(px4(state, "commander", "status").stdout)
        else:
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
        if isinstance(exc, subprocess.CalledProcessError):
            print((exc.stderr or exc.stdout or "")[-2000:], file=sys.stderr)
        raise SystemExit(1)
