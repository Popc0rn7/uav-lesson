#!/usr/bin/env python3
"""Docker：通过 Gazebo Transport 实测目标车轨迹，真值只用于场景验收。"""
import argparse
import json
import math
import threading
import time

from gz.transport13 import Node
from gz.msgs10.pose_v_pb2 import Pose_V


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=12)
    args = parser.parse_args()
    samples = []
    lock = threading.Lock()

    def receive(msg):
        for pose in msg.pose:
            if pose.name == 'target_car':
                stamp = pose.header.stamp.sec + pose.header.stamp.nsec / 1e9
                with lock:
                    samples.append((stamp, pose.position.x, pose.position.y, pose.position.z))

    node = Node()
    if not node.subscribe(Pose_V, '/model/target_car/pose', receive):
        raise SystemExit('订阅失败')
    deadline = time.monotonic() + 15
    while not samples:
        if time.monotonic() > deadline:
            raise SystemExit('未收到目标车位姿；检查 server 日志与 GZ_PARTITION')
        time.sleep(.05)
    deadline = time.monotonic() + args.seconds * 3 + 15
    while True:
        with lock:
            elapsed = samples[-1][0] - samples[0][0]
        if elapsed >= args.seconds:
            break
        if time.monotonic() > deadline:
            raise SystemExit('仿真时钟停止或运行速度过低')
        time.sleep(.1)
    with lock:
        data = list(samples)
    distance = sum(math.dist(a[1:3], b[1:3]) for a, b in zip(data, data[1:]))
    radial_error = max(abs(math.hypot(p[1], p[2]) - 24) for p in data)
    height_error = max(abs(p[3] - .65) for p in data)
    speed = distance / elapsed
    result = dict(sim_seconds=round(elapsed, 3), samples=len(data),
                  distance_m=round(distance, 3), speed_mps=round(speed, 4),
                  max_radius_error_m=round(radial_error, 4),
                  max_height_error_m=round(height_error, 4))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not (len(data) > 50 and abs(speed - 2) < .05 and radial_error < .15 and height_error < .05):
        raise SystemExit('目标车轨迹验收失败')
    print('PASS：目标车持续沿街区环路以 2 m/s 行驶')


if __name__ == '__main__':
    main()
