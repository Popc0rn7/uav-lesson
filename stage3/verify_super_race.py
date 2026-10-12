#!/usr/bin/env python3
"""Docker：执行中等难度 100 m corridor 往返，记录轨迹与点云净空。"""
import json
import hashlib
import math
import time
from pathlib import Path

import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped
from mars_quadrotor_msgs.msg import PositionCommand
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data
from scipy.spatial import cKDTree
from sensor_msgs.msg import PointCloud2


def main():
    rclpy.init()
    node = rclpy.create_node('super_corridor_verifier')
    state = dict(odom=0, clouds=0, commands=0, position=None, velocity=None,
                 last_odom=0., last_cloud=0., min_clearance_m=None, peak_speed_mps=0.,
                 path_length_m=0., max_abs_x_m=0., min_z_m=None, max_z_m=None)
    pcd = Path('/super_ws/src/SUPER/mars_uav_sim/perfect_drone_sim/pcd/corridor_poles_shrubs_medium.pcd')
    with pcd.open() as stream:
        for line in stream:
            if line.strip() == 'DATA ascii':
                break
        else:
            raise RuntimeError('验收要求 ASCII PCD')
        points = np.loadtxt(stream, usecols=(0, 1, 2))
    tree = cKDTree(points)
    state['map_points'] = len(points)
    state['pcd_sha256'] = hashlib.sha256(pcd.read_bytes()).hexdigest()
    previous = None
    trajectory = []

    def odom(msg):
        nonlocal previous
        p, v = msg.pose.pose.position, msg.twist.twist.linear
        pos = np.array([p.x, p.y, p.z])
        vel = [v.x, v.y, v.z]
        if not np.isfinite(pos).all() or not np.isfinite(vel).all():
            raise RuntimeError('非有限里程计')
        state.update(position=pos.tolist(), velocity=vel, last_odom=time.monotonic())
        state['odom'] += 1
        state['peak_speed_mps'] = max(state['peak_speed_mps'], math.dist(vel, [0, 0, 0]))
        state['max_abs_x_m'] = max(state['max_abs_x_m'], abs(p.x))
        state['min_z_m'] = p.z if state['min_z_m'] is None else min(state['min_z_m'], p.z)
        state['max_z_m'] = p.z if state['max_z_m'] is None else max(state['max_z_m'], p.z)
        if previous is not None:
            distance = float(np.linalg.norm(pos - previous))
            state['path_length_m'] += distance
            samples = previous + np.linspace(0, 1, max(2, math.ceil(distance / .05) + 1))[:, None] * (pos - previous)
        else:
            samples = pos[None, :]
        previous = pos
        if tree is not None:
            clearance = float(np.min(tree.query(samples)[0]))
            old = state['min_clearance_m']
            state['min_clearance_m'] = clearance if old is None else min(old, clearance)
        if state['odom'] % 10 == 0:
            trajectory.append([time.monotonic(), *pos.tolist(), *vel])

    def cloud(msg):
        if msg.width * msg.height:
            state['clouds'] += 1
            state['last_cloud'] = time.monotonic()

    def command(msg):
        state['commands'] += 1

    subscriptions = [
        node.create_subscription(Odometry, '/lidar_slam/odom', odom, qos_profile_sensor_data),
        node.create_subscription(PointCloud2, '/cloud_registered', cloud, qos_profile_sensor_data),
        node.create_subscription(PositionCommand, '/planning/pos_cmd', command, qos_profile_sensor_data),
    ]
    pub = node.create_publisher(PoseStamped, '/planning/click_goal', 10)
    started = time.monotonic()
    result = {'passed': False, 'scene': 'corridor_medium', 'speed_limit_mps': 10.,
              'robot_radius_m': .2, 'legs': []}
    try:
        while time.monotonic() - started < 60:
            rclpy.spin_once(node, timeout_sec=.1)
            if state['clouds'] >= 100 and tree is not None and pub.get_subscription_count() and state['odom'] >= 100:
                break
        else:
            raise RuntimeError('60 秒内未收到地图、点云、里程计或目标订阅')
        if math.dist(state['position'], [0, -50, 1.5]) > .5:
            raise RuntimeError('初始位置不匹配；请 down/up 后重新验收')
        for goal in ([0., 50., 1.5], [0., -50., 1.5]):
            msg = PoseStamped()
            msg.header.frame_id = 'world'
            msg.header.stamp = node.get_clock().now().to_msg()
            msg.pose.position.x, msg.pose.position.y, msg.pose.position.z = goal
            msg.pose.orientation.w = 1.
            pub.publish(msg)
            leg_start = time.monotonic()
            stable_since = None
            before_commands = state['commands']
            while time.monotonic() - leg_start < 120:
                rclpy.spin_once(node, timeout_sec=.05)
                now = time.monotonic()
                if now - state['last_odom'] > 1. or now - state['last_cloud'] > 2.:
                    raise RuntimeError('里程计或点云超时')
                if state['min_clearance_m'] is not None and state['min_clearance_m'] < .2:
                    raise RuntimeError('轨迹进入 0.2 m 点云净空门限')
                reached = math.dist(state['position'], goal) < .3 and math.dist(state['velocity'], [0, 0, 0]) < .5
                stable_since = (stable_since or now) if reached else None
                if stable_since and now - stable_since > 1.:
                    if state['commands'] <= before_commands:
                        raise RuntimeError('未收到规划指令')
                    result['legs'].append({'goal': goal, 'elapsed_s': now - leg_start,
                                           'final_error_m': math.dist(state['position'], goal)})
                    print(json.dumps(result['legs'][-1]), flush=True)
                    break
            else:
                raise RuntimeError('120 秒内未完成赛段')
        result['passed'] = True
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        result.update(state)
        result['total_elapsed_s'] = time.monotonic() - started
        Path('/tmp/super-race/result.json').write_text(json.dumps(result, indent=2) + '\n')
        np.savetxt('/tmp/super-race/trajectory.csv', np.asarray(trajectory), delimiter=',',
                   header='monotonic_s,x,y,z,vx,vy,vz')
        print(json.dumps(result, indent=2), flush=True)
        node.destroy_node()
        rclpy.shutdown()
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
