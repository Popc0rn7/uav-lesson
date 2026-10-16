#!/usr/bin/env python3
"""Docker 2：只读链路检查或显式请求任务；报告写入本次运行目录。"""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import signal
import shutil
import sys
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import String
from rosgraph_msgs.msg import Clock
from px4_msgs.msg import VehicleStatus
from mars_quadrotor_msgs.msg import PositionCommand
from rpc_client import rpc
from task_config import load_task
from dashboard import Dashboard,previous_summary



class Probe(Node):
    def __init__(self, dashboard=None, telemetry_only=False):
        super().__init__('airsim_stack_verifier')
        self.dashboard=dashboard
        self.telemetry_only=telemetry_only
        self.count = Counter()
        self.latest = {}
        self.received = {}
        self.records = []
        self.references = []
        self.collision = False
        self.baseline_collision = None
        self.contacts = []
        self.create_subscription(Clock, '/clock', lambda m: self.save('clock', m), 10)
        self.create_subscription(Odometry, '/lidar_slam/odom', lambda m: self.save('odom', m), 20)
        if not telemetry_only:
            for topic, key in [('/cloud_registered','cloud'), ('/rog_map/occ','map'), ('/rog_map/inf_occ','inflated')]:
                self.create_subscription(PointCloud2, topic, lambda m, k=key: self.save(k,m), qos_profile_sensor_data)
        for topic, key in [('/stage3/uav1/status','control'),('/stage3/uav1/task_status','task'),('/stage3/uav1/sensors','sensors')]:
            self.create_subscription(String, topic, lambda m, k=key: self.save(k,m), 10)
        self.create_subscription(VehicleStatus, '/fmu/out/vehicle_status_v4', lambda m: self.save('vehicle',m), qos_profile_sensor_data)
        self.create_subscription(PositionCommand, '/planning/pos_cmd', lambda m: self.save('cmd',m), qos_profile_sensor_data)
        self.create_subscription(PositionCommand, '/stage3/uav1/reference', lambda m: self.save('sent',m), qos_profile_sensor_data)
        self.request = None if telemetry_only else self.create_publisher(String, '/stage3/uav1/mission', 10)

    def save(self, key, msg):
        self.count[key] += 1
        self.latest[key] = msg
        self.received[key] = time.monotonic()
        if self.dashboard:
            if key=='clock':self.dashboard.clock(msg.clock.sec+msg.clock.nanosec*1e-9,self.received[key])
            elif key=='sent':self.dashboard.reference(msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,[msg.position.x,msg.position.y,msg.position.z])
            elif key=='odom':
                p,v=msg.pose.pose.position,msg.twist.twist.linear
                tracking=(self.latest.get('control',String()).data.startswith('track:') and self.received[key]-self.received.get('control',0)<1.5)
                self.dashboard.odometry(msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,[p.x,p.y,p.z],[v.x,v.y,v.z],tracking)
        if key in ('cmd','sent') and not self.telemetry_only:
            stamp = msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
            clock = self.latest.get('clock')
            received_sim = clock.clock.sec+clock.clock.nanosec*1e-9 if clock else None
            self.references.append(dict(kind=key, sim_s=stamp, received_wall_s=time.monotonic(),
                                        received_sim_s=received_sim,
                                        p=[msg.position.x,msg.position.y,msg.position.z],
                                        v=[msg.velocity.x,msg.velocity.y,msg.velocity.z],
                                        a=[msg.acceleration.x,msg.acceleration.y,msg.acceleration.z],
                                        trajectory_flag=int(msg.trajectory_flag)))

    def display(self,task,force=False):
        if self.dashboard is None:return
        wall=time.monotonic()
        snapshot=dict(configured_speed=task['speed_m_s'],ages={k:wall-v for k,v in self.received.items()},
                      control=self.latest.get('control',String()).data,task=self.latest.get('task',String()).data)
        if 'odom' in self.latest:
            msg=self.latest['odom'];p,v=msg.pose.pose.position,msg.twist.twist.linear
            snapshot['odom']=dict(stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,p=[p.x,p.y,p.z],v=[v.x,v.y,v.z])
        if 'sent' in self.latest:
            v=self.latest['sent'].velocity;snapshot['reference']=dict(v=[v.x,v.y,v.z])
        vehicle=self.latest.get('vehicle')
        if vehicle:
            modes={'NAVIGATION_STATE_OFFBOARD':'Offboard','NAVIGATION_STATE_AUTO_LAND':'Land',
                   'NAVIGATION_STATE_AUTO_LOITER':'Hold','NAVIGATION_STATE_POSCTL':'Position'}
            mode=next((name for key,name in modes.items() if getattr(vehicle,key,None)==vehicle.nav_state),str(vehicle.nav_state))
            snapshot['vehicle']=('Armed' if vehicle.arming_state==VehicleStatus.ARMING_STATE_ARMED else 'Disarmed')+' / '+mode
        self.dashboard.render(snapshot,wall,force)

    def healthy(self):
        wall = time.monotonic()
        return all(self.count[k] >= 3 and wall-self.received.get(k,0) < (.8 if k in ('map','inflated') else .5)
                   for k in ('clock','odom','cloud','vehicle','control','map','inflated')) and all(
                       self.latest[k].width > 0 for k in ('cloud','map','inflated'))

    def poll_collision(self):
        control = self.latest.get('control', String()).data
        if control.startswith('land:') or (self.baseline_collision is not None and control.startswith('idle:')):
            return
        data = rpc('simGetCollisionInfo', 'PX4', timeout=.3)
        stamp = data['time_stamp']
        if self.baseline_collision is None:
            self.baseline_collision = stamp
        elif data['has_collided'] and stamp != self.baseline_collision:
            self.contacts.append(dict(data=data))
            self.baseline_collision = stamp
            self.collision = True

    def record(self):
        if 'odom' not in self.latest:
            return
        msg = self.latest['odom']
        p, v = msg.pose.pose.position, msg.twist.twist.linear
        stamp = msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
        row = dict(sim_s=stamp, p=[p.x,p.y,p.z], v=[v.x,v.y,v.z],
                   wall_s=time.monotonic(),
                   control=self.latest.get('control', String()).data,
                   task=self.latest.get('task', String()).data)
        if 'clock' in self.latest:
            c = self.latest['clock'].clock
            row['odom_age_s'] = c.sec+c.nanosec*1e-9-stamp
        if 'cmd' in self.latest:
            cmd = self.latest['cmd']
            row['reference_sim_s'] = cmd.header.stamp.sec+cmd.header.stamp.nanosec*1e-9
            row['reference'] = [cmd.position.x,cmd.position.y,cmd.position.z]
            row['tracking_error_m'] = math.dist(row['p'],row['reference'])
        self.records.append(row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect','fly','fault','dashboard'])
    parser.add_argument('--case', choices=['lidar','planner','clock'])
    parser.add_argument('--dashboard',choices=['auto','ansi','plain','off'],default='auto')
    parser.add_argument('--dashboard-width',type=int,default=shutil.get_terminal_size((88,24)).columns)
    parser.add_argument('--seconds',type=float,default=0,help='dashboard：0表示持续显示，Ctrl+C只退出观察')
    parser.add_argument('--stop-file',type=Path,help='dashboard：由管理器写入的独立观察退出标记')
    args = parser.parse_args()
    if args.action == 'fault' and not args.case:
        parser.error('fault 需要 --case')
    task = load_task('/run/airsim/task.json')
    if not math.isfinite(args.seconds) or args.seconds<0:parser.error('seconds 必须为有限非负数')
    mode=args.dashboard if args.dashboard!='auto' else ('ansi' if sys.stdout.isatty() and os.environ.get('TERM')!='dumb' else 'plain')
    previous=None
    if args.action=='dashboard':
        reports=[p for p in Path('/run/airsim').glob('fly-task-*.json') if '.review.' not in p.name and '.latency.' not in p.name]
        if reports:
            previous=previous_summary(json.loads(max(reports,key=lambda p:p.stat().st_mtime_ns).read_text()))
    ui=Dashboard(mode,args.dashboard_width,previous=previous) if args.action!='inspect' else None
    rclpy.init()
    node = Probe(ui,telemetry_only=args.action=='dashboard')
    if args.action=='dashboard':
        end=time.monotonic()+args.seconds if args.seconds else math.inf
        try:
            while time.monotonic()<end and not (args.stop_file and args.stop_file.exists()):
                rclpy.spin_once(node,timeout_sec=.05);node.display(task)
        except KeyboardInterrupt:pass
        finally:
            node.display(task,force=True);ui.close();node.destroy_node();rclpy.try_shutdown()
        return
    started = time.monotonic()
    success = False
    reason = ''
    requested = False
    stopped_pid = None
    injected = None
    fault_reason = None
    last_collision = last_record = 0.
    path = Path('/run/airsim') / f'{args.action}-{args.case or "task"}-{time.time_ns()}.json'
    try:
        deadline = started+25
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
            node.display(task)
            if node.healthy() and node.latest['control'].data.startswith('idle: local_ready'):
                break
        else:
            raise RuntimeError('静止链路未就绪：' + str(dict(node.count)) + '; ' +
                               node.latest.get('sensors',String()).data + '; ' + node.latest.get('control',String()).data)
        if args.action == 'inspect':
            success, reason = True, 'clock/DDS/GNSS/cloud/ROG ready; disarmed'
        else:
            node.poll_collision()
            request_at = time.monotonic()
            task_count_at_request = node.count['task']
            acknowledged = False
            node.request.publish(String(data='start'))
            requested = True
            deadline = time.monotonic()+task['mission_timeout_s']*3+60
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=.02)
                wall = time.monotonic()
                node.display(task)
                if wall-last_record > .05:
                    node.record()
                    last_record = wall
                if wall-last_collision > .2:
                    node.poll_collision()
                    last_collision = wall
                status = node.latest.get('task',String()).data
                control = node.latest.get('control',String()).data
                if not acknowledged:
                    acknowledged = (node.count['task'] > task_count_at_request and
                                    status.startswith(('takeoff;', 'hold;', 'route;')))
                    if not acknowledged:
                        if wall-request_at > 3:
                            raise RuntimeError('任务启动未确认；'+status)
                        continue
                if args.action == 'fault' and stopped_pid is None and control.startswith('track:'):
                    needle = {'lidar':'/lesson/stage3/super/airsim/lidar_bridge.py',
                              'clock':'/lesson/stage3/super/airsim/clock_bridge.py',
                              'planner':'/super_ws/install/super_planner/lib/super_planner/fsm_node'}[args.case]
                    candidates = []
                    for proc in Path('/proc').iterdir():
                        if not proc.name.isdigit():
                            continue
                        try:
                            argv = (proc/'cmdline').read_bytes().split(b'\0')
                            if needle.encode() in argv:
                                candidates.append(int(proc.name))
                        except OSError:
                            pass
                    if len(candidates) != 1:
                        raise RuntimeError('无法唯一识别本容器的故障节点：' + str(candidates))
                    stopped_pid = candidates[0]
                    os.kill(stopped_pid, signal.SIGSTOP)
                    injected = wall
                if injected is not None:
                    expected = {'lidar':'lidar cloud timeout', 'planner':'SUPER command timeout',
                                'clock':'state or clock timeout'}[args.case]
                    if control.startswith('land:') and expected in control:
                        fault_reason = control
                    vehicle = node.latest.get('vehicle')
                    if fault_reason and vehicle and vehicle.arming_state != VehicleStatus.ARMING_STATE_ARMED:
                        success, reason = True, fault_reason + '; landed/disarmed'
                        break
                    if wall-injected > 45:
                        raise RuntimeError('故障未在 45 秒内触发预期降落并解除解锁；'+control)
                if node.collision:
                    raise RuntimeError('AirSim 报告新碰撞')
                if status.startswith('failed:') and injected is None:
                    raise RuntimeError(status)
                if status.startswith('complete:') and args.action != 'fault':
                    success, reason = True, status
                    break
            else:
                raise RuntimeError('任务墙钟等待超时')
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) or 'interrupted'
    finally:
        if stopped_pid is not None:
            try:
                os.kill(stopped_pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        if requested and not success:
            node.request.publish(String(data='land'))
            deadline = time.monotonic()+45
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=.05)
                node.display(task)
                vehicle = node.latest.get('vehicle')
                if vehicle and vehicle.arming_state != VehicleStatus.ARMING_STATE_ARMED:
                    break
        summary = dict(action=args.action, success=success, reason=reason, task=task['name'],
                       fault_case=args.case, fault_reason=fault_reason,
                       wall_seconds=time.monotonic()-started, counts=dict(node.count), collision=node.collision,
                       contacts=node.contacts,
                       status={k:node.latest.get(k,String()).data for k in ('control','task','sensors')},
                       cloud_points=node.latest['cloud'].width if 'cloud' in node.latest else 0,
                       map_points=node.latest['map'].width if 'map' in node.latest else 0,
                       inflated_points=node.latest['inflated'].width if 'inflated' in node.latest else 0)
        vehicle = node.latest.get('vehicle')
        summary['final_arming_state'] = int(vehicle.arming_state) if vehicle else None
        summary['final_nav_state'] = int(vehicle.nav_state) if vehicle else None
        summary['disarmed_confirmed'] = bool(vehicle and time.monotonic()-node.received.get('vehicle',0)<1.5
                                             and vehicle.arming_state != VehicleStatus.ARMING_STATE_ARMED)
        summary['cleanup_landing_unconfirmed'] = bool(requested and not success and not summary['disarmed_confirmed'])
        if node.records:
            summary['max_speed_m_s'] = max(math.dist(r['v'],[0,0,0]) for r in node.records)
            errors = [r['tracking_error_m'] for r in node.records if 'tracking_error_m' in r and r['control'].startswith('track:')]
            summary['max_tracking_error_m'] = max(errors, default=None)
            if len(node.records) > 1 and node.records[-1]['wall_s'] > node.records[0]['wall_s']:
                summary['simulation_rate'] = (node.records[-1]['sim_s']-node.records[0]['sim_s'])/(node.records[-1]['wall_s']-node.records[0]['wall_s'])
        if ui:
            summary['dashboard_window']=ui.metrics()
            node.display(task,force=True);ui.close()
        path.write_text(json.dumps(dict(summary=summary, records=node.records, references=node.references), indent=2))
        print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
        print('报告：' + str(path), flush=True)
        node.destroy_node()
        rclpy.try_shutdown()
    if not success:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
