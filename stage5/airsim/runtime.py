#!/usr/bin/env python3
"""PC：统一管理Shipping场景、Stage 5 PX4/ROS双Docker；保留显式Editor兼容模式。"""
import argparse
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from stage3.super.airsim.rpc_client import rpc
from stage5.airsim.config import load, settings, camera_model
from stage5.evidence import write_json
from stage5.airsim import scene_process

HERE = Path(__file__).resolve().parent
LABEL = 'io.uav-lesson.stage5.airsim.owner'


def command(*args, check=True, timeout=15):
    return subprocess.run(list(map(str, args)), check=check, capture_output=True, text=True, timeout=timeout)


def call(config, method, *args):
    return rpc(method, *args, host=config['rpc_host'], port=config['rpc_port'], timeout=4)


def container(name):
    out = command('docker', 'container', 'inspect', name, check=False)
    if out.returncode:
        if 'No such' in out.stderr:
            return None
        raise RuntimeError(out.stderr)
    return json.loads(out.stdout)[0]


def owned(state, role):
    info = container(state['config'][role+'_container'])
    if info and ((info['Config'].get('Labels') or {}).get(LABEL) != state['run_id'] or
                 info['Id'] != state.get(role+'_id')):
        raise RuntimeError(f'{role} 容器身份已改变，拒绝接管')
    return info


def px4(state, module, *args):
    info = owned(state, 'px4')
    if not info or not info['State']['Running']:
        raise RuntimeError('本次 PX4 未运行')
    return command('docker', 'exec', info['Id'], f'/opt/px4-gazebo/bin/px4-{module}',
                   '--instance', '5', *args, timeout=8)


def free_port(kind, port):
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.bind(('127.0.0.1', port))


def verify_editor(config):
    if call(config, 'listVehicles') != [config['vehicle_name']]:
        raise RuntimeError('场景车辆列表与配置不符')
    actual = json.loads(call(config, 'getSettingsString'))
    expected = settings(config)
    if actual != expected:
        raise RuntimeError('场景未加载当前配置；核对settings后down/up重启。')
    convoy = json.loads(call(config, 'simGetConvoyStatus'))
    if not convoy.get('ok') or convoy.get('state') not in ('idle', 'stopped'):
        raise RuntimeError(f'首轮传感器接入要求车队驻车：{convoy}')
    return dict(settings=actual, convoy=convoy)


def editor_listener(config):
    # PX4Multirotor 的 BeginPlay 可能等待 HIL 后才启动 RPC；不能先等 RPC，也不能探连 HIL。
    target = Path(config['editor_settings']).resolve()
    if json.loads(target.read_text()) != settings(config):
        raise RuntimeError('场景配置未安装；先 install-settings，再 Editor Play')
    listeners = command('ss', '-H', '-ltnp', 'sport = :4565').stdout
    pids = re.findall(r'pid=(\d+)', listeners)
    if config.get('scene_backend') == 'packaged':
        expected = scene_process.paths(config)[1]
        for pid in pids:
            try:
                if Path(f'/proc/{pid}/exe').resolve() == expected:
                    cmd = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode()
                    return dict(pid=int(pid), command_line=cmd, hil_port=4565, scene_backend='packaged')
            except OSError:
                continue
        raise RuntimeError('Shipping场景尚无HIL监听，见本轮scene.log')
    projects = list(target.parents[2].glob('*.uproject'))
    if len(projects) != 1:
        raise RuntimeError('场景工程目录必须包含唯一的 .uproject')
    project = projects[0]
    for pid in pids:
        command_line = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode()
        editor = 'UE4Editor' in command_line and str(project) in command_line
        packaged = project.parent/'Packages/LinuxNoEditor'/project.stem/'Binaries/Linux'/project.stem
        try:
            is_packaged = Path(f'/proc/{pid}/exe').resolve() in (
                packaged.resolve(), packaged.with_name(project.stem+'-Linux-Shipping').resolve())
        except OSError:
            is_packaged = False
        if editor or is_packaged:
            return dict(pid=int(pid), command_line=command_line, hil_port=4565,
                        scene_backend='packaged' if is_packaged else 'editor')
    raise RuntimeError('未找到目标 Editor/打包程序的 HIL 4565 监听；请Play或启动打包场景，勿探连该TCP端口')


