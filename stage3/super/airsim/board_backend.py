"""PC：RoboPi 内容寻址部署及本次运行管理；HDC 仅用于管理通道。"""
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
import sys

ROOT=Path(__file__).resolve().parents[3]
BASE='/data/local/workspace/stage3'
WORK=ROOT/'artifacts/robopi-stage3'
sys.path.insert(0,str(ROOT/'src'))
from uav_hdc import shell
from uav_dds import write_profile, probe_interface



def send(target, source, destination):
    subprocess.run(['hdc','-t',target,'file','send',str(source),destination],check=True,timeout=600)


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def bundle(destination):
    evidence=json.loads((WORK/'build-evidence.json').read_text())
    for name, expected in evidence['files'].items():
        path=WORK/'install'/name
        if not path.is_file() or checksum(path)!=expected:
            raise RuntimeError('构建产物与证据不符：'+name)
    shutil.copytree(ROOT/'robopi/stage3',destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc','AGENTS.md'))
    # Dereference repo symlinks to the one maintained source; no links leave the release.
    shutil.copytree(WORK/'install',destination/'install')
    shutil.copy2(WORK/'build-evidence.json',destination/'build-evidence.json')
    shutil.copy2(WORK/'build-input.json',destination/'build-input.json')
    files={str(p.relative_to(destination)):dict(sha256=checksum(p),mode=p.stat().st_mode&0o777)
           for p in sorted(destination.rglob('*')) if p.is_file()}
    release=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    (destination/'release.json').write_text(json.dumps(dict(release=release,files=files),indent=2))
    return release


def deploy(target):
    with tempfile.TemporaryDirectory() as temporary:
        source=Path(temporary)/'release'
        release=bundle(source)
        remote=BASE+'/releases/'+release
        quote=shlex.quote
        existing=shell(target,'if [ -e '+quote(remote)+' ]; then echo EXISTS; fi')
        if existing=='EXISTS':
            verify(target,remote,release)
            print('相同 release 已存在，校验通过：'+release)
        else:
            archive=Path(temporary)/'release.tar'
            with tarfile.open(archive,'w',format=tarfile.GNU_FORMAT) as stream:
                # OHOS tar rejects a root './' directory record under -C.
                for entry in sorted(source.iterdir()):
                    stream.add(entry,arcname=entry.name)
            upload=BASE+'/incoming-'+uuid.uuid4().hex+'.tar'
            staging=BASE+'/staging-'+uuid.uuid4().hex
            shell(target,'mkdir -p '+quote(BASE+'/releases'))
            space_code='import os; s=os.statvfs('+repr(BASE)+'); print(s.f_bavail*s.f_frsize)'
            available=int(shell(target,'python3 -B -c '+quote(space_code)))
            required=archive.stat().st_size+sum(p.stat().st_size for p in source.rglob('*') if p.is_file())
            if available < required:
                raise RuntimeError(f'板端空间不足：需要至少 {required} bytes，可用 {available} bytes')
            send(target,archive,upload)
            shell(target,'test "$(sha256sum '+quote(upload)+' | cut -d " " -f 1)" = '+quote(checksum(archive)))
            shell(target,'mkdir '+quote(staging)+' && tar -xf '+quote(upload)+' -C '+quote(staging),timeout=120)
            verify(target,staging,release)
            shell(target,'test ! -e '+quote(remote)+' && mv '+quote(staging)+' '+quote(remote)+' && rm '+quote(upload))
        WORK.mkdir(parents=True,exist_ok=True)
        record=WORK/'deployed.json'
        temporary=record.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(target=target,release=release,remote=remote),indent=2))
        temporary.replace(record)
        print('release 校验/部署通过：'+release,flush=True)
        return dict(target=target,release=release,remote=remote)


def verify(target, remote, expected=None):
    script="""import hashlib,json,pathlib,sys
r=pathlib.Path(sys.argv[1]); m=json.loads((r/'release.json').read_text())
if hashlib.sha256(json.dumps(m['files'],sort_keys=True).encode()).hexdigest()!=m['release']: raise RuntimeError('release metadata digest mismatch')
actual_files={str(p.relative_to(r)) for p in r.rglob('*') if p.is_file()}-{'release.json'}
if actual_files!=set(m['files']): raise RuntimeError('release file inventory mismatch')
for n,v in m['files'].items():
 p=r/n
 if p.is_symlink() or not p.resolve().is_relative_to(r.resolve()): raise RuntimeError('release path escapes root: '+n)
 with p.open('rb') as f: actual=hashlib.file_digest(f,'sha256').hexdigest()
 if actual!=v['sha256'] or p.stat().st_mode&0o777!=v['mode']: raise RuntimeError('release mismatch: '+n)
print(m['release'])
"""
    result=shell(target,'python3 -B -c '+shlex.quote(script)+' '+shlex.quote(remote),timeout=180)
    if expected is not None and result!=expected:
        raise RuntimeError('远端 release 与预期版本不符')
    return result


