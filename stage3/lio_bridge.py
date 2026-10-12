#!/usr/bin/env python3
"""FAST-LIO outputs → course coordinates and PX4 external vision. No truth/GNSS input."""
import math
import time
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2,PointField
from px4_msgs.msg import VehicleOdometry
from super_lidar import xyz
from lio_geometry import multiply,matrix,enu_flu_to_ned_frd,course_alignment


class LioBridge(Node):
    def __init__(self):
        super().__init__('stage3_lio_bridge')
        self.anchor=None
        self.accepted_at=0.;self.previous=None
        self.odom_pub=self.create_publisher(Odometry,'/lidar_slam/odom',20)
        self.cloud_pub=self.create_publisher(PointCloud2,'/cloud_registered',qos_profile_sensor_data)
        self.ev_pub=self.create_publisher(VehicleOdometry,'/fmu/in/vehicle_visual_odometry',20)
        self.create_subscription(Odometry,'/stage3/lio/odom_propagated',self.odom,qos_profile_sensor_data)
        self.create_subscription(PointCloud2,'/stage3/lio/cloud',self.cloud,qos_profile_sensor_data)
    def odom(self,msg):
        p=msg.pose.pose.position;o=msg.pose.pose.orientation
        position=np.array([p.x,p.y,p.z]);q=np.array([o.x,o.y,o.z,o.w])
        if not np.isfinite(position).all() or not np.isfinite(q).all() or not .9<np.linalg.norm(q)<1.1:return
        stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
        age=self.get_clock().now().nanoseconds*1e-9-stamp
        if not -.05<=age<=.3:return
        q/=np.linalg.norm(q)
        bv=msg.twist.twist.linear
        if not all(math.isfinite(v) for v in (bv.x,bv.y,bv.z)) or math.sqrt(bv.x*bv.x+bv.y*bv.y+bv.z*bv.z)>8:return
        if self.anchor is None:
            # Known launch convention: initially stationary, body forward=ENU +Y,
            # base_link resting 0.25 m above the flat course. This defines map axes;
            # neither simulator truth nor PX4 pose is read here.
            # FAST-LIO initializes gravity in camera_init. Align only heading:
            # cancelling a noisy first roll/pitch tilts the whole course map.
            alignment=course_alignment(q)
            r=matrix(alignment);translation=np.array([0.,0.,.25])-r@position
            self.anchor=alignment,r,translation
        alignment,r,translation=self.anchor
        world_p=r@position+translation;world_q=multiply(alignment,q)
        body_v=msg.twist.twist.linear
        world_v=r@matrix(q)@np.array([body_v.x,body_v.y,body_v.z])
        if not np.isfinite(world_v).all():return
        if not (abs(world_p[0])<=4 and -4<=world_p[1]<=104 and -1<=world_p[2]<=5):return
        if self.previous is not None:
            old_stamp,old_p=self.previous
            if stamp<=old_stamp or np.linalg.norm(world_p-old_p)>.3+8*(stamp-old_stamp):return
        self.previous=stamp,world_p.copy();self.accepted_at=time.monotonic()
        out=Odometry();out.header=msg.header;out.header.frame_id='world';out.child_frame_id='base_link'
        out.pose.pose.position.x,out.pose.pose.position.y,out.pose.pose.position.z=map(float,world_p)
        out.pose.pose.orientation.x,out.pose.pose.orientation.y,out.pose.pose.orientation.z,out.pose.pose.orientation.w=map(float,world_q)
        # ROG-Map/SUPER use world-frame linear velocity in this interface.
        out.twist.twist.linear.x,out.twist.twist.linear.y,out.twist.twist.linear.z=map(float,world_v)
        self.odom_pub.publish(out)
        ev=VehicleOdometry();ev.timestamp_sample=int(stamp*1e6);ev.timestamp=self.get_clock().now().nanoseconds//1000
        ev.pose_frame=VehicleOdometry.POSE_FRAME_NED;ev.velocity_frame=VehicleOdometry.VELOCITY_FRAME_NED
        ev.position=[float(world_p[1]),float(world_p[0]),-float(world_p[2])]
        ev.velocity=[float(world_v[1]),float(world_v[0]),-float(world_v[2])]
        ev.q=enu_flu_to_ned_frd(world_q);ev.angular_velocity=[float('nan')]*3
        # Conservative interface covariance floors; not a ground-truth confidence.
        ev.position_variance=[.0025]*3;ev.velocity_variance=[.01]*3;ev.orientation_variance=[.001]*3
        ev.quality=100;self.ev_pub.publish(ev)
    def cloud(self,msg):
        if self.anchor is None or time.monotonic()-self.accepted_at>.3 or msg.header.frame_id!='camera_init':return
        try:points=xyz(msg)
        except ValueError:return
        if not len(points):return
        _,r,translation=self.anchor
        points=points@r.T+translation
        points=points[np.isfinite(points).all(axis=1)]
        packed=np.column_stack((points,np.full(len(points),100.))).astype('<f4')
        out=PointCloud2();out.header=msg.header;out.header.frame_id='world';out.height=1;out.width=len(points)
        out.fields=[PointField(name=k,offset=i*4,datatype=7,count=1) for i,k in enumerate(('x','y','z','intensity'))]
        out.point_step=16;out.row_step=16*len(points);out.is_dense=True;out.data=packed.tobytes()
        self.cloud_pub.publish(out)


def main():
    rclpy.init();node=LioBridge()
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':main()
