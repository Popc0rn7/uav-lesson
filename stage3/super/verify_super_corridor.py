#!/usr/bin/env python3
"""ROS Docker：实体走廊往返验收；真值只用于独立评测。"""
import json
import math
import os
import time
from pathlib import Path
from urllib.request import urlopen
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from px4_msgs.msg import VehicleStatus
from std_msgs.msg import String
from sensor_msgs.msg import PointCloud2
from mars_quadrotor_msgs.msg import PositionCommand


def monitor():
    with urlopen('http://127.0.0.1:8096/state',timeout=2) as response:return json.load(response)


def main():
    rclpy.init();node=Node('stage3_corridor_check')
    state=dict(status='',odom=None,vehicle=None,clouds=0,cloud_at=0.,reference=None)
    node.create_subscription(PositionCommand,'/stage3/uav1/reference',lambda m:state.update(reference=m),qos_profile_sensor_data)
    def cloud(m):
        if m.width:
            state.update(clouds=state['clouds']+1,cloud_at=time.monotonic())
    node.create_subscription(PointCloud2,'/cloud_registered',cloud,qos_profile_sensor_data)
    node.create_subscription(String,'/stage3/uav1/status',lambda m:state.update(status=m.data),10)
    node.create_subscription(Odometry,'/lidar_slam/odom',lambda m:state.update(odom=m),10)
    node.create_subscription(VehicleStatus,'/fmu/out/vehicle_status_v4',lambda m:state.update(vehicle=m),qos_profile_sensor_data)
    command=node.create_publisher(String,'/stage3/uav1/command',10)
    goal_pub=node.create_publisher(PoseStamped,'/stage3/uav1/goal',10)
    layout=json.loads(Path('/lesson/stage3/super/corridor_layout.json').read_text())
    landmarks=json.loads(Path('/lesson/stage3/super/lio_landmarks.json').read_text()) if os.environ.get('STAGE3_WALL_LANDMARKS')=='true' else None
    speed=int(float(os.environ.get('STAGE3_SPEED','2')))
    report=dict(passed=False,speed_mps=speed,localization=os.environ.get('STAGE3_LOCALIZATION','px4'),wall_landmarks=landmarks is not None,reference_topic='/stage3/uav1/reference',legs=[],peak_speed_mps=0.,min_clearance_m=None,
                min_height_m=None,max_height_m=None,max_tracking_truth_error_m=0.,min_reference_z_m=None,max_reference_z_m=None,max_tracking_error_m=0.)
    trajectory=[];attempted=False;baseline=None;last_check=0.;offset=None

    def position():
        p=state['odom'].pose.pose.position;return [p.x,p.y,p.z]

    def audit():
        nonlocal last_check
        if time.monotonic()-last_check<.1:return
        last_check=time.monotonic();truth=monitor()
        if truth['contacts']:raise RuntimeError('Gazebo obstacle contact: '+str(truth['contacts'][-1]))
        if truth['pose'] is None or time.monotonic()-truth['pose_at']>.5:raise RuntimeError('Gazebo truth timeout')
        previous=state.get('truth')
        dt=truth.get('pose_sim_time',truth['sim_time'])-previous.get('pose_sim_time',previous['sim_time']) if previous else 0.
        if dt>0:state['truth_speed']=math.dist(truth['pose'],previous['pose'])/dt
        elif 'truth_speed' not in state:state['truth_speed']=float('inf')
        state['truth']=truth
        p=position();gt=truth['pose'];v=state['odom'].twist.twist.linear
        vel=math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)
        reference=state['reference']
        if reference is not None:
            rp=reference.position
            old=report['min_reference_z_m'];report['min_reference_z_m']=rp.z if old is None else min(old,rp.z)
            old=report['max_reference_z_m'];report['max_reference_z_m']=rp.z if old is None else max(old,rp.z)
            if state['status'].startswith(('track:','planning:','hover:')):
                report['max_tracking_error_m']=max(report['max_tracking_error_m'],math.dist(p,[rp.x,rp.y,rp.z]))
        report['peak_speed_mps']=max(report['peak_speed_mps'],vel)
        if offset is not None:
            height=gt[2]  # Physical AGL: Gazebo corridor floor is z=0.
            error=math.dist(gt,[p[i]+offset[i] for i in range(3)])
            report['max_tracking_truth_error_m']=max(report['max_tracking_truth_error_m'],error)
            if state['status'].startswith(('track:','planning:','hover:')):
                report['min_height_m']=height if report['min_height_m'] is None else min(report['min_height_m'],height)
                report['max_height_m']=height if report['max_height_m'] is None else max(report['max_height_m'],height)
                if not 1.3<=height<=2.2:raise RuntimeError('Actual flight outside height band: '+str(height))
        # In the flight layer, cylinders extend above the aircraft and shrubs stay below it.
        clearance=min(3-abs(gt[0]),*[math.hypot(gt[0]-x,gt[1]-y)-.1 for x,y in layout['poles']])
        if landmarks:
            for center in landmarks['centers']:
                distance=math.sqrt(sum(max(abs(gt[i]-center[i])-landmarks['size'][i]/2,0)**2 for i in range(3)))
                clearance=min(clearance,distance)
        if state['status'].startswith(('track:','planning:','hover:')):
            old=report['min_clearance_m'];report['min_clearance_m']=clearance if old is None else min(old,clearance)
            if clearance<.35:raise RuntimeError('Centre clearance below physical body envelope: '+str(clearance))
        trajectory.append([truth['sim_time'],*p,*gt,vel,reference.position.z if reference else float('nan')])
        report['last_real_time_factor']=truth['real_time_factor']
        if state['status'].startswith('land:') and not report.get('landing_requested'):
            raise RuntimeError('Bridge aborted task: '+state['status'])

    def wait(predicate,timeout,flight=False):
        deadline=time.monotonic()+timeout
        next_progress=time.monotonic()+5
        while time.monotonic()<deadline:
            rclpy.spin_once(node,timeout_sec=.02)
            if flight and state['odom']:audit()
            if predicate():return
            if time.monotonic()>=next_progress:
                print(f"等待中：{state['status'] or '尚未收到控制桥状态'}；点云帧数={state['clouds']}；剩余 {max(0,deadline-time.monotonic()):.0f} 秒",flush=True)
                next_progress=time.monotonic()+5
        raise RuntimeError('Timeout: '+state['status'])

    try:
        print('等待数据链就绪（最多 60 秒）…',flush=True)
        wait(lambda:state['vehicle'] is not None and state['odom'] is not None and state['status'].startswith('idle: local_ready') and command.get_subscription_count()>0 and state['clouds']>=20 and time.monotonic()-state['cloud_at']<.5,60)
        # Preflight can pass before the EKF's stationary alignment settles.
        print('数据链已就绪；等待 EKF 静止对齐 30 秒，随后自动起飞…',flush=True)
        settle_until=time.monotonic()+30
        wait(lambda:time.monotonic()>=settle_until,35)
        truth=monitor()
        if truth['world']!='corridor':raise RuntimeError('Wrong Gazebo world')
        if state['vehicle'].arming_state==state['vehicle'].ARMING_STATE_ARMED:raise RuntimeError('Already armed')
        p=position();offset=[truth['pose'][i]-p[i] for i in range(3)]
        report['truth_frame_translation']=offset
        print('发送起飞指令，等待 PX4 解锁与悬停（最多 45 秒）…',flush=True)
        attempted=True;command.publish(String(data='takeoff'))
        wait(lambda:state['status'].startswith('hover: hover_ready'),45,True)
        print('PASS: PX4 takeoff and hover',flush=True)
        for target in ([0.,100.,1.95],[0.,0.,1.95]):
            print(f'开始航段，目标 ENU={target}',flush=True)
            msg=PoseStamped();msg.header.frame_id='world';msg.pose.orientation.w=1.
            msg.pose.position.x,msg.pose.position.y,msg.pose.position.z=target
            goal_pub.publish(msg);begin=time.monotonic();stable=None
            def arrived():
                nonlocal stable
                v=state['odom'].twist.twist.linear
                err=math.dist(position(),target)
                truth_error=math.dist(state['truth']['pose'],target)
                okay=err<.3 and truth_error<.3 and state['truth_speed']<.3 and math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)<.3 and state['status'].startswith(('track:','hover: goal_reached'))
                stable=(stable or time.monotonic()) if okay else None
                # The bridge accepts a new goal only after acknowledging completion.
                # Evaluation can reach its stable interval before the bridge's timer.
                return stable is not None and time.monotonic()-stable>2 and state['status'].startswith('hover: goal_reached')
            wait(arrived,180 if speed==2 else 120,True)
            leg=dict(goal=target,elapsed_s=time.monotonic()-begin,endpoint_error_m=math.dist(position(),target),endpoint_truth_error_m=math.dist(state['truth']['pose'],target))
            report['legs'].append(leg);print(json.dumps(leg),flush=True)
    except Exception as exc:
        report['error']=str(exc)
        print('验收失败：'+str(exc),flush=True)
    finally:
        if attempted:
            report['landing_requested']=True;command.publish(String(data='land'))
            try:
                wait(lambda:state['vehicle'].arming_state!=state['vehicle'].ARMING_STATE_ARMED,60)
                report['landing_disarmed']=True
            except Exception as exc:report['landing_error']=str(exc)
        report['passed']=len(report['legs'])==2 and report.get('landing_disarmed',False) and 'error' not in report
        report['final_status']=state['status']
        out=Path('/tmp/stage3-corridor');out.mkdir(exist_ok=True)
        (out/f'result-{speed}.json').write_text(json.dumps(report,indent=2)+'\n')
        (out/f'trajectory-{speed}.csv').write_text('sim_s,x,y,z,gz_x,gz_y,gz_z,speed,reference_z\n'+'\n'.join(','.join(map(str,row)) for row in trajectory)+'\n')
        print(json.dumps(report,indent=2),flush=True);node.destroy_node();rclpy.try_shutdown()
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
