#!/usr/bin/env python3
"""PC：显式启用的 AirSim 诊断；不修改正常配置、模型或参数。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import threading
import uuid

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import runtime
from analyse import analyse


def capture(state_dir,seconds,hil,output=None,ready_event=None):
    state=json.loads((state_dir/'state.json').read_text())
    if state['phase']!='ready' or not runtime.host_alive(state):raise RuntimeError('当前管理实例未运行，不自动启动/接管')
    runtime.owned_container(state)
    ros=runtime.owned_ros(state)
    if not ros or not ros['State']['Running']:raise RuntimeError('ROS 容器未运行')
    owner=uuid.uuid4().hex
    directory=output or runtime.ROOT/'artifacts/airsim-diagnostics'/owner
    directory.mkdir(parents=True,exist_ok=False)
    directory.chmod(0o770)
    manifest=dict(owner=owner,mode='passive',seconds=seconds,normal_state=str(state_dir.resolve()),
                  observed_run=state['owner'],state_snapshot=state,hil_enabled=hil,
                  code_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')})
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2))
    sidecar=None;process=None
    try:
        if hil:
            result=runtime.command('docker','run','-d','--name','uav-hil-trace-'+owner[:12],
                '--network','host','--cap-drop','ALL','--cap-add','NET_RAW','--security-opt','no-new-privileges',
                '--group-add',str(os.getgid()),
                '--read-only','--tmpfs','/tmp:rw,nodev,nosuid,size=32m',
                '--label',f'{runtime.LABEL}={owner}',
                '--mount',f'type=bind,source={runtime.ROOT},target=/lesson,readonly',
                '--mount',f'type=bind,source={directory},target=/out',
                '--entrypoint','python3',state['config']['ros_image'],
                '/lesson/stage3/super/airsim/diagnostics/capture_socket.py','--seconds',str(seconds),'--output','/out/hil.pcap',timeout=30)
            sidecar=result.stdout.strip()
        with (directory/'ros.jsonl').open('w') as output_file,(directory/'ros.stderr.log').open('w') as error_file:
            process=subprocess.Popen(['docker','exec','-e','ROS_DOMAIN_ID=10','-e','ROS_LOCALHOST_ONLY=0',
                '-e','RMW_IMPLEMENTATION=rmw_fastrtps_cpp','-e','PYTHONDONTWRITEBYTECODE=1',
                '-e',f'ROS_LOG_DIR=/tmp/diagnostics-{owner}',state['ros_container'],'bash','-lc',
                'source /opt/ros/humble/setup.bash; source /opt/px4_ws/install/local_setup.bash; '
                'source /super_ws/install/local_setup.bash; '
                f'python3 -u /lesson/stage3/super/airsim/diagnostics/trace_ros.py --seconds {seconds} --token {owner}'],
                stdout=output_file,stderr=error_file)
            if ready_event:
                end=time.monotonic()+10
                while (directory/'ros.jsonl').stat().st_size==0:
                    if process.poll() is not None or time.monotonic()>end:raise RuntimeError('旁路观察者未就绪')
                    time.sleep(.05)
                ready_event.set()
            if process.wait(timeout=seconds+30):raise RuntimeError('ROS 观察进程失败，检查 '+str(directory/'ros.stderr.log'))
        if sidecar:
            result=runtime.command('docker','wait',sidecar,timeout=seconds+20)
            logs=runtime.command('docker','logs',sidecar,check=False)
            (directory/'hil.stderr.log').write_text(logs.stdout+logs.stderr)
            if result.stdout.strip()!='0':raise RuntimeError('HIL 抓包失败，检查 '+str(directory/'hil.stderr.log'))
        manifest['completed']=True
    finally:
        if process and process.poll() is None:
            if runtime.owned_ros(state):
                runtime.command('docker','exec',state['ros_container'],'python3','-c',
                    "import os,signal,sys;from pathlib import Path; "
                    "[(os.kill(int(p.name),signal.SIGTERM)) for p in Path('/proc').iterdir() "
                    "if p.name.isdigit() and (p/'cmdline').exists() "
                    "and b'/lesson/stage3/super/airsim/diagnostics/trace_ros.py' in (p/'cmdline').read_bytes().split(b'\\0') "
                    "and sys.argv[1].encode() in (p/'cmdline').read_bytes().split(b'\\0')]",owner,check=False)
            process.send_signal(signal.SIGINT)
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:process.terminate()
        if sidecar:
            info=runtime.inspect_container(sidecar)
            if info and (info['Config'].get('Labels') or {}).get(runtime.LABEL)==owner:
                logs=runtime.command('docker','logs',sidecar,check=False)
                (directory/'hil.stderr.log').write_text(logs.stdout+logs.stderr)
                runtime.command('docker','rm','-f',sidecar,check=False)
        (directory/'manifest.json').write_text(json.dumps(manifest,indent=2))
    analyse(directory)
    print('采集目录：',directory)
    return directory


def run_probe(state,action):
    return runtime.command('docker','exec','-e','ROS_DOMAIN_ID=10','-e','ROS_LOCALHOST_ONLY=0',
        '-e','RMW_IMPLEMENTATION=rmw_fastrtps_cpp','-e','PYTHONDONTWRITEBYTECODE=1',
        '-e','ROS_LOG_DIR=/run/airsim/ros-logs',state['ros_container'],'bash','-lc',
        'source /opt/ros/humble/setup.bash; source /opt/px4_ws/install/local_setup.bash; '
        'source /super_ws/install/local_setup.bash; '
        f'python3 -u /lesson/stage3/super/airsim/diagnostics/probe.py {action}',check=False,timeout=330 if action=='run' else 35)


def prepare_response(source,profile,load_profile,directory):
    from response_profile import load
    from task_config import load_task
    c=runtime.load_config(source.resolve())
    task=copy.deepcopy(load_task(c['super_task']))
    settings=json.loads(Path(c['settings']).read_text())
    original={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (source.resolve(),Path(c['settings']),Path(c['super_task']))}
    response=load(profile)
    if load_profile=='render-low':settings['ViewMode']='NoDisplay'
    elif load_profile=='lidar-low':task['lidar']['settings']['PointsPerSecond']=50000
    task.update(name='隔离固定轨迹响应 / '+load_profile,_diagnostics_response=response)
    # 固定出生点/任务边界继承明确选定的配置；默认使用已验证短程出生点。
    directory.mkdir(parents=True,exist_ok=False)
    (directory/'task.input.json').write_text(json.dumps(task,indent=2))
    (directory/'settings.input.json').write_text(json.dumps(settings,indent=2))
    token=directory.name
    c.update(super_task=str(directory/'task.input.json'),settings=str(directory/'settings.input.json'),
             container='uav-diag-px4-'+token[:12],ros_container='uav-diag-ros-'+token[:12],
             diagnostics=dict(load_profile=load_profile,profile=response))
    (directory/'runtime.input.json').write_text(json.dumps(c,indent=2))
    (directory/'manifest.json').write_text(json.dumps(dict(mode='isolated-response',original_sha256=original,
                                                           changes=dict(load_profile=load_profile),config=c),indent=2))
    return c


def response_up(source,profile,load_profile):
    # 先核实固定网络资源；不停止任何已有实例，也不写其状态。
    runtime.check_ports();runtime.check_port(__import__('socket').SOCK_DGRAM,8888)
    directory=runtime.ROOT/'artifacts/airsim-diagnostics'/uuid.uuid4().hex
    c=prepare_response(source,profile,load_profile,directory)
    state_dir=directory/'runtime';state_dir.mkdir()
    print('诊断状态目录：'+str(state_dir),flush=True)
    with runtime.management_lock(state_dir,'up'):
        runtime.up(c,state_dir,ros_entrypoint='/lesson/stage3/super/airsim/diagnostics/run_response.sh',
                   ros_check=lambda state:run_probe(state,'inspect'))
    return state_dir


def response_run(state_dir,hil):
    with runtime.management_lock(state_dir,'task'):
        state=json.loads((state_dir/'state.json').read_text())
        if not state['config'].get('diagnostics'):raise RuntimeError('拒绝在正常实例上接管控制；先 response-up')
        if not runtime.ready(state):raise RuntimeError('诊断实例未就绪')
        if (Path(state['run_dir'])/'land.request.json').exists():raise RuntimeError('本轮已人工中止，重新 response-up')
        ready=threading.Event();capture_dir=state_dir.parent/('capture-'+uuid.uuid4().hex)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(capture,state_dir,120,hil,capture_dir,ready)
            try:
                end=time.monotonic()+15
                while not ready.wait(.1):
                    if future.done():future.result()
                    if time.monotonic()>end:raise RuntimeError('旁路采集未就绪，不起飞')
                result=run_probe(state,'run')
                (state_dir.parent/'response.console.log').write_text(result.stdout+result.stderr)
                print(result.stdout,flush=True)
                for line in result.stdout.splitlines():
                    if line.startswith('报告：/run/airsim/'):
                        name=line.removeprefix('报告：/run/airsim/')
                        if Path(name).name==name:
                            from review_flight import review
                            review(Path(state['run_dir'])/name)
                result.check_returncode()
            except BaseException:
                runtime.request_land(state)
                raise
            finally:
                if sys.exc_info()[0] is None:
                    future.result()
                else:
                    try:future.result()
                    except Exception as exc:print("旁路采集另有失败："+str(exc),file=sys.stderr)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    cap=sub.add_parser('capture',help='只读观察当前实例，不起飞、不改参数')
    cap.add_argument('--state-dir',type=Path,default=runtime.ROOT/'artifacts/airsim-runtime')
    cap.add_argument('--seconds',type=int,default=15)
    cap.add_argument('--hil',action='store_true',help='临时 NET_RAW 容器，仅抓取 loopback TCP4560')
    cap.add_argument('--output',type=Path)
    analysis=sub.add_parser('analyse');analysis.add_argument('directory',type=Path);analysis.add_argument('--ulog',type=Path)
    up=sub.add_parser('response-up',help='创建独立诊断实例；不启动已有正常实例，不解锁')
    up.add_argument('--runtime-config',type=Path,default=HERE.parent/'runtime.super.json')
    up.add_argument('--profile',type=Path,default=HERE/'response_profile.json')
    up.add_argument('--load',choices=['baseline','render-low','lidar-low'],default='baseline')
    run=sub.add_parser('response-run',help='显式起飞执行固定轨迹；只能用于诊断实例')
    run.add_argument('--state-dir',type=Path,required=True);run.add_argument('--run',action='store_true');run.add_argument('--hil',action='store_true')
    args=parser.parse_args()
    if args.action=='capture':
        if not 1<=args.seconds<=120:parser.error('seconds 必须为 1～120')
        capture(args.state_dir.resolve(),args.seconds,args.hil,args.output.resolve() if args.output else None)
    elif args.action=='analyse':analyse(args.directory,args.ulog)
    elif args.action=='response-up':response_up(args.runtime_config,args.profile,args.load)
    else:
        if not args.run:parser.error('response-run 需要 --run 显式起飞')
        response_run(args.state_dir.resolve(),args.hil)


if __name__=='__main__':main()
