#!/usr/bin/env python3
"""Gazebo GUI Docker：机体后方近距离追随相机，并读取状态确认生效。"""
import time
from gz.transport13 import Node
from gz.msgs10.cameratrack_pb2 import CameraTrack


def main():
    node=Node();confirmed=[]
    def receive(msg):
        if (msg.track_mode==CameraTrack.FOLLOW and msg.follow_target.name=='x500_experiment_0'
                and abs(msg.follow_offset.x+4)<.01 and abs(msg.follow_offset.y)<.01
                and abs(msg.follow_offset.z-2)<.01):
            confirmed.append(True)
    node.subscribe(CameraTrack,'/gui/currently_tracked',receive)
    publisher=node.advertise('/gui/track',CameraTrack)
    msg=CameraTrack();msg.track_mode=CameraTrack.FOLLOW
    msg.follow_target.name='x500_experiment_0'
    msg.follow_offset.x=-4;msg.follow_offset.z=2
    msg.follow_pgain=msg.track_pgain=.15
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        publisher.publish(msg)
        time.sleep(.15)
        if confirmed:
            print('Gazebo chase view: aircraft local offset (-4, 0, 2) m')
            return
    raise SystemExit('Gazebo 后方跟随相机设置未确认；检查 GUI 是否加载完成')


if __name__=='__main__':main()
