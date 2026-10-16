#!/usr/bin/env python3
"""Docker 2：PX4 HIL 仿真时间 → ROS /clock；XRCE 时间同步必须关闭。"""
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from px4_msgs.msg import SensorCombined
from rosgraph_msgs.msg import Clock


class SimulationClock(Node):
    def __init__(self):
        super().__init__('airsim_px4_clock')
        self.pub = self.create_publisher(Clock, '/clock', 10)
        self.last = None
        self.create_subscription(SensorCombined, '/fmu/out/sensor_combined', self.sample, qos_profile_sensor_data)

    def sample(self, msg):
        if not msg.timestamp or msg.timestamp == self.last:
            return
        if self.last is not None and msg.timestamp < self.last:
            self.get_logger().error('PX4 仿真时间回跳；当前任务必须终止')
        out = Clock()
        out.clock.sec, out.clock.nanosec = divmod(int(msg.timestamp) * 1000, 1000000000)
        self.pub.publish(out)
        self.last = msg.timestamp


def main():
    rclpy.init()
    node = SimulationClock()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
