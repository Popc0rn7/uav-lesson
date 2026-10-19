#!/usr/bin/env python3
"""PC：Stage 2 ADRL 场景＋单 PX4 Docker；不运行 ROS 或自主竞速 baseline。"""
import argparse
import json
import math
import os
import signal
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/'stage3/super/airsim'))
# 复用 SUPER 已验证的进程身份、端口、互斥和 Docker 回收实现。
import runtime as process_manager
sys.path.insert(0, str(HERE))
from prepare import prepare
from session import rpc
from scene import load_settings, maximize_window

STATE_DIR = ROOT/'artifacts/stage2-airsim'


def ready(state, require_preflight=True):
    try:
        return check_ready(state, require_preflight)
    except subprocess.TimeoutExpired:
        # 切图会暂时停止 HIL；单次 listener 超时只表示尚未就绪。
        # up/load_level 的总 deadline 仍负责判定持续停流失败。
        return False


def check_ready(state, require_preflight=True):
    if not process_manager.host_alive(state):
        return False
    info = process_manager.owned_container(state)
    if not info or not info['State']['Running']:
        return False
    sensors = process_manager.px4(state, 'listener', 'sensor_combined', '-n', '2')
    import re
    stamps = re.findall(r'^    timestamp: (\d+)', sensors.stdout, re.M)
    if sensors.returncode or len(stamps) != 2 or int(stamps[1]) <= int(stamps[0]):
        return False
    position = process_manager.px4(state, 'listener', 'vehicle_local_position').stdout
    if not all(x in position for x in ('xy_valid: True', 'z_valid: True')):
        return False
    if require_preflight and 'Preflight check: OK' not in process_manager.px4(state, 'commander', 'check').stdout:
        return False
    try:
        return bool(rpc(state, 'ping')) and 'kinematics_estimated' in rpc(state, 'getMultirotorState', 'PX4')
    except (OSError, RuntimeError):
        return False


def stop_session(state):
    pid = state.get('rpc_pid')
    if pid is None:
        return
    try:
        if process_manager.start_ticks(pid) != state['rpc_start_ticks']:
            return
        argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        if str(HERE/'session.py').encode() not in argv or str(Path(state['run_dir'])/'rpc.sock').encode() not in argv:
            raise RuntimeError('RPC 代理进程身份不匹配，拒绝停止')
        os.killpg(pid, signal.SIGTERM)
    except (FileNotFoundError, ProcessLookupError):
        pass


def shutdown(state, force=False):
    try:
        process_manager.shutdown(state, STATE_DIR, force=force)
    finally:
        # 先停场景，后关闭持久 RPC；避免旧 rpclib 会话 teardown 崩溃。
        if not process_manager.host_alive(state):
            stop_session(state)


def load_level(state, level, deadline, already_loaded=False):
    if not level:
        return
    print(f'加载默认 level：{level}（不解锁、不启动比赛）…', flush=True)
    if not already_loaded:
        result = rpc(state, 'simLoadLevel', level)
        if result is not True:
            raise RuntimeError(f'默认 level 加载失败：{level}，返回 {result!r}')
    loaded_at = time.monotonic()
    stable = 0
    while time.monotonic() < deadline:
        if not process_manager.host_alive(state):
            raise RuntimeError('加载 level 后场景退出；查看 airsim-console.log')
        gates = rpc(state, 'simListSceneObjects', 'Gate.*')
        settled = all(math.sqrt(sum(v*v for v in rpc(state, 'getMultirotorState', name)
                                   ['kinematics_estimated']['linear_velocity'].values())) < .1
                      for name in ('PX4', 'drone_2'))
        if gates and settled and ready(state, require_preflight=False) and time.monotonic()-loaded_at >= 2:
            stable += 1
            if stable >= 3:
                state['level_loaded'] = dict(name=level, gate_count=len(gates), gates=gates)
                process_manager.write_state(STATE_DIR, state)
                print(f'{level} 已加载，赛门 {len(gates)} 个；切图后传感器/定位已重新就绪', flush=True)
                return
        else:
            stable = 0
        time.sleep(1)
    raise RuntimeError(f'{level} 加载后赛门/传感器/定位未就绪；查看本轮日志')


