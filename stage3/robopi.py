#!/usr/bin/env python3
"""PC：AirSim/SUPER 板端构建与部署。运行仍使用 airsim/runtime.py。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'stage3/super/airsim'))
import board_backend


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['preflight','build','deploy','pc-image'])
    parser.add_argument('--target')
    parser.add_argument('--jobs',type=int,default=2,help='build：主机交叉编译并发数')
    parser.add_argument('--config',type=Path,help='build：目标 SDK/依赖配置')
    parser.add_argument('--px4-image',help='pc-image：与基线相同的 PX4 镜像')
    parser.add_argument('--tag',default='uav-airsim-robopi-pc:local')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if args.jobs<1:parser.error('--jobs 必须为正数')
    if args.action in ('preflight','deploy') and not args.target:
        parser.error('设备操作必须显式 --target')
    if args.action=='build' and not args.config:parser.error('build 需要 --config')
    if args.action=='pc-image' and not args.px4_image:parser.error('pc-image 需要 --px4-image')
    if args.dry_run:
        print(json.dumps(dict(action=args.action,target=args.target,config=str(args.config) if args.config else None,
                              px4_image=args.px4_image,tag=args.tag,remote=board_backend.BASE),indent=2))
        return
    # Invoke the repository skill preflight engine before the relevant dependency chain.
    checks=[dict(kind='tool',tool=sys.executable,version_option='--version')]
    if args.action in ('preflight','deploy'):
        checks += [dict(kind='tool',tool='hdc',version_option='-v'),
                   dict(kind='hdc-identity',target=args.target)]
    if args.action=='build':
        checks += [dict(kind='file',path=str(args.config.resolve())),dict(kind='tool',tool='cmake'),dict(kind='tool',tool='ninja')]
    if args.action=='pc-image':checks += [dict(kind='tool',tool='docker',version_option='--version')]
    with tempfile.TemporaryDirectory() as tmp:
        manifest=Path(tmp)/'checks.json'
        manifest.write_text(json.dumps(dict(checks=checks)))
        subprocess.run([sys.executable,str(ROOT/'skills/hdc-master/scripts/preflight.py'),
                        '--manifest',str(manifest),'--timeout','15'],check=True)
    if args.action=='preflight':board_backend.preflight(args.target)
    elif args.action=='deploy':board_backend.deploy(args.target)
    elif args.action=='build':
        subprocess.run([sys.executable,str(ROOT/'stage3/board/build.py'),'--config',str(args.config),'--jobs',str(args.jobs)],check=True)
    else:
        image=json.loads(subprocess.check_output(['docker','image','inspect',args.px4_image],text=True))[0]
        reference=args.px4_image
        if reference.startswith('sha256:'):
            digests=image.get('RepoDigests') or []
            if digests:
                reference=digests[0]
            else:
                reference='uav-lesson-px4-source:'+image['Id'].split(':')[1][:16]
                subprocess.run(['docker','image','tag',image['Id'],reference],check=True)
        subprocess.run(['docker','build','--target','ros-airsim','--build-arg','PX4_IMAGE='+reference,
                        '-t','uav-airsim-ros-humble:local','-f',str(ROOT/'stage3/board/Dockerfile.airsim'),
                        str(ROOT/'stage3/board')],check=True)
        subprocess.run(['docker','build','--build-arg','PX4_IMAGE='+reference,
                        '-t',args.tag,'-f',str(ROOT/'stage3/board/Dockerfile.airsim'),str(ROOT/'stage3/board')],check=True)


if __name__=='__main__':main()
