#!/usr/bin/env python3
"""RoboPi：本次 stage3 进程身份与生命周期；不启动推理、Agent 或仿真。"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

RELEASE = Path(__file__).resolve().parent


def identity(pid):
    try:
        p = Path('/proc') / str(pid)
        stat = (p/'stat').read_text().rsplit(')', 1)[1].split()
        if stat[0] == 'Z':
            return None
        return dict(pid=pid, ticks=stat[19], exe=str((p/'exe').resolve()),
                    argv=(p/'cmdline').read_bytes().hex(), cwd=str((p/'cwd').resolve()))
    except (OSError, ProcessLookupError):
        return None


def alive(record):
    return bool(record and identity(record['pid']) == record)


def atomic(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2))
    temporary.replace(path)


def sample_resources(data):
    memory={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,value=line.split(':',1)
        if key in ('MemTotal','MemAvailable','MemFree','CmaTotal','CmaFree'):
            memory[key]=int(value.split()[0])
    processes={}
    for name,record in data.items():
        if not alive(record):continue
        fields=(Path('/proc')/str(record['pid'])/'stat').read_text().rsplit(')',1)[1].split()
        processes[name]=dict(cpu_ticks=int(fields[11])+int(fields[12]),
                             rss_bytes=int(fields[21])*os.sysconf('SC_PAGE_SIZE'))
    network={}
    for line in Path('/proc/net/dev').read_text().splitlines()[2:]:
        name,values=line.split(':',1);values=values.split()
        network[name.strip()]=dict(rx_bytes=int(values[0]),tx_bytes=int(values[8]))
    return dict(monotonic_s=time.monotonic(),clock_ticks_s=os.sysconf('SC_CLK_TCK'),
                cpu_ticks=[int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:]],
                memory_kib=memory,processes=processes,network=network)


def metadata(directory):
    data = json.loads((directory/'run.json').read_text())
    if data['owner'] != directory.name or Path(data['release']).resolve() != RELEASE:
        raise RuntimeError('run 所有者或 release 不匹配，拒绝操作')
    return data


def records(directory):
    metadata(directory)
    path = directory/'processes.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    allowed = {'supervisor','control','lidar','planner','mission'}
    for name, record in data.items():
        if name not in allowed or record.get('cwd') != str(directory):
            raise RuntimeError('项目进程记录不属于本次目录')
        argv = bytes.fromhex(record['argv']).split(b'\0')
        expected = {'supervisor': RELEASE/'manage.py', 'control': RELEASE/'app/super_px4.py',
                    'lidar': RELEASE/'app/airsim/lidar_bridge.py',
                    'planner': RELEASE/'install/lib/super_planner/fsm_node',
                    'mission': RELEASE/'app/airsim/waypoint_task.py'}[name]
        if os.fsencode(expected) not in argv:
            raise RuntimeError('项目节点命令行不匹配：'+name)
    return data


def signal_node(directory, name, value):
    data = records(directory)
    record = data.get(name)
    if not alive(record):
        raise RuntimeError('项目节点未运行或身份变化：'+name)
    os.kill(record['pid'], value)


def run(directory):
    options = metadata(directory)
    if options.get('profile'):
        profile = directory/'profile'
        profile.mkdir(exist_ok=True)
        os.environ['UAV_PROFILE_DIR'] = str(profile)
        os.environ['SUPER_PROFILE_PATH'] = str(profile/'planner.jsonl')
    with (directory/'supervisor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        data = {'supervisor': identity(os.getpid())}
        atomic(directory/'processes.json', data)
        children = []
        stopped = False
        def stop(*_):
            nonlocal stopped
            stopped = True
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            app = RELEASE/'app'
            task = str(directory/'task.json')
            args = ['--ros-args', '-p', 'use_sim_time:=true']
            nodes = {
                'control': [sys.executable, '-B', str(app/'super_px4.py'), *args,
                            '-p', 'lidar_height_required:=false', '-p', 'airsim_task_config:='+task],
                'lidar': [sys.executable, '-B', str(app/'airsim/lidar_bridge.py'), *args,
                          '-p', 'input_mode:=ros', '-p', 'task_config:='+task],
                'planner': [str(RELEASE/'install/lib/super_planner/fsm_node'), *args,
                            '-p', 'config_name:='+str(directory/'planner.yaml')],
                'mission': [sys.executable, '-B', str(app/'airsim/waypoint_task.py'), *args,
                            '-p', 'task_config:='+task],
            }
            for name, argv in nodes.items():
                with (directory/(name+'.log')).open('ab') as output:
                    child = subprocess.Popen(argv, cwd=directory, stdout=output, stderr=subprocess.STDOUT)
                children.append(child)
                # exec may still be replacing the forked process. Require expected argv.
                expected = b'\0'.join(os.fsencode(s) for s in argv) + b'\0'
                deadline = time.monotonic()+3
                while True:
                    record = identity(child.pid)
                    if record and bytes.fromhex(record['argv']) == expected:
                        break
                    if child.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('节点启动失败：'+name)
                    time.sleep(.02)
                data[name] = record
                atomic(directory/'processes.json', data)
            next_sample=0
            while not stopped:
                if any(p.poll() is not None for p in children):
                    raise RuntimeError('项目节点退出，停止其余算力节点；由 PX4 处理 Offboard 失联')
                if time.monotonic()>=next_sample:
                    try:
                        with (directory/'resources.jsonl').open('a') as stream:
                            stream.write(json.dumps(sample_resources(data))+'\n')
                    except OSError as exc:
                        print('资源采样失败：'+str(exc),flush=True)
                    next_sample=time.monotonic()+2
                time.sleep(.1)
        finally:
            for name, record in data.items():
                if name != 'supervisor' and alive(record):
                    os.kill(record['pid'], signal.SIGCONT)
                    os.kill(record['pid'], signal.SIGTERM)
            deadline = time.monotonic()+5
            for child in children:
                try:
                    child.wait(timeout=max(.01, deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    record = next((r for r in data.values() if r['pid']==child.pid), None)
                    if alive(record):
                        os.kill(child.pid, signal.SIGKILL)
                    child.wait(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run','status','stop','land','pause','resume','terminate'])
    parser.add_argument('directory', type=Path)
    parser.add_argument('--node', choices=['lidar','planner','control'])
    args = parser.parse_args()
    directory = args.directory.resolve()
    metadata(directory)
    if args.action == 'run':
        run(directory)
    elif args.action == 'status':
        data = records(directory)
        print(json.dumps(dict(running={k:alive(v) for k,v in data.items()},
                              cancelled=(directory/'land.request.json').exists())))
    elif args.action == 'land':
        atomic(directory/'land.request.json', {'owner': directory.name})
    elif args.action == 'stop':
        data = records(directory)
        # Stop the supervisor first; it cleans its verified children even after SIGSTOP.
        if alive(data.get('supervisor')):
            os.kill(data['supervisor']['pid'], signal.SIGTERM)
        deadline = time.monotonic()+10
        while any(alive(v) for v in data.values()) and time.monotonic()<deadline:
            time.sleep(.1)
        if any(alive(v) for v in data.values()):
            raise RuntimeError('仍有已识别项目进程，清理未完成')
    else:
        if not args.node:
            parser.error('需要 --node')
        signal_node(directory, args.node,
                    {'pause':signal.SIGSTOP, 'resume':signal.SIGCONT, 'terminate':signal.SIGTERM}[args.action])


if __name__ == '__main__':
    main()
