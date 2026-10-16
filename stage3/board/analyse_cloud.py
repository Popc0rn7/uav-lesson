#!/usr/bin/env python3
"""PC：按板端同机时钟分析长时间点云队列及失流现场，不推断单向网络延迟。"""
import argparse
from collections import Counter
import json
from pathlib import Path
from analyse_profile import read, stats


def analyse(run):
    lidar = read(run/'board-logs/profile/lidar.jsonl')
    control = read(run/'board-logs/profile/control.jsonl')
    origin = lidar[0]['mono_ns']
    snapshots = [r for r in lidar if r['kind'] == 'queue_snapshot']
    if not snapshots:
        raise ValueError('缺少 queue_snapshot；请部署带逐帧诊断的版本')

    def window(rows):
        kinds = Counter(r['kind'] for r in rows)
        pub = [r for r in rows if r['kind'] == 'cloud_publish']
        rx = [r for r in rows if r['kind'] == 'raw_received']
        snap = [r for r in rows if r['kind'] == 'queue_snapshot']
        return dict(events=dict(kinds),
                    drops=dict(Counter(r['reason'] for r in rows if r['kind'] == 'cloud_dropped')),
                    received_sim_age_s=stats([r['sim_age_s'] for r in rx]),
                    published_sim_age_s=stats([r['sim_age_s'] for r in pub]),
                    registration_wall_s=stats([r['process_wall_s'] for r in pub]),
                    registration_cpu_s=stats([r['process_cpu_s'] for r in pub]),
                    pose_queue_wait_s=stats([r['queue_wait_s'] for r in pub]),
                    raw_callback_gap_s=stats([(b['mono_ns']-a['mono_ns'])/1e9 for a,b in zip(rx,rx[1:])]),
                    pending=stats([r['pending'] for r in snap]),
                    oldest_wall_s=stats([r['oldest_wall_s'] for r in snap if r['oldest_wall_s'] is not None]))

    result = dict(duration_s=(lidar[-1]['mono_ns']-origin)/1e9, total=window(lidar), minutes=[], faults=[])
    raw_pc = [r for r in read(run/'profile/raw.jsonl') if r['kind'] == 'raw_publish']
    pc_by_stamp = {r['stamp']: i for i, r in enumerate(raw_pc)}
    received = [r for r in lidar if r['kind'] == 'raw_received']
    received_stamps = {r['stamp'] for r in received}
    result['receive_gaps'] = []
    for left, right in zip(received, received[1:]):
        gap = (right['mono_ns']-left['mono_ns'])/1e9
        if gap <= .5:
            continue
        item = dict(board_gap_s=gap, left=left, right=right)
        if left['stamp'] in pc_by_stamp and right['stamp'] in pc_by_stamp:
            begin, end = pc_by_stamp[left['stamp']], pc_by_stamp[right['stamp']]
            rows = raw_pc[begin:end+1]
            item.update(pc_publish_events_inside_gap=max(0, len(rows)-2),
                        never_observed_in_board_callbacks=sum(r['stamp'] not in received_stamps for r in rows),
                        pc_publish_gap_s=stats([(b['mono_ns']-a['mono_ns'])/1e9 for a,b in zip(rows,rows[1:])]))
        result['receive_gaps'].append(item)
    for minute in range(int(result['duration_s']//60)+1):
        rows = [r for r in lidar if minute*60 <= (r['mono_ns']-origin)/1e9 < (minute+1)*60]
        if rows:
            result['minutes'].append(dict(start_s=minute*60, **window(rows)))
    clouds = [r for r in control if r['kind'] == 'cloud_received']
    result['control'] = dict(received=len(clouds), accepted=sum(r['accepted'] for r in clouds),
                             rejected_sim_age_s=stats([r['sim_age_s'] for r in clouds if not r['accepted']]))
    for event in control:
        if event['kind'] != 'land_requested':
            continue
        now = event['mono_ns']
        recent = [r for r in lidar if now-2e9 <= r['mono_ns'] <= now]
        c = [r for r in clouds if now-2e9 <= r['mono_ns'] <= now]
        last_fresh = next((r for r in reversed(clouds) if r['mono_ns'] <= now and r['accepted']), None)
        result['faults'].append(dict(event=event, elapsed_s=(now-origin)/1e9,
                                    preceding_2s=window(recent), control_clouds=c,
                                    last_fresh_gap_s=(now-last_fresh['mono_ns'])/1e9 if last_fresh else None,
                                    receive_gap=next((g for g in result['receive_gaps']
                                                      if g['left']['mono_ns'] <= now <= g['right']['mono_ns']), None),
                                    drops=[r for r in recent if r['kind'] == 'cloud_dropped']))
    result['limitations'] = ['采样窗口内的消息计数差不等于网络丢包率；接收回调年龄包括传输与回调调度。',
                             '队列快照为 1 Hz，帧级发布/丢弃事件补充快照之间的变化；profile 本身有开销。']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    result = analyse(args.run)
    output = args.run/'cloud-summary.json'
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(output)
    print(json.dumps(dict(duration_s=result['duration_s'], total=result['total'],
                          control=result['control'], faults=result['faults']), ensure_ascii=False))


if __name__ == '__main__':
    main()
