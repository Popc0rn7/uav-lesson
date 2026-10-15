#!/usr/bin/env python3
"""PC：启动、查看、验证和关闭独立 Stage 5 Gazebo 街区。"""
import argparse
import os
import socket
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SERVER = 'uav-stage5-gazebo'
VIEW = 'uav-stage5-gazebo-view'
CAMERA = 'uav-stage5-camera-view'
PARTITION = 'uav-stage5'
LABEL = 'uav-lesson.stage5.scene=street'


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def exists(name):
    return subprocess.run(['docker', 'inspect', name], capture_output=True).returncode == 0


def check_port(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as exc:
            raise SystemExit(f'本任务端口 {port} 已占用，请检查已有服务：{exc}') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['up', 'view', 'view-follow', 'camera', 'takeoff', 'land',
                                        'target-start', 'target-stop', 'target-reset',
                                        'follow', 'mission', 'verify', 'verify-camera', 'down'])
    parser.add_argument('--image', default='px4io/px4-sitl-gazebo:latest')
    parser.add_argument('--camera-image', default='uav-computer-ros-humble:local')
    parser.add_argument('--seconds', type=float, help='follow 默认60秒，其他验证默认12秒')
    parser.add_argument('--target-speed', type=float, default=.7)
    parser.add_argument('--jev-budget', type=int, default=40)
    parser.add_argument('--task')
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--plan-only',action='store_true')
    parser.add_argument('--budget',type=int,default=10,help='mission的Qwen执行调用额度')
    parser.add_argument('--timeout',type=float,default=300,help='mission总墙钟秒数')
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    if args.seconds is None:args.seconds=60 if args.action in ('follow','mission') else 12
    if not 5 <= args.seconds <= 300:
        parser.error('seconds 须为 5～300 秒')
    run('docker', 'info', '--format', '{{.ServerVersion}}')
    if args.action=='view-follow':
        run('docker','exec',VIEW,'python3','/scene/chase_view.py')
        return
    if args.action in ('follow','mission'):
        python=ROOT/'.venv/bin/python'
        if not python.is_file():raise SystemExit('请先 PC 执行 uv sync --extra stage5')
        command=[python,HERE/('mission.py' if args.action=='mission' else 'follow.py'),'--seconds',args.seconds,
            '--target-speed',args.target_speed,'--jev-budget',args.jev_budget]
        if args.plan:command+=['--plan',args.plan]
        if args.action=='mission':
            command+=['--budget',args.budget,'--timeout',args.timeout]
            if args.task:command+=['--task',args.task]
            if args.plan_only:command+=['--plan-only']
        if args.output:command+=['--output',args.output]
        result=subprocess.run(list(map(str,command)))
        if result.returncode:raise SystemExit(result.returncode)
        return
    if args.action in ('target-start', 'target-stop', 'target-reset'):
        run('docker', 'exec', SERVER, 'python3', '/scene/target_command.py',
            '--speed', 2 if args.action == 'target-start' else 0)
        if args.action == 'target-reset':
            time.sleep(.2)
            result = run('docker', 'exec', SERVER, 'gz', 'service', '-s',
                '/world/stage5_street/set_pose', '--reqtype', 'gz.msgs.Pose',
                '--reptype', 'gz.msgs.Boolean', '--timeout', '3000', '--req',
                'name: "target_car", position: {x: 24 y: 0 z: 0.65}, '
                'orientation: {z: 0.7071067811865476 w: 0.7071067811865476}',
                capture_output=True, text=True)
            if 'data: true' not in result.stdout:
                raise SystemExit('车辆复位失败：' + result.stdout + result.stderr)
        return
    if args.action in ('takeoff', 'land'):
        command = ['docker', 'exec', SERVER, '/opt/px4-gazebo/bin/px4-commander', '--instance', '5']
        if args.action == 'takeoff':
            run(*command, 'arm')
            run(*command, 'takeoff')
        else:
            run(*command, 'land')
        return
    if args.action == 'down':
        for name in (CAMERA, VIEW, SERVER):
            if exists(name):
                label = subprocess.check_output(['docker', 'inspect', name, '--format',
                    '{{index .Config.Labels "uav-lesson.stage5.scene"}}'], text=True).strip()
                if label != 'street':
                    raise SystemExit(f'{name} 不属于本入口，拒绝删除')
                run('docker', 'stop', '-t', '5', name)
                run('docker', 'rm', name)
        return
    if args.action in ('verify', 'verify-camera'):
        if args.action == 'verify':
            run('docker', 'exec', SERVER, 'python3', '/scene/verify_motion.py', '--seconds', args.seconds)
        else:
            run('docker', 'exec', SERVER, 'python3', '/scene/verify_camera.py')
        return
    if args.action == 'camera':
        from depth_fusion import calibration
        if not exists(SERVER):
            raise SystemExit('请先运行 up')
        if exists(CAMERA):
            raise SystemExit(f'{CAMERA} 已存在；图像页面 http://127.0.0.1:8190')
        check_port(8190)
        run('docker', 'run', '--rm', '--pull=never', '--network', 'none',
            '--entrypoint', 'python3', args.camera_image, '-c', 'import numpy; import PIL')
        run('docker', 'run', '-d', '--pull=never', '--init', '--name', CAMERA,
            '--label', LABEL, '--network', 'host',
            '--mount', f'type=bind,source={ROOT}/stage2,target=/viewer,readonly',
            '--entrypoint', 'python3', args.camera_image, '/viewer/sensor_web.py',
            '--source', 'http://127.0.0.1:8189', '--port', '8190',
            '--far', str(calibration()['far_m']))
        print('RGB / 深度图：http://127.0.0.1:8190')
        return
    model_mounts = []
    for model in ('x500_experiment', 'mid360s'):
        source = ROOT / 'stage2/models' / model
        if not (source / 'model.sdf').is_file():
            raise SystemExit(f'缺少标准模型：{source}')
        model_mounts += ['--mount', f'type=bind,source={source},'
                         f'target=/opt/px4-gazebo/share/gz/models/{model},readonly']
    if args.action == 'view':
        if not exists(SERVER):
            raise SystemExit('请先运行 up')
        name = VIEW
        display, auth = os.environ.get('DISPLAY'), os.environ.get('XAUTHORITY')
        if not display or not auth or not Path(auth).is_file():
            raise SystemExit('需要 PC 图形桌面的 DISPLAY 与有效 XAUTHORITY')
        options = ['--mount', 'type=bind,source=/tmp/.X11-unix,target=/tmp/.X11-unix,readonly',
                   '--mount', f'type=bind,source={Path(auth).resolve()},target=/tmp/desktop.xauth,readonly',
                   '-e', f'DISPLAY={display}', '-e', 'XAUTHORITY=/tmp/desktop.xauth',
                   '-e', 'QT_X11_NO_MITSHM=1']
        if Path('/dev/dri/renderD128').exists():
            options += ['--device', '/dev/dri/renderD128']
        command = ['gz', 'sim', '-g']
    else:
        from generate_world import generate
        if exists(SERVER):
            raise SystemExit(f'{SERVER} 已存在；重新开始请先 down')
        run('docker', 'image', 'inspect', args.image, stdout=subprocess.DEVNULL)
        check_port(8189)
        generate()
        name, options = SERVER, ['-e', 'PX4_SYS_AUTOSTART=4001',
            '-e', 'PX4_SIM_MODEL=gz_x500_experiment', '-e', 'PX4_GZ_WORLD=stage5_street',
            '-e', 'PX4_GZ_MODEL_NAME=x500_experiment_0', '-e', 'PX4_UXRCE_DDS_PORT=8895',
            '-e', 'EGL_PLATFORM=surfaceless']
        if Path('/dev/dri/renderD128').exists():
            options += ['--device', '/dev/dri/renderD128']
        command = ['sh', '/scene/start.sh']
    if exists(name):
        raise SystemExit(f'{name} 已存在')
    run('docker', 'run', '-d', '--pull=never', '--init', '--name', name,
        '--label', LABEL, '--network', 'host', '-e', f'GZ_PARTITION={PARTITION}',
        '--mount', f'type=bind,source={HERE},target=/scene,readonly',
        '--mount', f'type=bind,source={ROOT},target=/lesson,readonly',
        *model_mounts, *options, '--entrypoint', '/usr/bin/env', args.image, *command)
    print(f'日志：docker logs {name}')
    if args.action == 'view':
        # Harmonic GUI 初始化时可能暂停 server；恢复本场景的时钟。
        time.sleep(3)
        run('docker','exec',VIEW,'python3','/scene/chase_view.py')
        result = run('docker', 'exec', SERVER, 'gz', 'service', '-s',
            '/world/stage5_street/control', '--reqtype', 'gz.msgs.WorldControl',
            '--reptype', 'gz.msgs.Boolean', '--timeout', '3000', '--req',
            'pause: false', capture_output=True, text=True)
        if 'data: true' not in result.stdout:
            raise SystemExit('恢复时钟失败：' + result.stdout + result.stderr)


if __name__ == '__main__':
    main()
