#!/usr/bin/env python3
"""PC：核验并记录 OHOS 主机工作区；不连接设备、不安装依赖或复制旧实验产物。"""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess


def environment(project):
    values = {}
    path = project / '.env'
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:]
            key, sep, value = line.partition('=')
            if sep:
                values[key.strip()] = ' '.join(shlex.split(value, comments=True))
    return {**values, **os.environ}


def describe(project):
    env = environment(project)
    def path(key, default=None):
        value = env.get(key) or default
        if not value:
            raise ValueError(f'请在项目 .env 设置 {key}')
        return (project / Path(value).expanduser()).absolute()
    paths = {'sdk': path('OHOS_SDK'), 'toolchains': path('OHOS_TOOLCHAINS_DIR'),
             'host_python': path('OHOS_HOST_PYTHON'),
             'work_dir': path('BOARD_WORK_DIR', '.board-work')}
    for file in (paths['sdk']/'build/cmake/ohos.toolchain.cmake',
                 paths['sdk']/'oh-uni-package.json', paths['toolchains']/'hdc', paths['host_python']):
        if not file.is_file():
            raise FileNotFoundError(file)
    # 仅 import 主机生成工具，不执行目标 ELF，也不调用网络服务。
    probe = "import json,sys; import em,catkin_pkg,lark,numpy,yaml; print(json.dumps({'python':sys.version.split()[0],'numpy':numpy.__version__}))"
    result = subprocess.run([str(paths['host_python']), '-c', probe],
                            text=True, capture_output=True, check=True, timeout=20)
    return {'paths': {key: str(value) for key, value in paths.items()},
            'sdk': json.loads((paths['sdk']/'oh-uni-package.json').read_text()),
            'host': json.loads(result.stdout)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--write', action='store_true', help='检查通过后写入工作区 host-environment.json')
    args = parser.parse_args()
    record = describe(args.project.resolve())
    if args.write:
        directory = Path(record['paths']['work_dir'])
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'host-environment.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