def prepare(config, directory, install=False):
    target = Path(config['editor_settings']).expanduser().resolve()
    output = directory/'prepared'
    output.mkdir(parents=True, exist_ok=True)
    desired = settings(config)
    write_json(output/'settings.json', desired)
    write_json(output/'calibration.json', camera_model(config))
    if install:
        # Play 时拒绝覆盖文件；不 reset、不关闭 UE、不模拟按键。
        for port in (config['rpc_port'], 4565):
            free_port(socket.SOCK_STREAM, port)
        current = json.loads(target.read_text())
        if current != desired:
            vehicle = current.get('Vehicles', {})
            name = config['vehicle_name']
            if list(vehicle) != [name]:
                raise RuntimeError('场景车辆已变化，拒绝覆盖')
            previous_pose = [vehicle[name].get(k) for k in ('X', 'Y', 'Z')]
            if previous_pose != config['spawn_ned_m'] or vehicle[name].get('Yaw') != config['spawn_yaw_deg']:
                # 允许明确调整出生位置/朝向，但不覆盖其他来源的未知设置。
                previous = {**config, 'spawn_ned_m': previous_pose, 'spawn_yaw_deg': vehicle[name].get('Yaw')}
                if current != settings(previous):
                    raise RuntimeError('出生位姿不同且现有设置不是本入口生成的已知配置，拒绝覆盖')
            backup = target.with_name(f'{target.name}.stage5-{uuid.uuid4().hex}.bak')
            with backup.open('xb') as stream:
                stream.write(target.read_bytes())
            write_json(output/'installation.json', dict(target=str(target), backup=str(backup)))
            write_json(target, desired)
    return dict(settings=str(output/'settings.json'), editor_settings=str(target), installed=install,
                next='执行runtime up自动启动Shipping场景' if config.get('scene_backend') == 'packaged' else 'Editor Play后执行up')


def inspect(state):
    directory = Path(state['run_dir'])
    path = directory/'sensors.json'
    sensors = json.loads(path.read_text()) if path.exists() else {}
    running = {role: bool((info := owned(state, role)) and info['State']['Running']) for role in ('px4', 'ros')}
    fresh = path.exists() and time.time()-path.stat().st_mtime < 2
    scene_info = state.get('scene')
    scene_running = scene_process.alive(scene_info) if scene_info else None
    transport_ready = bool(all(running.values()) and fresh and sensors.get('healthy') and scene_running is not False)
    return dict(run_id=state['run_id'], run_dir=str(directory), phase=state['phase'], running=running,
                ready=transport_ready and state['phase'] == 'ready', transport_ready=transport_ready,
                airsim_alive=scene_running, px4_running=running['px4'], ros_running=running['ros'],
                scene=dict(managed=bool(scene_info), running=scene_running, pid=scene_info.get('pid') if scene_info else None,
                           log=scene_info.get('log') if scene_info else None),
                sensors=sensors, sensor_status_fresh=fresh,
                raw_camera_source=f'http://127.0.0.1:{state["config"]["raw_port"]}',
                web_images='model_request_snapshots_only')


def archive(state):
    directory = Path(state['run_dir'])
    for role in ('px4', 'ros'):
        info = owned(state, role)
        if info:
            result = command('docker', 'logs', info['Id'], check=False)
            (directory/f'{role}-docker.log').write_text(result.stdout+result.stderr)


def shutdown(state, state_path, force=False):
    resources = {role: owned(state, role) for role in ('ros', 'px4')}
    info = resources['px4']
    if info and info['State']['Running'] and not force:
        status = px4(state, 'listener', 'vehicle_status').stdout
        if not any(line.strip() == 'arming_state: 1' for line in status.splitlines()):
            raise RuntimeError('尚未确认 Disarmed；先 land/status，仿真卡住时使用 down --force')
    state['phase'] = 'stopping'
    write_json(state_path, state)
    errors = []
    for role, info in resources.items():
        if info:
            try:
                command('docker', 'stop', '-t', '5', info['Id'])
            except Exception as exc:
                errors.append(f'{role} stop: {exc}')
            try:
                result = command('docker', 'logs', info['Id'], check=False)
                (Path(state['run_dir'])/f'{role}-docker.log').write_text(result.stdout+result.stderr)
            except Exception as exc:
                errors.append(f'{role} logs: {exc}')
            try:
                command('docker', 'rm', info['Id'])
            except Exception as exc:
                errors.append(f'{role} remove: {exc}')
    try:
        scene_process.stop(state.get('scene'))
    except Exception as exc:
        errors.append(f'scene stop: {exc}')
    if errors:
        state['cleanup_errors'] = errors
        write_json(state_path, state)
        raise RuntimeError('部分回收失败，保留stopping状态，可重新down：'+'; '.join(errors))
    state['phase'] = 'stopped'
    write_json(state_path, state)
    return dict(stopped=True, scene='本轮场景已回收' if state.get('scene') else '外部场景保持原状', run_dir=state['run_dir'])


