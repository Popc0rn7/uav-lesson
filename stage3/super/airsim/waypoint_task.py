#!/usr/bin/env python3
"""Docker 2：移植交接包航点/carrot 任务，只发目标和任务请求。"""
import time
from pathlib import Path
import numpy as np
import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from task_config import load_task


class Waypoints(Node):
    def __init__(self):
        super().__init__('airsim_waypoint_task')
        task_path = self.declare_parameter('task_config', '').value
        self.task = load_task(task_path)
        self.land_request = Path(task_path).parent/'land.request.json'
        self.command = self.create_publisher(String, '/stage3/uav1/command', 10)
        self.goals = self.create_publisher(PoseStamped, '/stage3/uav1/goal', 10)
        self.status_pub = self.create_publisher(String, '/stage3/uav1/task_status', 10)
        self.create_subscription(String, '/stage3/uav1/mission', self.request, 10)
        self.create_subscription(String, '/stage3/uav1/status', self.status, 10)
        self.create_subscription(Odometry, '/lidar_slam/odom', self.odom, 20)
        self.position = None
        self.velocity = None
        self.control = ''
        self.control_at = self.pose_at = 0.
        self.mode = 'idle'
        self.index = 0
        self.carrot = None
        self.anchor = None
        self.started = self.leg_started = self.hold_started = None
        self.last_clock = None
        self.clock_at = time.monotonic()
        self.create_timer(.1, self.tick, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def status(self, msg):
        self.control = msg.data
        self.control_at = time.monotonic()

    def odom(self, msg):
        p, v = msg.pose.pose.position, msg.twist.twist.linear
        self.position, self.velocity = np.array([p.x, p.y, p.z]), np.array([v.x, v.y, v.z])
        self.pose_at = time.monotonic()

    def request(self, msg):
        if msg.data == 'start' and self.land_request.exists():
            self.mode = 'failed: operator cancelled this run'
            return
        restartable = self.mode == 'idle' or self.mode.startswith(('complete:', 'failed:'))
        if msg.data == 'start' and restartable and self.control.startswith('idle: local_ready'):
            self.mode = 'takeoff'
            self.started = self.get_clock().now().nanoseconds * 1e-9
            self.index = 0
            self.carrot = self.anchor = None
            self.hold_started = self.leg_started = None
            self.command.publish(String(data='takeoff'))
        elif msg.data == 'land':
            self.abort('requested landing')

    def abort(self, reason):
        self.mode = 'failed: ' + reason
        self.command.publish(String(data='land'))

    def target(self, now):
        route = self.task['waypoints_enu_m']
        if self.anchor is None:
            self.anchor = self.position.copy()
        while self.index < len(route)-1:
            wp = np.asarray(route[self.index])
            leg = wp-self.anchor
            length = np.linalg.norm(leg)
            passed = length > 1e-6 and np.dot(self.position-wp, leg/length) > 0
            lateral = np.linalg.norm((self.position-wp) - np.dot(self.position-wp, leg/length)*leg/length) if length > 1e-6 else 0
            reached = np.linalg.norm(wp-self.position) <= self.task['waypoint_tolerance_m'] or (
                passed and lateral <= self.task['waypoint_tolerance_m'])
            if self.task['waypoint_mode'] == 'stop':
                reached = reached and self.control.startswith('hover: goal_reached')
            if reached:
                self.anchor = wp
                self.index += 1
                self.carrot = None
                self.leg_started = now
            else:
                break
        goal = np.asarray(route[self.index])
        distance = np.linalg.norm(goal-self.position)
        if self.task['goal_mode'] == 'direct':
            target = goal
            final_target = True
        else:
            target = self.position + (goal-self.position) * min(1., self.task['carrot_distance_m']/max(distance, 1e-9))
            final_target = distance <= self.task['carrot_distance_m']
        if self.carrot is None or np.linalg.norm(target-self.carrot) >= self.task['carrot_refresh_m'] or (
                final_target and np.linalg.norm(self.carrot-goal) > 1e-6):
            msg = PoseStamped()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = 'world'
            msg.pose.position.x, msg.pose.position.y, msg.pose.position.z = map(float, target)
            msg.pose.orientation.w = 1.
            self.goals.publish(msg)
            self.carrot = target
        if self.index == len(route)-1 and distance <= self.task['goal_tolerance_m'] and np.linalg.norm(self.velocity) < .3:
            self.hold_started = self.hold_started or now
            if now-self.hold_started >= 2.:
                if self.task['finish'] == 'land':
                    self.mode = 'landing'
                    self.command.publish(String(data='land'))
                else:
                    self.mode = 'complete: hover'
        else:
            self.hold_started = None

    def tick(self):
        wall = time.monotonic()
        now = self.get_clock().now().nanoseconds * 1e-9
        active = self.mode in ('takeoff', 'hold', 'route')
        if active and self.land_request.exists():
            self.abort('operator requested landing')
            active = False
        if now != self.last_clock:
            if self.last_clock is not None and now < self.last_clock and active:
                self.abort('simulation reset')
            self.clock_at = wall
        self.last_clock = now
        if active and (wall-self.control_at > 1.5 or wall-self.pose_at > .5 or wall-self.clock_at > .5):
            self.abort('state/clock timeout')
        elif active and self.control.startswith('land:'):
            self.mode = 'failed: ' + self.control
        elif active and self.started is not None and now-self.started > self.task['mission_timeout_s']:
            self.abort('mission timeout')
        elif self.mode == 'takeoff' and self.control.startswith('hover: hover_ready'):
            self.mode, self.hold_started = 'hold', now
        elif self.mode == 'hold' and now-self.hold_started >= self.task['hold_after_takeoff_s']:
            self.mode, self.leg_started, self.hold_started = 'route', now, None
        elif self.mode == 'route':
            if now-self.leg_started > self.task['leg_timeout_s']:
                self.abort('waypoint timeout')
            elif self.position is not None:
                self.target(now)
        elif self.mode == 'landing' and self.control.startswith('idle:'):
            self.mode = 'complete: landed/disarmed'
        self.status_pub.publish(String(data=f'{self.mode}; waypoint={self.index+1}/{len(self.task["waypoints_enu_m"])}'))


def main():
    rclpy.init()
    node = Waypoints()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
