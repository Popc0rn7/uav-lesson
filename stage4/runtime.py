#!/usr/bin/env python3
"""PC: own AirSim/PX4 lifecycle, a lightweight ROS workload, and task recovery."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from stage3.super.airsim import runtime as host
from stage3.super.airsim.rpc_client import rpc
from stage4.api_client import AeroVLAClient
from stage4.contracts import atomic_json, validate_task, yaw_xyzw

HERE=Path(__file__).resolve().parent
API_ENV=('AEROVLA_API_URL','AEROVLA_API_TIMEOUT_S','AEROVLA_API_KEY')


def read(path): return json.loads(path.read_text())


def fresh(path,age=2.):
    return read(path) if path.exists() and time.time()-path.stat().st_mtime<age else {}


def config(path):
    data=host.load_config(path.resolve())
    if data.get('super_task') or data.get('compute','docker')!='docker':
        raise ValueError('Stage 4 requires a standalone ROS Docker workload')
    for key in ('ros_container',):
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]+',data[key]) or data[key]==data['container']:
            raise ValueError('Invalid ROS container name')
    data['task_file']=str(host.resolve(data['task_file'],path.resolve().parent))
    return data


def settings(config,task):
    result=host.runtime_settings(config)
    vehicle=result['Vehicles']['PX4']
    acceleration=task['control']['acceleration_m_s2']
    vehicle.setdefault('Parameters',{}).update(MPC_ACC_HOR=acceleration,MPC_ACC_HOR_MAX=acceleration)
    vehicle.update(zip(('X','Y','Z'),task['spawn_ned_m']))
    vehicle['Yaw']=math.degrees(yaw_xyzw(task['start_quaternion_xyzw']))
    return result


def wait_ros(state):
    directory=Path(state['run_dir']); deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        info=host.owned_ros(state)
        if not info or not info['State']['Running']: raise RuntimeError('ROS exited; check node-logs')
        c=fresh(directory/'control.json'); s=fresh(directory/'sensors.json')
        if c.get('healthy') and c.get('cameras_ready') and s.get('pairs',0)>=2:
            return subprocess.CompletedProcess([],0,json.dumps(dict(control=c,sensors=s)), '')
        time.sleep(.5)
    raise RuntimeError(f'ROS/camera/clock startup timeout; inspect {directory}/node-logs and sensors.json')


def initialize_scene(task):
    obj=task['object']; q=obj['quaternion_xyzw']
    pose=dict(position=dict(zip(('x_val','y_val','z_val'),obj['position'])),
              orientation=dict(zip(('x_val','y_val','z_val','w_val'),q)))
    scale=dict.fromkeys(('x_val','y_val','z_val'),float(obj['scale']))
    if not rpc('simSpawnObject','stage4_target',obj['asset'],pose,scale,False,False,timeout=10):
        raise RuntimeError(f'Town05 target asset could not be spawned: {obj["asset"]}')
    # Deliberately do not call pause, setPose, reset, or AirSim movement APIs.


def prepare_px4(state):
    """Select autonomous standby while disarmed; Manual requires disabled sticks."""
    status=host.px4(state,'listener','vehicle_status').stdout
    def field(text,name,value):
        return bool(re.search(r'^\s+'+re.escape(name)+': '+re.escape(value)+r'\s*$',text,re.M))
    if not field(status,'arming_state','1') or not field(status,'nav_state','0'):
        return
    position=host.px4(state,'listener','vehicle_local_position').stdout
    if not field(position,'xy_valid','True') or not field(position,'z_valid','True'):
        return
    print('PX4 未解锁且定位有效：Manual → Hold，随后继续正常预检',flush=True)
    result=host.px4(state,'commander','mode','auto:loiter')
    (Path(state['run_dir'])/'px4-standby.log').write_text(
        'Disarmed + valid local position: request Hold before normal preflight checks\n'+result.stdout+result.stderr)
    if result.returncode:
        raise RuntimeError('PX4 rejected disarmed Hold request; inspect px4-standby.log')


def start(config,directory):
    task=validate_task(read(Path(config['task_file'])))
    def check(state):
        initialize_scene(task)
        result=wait_ros(state)
        run_dir=Path(state['run_dir'])
        sources={p.name:__import__('hashlib').sha256(p.read_bytes()).hexdigest()
                 for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py','.sh','.json','.html','.css')}
        atomic_json(run_dir/'stage4-source.json',dict(sources=sources,
            ros_image=read_image(config['ros_image']),model_service='externally managed',
            task_source=task.get('source')))
        return result
    from src.uav_scene_env import configuration
    values = configuration()
    previous = {key: os.environ.get(key) for key in API_ENV}
    try:
        for key in API_ENV:
            if key in values:
                os.environ[key] = values[key]
        host.up(config,directory,ros_entrypoint='/lesson/stage4/run_nodes.sh',ros_check=check,
                ros_runtime=dict(task=task,settings=settings(config,task),env=API_ENV,prepare_px4=prepare_px4))
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value



def read_image(name):
    return json.loads(host.command('docker','image','inspect',name).stdout)[0]['Id']


def inspect(state):
    info=host.owned_ros(state); px4=host.owned_container(state)
    directory=Path(state['run_dir'])
    c=fresh(directory/'control.json'); s=fresh(directory/'sensors.json')
    ready=bool(host.host_alive(state) and px4 and px4['State']['Running'] and info and info['State']['Running']
               and c.get('healthy') and c.get('cameras_ready'))
    return dict(ready=ready,phase=state['phase'],run_dir=str(directory),control=c,sensors=s,
                api_configured=bool(c.get('api_configured')),
                api_verified=(directory/'inference.jsonl').is_file(),report=read(directory/'report.json') if (directory/'report.json').exists() else None)


def reconcile_collision(report, collision, baseline_stamp):
    """Catch an impact arriving after the control node wrote its final report."""
    stamp=collision.get('time_stamp',0)
    if collision.get('has_collided') and stamp>baseline_stamp:
        report['collision']=collision
        landed_at=report.get('landing_started_sim_s')
        if landed_at is not None and stamp*1e-9<landed_at:
            report.update(flight_collision=True,task_success=False,chain_completed=False,mode='failed',
                          reason='collision before landing (PC final reconciliation)')
    return report


def task(state,mode):
    directory=Path(state['run_dir'])
    if not inspect(state)['ready']: raise RuntimeError('Stack not ready; inspect before task')
    if (directory/'start.json').exists() or (directory/'land.request.json').exists():
        raise RuntimeError('One task per run; land/down/up before another task')
    if mode=='api':
        if not fresh(directory/'control.json').get('api_configured'):
            raise RuntimeError('Set AEROVLA_API_URL before up; container has no inference configuration')
        # Check the endpoint actually inherited by the container, independent of
        # which PC terminal submits the task.
        host.command('docker','exec','--workdir','/lesson',state['ros_container'],'python3','-c',
                     'from stage4.api_client import AeroVLAClient; print(AeroVLAClient().health())',timeout=130)
    baseline=rpc('simGetCollisionInfo','PX4',timeout=2)
    baseline_stamp=baseline.get('time_stamp',0)
    atomic_json(directory/'collision-baseline.json',baseline)
    atomic_json(directory/'start.json',dict(mode=mode))
    deadline=time.monotonic()+read(directory/'task.json')['control']['mission_timeout_s']+75
    target=read(directory/'task.json')['target_ned_m']
    truth_min=None; truth_at_land=None
    try:
        while time.monotonic()<deadline:
            if (directory/'report.json').exists():
                report=read(directory/'report.json')
                report=reconcile_collision(report,rpc('simGetCollisionInfo','PX4',timeout=2),baseline_stamp)
                atomic_json(directory/'report.json',report)
                print(json.dumps(report,ensure_ascii=False,indent=2))
                atomic_json(directory/'evaluation.json',dict(minimum_world_truth_distance_m=truth_min,
                    world_truth_distance_at_land_request_m=truth_at_land,
                    method='AirSim global actor pose, sampled on PC only; no feedback to control'))
                return bool(report['chain_completed'])
            info=host.owned_ros(state)
            if not info or not info['State']['Running']:
                raise RuntimeError('ROS stack exited; PX4 Offboard-loss fallback must be checked')
            collision=rpc('simGetCollisionInfo','PX4',timeout=2)
            if collision.get('has_collided') and collision.get('time_stamp',0)>baseline_stamp:
                collision['observed_control_mode']=fresh(directory/'control.json').get('mode','unknown')
                atomic_json(directory/'collision.json',collision)
            try:
                truth=rpc('simGetObjectPose','PX4',timeout=2)
                point=truth['position']; world=[float(point[k]) for k in ('x_val','y_val','z_val')]
                if not all(math.isfinite(v) for v in world): raise RuntimeError('Missing simulator actor pose for evaluation')
                distance=math.dist(world,target); truth_min=distance if truth_min is None else min(truth_min,distance)
                control=fresh(directory/'control.json')
                if control.get('mode')=='land' and truth_at_land is None: truth_at_land=distance
                with (directory/'truth.jsonl').open('a') as output:
                    output.write(json.dumps(dict(world_ned=world,distance_m=distance,
                        sampled_monotonic_s=time.monotonic(),control_sim_s=control.get('sim_s'),
                        control_mode=control.get('mode'),note='RPC sample; control sim time is a nearby status sample'))+'\n')
            except Exception as exc:
                with (directory/'evaluation-errors.log').open('a') as output:
                    output.write(str(exc)+'\n')
            time.sleep(.5)
        raise TimeoutError('Task/landing deadline exceeded; use status/land/stop')
    except BaseException:
        host.request_land(state)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare-task','build','up','inspect','status','task','land','stop','down','api-probe','review','webui'))
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--speed',type=float); parser.add_argument('--acceleration',type=float)
    parser.add_argument('--stable',type=float,help='Required settling time in simulation seconds (up only)')
    parser.add_argument('--config',type=Path,default=HERE/'runtime.town05.json')
    parser.add_argument('--state-dir',type=Path,default=ROOT/'artifacts/stage4-runtime')
    parser.add_argument('--task-file',type=Path)
    parser.add_argument('--source',type=Path,default=ROOT.parent/'AeroVLA')
    parser.add_argument('--task-index',type=int,default=0)
    parser.add_argument('--ground-z',type=float,default=0.)
    parser.add_argument('--fixed-actions',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--no-display',action='store_true')
    parser.add_argument('--force',action='store_true')
    parser.add_argument('--front',type=Path); parser.add_argument('--down',type=Path)
    args=parser.parse_args()
    if args.action=='webui':
        from stage4.webui import serve
        serve(args.state_dir.resolve(),args.host,args.port); return
    if (args.speed is not None or args.acceleration is not None or args.stable is not None) and args.action!='up':
        parser.error('--speed/--acceleration/--stable only support up')
    if args.force and args.action!='down': parser.error('--force is only supported for down')
    if args.no_display and args.action!='up': parser.error('--no-display is only supported for up')
    if args.fixed_actions and args.action!='task': parser.error('--fixed-actions is only supported for task')
    if args.action=='prepare-task':
        from stage4.prepare_task import prepare
        output=args.task_file or ROOT/'artifacts/stage4/task.json'
        if output.exists(): raise FileExistsError(f'Refusing to overwrite {output}')
        output.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(output,prepare(args.source,args.task_index,args.ground_z)); print(output); return
    if args.action=='build':
        result=host.streaming_command('docker','build','--network','host','-t','uav-stage4-ros:local',HERE,timeout=1200)
        result.check_returncode(); return
    if args.action=='api-probe':
        if not args.front or not args.down: parser.error('api-probe requires --front and --down PNG files')
        c=config(args.config); t=validate_task(read(args.task_file or Path(c['task_file'])))
        client=AeroVLAClient(); client.health()
        result=client.infer('offline-probe',0.,t['start_ned_m'],t['start_quaternion_xyzw'],t['target_ned_m'],
                            t['instruction'],args.front.read_bytes(),args.down.read_bytes())
        print(json.dumps(result,ensure_ascii=False,indent=2)); return
    if args.dry_run:
        if args.action!='up': parser.error('--dry-run only supports up')
        c=config(args.config)
        if args.task_file: c['task_file']=str(args.task_file.resolve())
        t=validate_task(read(Path(c['task_file'])))
        if args.speed is not None: t['control']['speed_m_s']=args.speed
        if args.acceleration is not None: t['control']['acceleration_m_s2']=args.acceleration
        if args.stable is not None: t['control']['stable_s']=args.stable
        t=validate_task(t)
        print(json.dumps(dict(config=c,task=t,settings=settings(c,t),
                              topology='AirSim host + PX4 Docker + ROS Docker + external inference API'),ensure_ascii=False,indent=2)); return
    directory=args.state_dir.resolve(); directory.mkdir(parents=True,exist_ok=True)
    with host.management_lock(directory,args.action,args.force):
        if args.action=='up':
            c=config(args.config)
            if args.task_file: c['task_file']=str(args.task_file.resolve())
            if args.speed is not None or args.acceleration is not None or args.stable is not None:
                profile=read(Path(c['task_file']))
                profile.setdefault('control',{})
                if args.speed is not None: profile['control']['speed_m_s']=args.speed
                if args.acceleration is not None: profile['control']['acceleration_m_s2']=args.acceleration
                if args.stable is not None: profile['control']['stable_s']=args.stable
                profile=validate_task(profile)
                profile_path=directory/'task-profile.json'
                atomic_json(profile_path,profile); c['task_file']=str(profile_path)
            if args.no_display: c['no_display']=True
            # The common manager mounts its output at /run/airsim; the Stage 4
            # launcher creates /run/stage4 as an alias within this owned container.
            start(c,directory); return
        path=directory/'state.json'
        if not path.exists():
            if args.action in ('status','down','stop'): print('尚无 Stage 4 运行实例'); return
            raise RuntimeError('Run up first')
        state=read(path)
        if args.action in ('inspect','status'):
            result=inspect(state); print(json.dumps(result,ensure_ascii=False,indent=2))
            if args.action=='status': print(host.px4(state,'commander','status').stdout)
            elif not result['ready']: raise RuntimeError('Stage 4 is not ready')
        elif args.action=='land': host.request_land(state)
        elif args.action in ('stop','down'):
            if state['phase']!='stopped': host.shutdown(state,directory,args.force or args.action=='stop')
            print('资源已回收，日志保留；急停不代表正常降落' if args.force or args.action=='stop' else '已停止，日志保留')
        elif args.action=='task':
            if not task(state,'fixed' if args.fixed_actions else 'api'): raise RuntimeError('Task failed; see report')
        elif args.action=='review':
            from stage4.review import review
            print(json.dumps(review(Path(state['run_dir'])),ensure_ascii=False,indent=2))


if __name__=='__main__':
    try: main()
    except (Exception,KeyboardInterrupt) as exc:
        print(f'失败：{exc}',file=sys.stderr)
        if isinstance(exc,subprocess.CalledProcessError): print((exc.stderr or exc.stdout or '')[-3000:],file=sys.stderr)
        raise SystemExit(1)
