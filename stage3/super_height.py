#!/usr/bin/env python3
"""ROS Docker：将雷达地面高度作为 PX4 外部里程计的 Z 测量。"""
import json
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import Float64, String
from px4_msgs.msg import VehicleOdometry
from super_lidar import xyz
from lidar_height import estimate_height


class Height(Node):
    def __init__(self):
        super().__init__('stage3_lidar_ground_height')
        self.sensor_z=self.declare_parameter('sensor_z',.135).value
        self.pub=self.create_publisher(VehicleOdometry,'/fmu/in/vehicle_visual_odometry',10)
        self.height=self.create_publisher(Float64,'/stage3/uav1/lidar_height',10)
        self.quality=self.create_publisher(String,'/stage3/uav1/lidar_height_quality',10)
        self.create_subscription(PointCloud2,'/stage3/lidar/filtered',self.cloud,qos_profile_sensor_data)

    def cloud(self,msg):
        try:result=estimate_height(xyz(msg),sensor_z=self.sensor_z)
        except ValueError as exc:self.get_logger().warn(str(exc));return
        if result is None:return
        out=VehicleOdometry();out.timestamp_sample=msg.header.stamp.sec*1000000+msg.header.stamp.nanosec//1000
        out.timestamp=self.get_clock().now().nanoseconds//1000
        out.pose_frame=VehicleOdometry.POSE_FRAME_NED
        out.position=[0.,0.,-result['height_m']];out.q=[1.,0.,0.,0.]
        out.velocity_frame=VehicleOdometry.VELOCITY_FRAME_NED
        out.velocity=out.angular_velocity=[float('nan')]*3
        out.position_variance=[100.,100.,max(.0025,result['rms_m']**2)]
        out.orientation_variance=out.velocity_variance=[float('nan')]*3
        out.quality=100;self.pub.publish(out)
        self.height.publish(Float64(data=result['height_m']))
        self.quality.publish(String(data=json.dumps(result)))


def main():
    rclpy.init();node=Height()
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':main()