def preflight(target, release=None, *, required_features=()):
    import sys
    with tempfile.TemporaryDirectory() as temporary:
        manifest=Path(temporary)/'checks.json'
        manifest.write_text(json.dumps(dict(checks=[dict(kind='tool',tool='hdc',version_option='-v'),
            dict(kind='hdc-identity',target=target)])))
        subprocess.run([sys.executable,str(ROOT/'skills/hdc-master/scripts/preflight.py'),
                        '--manifest',str(manifest),'--timeout','15'],check=True)
    script='set -e; uname -a; id; df -k /data/local/tmp; command -v python3; command -v tar; command -v nohup'
    print(shell(target,script))
    # Base environment is probed without uploading or modifying any board file.
    bootstrap=(ROOT/'robopi/stage3/ros_env.sh').read_text()
    probe="import sys,sysconfig,numpy,rclpy; from std_msgs.msg import String; from sensor_msgs.msg import PointCloud2; import json; print(json.dumps(dict(version=sys.version,SOABI=sysconfig.get_config_var('SOABI'),numpy=numpy.__version__)))"
    print(shell(target,bootstrap+'\npython3 -B -c '+shlex.quote(probe)))
    if release:
        verify(target,release,Path(release).name)
        probe="import json,sysconfig,pathlib; evidence=json.loads(pathlib.Path("+repr(release+'/build-evidence.json')+").read_text()); assert sysconfig.get_config_var('SOABI')==evidence['soabi'], 'target SOABI mismatch'; import numpy; from scipy.spatial.transform import Rotation,Slerp; from px4_msgs.msg import VehicleStatus,VehicleOdometry,FailsafeFlags; from mars_quadrotor_msgs.msg import PositionCommand; from rclpy.serialization import serialize_message,deserialize_message; m=PositionCommand(); assert deserialize_message(serialize_message(m),PositionCommand)==m; print('target imports/serialization OK')"
        environment=environment_script(release)
        print(shell(target,environment+'\npython3 -B -c '+shlex.quote(probe)))
        feature_probe=('import json,pathlib; e=json.loads(pathlib.Path('+repr(release+'/build-evidence.json')+
                       ').read_text()); required='+repr(tuple(required_features))+
                       '; assert set(required)<=set(e.get("features",[])), "release 不支持请求的功能；先重新 build/deploy"')
        if required_features:
            shell(target,'python3 -B -c '+shlex.quote(feature_probe))
        # Ask the target loader to resolve the planner closure without starting a ROS node.
        executable=shlex.quote(release+'/install/lib/super_planner/fsm_node')
        linked = shell(target,environment+'\nif command -v ldd >/dev/null 2>&1; then ldd '+executable+
                       '; else /lib/ld-musl-aarch64.so.1 --list '+executable+'; fi')
        WORK.mkdir(parents=True,exist_ok=True)
        (WORK/('loader-'+Path(release).name+'.txt')).write_text(linked+'\n')
        if any(word in linked for word in ('not found', 'Error loading', 'Error relocating')):
            raise RuntimeError('目标规划器动态依赖未解析，停止启动')
        print('目标动态依赖解析通过，完整 loader 输出保存在 artifacts/robopi-stage3')


def environment_script(release):
    q=shlex.quote
    return ('. '+q(release+'/ros_env.sh')+'\n'
            'export AMENT_PREFIX_PATH='+q(release+'/install')+':$AMENT_PREFIX_PATH\n'
            'export LD_LIBRARY_PATH='+q(release+'/install/lib')+':$LD_LIBRARY_PATH\n'
            'export PYTHONPATH='+q(release+'/install/lib/python3.12/site-packages')+':'+q(release+'/app')+':$PYTHONPATH')


def selected(target):
    result=json.loads((WORK/'deployed.json').read_text())
    if (not re.fullmatch(r'[a-f0-9]{64}', result.get('release','')) or
            result.get('remote') != BASE+'/releases/'+result.get('release','')):
        raise RuntimeError('部署记录中的 release 路径无效')
    if result['target']!=target:
        raise RuntimeError('部署记录与本次 target 不一致，先对显式目标 deploy')
    return result