def reset_race(state, args):
    """完整重建仿真，在 PX4 启动前恢复地图起点，避免在线瞬移。"""
    status = process_manager.px4(state, 'listener', 'vehicle_status').stdout
    if 'arming_state: 1' not in status:
        raise RuntimeError('未确认 PX4 已解除解锁，拒绝复位比赛位置')
    if rpc(state, 'isApiControlEnabled', 'PX4'):
        raise RuntimeError('API 控制仍开启，拒绝复位比赛位置')
    config = state['config']
    args.settings = Path(config['settings_input'])
    args.image = config['image']
    args.window_mode = config['window_mode']
    if not args.display and state.get('pid'):
        try:
            environment = Path(f"/proc/{state['pid']}/environ").read_bytes().split(b'\0')
            args.display = next((v.split(b'=', 1)[1].decode() for v in environment
                                 if v.startswith(b'DISPLAY=')), None)
        except OSError:
            pass
    print('复位比赛：回收本轮，再从地图内置起点重新启动；端口释放可能需要等待。', flush=True)
    shutdown(state)
    up(args)


def start_race(state):
    """先启动原生 Tier 2 赛务，确认其执行后才允许课程控制器运行。"""
    if state.get('race', {}).get('phase') != 'prepared':
        raise RuntimeError('本轮不在准备状态；重复比赛需先 reset-race')
    status = process_manager.px4(state, 'listener', 'vehicle_status').stdout
    if 'arming_state: 1' not in status:
        raise RuntimeError('开赛前须保持未解锁；请先落地并 reset-race')
    if not ready(state, require_preflight=False):
        raise RuntimeError('传感器/定位链路未就绪，不能开赛；解锁检查在控制开始前单独执行')
    # Tier 2 为原生无对手赛制：保留第二机体满足起跑区分配，开赛时由赛务隐藏它。
    result = rpc(state, 'simStartRace', 2)
    if result is False:
        raise RuntimeError('原生赛务拒绝开赛')
    deadline = time.monotonic()+5
    while time.monotonic() < deadline:
        if rpc(state, 'simGetDisqualified', 'drone_2'):
            state['race'].update(phase='racing', tier=2, started_wall_time=time.time())
            process_manager.write_state(STATE_DIR, state)
            print('原生比赛已开始（Tier 2 / Go!）；现在可用 QGC 解锁或运行 test。未自动起飞。')
            return
        time.sleep(.1)
    raise RuntimeError('未观察到原生 Tier 2 开赛状态；不开放课程控制器')


