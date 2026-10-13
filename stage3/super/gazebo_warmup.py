#!/usr/bin/env python3
"""Gazebo Docker：启动时订阅气压计，触发传感器并等待桥接就绪。"""
import time
import os
from gz.transport13 import Node
from gz.msgs10.fluid_pressure_pb2 import FluidPressure
from gz.msgs10.navsat_pb2 import NavSat
from gz.msgs10.magnetometer_pb2 import Magnetometer

node=Node()
received=[]
gps_received=[]
mag_received=[]
def receive(msg):
    if msg.pressure>0:received.append(time.monotonic())
topic=f'/world/{os.environ.get("PX4_GZ_WORLD", "default")}/model/x500_experiment_0/link/base_link/sensor/air_pressure_sensor/air_pressure'
if not node.subscribe(FluidPressure,topic,receive):raise SystemExit('barometer subscribe failed')
gps_topic=f'/world/{os.environ.get("PX4_GZ_WORLD", "default")}/model/x500_experiment_0/link/base_link/sensor/navsat_sensor/navsat'
if not node.subscribe(NavSat,gps_topic,lambda msg:gps_received.append(time.monotonic())):
    raise SystemExit('GNSS subscribe failed')
mag_topic=f'/world/{os.environ.get("PX4_GZ_WORLD", "default")}/model/x500_experiment_0/link/base_link/sensor/magnetometer_sensor/magnetometer'
if not node.subscribe(Magnetometer,mag_topic,lambda msg:mag_received.append(time.monotonic())):
    raise SystemExit('magnetometer subscribe failed')
deadline=time.monotonic()+60
while time.monotonic()<deadline:
    if received and gps_received and mag_received and time.monotonic()-max(received[0],gps_received[0],mag_received[0])>5:
        print('Gazebo warmup received pressure, GNSS and magnetometer',flush=True)
        break
    time.sleep(.1)
else:raise SystemExit('Gazebo pressure/GNSS/magnetometer warmup timed out')
