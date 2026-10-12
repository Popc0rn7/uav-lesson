#!/usr/bin/env python3
"""PC：Humble perfect_drone_sim corridor 竞速 demo。"""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / 'thirdparty/super_gazebo_ws'
NAME = 'uav-stage3-race'
IMAGE = 'uav-stage3-race:local'


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'up', 'verify', 'view', 'view-close', 'logs', 'down'])
    args = parser.parse_args()
    if args.action == 'build':
        if not (WS / 'src/SUPER').is_dir():
            parser.error('先运行 stage3/super_docker.py prepare 和 build')
        run('docker', 'build', '-f', ROOT / 'stage3/Dockerfile.race', '-t', IMAGE, ROOT / 'stage3')
        run('docker', 'run', '--rm', '--network', 'none', '--user', f'{os.getuid()}:{os.getgid()}',
            '--mount', f'type=bind,source={WS},target=/super_ws', '--entrypoint', 'bash', IMAGE, '-lc',
            'set -e; source /opt/ros/humble/setup.bash; cd /super_ws; '
            'CMAKE_BUILD_PARALLEL_LEVEL=2 MAKEFLAGS=-j2 colcon build '
            '--packages-up-to perfect_drone_sim super_planner --executor sequential '
            '--cmake-args -DCMAKE_BUILD_TYPE=Release')
    elif args.action == 'up':
        if not (WS / 'install/perfect_drone_sim').is_dir():
            parser.error('请先 build')
        run('docker', 'run', '-d', '--init', '--name', NAME, '--network', 'host',
            '--mount', f'type=bind,source={ROOT},target=/lesson,readonly',
            '--mount', f'type=bind,source={WS},target=/super_ws', IMAGE)
    elif args.action == 'verify':
        run('docker', 'exec', NAME, 'bash', '-lc',
            'source /opt/ros/humble/setup.bash; source /super_ws/install/local_setup.bash; '
            'python3 /lesson/stage3/verify_super_race.py')
    elif args.action == 'view':
        display = os.environ.get('DISPLAY')
        authority = os.environ.get('XAUTHORITY')
        if not display or not authority or not Path(authority).is_file():
            parser.error('请在 PC 图形桌面终端执行，需要 DISPLAY 和可读的 XAUTHORITY')
        run('docker', 'run', '-d', '--init', '--name', NAME + '-view', '--network', 'host',
            '--user', f'{os.getuid()}:{os.getgid()}',
            '--mount', 'type=bind,source=/tmp/.X11-unix,target=/tmp/.X11-unix,readonly',
            '--mount', f'type=bind,source={Path(authority).resolve()},target=/tmp/desktop.xauth,readonly',
            '--mount', f'type=bind,source={ROOT},target=/lesson,readonly',
            '--mount', f'type=bind,source={WS},target=/super_ws,readonly',
            '-e', f'DISPLAY={display}', '-e', 'XAUTHORITY=/tmp/desktop.xauth',
            '-e', 'FASTRTPS_DEFAULT_PROFILES_FILE=/lesson/stage3/race_view_dds.xml',
            '-e', 'QT_X11_NO_MITSHM=1', '--entrypoint', 'bash', IMAGE, '-lc',
            'source /opt/ros/humble/setup.bash; source /super_ws/install/local_setup.bash; '
            'exec rviz2 -d /lesson/stage3/super_race.rviz')
    elif args.action == 'view-close':
        run('docker', 'stop', '-t', '10', NAME + '-view')
        run('docker', 'rm', NAME + '-view')
    elif args.action == 'logs':
        run('docker', 'exec', NAME, 'bash', '-lc', 'tail -n 40 /tmp/super-race/*.log')
    else:
        run('docker', 'stop', '-t', '10', NAME)
        run('docker', 'rm', NAME)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
