#!/usr/bin/env python3
"""PC：分析同一次 run 的可选计算/传输 profile；不跨主机相减绝对时钟。"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics


def stats(values):
    values = sorted(values)
    if not values:
        return None
    return dict(samples=len(values), median=statistics.median(values),
                p95=values[round((len(values)-1)*.95)], maximum=values[-1])


def read(path):
    if not path.exists():
        raise FileNotFoundError(path)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def analyse(run):
    board = run/'board-logs/profile'
    scopes = defaultdict(list)
    for row in read(board/'planner.jsonl'):
        scopes[row['scope']].append(row)
    reports=[p for p in run.glob('fly-task-*.json') if not p.name.endswith('.review.json')]
    if len(reports)!=1:
        raise ValueError('profile run 必须有唯一的实际飞行报告')
    result = dict(flight_result=json.loads(reports[0].read_text())['summary'], computation={})
    for name, rows in scopes.items():
        result['computation'][name] = dict(
            wall_s=stats([r['wall_ns']/1e9 for r in rows]),
            thread_cpu_s=stats([r['thread_cpu_ns']/1e9 for r in rows if r['thread_cpu_ns']>=0]),
            non_cpu_s=stats([max(0,r['wall_ns']-r['thread_cpu_ns'])/1e9
                             for r in rows if r['thread_cpu_ns']>=0]),
            process_cpu_s=stats([r['process_cpu_ns']/1e9 for r in rows if r['process_cpu_ns']>=0]))
    lidar = read(board/'lidar.jsonl')
    raw = {r['stamp']:r for r in read(run/'profile/raw.jsonl') if r['kind']=='raw_publish'}
    received = {r['stamp']:r for r in lidar if r['kind']=='raw_received'}
    published = {r['stamp']:r for r in lidar if r['kind']=='cloud_publish'}
    observed = {}
    for r in read(run/'observer-profile.jsonl'):
        if r.get('kind')=='cloud_observed':
            observed.setdefault(r['source_sim_ns'],r)
    roundtrip, inside, outside = [], [], []
    for stamp in raw.keys() & received.keys() & published.keys() & observed.keys():
        total=(observed[stamp]['mono_ns']-raw[stamp]['mono_ns'])/1e9
        processing=(published[stamp]['mono_ns']-received[stamp]['mono_ns'])/1e9
        roundtrip.append(total);inside.append(processing);outside.append(total-processing)
    result['cloud_pipeline'] = dict(
        raw_published=len(raw), board_received=len(received), board_published=len(published),
        pc_observed=len(observed), matched_frames=len(roundtrip),
        pc_roundtrip_s=stats(roundtrip), board_residence_s=stats(inside),
        transport_and_unmeasured_callbacks_s=stats(outside),
        registration_wall_s=stats([r['process_wall_s'] for r in published.values()]),
        registration_thread_cpu_s=stats([r['process_cpu_s'] for r in published.values()]),
        pose_queue_wait_s=stats([r['queue_wait_s'] for r in published.values()]),
        rpc_wall_s=stats([r['rpc_wall_s'] for r in raw.values()]))
    control=read(board/'control.jsonl')
    for name,kind in [('valid_commands','command_accepted'),('setpoints','setpoint_published')]:
        rows=[r for r in control if r['kind']==kind]
        result[name]=dict(count=len(rows),gap_s=stats([(b['mono_ns']-a['mono_ns'])/1e9 for a,b in zip(rows,rows[1:])]))
    result['landing']=[r for r in control if r['kind']=='land_requested']
    result['limitations']=[
        '嵌套计算 scope 不可相加；process CPU 包含其他线程，non_cpu 包含调度、锁与阻塞，不能直接称为网络延迟。',
        '点云总时长的两端均为 PC 单调时钟，板内驻留用板端同一时钟计算；不依赖 PC/板端时钟同步。',
        '扣除板内驻留后的余量包含双向 DDS、序列化、发布与回调调度；不是纯线速或独立单向网络延迟。',
        '命令间隔覆盖完整 run，包含悬停和任务切换；profile 产生额外观测开销，需再以关闭 profile 的配置验收。']
    result['limitations'].append('各记录器开始/结束窗口不同；帧计数差不能直接解释为丢包率，计算 scope 包含失败后收尾。')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    args=parser.parse_args()
    result=analyse(args.run)
    destination=args.run/'profile-summary.json'
    destination.write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print(destination)
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':
    main()
