#!/usr/bin/env python3
"""PC：从本次 RoboPi 导出目标依赖并重定位到本地，不修改板端基础环境。"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys
import tarfile
import uuid

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'artifacts/robopi-stage3'
sys.path.insert(0,str(ROOT/'stage3/super/airsim'))
import board_backend
sys.path.insert(0,str(ROOT/'src'))
from uav_env import configured_path


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def extract(archive, output):
    # Preserve the original archive; rewrite only known absolute target symlinks.
    def safe(member, destination):
        if member.issym() and member.linkname.startswith('/'):
            if not member.linkname.startswith('/sys_prod/robot/'):
                raise ValueError('未知绝对符号链接：'+member.linkname)
            target=member.linkname.removeprefix('/sys_prod/robot/')
            member.linkname=os.path.relpath(target, str(PurePosixPath(member.name).parent))
        return tarfile.data_filter(member,destination)
    with tarfile.open(archive) as stream:stream.extractall(output,filter=safe)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',required=True)
    parser.add_argument('--sdk',type=Path,help='默认读取根 .env 的 OHOS_SDK')
    parser.add_argument('--host-python',type=Path,help='默认读取根 .env 的 OHOS_HOST_PYTHON')
    parser.add_argument('--resume-remote', help='恢复本次中断导出，指定已核实属于本项目的远端归档')
    parser.add_argument('--reuse-archive',action='store_true',help='复用本次已校验归档；仍重新核验设备 ABI')
    args=parser.parse_args()
    sdk=(args.sdk or configured_path('OHOS_SDK')).resolve()
    host=(args.host_python or configured_path('OHOS_HOST_PYTHON')).expanduser().absolute()
    for path in (sdk/'build/cmake/ohos.toolchain.cmake',host):
        if not path.is_file():raise FileNotFoundError(path)
    board_backend.preflight(args.target)
    WORK.mkdir(exist_ok=True)
    q=shlex.quote
    bootstrap=(ROOT/'robopi/stage3/ros_env.sh').read_text()
    code="import sysconfig,json,numpy; print(json.dumps(dict(SOABI=sysconfig.get_config_var('SOABI'),EXT_SUFFIX=sysconfig.get_config_var('EXT_SUFFIX'),numpy=numpy.__version__)))"
    abi=json.loads(board_backend.shell(args.target,bootstrap+'\npython3 -B -c '+q(code)))
    target=WORK/'target';target.mkdir(exist_ok=True)
    archive=target/'dependencies.tar'
    stamp=target/'export.json'
    if not args.reuse_archive:
        if archive.exists():raise RuntimeError('已有目标归档，使用 --reuse-archive 或先备份 target 目录')
        remote=args.resume_remote or '/data/local/tmp/uav-stage3-deps-'+uuid.uuid4().hex+'.tar'
        if not remote.startswith('/data/local/tmp/uav-stage3-deps-') or not remote.endswith('.tar'):
            raise ValueError('恢复归档路径不属于本项目临时目录')
        (target/'pending-export.json').write_text(json.dumps(dict(target=args.target,remote=remote),indent=2))
        paths=['install/include','install/lib','install/share','install/bin','out/include','out/share','out/bin','out/lib/cmake',
               'out/lib/python3.12/site-packages/numpy/_core/include']
        # Expand only shared target libraries, not model caches or Python site-packages.
        script='tar -cf '+q(remote)+' -C /sys_prod/robot '+' '.join(map(q,paths))+' '
        libraries=board_backend.shell(args.target,"python3 -B -c "+q("from pathlib import Path; print(' '.join(str(p.relative_to('/sys_prod/robot')) for p in sorted(Path('/sys_prod/robot/out/lib').glob('lib*')) if '.so' in p.name or p.suffix=='.a'))"))
        script+=' '.join(q(p) for p in libraries.split())
        print('导出本次目标 ROS、PCL/运行库、开发头文件…',flush=True)
        print('远端归档：'+remote,flush=True)
        if not args.resume_remote:
            board_backend.shell(args.target,script,timeout=600)
        else:
            board_backend.shell(args.target,'tar -tf '+q(remote)+' >/dev/null',timeout=120)
        checksum=board_backend.shell(args.target,'sha256sum '+q(remote),timeout=600).split()[0]
        subprocess.run(['hdc','-t',args.target,'file','recv',remote,str(archive)],check=True,timeout=600)
        if digest(archive)!=checksum:raise RuntimeError('归档校验失败，保留远端归档：'+remote)
        stamp.write_text(json.dumps(dict(target=args.target,SOABI=abi['SOABI'],sha256=checksum,remote=remote),indent=2))
        board_backend.shell(args.target,'rm '+q(remote))
    recorded=json.loads(stamp.read_text())
    if recorded['target']!=args.target or recorded['SOABI']!=abi['SOABI'] or digest(archive)!=recorded['sha256']:
        raise RuntimeError('归档与当前设备/ABI/校验记录不一致')
    raw=target/'raw';deps=target/'deps'
    if not raw.exists():
        raw.mkdir();extract(archive,raw)
    if not deps.exists():shutil.copytree(raw,deps,symlinks=True)
    mappings=[('/mnt/ohos/ohos-robot-toolchain/18/native/sysroot/usr',str(deps/'out')),
              ('/mnt/ohos/install',str(deps/'install')),('/sys_prod/robot/install',str(deps/'install')),
              ('/sys_prod/robot/out',str(deps/'out')),
              ('/root/conda/envs/ros_env/lib/python3.12/site-packages/numpy/_core/include',
               str(deps/'out/lib/python3.12/site-packages/numpy/_core/include'))]
    changed=[]
    for path in deps.rglob('*'):
        if path.is_symlink():
            old=os.readlink(path);new=old
            for original,replacement in mappings:new=new.replace(original,replacement)
            if new!=old:path.unlink();path.symlink_to(new)
        elif path.is_file() and path.suffix in ('.cmake','.pc','.sh','.dsv'):
            try:
                old=path.read_text()
            except UnicodeDecodeError:
                continue  # A few vendor files use a text suffix for binary data; preserve them.
            new=old
            for original,replacement in mappings:new=new.replace(original,replacement)
            if new!=old:path.write_text(new);changed.append(str(path.relative_to(deps)))
    (target/'relocations.json').write_text(json.dumps(changed,indent=2))
    metadata=target/'python-target.json';metadata.write_text(json.dumps(abi,indent=2))
    # Export the PC baseline's exact PX4 message source, including git identity.
    source=WORK/'sources/px4_msgs'
    if not source.exists():
        source.parent.mkdir(exist_ok=True)
        container=subprocess.check_output(['docker','create','--network','none','uav-computer-ros-humble:local'],text=True).strip()
        try:subprocess.run(['docker','cp',container+':/opt/px4_ws/src/px4_msgs',str(source)],check=True)
        finally:subprocess.run(['docker','rm',container],check=True)
    config=dict(sdk=str(sdk),deps=str(deps),python_deps=str(deps),host_python=str(host),
                target_metadata=str(metadata),px4_source=str(source),target_verified=True)
    (WORK/'board-config.local.json').write_text(json.dumps(config,indent=2))
    print('目标快照准备完成：'+str(WORK/'board-config.local.json'))


if __name__=='__main__':main()
