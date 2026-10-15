#!/usr/bin/env python3
"""Gazebo Docker：车辆/飞机真值只用于跟随距离评测，不连接控制接口。"""
import argparse
import json
import math
from pathlib import Path
import statistics
import threading
import time
from gz.transport13 import Node
from gz.msgs10.pose_v_pb2 import Pose_V


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=30)
    parser.add_argument('--output',type=Path,default=Path('/tmp/stage5-follow-eval.json'))
    args=parser.parse_args()
    samples=[];lock=threading.Lock();last_at=0
    def receive(msg):
        nonlocal last_at
        poses={p.name:p for p in msg.pose}
        if not {'target_car','x500_experiment_0'} <= poses.keys():return
        now=time.monotonic()
        if now-last_at<.1:return
        last_at=now
        car=poses['target_car'];drone=poses['x500_experiment_0'];q=drone.orientation
        own=[drone.position.x+.24*2*(q.x*q.z+q.w*q.y),
             drone.position.y+.24*2*(q.y*q.z-q.w*q.x),
             drone.position.z+.24*(1-2*(q.x*q.x+q.y*q.y))]
        cq=car.orientation
        yaw=math.atan2(2*(cq.w*cq.z+cq.x*cq.y),1-2*(cq.y*cq.y+cq.z*cq.z))
        direction=[math.cos(yaw),math.sin(yaw)]
        rear=[car.position.x-1.2*direction[0],car.position.y-1.2*direction[1],car.position.z]
        delta=[own[i]-rear[i] for i in range(3)]
        behind=-(delta[0]*direction[0]+delta[1]*direction[1])
        lateral=delta[0]*-direction[1]+delta[1]*direction[0]
        with lock:samples.append(dict(wall_time=now,sim_time=msg.header.stamp.sec+msg.header.stamp.nsec/1e9,
            drone_world=own,car_world=[car.position.x,car.position.y,car.position.z],
            behind_rear_m=behind,lateral_m=lateral,above_rear_m=delta[2],
            horizontal_range_m=math.hypot(delta[0],delta[1])))
    node=Node();node.subscribe(Pose_V,'/world/stage5_street/dynamic_pose/info',receive)
    time.sleep(args.seconds)
    with lock:rows=list(samples)
    if len(rows)<10:raise SystemExit('真值评测样本不足')
    tail=rows[len(rows)//2:]
    travel=sum(math.dist(a['car_world'],b['car_world']) for a,b in zip(rows,rows[1:]))
    summary=dict(samples=len(rows),wall_seconds=rows[-1]['wall_time']-rows[0]['wall_time'],car_travel_m=travel,
        median_behind_rear_m=statistics.median(r['behind_rear_m'] for r in tail),
        median_horizontal_range_m=statistics.median(r['horizontal_range_m'] for r in tail),
        median_above_rear_m=statistics.median(r['above_rear_m'] for r in tail),
        median_abs_lateral_m=statistics.median(abs(r['lateral_m']) for r in tail),
        max_tail_distance_error_m=max(abs(r['horizontal_range_m']-8) for r in tail),
        geometry='car rear centre = model position -1.2m along forward; aircraft base_link centre',
        evaluation_only=True)
    args.output.write_text(json.dumps(dict(summary=summary,samples=rows),indent=2))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
