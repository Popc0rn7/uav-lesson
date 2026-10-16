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
from cloud_wire import TOPIC, decode
from task_config import load_task
from profile_events import Recorder


class Lidar(Node):
    def __init__(self):
        super().__init__('airsim_lidar')
        self.profile = Recorder('lidar')
        self.task = load_task(self.declare_parameter('task_config', '').value)
        self.poses = deque(maxlen=600)
        self.pending = deque(maxlen=10)
        self.last = None
        self.raw_subscription = None
        self.pose_wall = 0.
        self.counts = dict(received=0, published=0, overflow=0, stale_cloud=0,
                           stale_pose=0, no_bracket=0, invalid=0, empty=0)
        self.received_wall = self.published_wall = 0.
        self.pub = self.create_publisher(PointCloud2, '/cloud_registered', qos_profile_sensor_data)
        self.status = self.create_publisher(String, '/stage3/uav1/sensors', 10)
        self.create_subscription(Odometry, '/lidar_slam/odom', self.pose, 20)
        if self.declare_parameter('input_mode', 'rpc').value == 'ros':
            self.raw_subscription = self.create_subscription(PointCloud2, TOPIC, self.raw, qos_profile_sensor_data)
        else:
            self.create_timer(.05, self.poll, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.create_timer(.01, self.process, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.create_timer(1., self.snapshot, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def snapshot(self):
        now = time.monotonic()
        sim = self.get_clock().now().nanoseconds * 1e-9
        self.profile.emit('queue_snapshot', counts=dict(self.counts), pending=len(self.pending),
                          oldest_wall_s=now-self.pending[0][2] if self.pending else None,
                          oldest_sim_age_s=sim-self.pending[0][0]*1e-9 if self.pending else None,
                          latest_pose_age_s=sim-self.poses[-1][0] if self.poses else None,
                          pose_callback_age_s=now-self.pose_wall,
                          raw_callback_age_s=now-self.received_wall,
                          publish_gap_s=now-self.published_wall)

    def dropped(self, reason, stamp):
        self.counts[reason] += 1
        seconds = stamp * 1e-9
        before = next((p[0] for p in reversed(self.poses) if p[0] <= seconds), None)
        after = next((p[0] for p in self.poses if p[0] >= seconds), None)
        self.profile.emit('cloud_dropped', reason=reason, stamp=stamp, pending=len(self.pending),
                          latest_pose_stamp=self.poses[-1][0] if self.poses else None,
                          bracket_before=before, bracket_after=after)

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

    def raw(self, msg):
        try:
            stamp = msg.header.stamp.sec * 1000000000 + msg.header.stamp.nanosec
            started, cpu = time.monotonic(), time.thread_time()
            self.received_wall = started
            self.counts['received'] += 1
            self.profile.emit('raw_received', stamp=stamp,
                              sim_age_s=self.get_clock().now().nanoseconds*1e-9-stamp*1e-9)
            points = decode(msg)
            self.profile.emit('raw_decoded', stamp=stamp, wall_s=time.monotonic()-started,
                              cpu_s=time.thread_time()-cpu)
            self.enqueue(stamp, points)
        except ValueError as exc:
            self.status.publish(String(data='dropped: ' + str(exc)))

    def enqueue(self, stamp, points):
        if stamp and stamp != self.last:
            if self.last is not None and stamp < self.last:
                self.poses.clear()
                self.pending.clear()
            self.last = stamp
            if len(self.pending) == self.pending.maxlen:
                self.dropped('overflow', self.pending[0][0])
            self.pending.append((stamp, points, time.monotonic()))

    def poll(self):
        from rpc_client import rpc
        try:
            data = rpc('getLidarData', self.task['lidar']['name'], 'PX4', timeout=.3)
            stamp = int(data['time_stamp'])
            self.enqueue(stamp, data['point_cloud'])
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            self.status.publish(String(data='RPC error: ' + str(exc)))

    def process(self):
        while self.pending:
            stamp, points, received = self.pending[0]
            seconds = stamp * 1e-9
            if time.monotonic() - received > .5 or time.monotonic() - self.pose_wall > .5:
                self.pending.popleft()
                self.dropped('stale_cloud' if time.monotonic()-received > .5 else 'stale_pose', stamp)
                self.status.publish(String(data='dropped: stale pose/cloud'))
                continue
            if not self.poses or seconds > self.poses[-1][0]:
                return
            self.pending.popleft()
            pose = interpolate(self.poses, seconds)
            if pose is None:
                self.dropped('no_bracket', stamp)
                self.status.publish(String(data='dropped: no pose bracket within 50 ms'))
                continue
            try:
                started, cpu = time.monotonic(), time.thread_time()
                world = register(points, pose, self.task['lidar'])
            except ValueError as exc:
                self.dropped('invalid', stamp)
                self.status.publish(String(data='dropped: ' + str(exc)))
                continue
            if not len(world):
                self.dropped('empty', stamp)
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
            self.profile.emit('cloud_publish', stamp=stamp, process_wall_s=time.monotonic()-started,
                              process_cpu_s=time.thread_time()-cpu,
                              queue_wait_s=started-received, points=len(world), pending=len(self.pending),
                              sim_age_s=self.get_clock().now().nanoseconds*1e-9-seconds)
            self.pub.publish(out)
            self.counts['published'] += 1
            self.published_wall = time.monotonic()
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
