#!/usr/bin/env python3
"""ROS Docker：实际链路采样，不发送飞行命令。"""
import json
import time
import os
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from px4_msgs.msg import VehicleOdometry, VehicleStatus
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2, Imu
from std_msgs.msg import String, Float64
from rosgraph_msgs.msg import Clock


def main():
    rclpy.init();node=Node('stage3_inspect')
    counts={};latest={};stamps={}
    sensor_topic='/stage3/lidar/filtered' if os.environ.get('STAGE3_CORRIDOR')=='true' else '/mid360s/scan/points'
    def receive(name,msg):
        counts[name]=counts.get(name,0)+1
        if name=='px4_odom':latest[name]={'pose_frame':msg.pose_frame,'velocity_frame':msg.velocity_frame,'position':[float(x) for x in msg.position]}
        elif name=='px4_status':latest[name]={'armed':msg.arming_state,'nav_state':msg.nav_state,'preflight':msg.pre_flight_checks_pass}
        elif name in ('odom','lio_correction','lio_propagated'):
            stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
            latest[name]={'frame':msg.header.frame_id,'position':[msg.pose.pose.position.x,msg.pose.pose.position.y,msg.pose.pose.position.z],'stamp':stamp}
            stamps.setdefault(name,[]).append(stamp)
        elif name in ('raw','world'):latest[name]={'frame':msg.header.frame_id,'points':msg.width*msg.height,'stamp':msg.header.stamp.sec+msg.header.stamp.nanosec/1e9}
        elif name=='status':latest[name]=msg.data
        elif name=='height':latest[name]=msg.data
        elif name=='imu':latest[name]={'frame':msg.header.frame_id,'accel':[msg.linear_acceleration.x,msg.linear_acceleration.y,msg.linear_acceleration.z],'orientation_available':bool(msg.orientation_covariance[0]>=0)}
        elif name=='livox':
            offsets=[p.offset_time for p in msg.points]
            latest[name]={'points':msg.point_num,'min_offset_ns':min(offsets) if offsets else None,'max_offset_ns':max(offsets) if offsets else None,'timebase_matches_header':msg.timebase==msg.header.stamp.sec*1000000000+msg.header.stamp.nanosec}
        else:latest[name]=msg.clock.sec+msg.clock.nanosec/1e9
    for name,kind,topic in [('px4_odom',VehicleOdometry,'/fmu/out/vehicle_odometry'),
                            ('px4_status',VehicleStatus,'/fmu/out/vehicle_status_v4'),
                            ('odom',Odometry,'/lidar_slam/odom'),('raw',PointCloud2,sensor_topic),
                            ('world',PointCloud2,'/cloud_registered'),('status',String,'/stage3/uav1/status'),
                            ('clock',Clock,'/clock')]:
        counts[name]=0
        node.create_subscription(kind,topic,lambda msg,n=name:receive(n,msg),qos_profile_sensor_data)
    if os.environ.get('STAGE3_CORRIDOR')=='true' and os.environ.get('STAGE3_HEIGHT_SOURCE','lidar')=='lidar':
        counts['height']=0
        node.create_subscription(Float64,'/stage3/uav1/lidar_height',lambda msg:receive('height',msg),10)
    if os.environ.get('STAGE3_CORRIDOR')=='true':
        counts['imu']=0
        node.create_subscription(Imu,'/stage3/uav1/imu',lambda msg:receive('imu',msg),qos_profile_sensor_data)
    use_lio=os.environ.get('STAGE3_LOCALIZATION')=='fastlio'
    if use_lio:
        from livox_ros_driver2.msg import CustomMsg
        counts['livox']=0
        node.create_subscription(CustomMsg,'/stage3/lio/lidar',lambda msg:receive('livox',msg),qos_profile_sensor_data)
        for name,topic in [('lio_correction','/stage3/lio/odom'),('lio_propagated','/stage3/lio/odom_propagated')]:
            counts[name]=0
            node.create_subscription(Odometry,topic,lambda msg,n=name:receive(n,msg),qos_profile_sensor_data)
    # Startup can precede model/sensor loading. Wait for real data and PX4 health,
    # then measure an independent eight-second window.
    deadline=time.monotonic()+60
    ready=False
    while time.monotonic()<deadline:
        rclpy.spin_once(node,timeout_sec=.1)
        local_ready=os.environ.get('STAGE3_CORRIDOR')=='true' and str(latest.get('status','')).startswith(('idle: local_ready','prestream:','takeoff:','hover:','planning:','track:'))
        if all(counts.values()) and (latest.get('px4_status',{}).get('preflight') or local_ready):
            ready=True;break
    for name in counts:counts[name]=0
    stamps.clear();first_clock=latest.get('clock',0.)
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:rclpy.spin_once(node,timeout_sec=.1)
    sim_duration=latest.get('clock',0.)-first_clock
    rates={name:count/sim_duration for name,count in counts.items()} if sim_duration>0 else {}
    timing={}
    for name,values in stamps.items():
        gaps=[b-a for a,b in zip(values,values[1:])]
        if gaps:timing[name]={'min_dt_s':min(gaps),'max_dt_s':max(gaps),'duplicate_or_regressing_stamps':sum(g<=0 for g in gaps)}
    if use_lio:
        # A few early accepted frames are not a healthy continuous LIO chain.
        ready=ready and rates.get('odom',0)>=180 and rates.get('lio_propagated',0)>=180 and rates.get('world',0)>=25.5 and rates.get('imu',0)>=180
        ready=ready and not any(v['duplicate_or_regressing_stamps'] for v in timing.values())
    print(json.dumps({'ready':ready,'sensor_ros_topic':sensor_topic,'counts':counts,'sim_duration_s':sim_duration,'rates_sim_hz':rates,'timing':timing,'latest':latest},indent=2))
    node.destroy_node();rclpy.shutdown()
    return 0 if ready and all(counts.values()) else 1


if __name__=='__main__':raise SystemExit(main())
