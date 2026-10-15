#!/usr/bin/env python3
"""Gazebo Docker：等待车辆控制插件订阅，再重复发送场景运动命令。"""
import argparse
import math
import time
from gz.transport13 import Node
from gz.msgs10.twist_pb2 import Twist


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--speed',type=float,required=True)
    args=parser.parse_args()
    if not math.isfinite(args.speed) or not 0<=args.speed<=3:parser.error('speed须为0～3 m/s')
    node=Node();publisher=node.advertise('/stage5/target/cmd_vel',Twist)
    deadline=time.monotonic()+2
    while not publisher.has_connections():
        if time.monotonic()>=deadline:raise SystemExit('车辆控制插件未连接；命令未发送')
        time.sleep(.02)
    msg=Twist();msg.linear.x=args.speed;msg.angular.z=args.speed/24
    for _ in range(6):
        if not publisher.publish(msg):raise SystemExit('车辆运动命令发布失败')
        time.sleep(.05)


if __name__=='__main__':main()
