#!/usr/bin/env python3
"""ROS Docker：FCU 位姿处的模拟原始 IMU；不给 LIO 提供仿真绝对姿态。"""
import math
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Imu


class RawImu(Node):
    def __init__(self):
        super().__init__('stage3_super_fcu_imu')
        self.ready=False
        self.stationary_since=None
        self.pub=self.create_publisher(Imu,'/stage3/uav1/imu',20)
        self.create_subscription(Imu,'/stage3/uav1/imu_raw',self.receive,qos_profile_sensor_data)
    def receive(self,msg):
        if not self.ready:
            stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
            a=msg.linear_acceleration;g=msg.angular_velocity
            stationary=9.3<math.sqrt(a.x*a.x+a.y*a.y+a.z*a.z)<10.3 and math.sqrt(g.x*g.x+g.y*g.y+g.z*g.z)<.05
            if not stationary:
                self.stationary_since=None
                return
            if self.stationary_since is None:self.stationary_since=stamp
            if stamp-self.stationary_since<.5:return
            self.ready=True
            self.get_logger().info('IMU stationary gravity warmup complete; raw measurements enabled')
        msg.header.frame_id='base_link'
        msg.orientation.x=msg.orientation.y=msg.orientation.z=0.;msg.orientation.w=1.
        msg.orientation_covariance=[-1.,0.,0.,0.,0.,0.,0.,0.,0.]
        msg.angular_velocity_covariance=[.0008726646**2,0.,0.,0.,.0008726646**2,0.,0.,0.,.0008726646**2]
        msg.linear_acceleration_covariance=[.00637**2,0.,0.,0.,.00637**2,0.,0.,0.,.00637**2]
        self.pub.publish(msg)


def main():
    rclpy.init();node=RawImu()
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':main()
