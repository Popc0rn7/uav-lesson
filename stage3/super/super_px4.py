#!/usr/bin/env python3
"""ROS Docker：SUPER ENU 命令 → PX4 NED；只用于单机 SITL。"""
import math
from pathlib import Path as FilePath
import time
import rclpy
from rclpy.node import Node
from rclpy.clock import Clock, ClockType
from rclpy.qos import qos_profile_sensor_data
from px4_msgs.msg import VehicleOdometry, VehicleStatus, VehicleCommand, OffboardControlMode, TrajectorySetpoint, FailsafeFlags
from nav_msgs.msg import Odometry
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String, Float64
from mars_quadrotor_msgs.msg import PositionCommand


def ned(v):
    return [float(v[1]), float(v[0]), -float(v[2])]


class Bridge(Node):
    def __init__(self):
        super().__init__('super_px4_bridge')
        self.declare_parameter('corridor', False)
        self.declare_parameter('speed', 2.0)
        task_path = self.declare_parameter('airsim_task_config', '').value
        self.airsim_task = None
        self.land_request = FilePath(task_path).parent/'land.request.json' if task_path else None
        if task_path:
            from airsim.task_config import load_task
            self.airsim_task = load_task(task_path)
        self.use_lio=self.declare_parameter('use_lio',False).value
        self.height_required=self.declare_parameter('lidar_height_required',True).value
        self.corridor = self.get_parameter('corridor').value
        self.speed_limit = self.get_parameter('speed').value + 1.0
        self.takeoff_height = 1.95 if self.corridor else 2.0
        self.origin = None if self.corridor else [0.,0.,0.]
        if self.airsim_task:
            self.origin = None
            self.takeoff_height = self.airsim_task['takeoff_height_m']
            self.speed_limit = self.airsim_task['speed_m_s'] + 1.0
        self.p = self.v = self.vehicle = self.hold = self.sample = None
        self.odom_at = self.status_at = self.sample_at = self.cloud_at = 0.
        self.height_at=0.
        self.failsafe=None;self.flags_at=0.
        self.create_subscription(Float64,'/stage3/uav1/lidar_height',self.height,10)
        self.create_subscription(FailsafeFlags,'/fmu/out/failsafe_flags',self.health,qos_profile_sensor_data)
        self.mode = 'idle'
        self.clock_last = None
        self.clock_at = time.monotonic()
        self.reset = None
        self.started = self.last_request = 0.
        self.stable = None
        self.goal_stable = None
        self.yaw = 0.
        self.goal = None
        self.reason = 'disarmed; send takeoff'
        self.create_subscription(VehicleOdometry, '/fmu/out/vehicle_odometry', self.odom, qos_profile_sensor_data)
        self.create_subscription(VehicleStatus, '/fmu/out/vehicle_status_v4', self.status, qos_profile_sensor_data)
        self.create_subscription(PositionCommand, '/planning/pos_cmd', self.accept, qos_profile_sensor_data)
        self.create_subscription(String, '/stage3/uav1/command', self.command, 10)
        self.create_subscription(PoseStamped, '/stage3/uav1/goal', self.goal_received, 10)
        from sensor_msgs.msg import PointCloud2
        self.create_subscription(PointCloud2, '/cloud_registered', self.cloud, qos_profile_sensor_data)
        if self.use_lio:self.create_subscription(Odometry,'/lidar_slam/odom',self.lio_odom,20)
        self.odom_pub = self.create_publisher(Odometry, '/lidar_slam/odom', 10)
        self.goal_pub = self.create_publisher(PoseStamped, '/goal_pose', 10)
        self.status_pub = self.create_publisher(String, '/stage3/uav1/status', 10)
        self.control_pub = self.create_publisher(OffboardControlMode, '/fmu/in/offboard_control_mode', 10)
        self.sp_pub = self.create_publisher(TrajectorySetpoint, '/fmu/in/trajectory_setpoint', 10)
        self.reference_pub=self.create_publisher(PositionCommand,'/stage3/uav1/reference',qos_profile_sensor_data)
        suffix = f'_v{VehicleCommand.MESSAGE_VERSION}' if VehicleCommand.MESSAGE_VERSION else ''
        self.command_pub = self.create_publisher(VehicleCommand, '/fmu/in/vehicle_command'+suffix, 10)
        from tf2_ros import TransformBroadcaster
        from nav_msgs.msg import Path
        from visualization_msgs.msg import Marker
        self.tf = TransformBroadcaster(self)
        self.path = Path(); self.path.header.frame_id='world'
        self.path_pub = self.create_publisher(Path, '/stage3/uav1/path', 10)
        self.robot_pub = self.create_publisher(Marker, '/stage3/uav1/robot', 10)
        self.create_timer(.02, self.tick, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def cloud(self, msg):
        age = self.get_clock().now().nanoseconds/1e9-(msg.header.stamp.sec+msg.header.stamp.nanosec/1e9)
        if msg.header.frame_id == 'world' and -.05 <= age <= .5 and msg.width:
            self.cloud_at = time.monotonic()

    def status(self, msg):
        self.vehicle = msg
        self.status_at = time.monotonic()
        if self.mode == 'land' and msg.arming_state != msg.ARMING_STATE_ARMED:
            self.mode, self.reason = 'idle', 'disarmed'

    def odom(self, msg):
        if msg.pose_frame != msg.POSE_FRAME_NED or msg.velocity_frame != msg.VELOCITY_FRAME_NED:
            return
        if not all(math.isfinite(x) for x in list(msg.position)+list(msg.velocity)+list(msg.q)):
            return
        if self.reset is not None and msg.reset_counter != self.reset and self.mode not in ('idle','land'):
            self.land('estimator reset')
        self.reset = msg.reset_counter
        raw_p = ned(msg.position)
        if not self.use_lio:self.v=ned(msg.velocity)
        if self.origin is None:
            if self.vehicle is None or not self.ready() or self.vehicle.arming_state==self.vehicle.ARMING_STATE_ARMED:
                return
            # Anchor the course frame using PX4 alone and the known resting base height.
            # Gazebo truth is never an input to the control bridge.
            self.origin=[raw_p[0],raw_p[1],raw_p[2]-(0. if self.airsim_task else .25)]
        elif self.corridor and self.mode == 'idle' and self.vehicle is not None and self.ready() and self.vehicle.arming_state != self.vehicle.ARMING_STATE_ARMED:
            self.origin=[raw_p[0],raw_p[1],raw_p[2]-.25]
        if self.use_lio:return
        self.p=[raw_p[i]-self.origin[i] for i in range(3)]
        self.odom_at = time.monotonic()
        w,x,y,z = map(float,msg.q)
        if self.mode == 'idle':
            self.yaw = math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
        out = Odometry()
        sample = int(msg.timestamp_sample)
        out.header.stamp.sec, out.header.stamp.nanosec = sample // 1000000, (sample % 1000000)*1000
        out.header.frame_id, out.child_frame_id = 'world', 'base_link'
        out.pose.pose.position.x,out.pose.pose.position.y,out.pose.pose.position.z = self.p
        h = math.sqrt(.5)
        out.pose.pose.orientation.w,out.pose.pose.orientation.x = h*(w+z),h*(x+y)
        out.pose.pose.orientation.y,out.pose.pose.orientation.z = h*(x-y),h*(w-z)
        # Child-frame FLU velocity, rather than world-frame ENU velocity.
        rotation = ((1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y)),
                    (2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x)),
                    (2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)))
        body = [sum(rotation[j][i]*msg.velocity[j] for j in range(3)) for i in range(3)]
        # SUPER / ROG-Map consume world-frame velocity (same convention as perfect_drone_sim).
        out.twist.twist.linear.x,out.twist.twist.linear.y,out.twist.twist.linear.z = self.v
        self.odom_pub.publish(out)
        self.visualize(out)

    def lio_odom(self,out):
        if out.header.frame_id!='world':return
        stamp=out.header.stamp.sec+out.header.stamp.nanosec*1e-9
        if not -.05<=self.get_clock().now().nanoseconds*1e-9-stamp<=.3:return
        p=out.pose.pose.position;v=out.twist.twist.linear
        values=[p.x,p.y,p.z,v.x,v.y,v.z]
        if not all(math.isfinite(x) for x in values):return
        self.p=values[:3];self.v=values[3:];self.odom_at=time.monotonic()
        if self.mode=='idle':
            q=out.pose.pose.orientation
            yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
            self.yaw=math.pi/2-yaw
        self.visualize(out)

    def visualize(self,out):
        wall=time.monotonic()
        if wall-getattr(self,'visual_at',0.)<1/30:return
        self.visual_at=wall
        from geometry_msgs.msg import TransformStamped
        from visualization_msgs.msg import Marker
        transform=TransformStamped();transform.header=out.header;transform.child_frame_id='base_link'
        transform.transform.translation.x,transform.transform.translation.y,transform.transform.translation.z=self.p
        transform.transform.rotation=out.pose.pose.orientation;self.tf.sendTransform(transform)
        if len(self.path.poses)==0 or math.dist(self.p,[self.path.poses[-1].pose.position.x,self.path.poses[-1].pose.position.y,self.path.poses[-1].pose.position.z])>.1:
            pose=PoseStamped();pose.header=out.header;pose.pose=out.pose.pose
            self.path.poses.append(pose);self.path.poses=self.path.poses[-10000:]
            self.path.header.stamp=out.header.stamp;self.path_pub.publish(self.path)
        robot=Marker();robot.header=out.header;robot.ns='uav1';robot.id=0;robot.type=Marker.CUBE;robot.action=Marker.ADD
        robot.pose=out.pose.pose;robot.scale.x=robot.scale.y=.25;robot.scale.z=.08
        robot.color.r=1.;robot.color.g=.7;robot.color.b=.1;robot.color.a=1.;self.robot_pub.publish(robot)
        from geometry_msgs.msg import Point
        arms=Marker();arms.header=out.header;arms.ns='uav1';arms.id=1;arms.type=Marker.LINE_LIST;arms.action=Marker.ADD
        arms.pose=out.pose.pose;arms.scale.x=.035;arms.color.r=arms.color.g=arms.color.b=arms.color.a=1.
        arms.points=[Point(x=x,y=y,z=0.) for x,y in ((-.25,-.25),(.25,.25),(-.25,.25),(.25,-.25))]
        self.robot_pub.publish(arms)

    def send(self, command, p1=0., p2=0.):
        out = VehicleCommand()
        out.timestamp = self.get_clock().now().nanoseconds//1000
        out.command,out.param1,out.param2 = command,float(p1),float(p2)
        out.target_system=out.target_component=out.source_system=out.source_component=1
        out.from_external=True
        self.command_pub.publish(out)

    def height(self,msg):
        if math.isfinite(msg.data) and .1<msg.data<4.5:self.height_at=time.monotonic()

    def health(self,msg):
        self.failsafe=msg;self.flags_at=time.monotonic()

    def ready(self):
        if not (self.corridor or self.airsim_task):return self.vehicle is not None and self.vehicle.pre_flight_checks_pass
        if self.failsafe is None or time.monotonic()-self.flags_at>1.5:return False
        invalid=('angular_velocity_invalid','attitude_invalid','local_altitude_invalid','local_position_invalid',
                 'local_velocity_invalid','battery_unhealthy','fd_critical_failure','fd_esc_arming_failure',
                 'fd_motor_failure','geofence_breached')
        return not any(getattr(self.failsafe,key) for key in invalid)

    def land(self, reason):
        if self.airsim_task and self.mode == 'land':
            return
        self.mode,self.reason,self.sample,self.goal = 'land',reason,None,None
        self.send(VehicleCommand.VEHICLE_CMD_NAV_LAND)

    def command(self,msg):
        if msg.data == 'land':
            self.land('requested landing')
        elif msg.data == 'takeoff' and self.mode == 'idle' and self.p and self.vehicle and self.origin is not None:
            if self.land_request and self.land_request.exists():
                self.reason='takeoff rejected: operator cancelled this run';return
            if not self.ready():self.reason='takeoff rejected: local estimate unavailable';return
            if self.airsim_task and time.monotonic()-self.cloud_at>.3:
                self.reason='takeoff rejected: stale lidar';return
            if self.corridor and self.height_required and time.monotonic()-self.height_at>.3:
                self.reason='takeoff rejected: stale lidar height';return
            if self.vehicle.arming_state == self.vehicle.ARMING_STATE_ARMED or time.monotonic()-self.odom_at>.5:
                return
            self.hold=[self.p[0],self.p[1],self.takeoff_height]
            self.mode,self.reason,self.started='prestream','takeoff prestream',time.monotonic()
            self.sample=self.goal=None
            self.stable=None

    def goal_received(self,msg):
        p=msg.pose.position
        allowed = ('hover','planning','track') if self.airsim_task else ('hover',)
        if self.mode not in allowed or msg.header.frame_id != 'world' or not all(math.isfinite(x) for x in (p.x,p.y,p.z)):
            return
        bounds = (abs(p.x)<=2.5 and -.5<=p.y<=100.5 and .5<=p.z<=12.0) if self.corridor else (abs(p.x)<=10 and abs(p.y)<=10 and .5<=p.z<=5)
        if self.airsim_task:
            from airsim.task_config import inside
            bounds = inside(self.airsim_task, [p.x,p.y,p.z])
        if not bounds or time.monotonic()-self.cloud_at>.5:
            self.reason='goal rejected: bounds or stale lidar'
            return
        msg.header.stamp=self.get_clock().now().to_msg()
        self.goal=[p.x,p.y,p.z]
        self.goal_stable=None
        if not (self.airsim_task and self.mode == 'track'):
            self.sample=None
            self.mode,self.reason,self.started='planning','waiting for SUPER',time.monotonic()
        self.goal_pub.publish(msg)

    def accept(self,msg):
        if self.mode not in ('planning','track') or msg.header.frame_id!='world':
            return
        p,v,a=[[float(getattr(vector,k)) for k in ('x','y','z')] for vector in (msg.position,msg.velocity,msg.acceleration)]
        age=self.get_clock().now().nanoseconds/1e9-(msg.header.stamp.sec+msg.header.stamp.nanosec/1e9)
        valid=all(math.isfinite(x) for x in p+v+a) and -.05<=age<=.3
        # Preserve the full SUPER trajectory, including vertical feedforward.
        bounds = (abs(p[0])<=2.5 and -1<=p[1]<=101 and .2<=p[2]<=12.0) if self.corridor else (abs(p[0])<=10 and abs(p[1])<=10 and .2<=p[2]<=5)
        if self.airsim_task:
            from airsim.task_config import inside
            bounds = inside(self.airsim_task, p)
        valid=valid and bounds
        valid=valid and math.dist(v,[0,0,0])<=self.speed_limit and math.dist(a,[0,0,0])<=(self.airsim_task['max_acc_m_s2']+.5 if self.airsim_task else 6.)
        valid=valid and self.p is not None and math.dist(p,self.p)<=3.
        if not valid:
            self.land(f'SUPER command rejected: p={p}, v={v}, a={a}, age={age:.4f}, error={math.dist(p,self.p) if self.p else -1:.3f}'); return
        self.sample,self.sample_at=(p,v,a),time.monotonic()
        self.mode,self.reason='track','tracking SUPER'

    def tick(self):
        wall=time.monotonic(); now=self.get_clock().now().nanoseconds/1e9
        active=self.mode in ('prestream','takeoff','hover','planning','track')
        if active and self.land_request and self.land_request.exists():
            self.land('operator requested landing');active=False
        if self.mode=='idle' and (self.corridor or self.airsim_task):
            local_ready=self.ready() and self.p and self.origin is not None and wall-self.odom_at<.3 and wall-self.cloud_at<.3 and (not self.height_required or wall-self.height_at<.3)
            self.reason='local_ready; send takeoff' if local_ready else 'waiting for healthy local estimate and lidar'
            if self.land_request and self.land_request.exists():
                self.reason='operator cancelled this run; down/up required'
        if now!=self.clock_last:
            if self.clock_last is not None and now<self.clock_last and active:
                self.land('simulation reset');active=False
            self.clock_at=wall
        self.clock_last=now
        if active and (wall-self.odom_at>.5 or wall-self.status_at>1.5 or wall-self.clock_at>.5):
            self.land('state or clock timeout');active=False
        if active and self.corridor and self.height_required and wall-self.height_at>.5:
            self.land('lidar height timeout');active=False
        if active and (self.corridor or self.airsim_task) and not self.ready():
            self.land('local estimate unavailable');active=False
        if active and self.mode not in ('prestream','takeoff') and self.vehicle.nav_state!=self.vehicle.NAVIGATION_STATE_OFFBOARD:
            self.land('PX4 left Offboard');active=False
        if self.mode=='prestream' and wall-self.started>2:
            self.mode='takeoff'
        if self.mode=='takeoff':
            if wall-self.started>30:
                self.land('takeoff timeout');active=False
            elif wall-self.last_request>1:
                self.last_request=wall
                self.send(VehicleCommand.VEHICLE_CMD_DO_SET_MODE,1,6)
                self.send(VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM,1)
            if self.p and math.dist(self.p,self.hold)<(.15 if self.corridor else .3) and math.dist(self.v,[0,0,0])<.3:
                self.stable=self.stable or wall
                if wall-self.stable>3:self.mode,self.reason='hover','hover_ready'
            else:self.stable=None
        if self.mode=='planning' and wall-self.started>10:
            self.land('planning timeout');active=False
        if self.mode=='track' and wall-self.sample_at>.5:
            self.land('SUPER command timeout');active=False
        if self.mode=='track' and wall-self.cloud_at>.5:
            self.land('lidar cloud timeout');active=False
        if active and self.airsim_task and wall-self.cloud_at>.5:
            self.land('lidar cloud timeout');active=False
        if self.mode=='track' and self.goal and self.p:
            if math.dist(self.p,self.goal)<.3 and math.dist(self.v,[0.,0.,0.])<.3:
                self.goal_stable=self.goal_stable or wall
                if wall-self.goal_stable>2.:
                    self.hold=list(self.goal)
                    self.mode,self.reason,self.sample,self.goal='hover','goal_reached',None,None
            else:self.goal_stable=None
        if active and self.hold:
            p,v,a=self.sample if self.mode=='track' else (self.hold,[0.,0.,0.],[0.,0.,0.])
            hb=OffboardControlMode();hb.timestamp=int(now*1e6);hb.position=True
            self.control_pub.publish(hb)
            sp=TrajectorySetpoint();sp.timestamp=hb.timestamp
            sp.position,sp.velocity,sp.acceleration=ned([p[i]+self.origin[i] for i in range(3)]),ned(v),ned(a)
            sp.yaw,sp.yawspeed=float(self.yaw),0.
            self.sp_pub.publish(sp)
            reference=PositionCommand();reference.header.stamp=self.get_clock().now().to_msg();reference.header.frame_id='world'
            for vector,values in ((reference.position,p),(reference.velocity,v),(reference.acceleration,a)):
                vector.x,vector.y,vector.z=values
            self.reference_pub.publish(reference)
        self.status_pub.publish(String(data=f'{self.mode}: {self.reason}'))


def main():
    rclpy.init();node=Bridge()
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':main()
