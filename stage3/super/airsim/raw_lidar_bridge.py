#!/usr/bin/env python3
"""PC 仿真容器：本机 AirSim RPC → 原始传感器点云；无位姿反馈。"""
import time
import rclpy
from rclpy.node import Node
from rclpy.clock import Clock, ClockType
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2, PointField
from std_msgs.msg import String
from cloud_wire import TOPIC, FRAME, encode
from rpc_client import rpc
from task_config import load_task
from profile_events import Recorder


class RawLidar(Node):
    def __init__(self):
        super().__init__('airsim_raw_lidar')
        self.profile = Recorder('raw')
        self.task = load_task(self.declare_parameter('task_config', '').value)
        self.publisher = self.create_publisher(PointCloud2, TOPIC, qos_profile_sensor_data)
        self.status = self.create_publisher(String, '/stage3/uav1/raw_sensors', 10)
        self.last = None
        self.frames = self.bytes = 0
        self.started = time.monotonic()
        self.create_timer(.05, self.poll, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def poll(self):
        try:
            started = time.monotonic()
            data = rpc('getLidarData', self.task['lidar']['name'], 'PX4', timeout=.3)
            rpc_finished = time.monotonic()
            stamp = int(data['time_stamp'])
            if not stamp or stamp == self.last:
                return
            out = PointCloud2()
            out.data = encode(data['point_cloud'])
            out.header.stamp.sec, out.header.stamp.nanosec = divmod(stamp, 1000000000)
            out.header.frame_id = FRAME
            out.height, out.width = 1, len(out.data) // 12
            out.fields = [PointField(name=k, offset=i*4, datatype=PointField.FLOAT32, count=1)
                          for i, k in enumerate(('x', 'y', 'z'))]
            out.point_step, out.row_step = 12, len(out.data)
            out.is_dense = False
            self.profile.emit('raw_publish', stamp=stamp, rpc_wall_s=rpc_finished-started,
                              pack_wall_s=time.monotonic()-rpc_finished)
            self.publisher.publish(out)
            self.last = stamp
            self.frames += 1
            self.bytes += len(out.data)
            elapsed = max(.001, time.monotonic()-self.started)
            self.status.publish(String(data=f'ok: stamp={stamp} frames={self.frames} hz={self.frames/elapsed:.2f} bytes_s={self.bytes/elapsed:.0f}'))
        except (OSError, RuntimeError, ValueError, KeyError, OverflowError) as exc:
            self.status.publish(String(data='RPC error: '+str(exc)))


def main():
    rclpy.init()
    node = RawLidar()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
