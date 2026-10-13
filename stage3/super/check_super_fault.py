#!/usr/bin/env python3
"""ROS Docker：独立冷启动运行中验证点云、规划或时钟故障后的降落。"""
import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from px4_msgs.msg import VehicleStatus
from sensor_msgs.msg import PointCloud2
from nav_msgs.msg import Odometry
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['lidar','planner','clock'],required=True)
    args=parser.parse_args()
    rclpy.init();node=Node('stage3_fault_check');state=dict(status='',vehicle=None,clouds=0,propagated=0,propagated_at=0.)
    use_lio=os.environ.get('STAGE3_LOCALIZATION')=='fastlio'
    persistent=use_lio and args.case=='lidar'
    if use_lio:
        def propagated(msg):
            state['propagated']+=1;state['propagated_at']=time.monotonic()
        node.create_subscription(Odometry,'/stage3/lio/odom_propagated',propagated,qos_profile_sensor_data)
    node.create_subscription(String,'/stage3/uav1/status',lambda m:state.update(status=m.data),10)
    node.create_subscription(VehicleStatus,'/fmu/out/vehicle_status_v4',lambda m:state.update(vehicle=m),qos_profile_sensor_data)
    node.create_subscription(PointCloud2,'/cloud_registered',lambda m:state.update(clouds=state['clouds']+1),qos_profile_sensor_data)
    command=node.create_publisher(String,'/stage3/uav1/command',10)
    goal=node.create_publisher(PoseStamped,'/stage3/uav1/goal',10)
    report=dict(passed=False,case=args.case,persistent_lidar_loss=persistent,
                localization=os.environ.get('STAGE3_LOCALIZATION','px4'),
                wall_landmarks=os.environ.get('STAGE3_WALL_LANDMARKS')=='true',
                speed_mps=float(os.environ.get('STAGE3_SPEED','2')));pid=None;paused=False;attempted=False

    def wait(predicate,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            rclpy.spin_once(node,timeout_sec=.02)
            if predicate():return
        raise RuntimeError('Timeout: '+state['status'])

    def pause(value):
        result=subprocess.run(['gz','service','-s','/world/corridor/control','--reqtype','gz.msgs.WorldControl',
                        '--reptype','gz.msgs.Boolean','--timeout','2000','--req','pause: '+str(value).lower()],
                        check=True,capture_output=True,text=True,timeout=5)
        if 'data: true' not in result.stdout:raise RuntimeError('Gazebo pause service not acknowledged: '+result.stdout+result.stderr)

    try:
        wait(lambda:state['vehicle'] is not None and state['status'].startswith('idle: local_ready') and state['clouds']>=20 and (not use_lio or state['propagated']>=20) and command.get_subscription_count()>0,60)
        settle_until=time.monotonic()+30
        wait(lambda:time.monotonic()>=settle_until,35)
        if state['vehicle'].arming_state==state['vehicle'].ARMING_STATE_ARMED:raise RuntimeError('Requires fresh Disarmed run')
        attempted=True;command.publish(String(data='takeoff'))
        wait(lambda:state['status'].startswith('hover: hover_ready'),45)
        msg=PoseStamped();msg.header.frame_id='world';msg.pose.orientation.w=1.;msg.pose.position.y=5.;msg.pose.position.z=1.95
        goal.publish(msg);wait(lambda:state['status'].startswith('track:'),15)
        motion_until=time.monotonic()+1.
        wait(lambda:time.monotonic()>=motion_until,3)
        started=time.monotonic()
        if args.case=='clock':
            paused=True;pause(True)
        else:
            suffix=('/stage3_lidar/timed_lidar' if os.environ.get('STAGE3_LOCALIZATION')=='fastlio' else '/stage3_lidar/prefilter') if args.case=='lidar' else '/super_planner/fsm_node'
            matches=[]
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():continue
                try:
                    executable=(entry/'cmdline').read_bytes().split(b'\0')[0].decode()
                    if executable.startswith('/super_ws/install') and executable.endswith(suffix):matches.append(int(entry.name))
                except (OSError,UnicodeError):pass
            if len(matches)!=1:raise RuntimeError('Expected one task process: '+str(matches))
            pid=matches[0];os.kill(pid,signal.SIGSTOP)
        report['injection_acknowledged']=True
        wait(lambda:state['status'].startswith('land:'),3)
        report['response_s']=time.monotonic()-started;report['failure_status']=state['status']
        if args.case=='clock':pause(False);paused=False
        # LIO case keeps the LiDAR stopped through the entire landing, so the
        # FCU barometer fallback is exercised without restored vision aiding.
        if pid is not None and not persistent:os.kill(pid,signal.SIGCONT);pid=None
        wait(lambda:state['vehicle'].arming_state!=state['vehicle'].ARMING_STATE_ARMED,60)
        report['landing_disarmed']=True
        if persistent:
            report['lidar_stopped_until_disarmed']=True
            report['propagation_silence_s']=time.monotonic()-state['propagated_at']
            report['propagation_stopped']=report['propagation_silence_s']>.5
        with urlopen('http://127.0.0.1:8096/state',timeout=2) as response:truth=json.load(response)
        report['contact_count']=len(truth['contacts'])
        report['landing_height_m']=truth['pose'][2] if truth['pose'] is not None else None
        # Pausing physics stops clock, odometry and lidar together. The first
        # freshness watchdog to expire depends on their latest sample times.
        expected=('state or clock timeout','planner or lidar timeout') if args.case=='clock' or persistent else ('planner or lidar timeout',)
        report['passed']=(any(reason in report['failure_status'] for reason in expected) and report['response_s']<3
                          and not report['contact_count'] and report['landing_height_m'] is not None
                          and report['landing_height_m']<.4 and time.monotonic()-truth['pose_at']<.5
                          and (not persistent or report.get('propagation_stopped',False)))
    except Exception as exc:report['error']=str(exc)
    finally:
        if paused:pause(False)
        if pid is not None:os.kill(pid,signal.SIGCONT)
        if attempted and not report.get('landing_disarmed'):
            command.publish(String(data='land'))
            try:
                wait(lambda:state['vehicle'].arming_state!=state['vehicle'].ARMING_STATE_ARMED,60)
                report['landing_disarmed']=True
            except Exception as exc:report['landing_error']=str(exc)
        out=Path('/tmp/stage3-corridor');out.mkdir(exist_ok=True)
        (out/f'fault-{args.case}.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2));node.destroy_node();rclpy.try_shutdown()
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