def network_preflight(target,pc_address,board_address):
    import inspect
    pc=probe_interface(pc_address)
    code=inspect.getsource(probe_interface)+'\nimport json; print(json.dumps(probe_interface('+repr(board_address)+')))'
    board=json.loads(shell(target,'unset LD_PRELOAD; python3 -B -c '+shlex.quote(code)))
    print('本次网络地址/链路检查：'+json.dumps(dict(pc=pc,board=board)))
    return dict(pc=pc,board=board)


def initialize(state):
    target=state['config']['target']
    deployment=selected(target)
    required=[]
    if state['config'].get('board_profile',False):required.append('native-wall-cpu-profile-v1')
    if state['config'].get('planner_timing','baseline')!='baseline':required.append('clock-aware-replan-v1')
    preflight(target,deployment['remote'],required_features=required)
    remote=BASE+'/runs/'+state['owner']
    state['board']=dict(**deployment,run=remote)
    shell(target,'mkdir -p '+shlex.quote(BASE+'/runs')+' && mkdir '+shlex.quote(remote))
    from planner_config import generate
    directory=Path(state['run_dir'])
    generate(directory/'task.json',directory/'planner.yaml',
             timing_profile=state['config'].get('planner_timing','baseline'))
    write_profile(state['config']['pc_address'],state['config']['board_address'],directory/'dds-pc.xml',loopback=True)
    write_profile(state['config']['board_address'],state['config']['pc_address'],directory/'dds-board.xml')
    metadata=directory/'board-run.json'
    metadata.write_text(json.dumps(dict(owner=state['owner'],release=deployment['remote'],
                                        profile=state['config'].get('board_profile',False))))
    if state['config'].get('board_profile',False):
        (directory/'profile').mkdir(exist_ok=True)
        (directory/'profile.enabled').write_text('optional diagnostic enabled\n')
    for source,dest in [(directory/'task.json','task.json'),(directory/'planner.yaml','planner.yaml'),(metadata,'run.json'),(directory/'dds-board.xml','dds.xml')]:
        send(target,source,remote+'/'+dest)
        shell(target,'test "$(sha256sum '+shlex.quote(remote+'/'+dest)+' | cut -d " " -f 1)" = '+shlex.quote(checksum(source)))


def start(state):
    board=state['board'];q=shlex.quote
    shell(board['target'],'nohup sh '+q(board['remote']+'/launch.sh')+' '+q(board['run'])+' >'+q(board['run']+'/supervisor.log')+' 2>&1 </dev/null &')
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        result=status(state)
        if result['running'].get('supervisor') and all(result['running'].get(k) for k in ('control','lidar','planner','mission')):
            return
        time.sleep(.2)
    raise RuntimeError('板端节点未启动；检查 '+board['run']+'/supervisor.log')


def action(state, operation, node=None):
    board=state['board'];q=shlex.quote
    script='python3 -B '+q(board['remote']+'/manage.py')+' '+q(operation)+' '+q(board['run'])
    if node:script+=' --node '+q(node)
    return shell(board['target'],script)


def status(state):
    return json.loads(action(state,'status'))


def stop(state):
    action(state,'stop')
    # Only owned run logs; HDC failure propagates and the runtime keeps stopping state.
    board=state['board']
    output=Path(state['run_dir'])/'board-logs'
    output.mkdir(exist_ok=True)
    for name in ('supervisor.log','control.log','lidar.log','planner.log','mission.log','processes.json','resources.jsonl'):
        exists=shell(board['target'],'if [ -f '+shlex.quote(board['run']+'/'+name)+' ]; then echo EXISTS; fi')
        if exists!='EXISTS':
            (output/(name+'.missing')).write_text('本次运行未创建该文件；可能在节点启动前失败\n')
            continue
        subprocess.run(['hdc','-t',board['target'],'file','recv',board['run']+'/'+name,str(output/name)],check=True,timeout=30)
    if state['config'].get('board_profile',False):
        (output/'profile').mkdir(exist_ok=True)
        for name in ('planner','lidar','control'):
            source=board['run']+'/profile/'+name+'.jsonl'
            exists=shell(board['target'],'if [ -f '+shlex.quote(source)+' ]; then echo EXISTS; fi')
            if exists=='EXISTS':
                subprocess.run(['hdc','-t',board['target'],'file','recv',source,
                                str(output/'profile'/(name+'.jsonl'))],check=True,timeout=60)