def up(args):
    state_file = STATE_DIR/'state.json'
    if state_file.exists():
        old = json.loads(state_file.read_text())
        if old['phase'] != 'stopped':
            if ready(old, require_preflight=False):
                if not old.get('race'):
                    raise RuntimeError('旧实例没有原生准备区状态；落地后执行 reset-race')
                print(f"Stage 2 实例已就绪，比赛阶段 {old['race']['phase']}；配置变更需先 down 再 up")
                return
            raise RuntimeError('已有实例未正常停止；先 status / down，故障回收用 stop')
    settings = load_settings(args.settings)
    image = process_manager.command('docker', 'image', 'inspect', args.image)
    args.image = json.loads(image.stdout)[0]['Id']
    if process_manager.inspect_container('uav-stage2-airsim-px4'):
        raise RuntimeError('同名容器已存在；拒绝接管')
    process_manager.check_ports()
    package = STATE_DIR/'package-realtime-sitl'
    executable = prepare(args.scene if args.scene is not None else process_manager.scene_package(process_manager.scene_binary('AIRSIM_RACE')),
                         package, disable_lockstep=True)
    owner = uuid.uuid4().hex
    run_dir = STATE_DIR/owner
    run_dir.mkdir()
    (run_dir/'px4-logs').mkdir()
    settings_path = run_dir/'settings.json'
    settings_path.write_text(json.dumps(settings, indent=2)+'\n')
    # ADRL 旧包从可执行文件旁读取设置，避免修改用户 Documents/AirSim。
    sidecar = executable.parent/'settings.json'
    if sidecar.is_symlink() and not sidecar.resolve().is_relative_to(STATE_DIR):
        raise RuntimeError(f'拒绝覆盖未知设置链接：{sidecar}')
    if sidecar.exists() and not sidecar.is_symlink():
        raise RuntimeError(f'拒绝覆盖未知设置：{sidecar}')
    sidecar.unlink(missing_ok=True)
    sidecar.symlink_to(settings_path)
    state = dict(owner=owner, fingerprint=owner, phase='starting', run_dir=str(run_dir),
                 container='uav-stage2-airsim-px4', container_id=None,
                 binary=str(executable), runtime_settings=str(settings_path),
                 config=dict(image=args.image, settings_input=str(args.settings.resolve()),
                             level=settings.get('Default Environment', ''),
                             view_mode=settings.get('ViewMode', ''), window_mode=args.window_mode))
    env = os.environ.copy()
    if args.display:
        env['DISPLAY'] = args.display
    if not env.get('DISPLAY'):
        raise RuntimeError('需要 PC 图形会话的 DISPLAY，或显式 --display :N')
    with (run_dir/'airsim-console.log').open('w') as log:
        process = subprocess.Popen([str(executable), 'ADRL', '-windowed', '-ResX=1280', '-ResY=720',
                                    '-nosound', '-vulkan', *process_manager.AIRSIM_INPUT_ARGS,
                                    f'-settings={settings_path}'],
                                   cwd=package, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    state.update(pid=process.pid, start_ticks=process_manager.start_ticks(process.pid))
    process_manager.write_state(STATE_DIR, state)
    try:
        with (run_dir/'rpc-session.log').open('w') as log:
            proxy = subprocess.Popen([sys.executable, str(HERE/'session.py'), 'serve', str(run_dir/'rpc.sock')],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        state.update(rpc_pid=proxy.pid, rpc_start_ticks=process_manager.start_ticks(proxy.pid))
        process_manager.write_state(STATE_DIR, state)
        deadline = time.monotonic()+180
        print(f'AirSim PID={process.pid}，等待场景 TCP 4560；日志 {run_dir}', flush=True)
        while not process_manager.listen_owned(process.pid, 4560):
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('场景没有监听 4560；查看 airsim-console.log')
            time.sleep(.3)
        if args.window_mode == 'maximized':
            state['window'] = maximize_window(process.pid, env.get('DISPLAY'))
            process_manager.write_state(STATE_DIR, state)
            print(f"窗口已最大化（非全屏）：{state['window']['width']}×{state['window']['height']}", flush=True)
        level = settings.get('Default Environment', '')
        if level:
            print('先加载默认地图，再启动 PX4，避免已运行 HIL 跨地图时钟/原点重置。', flush=True)
            while True:
                try:
                    if rpc(state, 'ping'):
                        break
                except (OSError, RuntimeError):
                    if time.monotonic() > deadline:
                        raise RuntimeError('PX4 启动前场景 RPC 未就绪')
                time.sleep(.5)
            if rpc(state, 'simLoadLevel', level) is not True:
                raise RuntimeError(f'默认地图加载失败：{level}')
            time.sleep(2)
            rpc(state, 'simResetRace')
            time.sleep(1)
            slots = {name: rpc(state, 'simGetVehiclePose', name) for name in ('PX4', 'drone_2')}
            for pose in slots.values():
                if not all(math.isfinite(v) for values in pose.values() for v in values.values()):
                    raise RuntimeError('原生起跑区摆放位姿无效')
            if math.dist(list(slots['PX4']['position'].values()),
                         list(slots['drone_2']['position'].values())) < .01:
                raise RuntimeError('原生赛务未分配两个不同出发位，拒绝回退到 PlayerStart')
            start_pose = slots['PX4']
            state['race'] = dict(phase='prepared', tier=2, start_positions=slots,
                                 placement='native start_block / race_start')
        result = process_manager.command('docker', 'run', '-d', '--init', '--name', state['container'],
            '--network', 'host', '--label', f'{process_manager.LABEL}={owner}',
            '--mount', f'type=bind,source={ROOT}/stage3/super/airsim,target=/lesson-airsim,readonly',
            '--mount', f'type=bind,source={run_dir}/px4-logs,target=/flight-logs',
            '--mount', f'type=bind,source={run_dir}/px4-logs,target=/root/.local/share/px4/rootfs/fs/log',
            '--entrypoint', '/bin/bash', args.image, '/lesson-airsim/px4_start.sh', timeout=30)
        state['container_id'] = result.stdout.strip()
        process_manager.write_state(STATE_DIR, state)
        print('PX4 已启动，等待传感器、定位与 RPC…', flush=True)
        while not ready(state, require_preflight=False):
            if not process_manager.host_alive(state) or time.monotonic() > deadline:
                raise RuntimeError('PX4/场景未就绪；查看本轮日志')
            time.sleep(1)
        load_level(state, level, deadline, already_loaded=True)
        if level:
            actual_pose = rpc(state, 'simGetVehiclePose', 'PX4')
            expected, actual = start_pose['position'], actual_pose['position']
            error_xy = math.hypot(expected['x_val']-actual['x_val'], expected['y_val']-actual['y_val'])
            qa, qb = start_pose['orientation'], actual_pose['orientation']
            angle = math.degrees(2*math.acos(min(1., abs(sum(qa[key]*qb[key] for key in qa)))))
            if error_xy > .15 or angle > 5:
                raise RuntimeError('原生固定出发位准备未生效，拒绝标记就绪')
            state['race_reset'] = dict(native_start=start_pose, after=actual_pose,
                                      horizontal_error_m=error_xy, orientation_error_deg=angle,
                                      api_control=rpc(state, 'isApiControlEnabled', 'PX4'))
        health = process_manager.px4(state, 'commander', 'check').stdout
        state['startup_preflight'] = dict(ok='Preflight check: OK' in health, output=health)
        state['phase'] = 'ready'
        process_manager.write_state(STATE_DIR, state)
        print('Stage 2 已进入原生准备区；未开赛、未解锁。执行 start-race 后再开始控制。')
        if not state['startup_preflight']['ok']:
            print('PX4 preflight 尚未通过：保留场景供 QGC 配置/等待定位收敛；不代表允许解锁。请检查 QGC 消息。')
    except BaseException as exc:
        failure = dict(error_type=type(exc).__name__, error=str(exc),
                       host_returncode=process.poll(), traceback=traceback.format_exc())
        (run_dir/'startup-error.json').write_text(json.dumps(failure, indent=2)+'\n')
        state['startup_error'] = failure
        process_manager.write_state(STATE_DIR, state)
        print(f'启动失败：{type(exc).__name__}: {exc}；回收本轮资源。诊断：{run_dir}/startup-error.json',
              file=sys.stderr, flush=True)
        shutdown(state, force=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['up', 'status', 'down', 'stop', 'land', 'test', 'reset-race', 'start-race'])
    parser.add_argument('--scene', type=Path, default=None)
    parser.add_argument('--image', default='px4io/px4-sitl-gazebo:latest')
    parser.add_argument('--display', help='up：显式指定 PC X11 显示器')
    parser.add_argument('--settings', type=Path, default=HERE/'settings.json',
                        help='up：原生 AirSim 设置，包含默认 level 和视角')
    parser.add_argument('--window-mode', choices=['maximized', 'windowed'], default='maximized',
                        help='up：默认窗口最大化（非 fullscreen）；windowed 保留 1280×720')
    parser.add_argument('--finish', choices=['land', 'loss', 'handoff'], default='land',
                        help='test：正常降落、设定值失流降落、外部 Hold 接管（需随后 land）')
    args = parser.parse_args()
    if args.action != 'test' and args.finish != 'land':
        parser.error('--finish 只用于 test')
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with process_manager.management_lock(STATE_DIR, args.action):
        if args.action == 'up':
            up(args)
            return
        state_file = STATE_DIR/'state.json'
        if not state_file.exists():
            if args.action in ('status', 'down', 'stop'):
                print('尚无 Stage 2 管理实例')
                return
            raise RuntimeError('请先 up')
        state = json.loads(state_file.read_text())
        if args.action == 'status':
            info = process_manager.owned_container(state)
            print(json.dumps(dict(phase=state['phase'], airsim_alive=process_manager.host_alive(state),
                px4_running=bool(info and info['State']['Running']), run_dir=state['run_dir'],
                live_sensor_position_ready=ready(state, require_preflight=False)
                    if info and info['State']['Running'] else False,
                startup=state['config'], window=state.get('window'),
                level_loaded=state.get('level_loaded'), startup_preflight=state.get('startup_preflight'),
                startup_error=state.get('startup_error'), race_reset=state.get('race_reset'),
                race=state.get('race')), indent=2))
            if info and info['State']['Running']:
                print(process_manager.px4(state, 'commander', 'status').stdout)
                print(process_manager.px4(state, 'commander', 'check').stdout)
        elif args.action in ('down', 'stop'):
            if args.action == 'stop':
                (Path(state['run_dir'])/'land.request').touch()
            if state['phase'] != 'stopped':
                shutdown(state, force=args.action == 'stop')
            print('实例已停止，日志保留；stop 为仿真急停，不代表正常降落' if args.action == 'stop' else '实例已停止，日志保留')
        elif args.action == 'start-race':
            start_race(state)
        elif args.action == 'reset-race':
            if state['phase'] != 'ready':
                raise RuntimeError('请先启动场景')
            reset_race(state, args)
        elif args.action == 'land':
            (Path(state['run_dir'])/'land.request').touch()
            process_manager.owned_container(state)
            result = process_manager.px4(state, 'commander', 'mode', 'auto:land')
            if result.returncode:
                raise RuntimeError(result.stdout+result.stderr)
            print(result.stdout)
            print('已请求降落；通过 status 确认解除解锁')
        elif args.action == 'test':
            if state.get('race', {}).get('phase') != 'racing':
                raise RuntimeError('尚未开赛；先执行 start-race，再开始控制')
            if state['phase'] != 'ready' or not ready(state):
                raise RuntimeError('实例未就绪')
            from flight import fly
            fly(state, finish=args.finish)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
