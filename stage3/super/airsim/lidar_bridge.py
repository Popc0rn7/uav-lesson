#!/usr/bin/env python3
"""Docker 2：AirSim 雷达读取、过滤与 PX4/GNSS 采样位姿配准。"""
from collections import deque
import time
import numpy as np
import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2, PointField
from std_msgs.msg import String
from geometry import interpolate, register
from rpc_client import rpc
from task_config import load_task


class Lidar(Node):
    def __init__(self):
        super().__init__('airsim_lidar')
        self.task = load_task(self.declare_parameter('task_config', '').value)
        self.poses = deque(maxlen=600)
        self.pending = deque(maxlen=10)
        self.last = None
        self.pose_wall = 0.
        self.pub = self.create_publisher(PointCloud2, '/cloud_registered', qos_profile_sensor_data)
        self.status = self.create_publisher(String, '/stage3/uav1/sensors', 10)
        self.create_subscription(Odometry, '/lidar_slam/odom', self.pose, 20)
        self.create_timer(.05, self.poll, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.create_timer(.01, self.process, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def pose(self, msg):
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        if self.poses and stamp < self.poses[-1][0]:
            self.poses.clear()
            self.pending.clear()
            self.last = None
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        if msg.header.frame_id == 'world':
            self.poses.append((stamp, [p.x, p.y, p.z], [q.x, q.y, q.z, q.w]))
            self.pose_wall = time.monotonic()

    def poll(self):
        try:
            data = rpc('getLidarData', self.task['lidar']['name'], 'PX4', timeout=.3)
            stamp = int(data['time_stamp'])
            if stamp and stamp != self.last:
                if self.last is not None and stamp < self.last:
                    self.poses.clear()
                    self.pending.clear()
                self.last = stamp
                self.pending.append((stamp, data['point_cloud'], time.monotonic()))
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            self.status.publish(String(data='RPC error: ' + str(exc)))

    def process(self):
        while self.pending:
            stamp, points, received = self.pending[0]
            seconds = stamp * 1e-9
            if time.monotonic() - received > .5 or time.monotonic() - self.pose_wall > .5:
                self.pending.popleft()
                self.status.publish(String(data='dropped: stale pose/cloud'))
                continue
            if not self.poses or seconds > self.poses[-1][0]:
                return
            self.pending.popleft()
            pose = interpolate(self.poses, seconds)
            if pose is None:
                self.status.publish(String(data='dropped: no pose bracket within 50 ms'))
                continue
            try:
                world = register(points, pose, self.task['lidar'])
            except ValueError as exc:
                self.status.publish(String(data='dropped: ' + str(exc)))
                continue
            if not len(world):
                continue
            out = PointCloud2()
            out.header.stamp.sec, out.header.stamp.nanosec = divmod(stamp, 1000000000)
            out.header.frame_id = 'world'
            out.height, out.width = 1, len(world)
            out.fields = [PointField(name=k, offset=i*4, datatype=PointField.FLOAT32, count=1)
                          for i, k in enumerate(('x', 'y', 'z', 'intensity'))]
            out.point_step, out.row_step = 16, len(world)*16
            out.is_dense = True
            out.data = np.column_stack((world, np.ones(len(world)))).astype('<f4').tobytes()
            self.pub.publish(out)
            self.status.publish(String(data=f'ok: stamp={stamp} points={len(world)}'))


def main():
    rclpy.init()
    node = Lidar()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