def start(config, directory):
    state_path = directory/'state.json'
    if state_path.exists():
        previous = json.loads(state_path.read_text())
        if previous['phase'] != 'stopped':
            if previous['phase'] == 'ready' and previous['config'] == config:
                report = inspect(previous)
                if report['ready']: return report
            raise RuntimeError('本入口已有未回收运行记录；先status/down，不覆盖现场')
    for name in (config['px4_container'], config['ros_container'], 'uav-stage5-gazebo'):
        if container(name):
            raise RuntimeError(f'{name} 已存在，先确认来源及状态')
    managed = config.get('scene_backend') == 'packaged'
    editor = None
    if managed:
        scene_process.validate(config)
        if json.loads(Path(config['editor_settings']).read_text()) != settings(config):
            raise RuntimeError('包内settings与runtime配置不一致；先install-settings或核对配置')
        # 只绑定检查端口是否可用，绝不作为客户端连接HIL。
        until = time.monotonic()+60
        while True:
            try:
                for port in (4565, config['rpc_port']): free_port(socket.SOCK_STREAM, port)
                break
            except OSError:
                listeners = command('ss', '-H', '-ltnp', '( sport = :4565 or sport = :'+str(config['rpc_port'])+' )').stdout
                if listeners.strip() or time.monotonic() >= until:
                    raise RuntimeError('场景端口被其他实例或残留连接占用；先关闭旧场景/down，不接管外部实例') from None
                time.sleep(.5)
    else:
        editor = editor_listener(config)
    free_port(socket.SOCK_STREAM, config['raw_port'])
    for port in (8895, 14585, 14586, 18575, 14285, 13035):
        free_port(socket.SOCK_DGRAM, port)
    images = {role: json.loads(command('docker', 'image', 'inspect', config[role+'_image']).stdout)[0]['Id']
              for role in ('px4', 'ros')}
    run_id = uuid.uuid4().hex
    run_dir = directory/run_id
    (run_dir/'px4-logs').mkdir(parents=True)
    write_json(run_dir/'config.json', config)
    write_json(run_dir/'settings.json', settings(config))
    if editor: write_json(run_dir/'editor.json', editor)
    write_json(run_dir/'calibration.json', camera_model(config))
    sources = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in [*HERE.glob('*.py'), *HERE.glob('*.sh'), *HERE.glob('*.xml'), ROOT/'stage3/super/airsim/rpc_client.py',
                            ROOT/'stage3/super/airsim/clock_bridge.py', ROOT/'stage2/models/x500_experiment/model.sdf']}
    write_json(run_dir/'identity.json', dict(images=images, sources=sources,
        commit=command('git', '-C', ROOT, 'rev-parse', 'HEAD').stdout.strip(),
        git_status=command('git', '-C', ROOT, 'status', '--short').stdout, editor_managed_externally=not managed))
    state = dict(run_id=run_id, run_dir=str(run_dir), config=config, phase='starting')
    write_json(state_path, state)
    try:
        if managed:
            state['scene'] = scene_process.launch(config, run_dir)
            write_json(state_path, state)
            write_json(run_dir/'scene.json', state['scene'])
            deadline = time.monotonic()+60
            while True:
                if not scene_process.alive(state['scene']):
                    raise RuntimeError(f'Shipping场景退出，见{run_dir}/scene.log')
                try:
                    editor = editor_listener(config)
                    if editor['pid'] != state['scene']['pid']:
                        raise RuntimeError('HIL监听不属于本轮启动的场景')
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f'Shipping场景60秒未建立HIL监听，见{run_dir}/scene.log') from None
                time.sleep(.5)
            write_json(run_dir/'editor.json', editor)
        for role in ('px4', 'ros'):
            mounts = ['--mount', f'type=bind,source={ROOT},target=/lesson,readonly',
                      '--mount', f'type=bind,source={run_dir},target=/run/stage5']
            if role == 'px4':
                mounts += ['--mount', f'type=bind,source={run_dir}/px4-logs,target=/flight-logs']
            script = 'px4_start.sh' if role == 'px4' else 'run_nodes.sh'
            result = command('docker', 'run', '-d', '--pull=never', '--init', '--network', 'host',
                             '--name', config[role+'_container'], '--label', f'{LABEL}={run_id}',
                             *mounts, '--entrypoint', 'bash', images[role], f'/lesson/stage5/airsim/{script}')
            state[role+'_id'] = result.stdout.strip()
            write_json(state_path, state)
        deadline = time.monotonic()+120
        while time.monotonic() < deadline:
            report = inspect(state)
            if not all(report['running'].values()):
                raise RuntimeError('PX4/ROS 容器退出；检查本轮 node-logs')
            if report['transport_ready']:
                online = verify_editor(config)
                write_json(run_dir/'convoy-before.json', online['convoy'])
                # 与 SUPER 的独立 PX4 接入一致：有效定位、未解锁后进 Hold 再正常预检。
                status = px4(state, 'listener', 'vehicle_status').stdout
                if any(line.strip() == 'arming_state: 1' for line in status.splitlines()):
                    px4(state, 'commander', 'mode', 'auto:loiter')
                check = px4(state, 'commander', 'check')
                (run_dir/'preflight.log').write_text(check.stdout+check.stderr)
                if 'Preflight check: OK' in check.stdout:
                    state['phase'] = 'ready'
                    write_json(state_path, state)
                    report = inspect(state)
                    write_json(run_dir/'startup.json', report)
                    archive(state)
                    return report
            time.sleep(1)
        raise TimeoutError(f'传感器/PX4 120秒未就绪；保留现场 {run_dir}')
    except BaseException as exc:
        state.update(phase='failed', error=str(exc))
        write_json(state_path, state)
        archive(state)
        raise


