#!/usr/bin/env python3
"""Docker 2 只读旁路观察；不发布控制/目标/时钟，不更改 QoS 或发布频率。"""
import argparse
from collections import Counter
import json
import math
import numbers
import sys
import time
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from mars_quadrotor_msgs.msg import PositionCommand
from px4_msgs.msg import TrajectorySetpoint,VehicleOdometry
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import PointCloud2


class Trace(Node):
    def __init__(self, compact=False, cloud_dir=None):
        super().__init__('airsim_passive_trace_'+str(time.time_ns()))
        self.compact = compact
        self.cloud_dir = Path(cloud_dir) if cloud_dir else None
        self.cloud_saved_at = 0.
        if self.cloud_dir: self.cloud_dir.mkdir(parents=True, exist_ok=True)
        self.clock=None;self.counts=Counter()
        self.create_subscription(Clock,'/clock',self.clock_sample,qos_profile_sensor_data)
        for topic,kind in [('/planning/pos_cmd','planner'),('/stage3/uav1/reference','adapter')]:
            self.create_subscription(PositionCommand,topic,lambda m,k=kind:self.command(m,k),qos_profile_sensor_data)
        self.create_subscription(TrajectorySetpoint,'/fmu/in/trajectory_setpoint',self.setpoint,qos_profile_sensor_data)
        self.create_subscription(VehicleOdometry,'/fmu/out/vehicle_odometry',self.odom,qos_profile_sensor_data)
        if compact:
            self.create_subscription(PointCloud2, '/cloud_registered', self.cloud, qos_profile_sensor_data)

    def cloud(self, msg):
        stamp=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
        self.emit('cloud_observed', source_sim_ns=stamp)
        if self.cloud_dir and time.monotonic()-self.cloud_saved_at >= 1:
            import numpy as np
            fields={f.name:(f.offset,f.datatype) for f in msg.fields}
            if msg.header.frame_id!='world' or msg.is_bigendian or msg.height!=1 or msg.point_step<12 or len(msg.data)<msg.width*msg.point_step or any(
                    fields.get(k)!=(i*4,7) for i,k in enumerate(('x','y','z'))):
                return
            points=np.ndarray((msg.width,3),dtype='<f4',buffer=bytes(msg.data),strides=(msg.point_step,4))
            points=points[np.isfinite(points).all(axis=1)][::max(1,math.ceil(msg.width/25000))]
            path=self.cloud_dir/(str(stamp)+'.npz')
            if not path.exists():np.savez_compressed(path,points=points,stamp=stamp)
            self.cloud_saved_at=time.monotonic()

    def emit(self,kind,**values):
        self.counts[kind]+=1
        def clean(value):
            if isinstance(value,list):return [clean(x) for x in value]
            if isinstance(value,numbers.Integral):return int(value)
            if isinstance(value,numbers.Real):return float(value) if math.isfinite(value) else None
            return value
        values={k:clean(v) for k,v in values.items()}
        print(json.dumps(dict(kind=kind,mono_ns=time.monotonic_ns(),wall_ns=time.time_ns(),
                              observed_clock_ns=self.clock,**values),separators=(',',':'),allow_nan=False))

    def clock_sample(self,msg):
        self.clock=msg.clock.sec*10**9+msg.clock.nanosec
        if not self.compact:self.emit('clock',source_sim_ns=self.clock)

    def command(self,msg,kind):
        self.emit(kind,source_sim_ns=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec,
                  p=[msg.position.x,msg.position.y,msg.position.z],v=[msg.velocity.x,msg.velocity.y,msg.velocity.z],
                  a=[msg.acceleration.x,msg.acceleration.y,msg.acceleration.z])

    def setpoint(self,msg):
        # yawspeed 可为 NaN；记录本方案实际有限的 p/v/a，其他字段不混入 JSON。
        self.emit('dds_input_observed',source_sim_ns=int(msg.timestamp)*1000,
                  p=list(msg.position),v=list(msg.velocity),a=list(msg.acceleration))

    def odom(self,msg):
        if self.compact:return
        self.emit('odom',source_sim_ns=int(msg.timestamp_sample)*1000,p=list(msg.position),v=list(msg.velocity))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,required=True)
    parser.add_argument('--token',required=True)
    parser.add_argument('--compact', action='store_true', help='profile：省略高频 clock/odom 输出，增加配准点云观察')
    parser.add_argument('--cloud-dir', help='compact 模式每墙钟秒保存一帧 world 点云，仅供离线显示')
    args=parser.parse_args()
    if not 1<=args.seconds<=1800:parser.error('seconds 必须为 1～1800')
    if args.cloud_dir and not args.compact:parser.error('--cloud-dir 需要 --compact')
    rclpy.init();node=Trace(args.compact,args.cloud_dir);start=time.monotonic();cpu=time.process_time()
    print(json.dumps(dict(kind='observer_ready',mono_ns=time.monotonic_ns())))
    try:
        while time.monotonic()-start<args.seconds:rclpy.spin_once(node,timeout_sec=.05)
    finally:
        print(json.dumps(dict(kind='observer_summary',wall_seconds=time.monotonic()-start,
                              cpu_seconds=time.process_time()-cpu,counts=dict(node.counts))))
        node.destroy_node();rclpy.try_shutdown();sys.stdout.flush()


if __name__=='__main__':main()
