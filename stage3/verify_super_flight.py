#!/usr/bin/env python3
"""ROS Docker：显式 --fly 后验收单机 SITL 起飞、规划到点和降落。"""
import argparse
import json
import math
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from geometry_msgs.msg import PoseStamped
from px4_msgs.msg import VehicleStatus


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fly',action='store_true',required=True)
    parser.add_argument('--goal',type=float,nargs=3,default=[2.,0.,2.])
    parser.add_argument('--report',default='/tmp/stage3-super-flight.json')
    args=parser.parse_args()
    rclpy.init();node=Node('stage3_super_flight_check')
    state={'status':'','odom':None,'vehicle':None}
    node.create_subscription(String,'/stage3/uav1/status',lambda msg:state.update(status=msg.data),10)
    node.create_subscription(Odometry,'/lidar_slam/odom',lambda msg:state.update(odom=msg),10)
    node.create_subscription(VehicleStatus,'/fmu/out/vehicle_status_v4',lambda msg:state.update(vehicle=msg),qos_profile_sensor_data)
    command=node.create_publisher(String,'/stage3/uav1/command',10)
    goal=node.create_publisher(PoseStamped,'/stage3/uav1/goal',10)
    report={'passed':False,'goal':args.goal,'steps':[]}
    def wait(predicate,timeout):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            rclpy.spin_once(node,timeout_sec=.05)
            if predicate():return
        raise RuntimeError('Timeout: '+state['status'])
    attempted=False
    try:
        wait(lambda:state['vehicle'] is not None and state['vehicle'].pre_flight_checks_pass and command.get_subscription_count()>0,60)
        attempted=True;command.publish(String(data='takeoff'))
        wait(lambda:state['status'].startswith('hover: hover_ready'),45)
        report['steps'].append('takeoff_hover_passed');print('PASS: takeoff and stable hover',flush=True)
        target=PoseStamped();target.header.frame_id='world';target.pose.orientation.w=1.
        target.pose.position.x,target.pose.position.y,target.pose.position.z=args.goal
        goal.publish(target)
        stable=[None]
        def arrived():
            msg=state['odom']
            if msg is None:return False
            p=msg.pose.pose.position;v=msg.twist.twist.linear
            error=math.dist([p.x,p.y,p.z],args.goal)
            speed=math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)
            report['endpoint_error_m']=error
            if (state['status'].startswith('track:') or state['status']=='hover: goal_reached') and error<.3 and speed<.3:
                stable[0]=stable[0] or time.monotonic()
                return time.monotonic()-stable[0]>2.
            stable[0]=None;return False
        wait(arrived,90)
        report['steps'].append('SUPER_goal_passed');print('PASS: SUPER goal reached',flush=True)
    except RuntimeError as exc:report['error']=str(exc)
    finally:
        if attempted:
            command.publish(String(data='land'))
            try:
                wait(lambda:state['vehicle'].arming_state!=state['vehicle'].ARMING_STATE_ARMED,60)
                report['steps'].append('landing_disarmed')
            except RuntimeError as exc:report['landing_error']=str(exc)
        report['passed']=report['steps']==['takeoff_hover_passed','SUPER_goal_passed','landing_disarmed']
        report['final_status']=state['status']
        from pathlib import Path
        Path(args.report).write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2),flush=True)
        node.destroy_node();rclpy.try_shutdown()
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