@contextmanager
def management_lock(directory, action, force=False):
    """与SUPER一致：任务/生命周期互斥，status与独立恢复入口不被任务阻塞。"""
    recovery = action in ('land', 'stop') or (action == 'down' and force)
    with ExitStack() as stack:
        if recovery:
            stream = stack.enter_context((directory/'recovery.lock').open('a'))
            try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('另一个恢复命令正在执行；可用status查看状态') from None
        stream = stack.enter_context((directory/'runtime.lock').open('a'))
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if not (recovery or action in ('status', 'inspect')):
                raise RuntimeError('任务/管理命令正在执行；仍可status、land或stop') from None
            if recovery:
                path = directory/'state.json'
                state = json.loads(path.read_text()) if path.exists() else {}
                if state.get('phase') not in ('ready', 'stopping', 'stopped', 'failed'):
                    raise RuntimeError('正在初始化，先中断up再stop，不并发接管创建中的资源') from None
        yield


def cancel_task(state, reason):
    write_json(Path(state['run_dir'])/'land.request.json', dict(run_id=state['run_id'], reason=reason, requested_at=time.time()))


def request_land(state):
    cancel_task(state, 'manual_land')
    output = px4(state, 'commander', 'land')
    return dict(requested=True, response=output.stdout, note='请求不代表已落地；status确认armed=false；本轮任务已取消，重新任务先down/up')


def dispatch(args, task_args=()):
    directory = args.state_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory/'state.json'
    if args.action == 'task':
        from stage5.airsim.task import main as task_main
        return task_main(['run', '--state-dir', str(directory), *task_args])
    with management_lock(directory, args.action, args.force):
        return dispatch_locked(args, directory, state_path)


