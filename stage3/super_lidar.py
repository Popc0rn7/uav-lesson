#!/usr/bin/env python3
"""ROS Docker：按采样时刻将 MID-360S 近似雷达点云变到 PX4 局部 ENU。"""
from collections import deque
import math
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2, PointField


def seconds(stamp):
    return stamp.sec+stamp.nanosec/1e9


def xyz(msg):
    fields={f.name:f for f in msg.fields}
    if any(k not in fields or fields[k].datatype!=PointField.FLOAT32 or fields[k].offset+4>msg.point_step for k in ('x','y','z')):
        raise ValueError('invalid FLOAT32 xyz fields')
    if msg.row_step<msg.width*msg.point_step or len(msg.data)<msg.height*msg.row_step:
        raise ValueError('truncated cloud')
    dtype=np.dtype({'names':['x','y','z'], 'formats':[('>f4' if msg.is_bigendian else '<f4')]*3,
                    'offsets':[fields[k].offset for k in ('x','y','z')], 'itemsize':msg.point_step})
    data=np.ndarray((msg.height,msg.width),dtype=dtype,buffer=msg.data,strides=(msg.row_step,msg.point_step))
    return np.column_stack([data[k].reshape(-1) for k in ('x','y','z')])


def rotation(q):
    v=np.array([q.w,q.x,q.y,q.z]);norm=np.linalg.norm(v)
    if not math.isfinite(norm) or norm<.5:raise ValueError('invalid quaternion')
    w,x,y,z=v/norm
    return np.array([[1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y)],
                     [2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x)],
                     [2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)]])


class Lidar(Node):
    def __init__(self):
        super().__init__('super_mid360_adapter')
        self.sensor_z=self.declare_parameter('sensor_z',.135).value
        self.declare_parameter('range_max', 39.9)
        self.declare_parameter('input_topic', '/mid360s/scan/points')
        self.range_max = self.get_parameter('range_max').value
        self.poses=deque(maxlen=300)
        self.pending=deque(maxlen=3)
        self.last=None
        self.pub=self.create_publisher(PointCloud2,'/cloud_registered',qos_profile_sensor_data)
        self.create_subscription(Odometry,'/lidar_slam/odom',self.pose,20)
        self.create_subscription(PointCloud2,self.get_parameter('input_topic').value,self.cloud,qos_profile_sensor_data)
        self.create_timer(.01,self.process)

    def pose(self,msg):
        stamp=seconds(msg.header.stamp)
        if self.poses and stamp<self.poses[-1][0]:
            self.poses.clear();self.pending.clear();self.last=None
        self.poses.append((stamp,msg.pose.pose))

    def cloud(self,msg):
        if msg.header.frame_id!='mid360s_sensor':
            self.get_logger().error('Unexpected sensor frame: '+msg.header.frame_id);return
        self.pending.append(msg)

    def process(self):
        if not self.poses:return
        while self.pending:
            msg=self.pending[0];stamp=seconds(msg.header.stamp)
            if stamp>self.poses[-1][0]:return
            self.pending.popleft()
            t,pose=min(self.poses,key=lambda entry:abs(entry[0]-stamp))
            if abs(t-stamp)>.05 or stamp==self.last:continue
            try:
                points=xyz(msg)
                ranges=np.linalg.norm(points,axis=1)
                points=points[np.isfinite(points).all(axis=1)&(ranges>=.6)&(ranges<self.range_max)]
                # Reduce repeated rays in the sensor frame before rotating the dense scan.
                cells=np.floor(points/.1).astype(np.int64)+(1<<20)
                keys=(cells[:,0]<<42)|(cells[:,1]<<21)|cells[:,2]
                _,indices=np.unique(keys,return_index=True)
                points=points[indices]
                # Actual mount extrinsic, shared with height estimator and self filter.
                points=(points+[0,0,self.sensor_z])@rotation(pose.orientation).T
                points+=np.array([pose.position.x,pose.position.y,pose.position.z])
                if not len(points):continue
                cells=np.floor(points/.1).astype(np.int64)+(1<<20)
                if np.any(cells<0) or np.any(cells>=(1<<21)):
                    raise ValueError('cloud outside voxel encoding bounds')
                keys=(cells[:,0]<<42)|(cells[:,1]<<21)|cells[:,2]
                _,indices=np.unique(keys,return_index=True)
                points=np.asarray(points[indices],dtype='<f4')
                # ROG-Map consumes pcl::PointXYZI, supply deterministic intensity.
                packed=np.column_stack((points,np.ones(len(points),dtype='<f4'))).astype('<f4')
                out=PointCloud2();out.header.stamp=msg.header.stamp;out.header.frame_id='world'
                out.height,out.width=1,len(points)
                out.fields=[PointField(name=k,offset=i*4,datatype=PointField.FLOAT32,count=1)
                            for i,k in enumerate(('x','y','z','intensity'))]
                out.point_step,out.row_step=16,len(points)*16
                out.is_dense=True;out.data=packed.tobytes()
                self.pub.publish(out);self.last=stamp
            except ValueError as exc:self.get_logger().warn(str(exc))


def main():
    rclpy.init();node=Lidar()
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':main()