def dispatch_locked(args, directory, state_path):
    if args.action == 'health':
        # 显式health是任务前检查，含三次最小模型推理；status仍保持只读、不调用模型。
        output = command(sys.executable, HERE/'task.py', 'check', '--state-dir', directory,
                         check=False, timeout=120)
        print(output.stdout, end='')
        if output.stderr:
            print(output.stderr, file=sys.stderr, end='')
        raise SystemExit(output.returncode)
    if args.action in ('prepare', 'install-settings'):
        result = prepare(load(args.config), directory, args.action == 'install-settings')
    elif args.action == 'up':
        config = load(args.config)
        if args.image: config['px4_image'] = args.image
        result = start(config, directory)
    elif args.action in ('down', 'stop'):
        if state_path.exists():
            state = json.loads(state_path.read_text())
            if args.force or args.action == 'stop': cancel_task(state, 'simulation_stop')
            result = shutdown(state, state_path, args.force or args.action == 'stop')
            if args.force or args.action == 'stop': result['note'] = '仿真急停，不代表正常降落'
        else: result = dict(stopped=True, phase='not_started')
    elif args.action in ('inspect', 'status'):
        if not state_path.exists():
            result = dict(phase='not_started', ready=False)
        else:
            result = inspect(json.loads(state_path.read_text()))
    elif args.action == 'land':
        result = request_land(json.loads(state_path.read_text()))
    elif args.action == 'verify-camera':
        state = json.loads(state_path.read_text())
        info = owned(state, 'ros')
        if not info or not info['State']['Running']:
            raise RuntimeError('本次 ROS 容器未运行')
        output = command('docker', 'exec', info['Id'], 'python3', '/lesson/stage5/verify_camera.py',
                         '--source', f'http://127.0.0.1:{state["config"]["raw_port"]}',
                         '--output', '/run/stage5/camera-check', timeout=75)
        print(output.stdout)
        return
    elif args.action == 'verify-ros':
        state = json.loads(state_path.read_text())
        info = owned(state, 'ros')
        if not info or not info['State']['Running']:
            raise RuntimeError('本次ROS容器未运行')
        shell = ('source /opt/ros/humble/setup.bash; source /opt/px4_ws/install/local_setup.bash; '
                 'exec python3 /lesson/stage5/airsim/verify_ros.py')
        output = command('docker', 'exec', '-e', 'ROS_DOMAIN_ID=15',
                         '-e', 'FASTRTPS_DEFAULT_PROFILES_FILE=/lesson/stage5/airsim/fastdds.xml',
                         info['Id'], 'bash', '-c', shell, check=False, timeout=20)
        print(output.stdout, end='')
        if output.returncode:
            raise SystemExit(output.stderr or 'ROS接口验收失败')
        return
    else:
        state = json.loads(state_path.read_text())
        config = state['config']
        # 使用真实传感器桥原始帧，不申请 API 控制，不改变视角或机体位置。
        from urllib.request import build_opener, ProxyHandler
        import struct
        opener = build_opener(ProxyHandler({}))
        output = Path(state['run_dir'])/f'snapshot-{time.time_ns()}'
        output.mkdir()
        for key in ('rgb', 'depth'):
            with opener.open(f'http://127.0.0.1:{config["raw_port"]}/{key}', timeout=3) as response:
                wire = response.read()
            size = struct.unpack('!I', wire[:4])[0]
            metadata = json.loads(wire[4:4+size])
            write_json(output/f'{key}.json', metadata)
            header = (f'P6\n{metadata["width"]} {metadata["height"]}\n255\n'.encode() if key == 'rgb' else b'')
            (output/('rgb.ppm' if key == 'rgb' else 'depth.f32')).write_bytes(header+wire[4+size:])
        result = dict(snapshot=str(output))
    print(json.dumps(result, ensure_ascii=False, indent=2))



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'install-settings', 'up', 'inspect', 'status', 'health', 'task', 'land', 'stop', 'down', 'snapshot', 'verify-camera', 'verify-ros'))
    parser.add_argument('--config', type=Path, default=HERE/'runtime.demo.json')
    parser.add_argument('--state-dir', type=Path, default=ROOT/'artifacts/stage5-airsim')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='up：只显示配置和拓扑，不启动进程或连接Docker/模型')
    parser.add_argument('--image', help='up：覆盖本地PX4镜像，不拉取')
    args, task_args = parser.parse_known_args(argv)
    if task_args and args.action != 'task': parser.error('未知参数：'+' '.join(task_args))
    if args.action != 'up' and (args.dry_run or args.image): parser.error('--dry-run/--image仅用于up')
    if args.force and args.action != 'down':
        parser.error('--force仅用于down，回收本轮场景与容器，不接管外部Editor')
    if args.dry_run:
        config = load(args.config)
        if args.image: config['px4_image'] = args.image
        print(json.dumps(dict(config=config, topology=['Shipping scene','PX4 Docker','ROS RGBD Docker'], task='Qwen/DINO/Jev -> PX4', model_calls=False),ensure_ascii=False,indent=2))
        return 0
    return dispatch(args, task_args)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as exc:
        print(f'失败：{exc}', file=sys.stderr)
        raise SystemExit(1)
