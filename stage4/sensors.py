"""ROS Docker: AirSim cameras and PX4 estimates; truth never feeds control."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import math
from pathlib import Path
import time

from PIL import Image as PILImage
import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from px4_msgs.msg import VehicleOdometry, SensorCombined
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image, CameraInfo, Imu
from geometry_msgs.msg import TransformStamped
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster
from std_msgs.msg import String

from stage3.super.airsim.rpc_client import rpc
from stage4.contracts import PREFIX, enu, enu_flu_quaternion, validate_task
from stage4.evaluation import DEPTH_CAMERAS, depth_proximity


def stamp(seconds):
    from builtin_interfaces.msg import Time
    ns = round(seconds*1e9)
    return Time(sec=ns//1000000000, nanosec=ns%1000000000)


class Sensors(Node):
    def __init__(self, directory=Path('/run/stage4')):
        super().__init__('stage4_sensors')
        self.directory = directory
        self.task = validate_task(json.loads((directory/'task.json').read_text()))
        self.poses = deque(maxlen=1000)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.pose_wall = self.published_wall = 0.
        self.last_stamp = 0
        self.count = 0
        self.error = 'waiting for cameras and PX4 estimates'
        self.odom_pub = self.create_publisher(Odometry, PREFIX+'/odom', qos_profile_sensor_data)
        self.observation_pub = self.create_publisher(Odometry, PREFIX+'/observation/odom', qos_profile_sensor_data)
        self.imu_pub = self.create_publisher(Imu, PREFIX+'/imu', qos_profile_sensor_data)
        self.status_pub = self.create_publisher(String, PREFIX+'/sensors', 10)
        self.depth_pub = self.create_publisher(String, PREFIX+'/observation/depth',10)
        self.images = {name: self.create_publisher(Image, PREFIX+f'/camera/{name}/image_raw', qos_profile_sensor_data)
                       for name in ('front','down')}
        self.infos = {name: self.create_publisher(CameraInfo, PREFIX+f'/camera/{name}/camera_info', qos_profile_sensor_data)
                      for name in self.images}
        self.create_subscription(VehicleOdometry, '/fmu/out/vehicle_odometry', self.pose, qos_profile_sensor_data)
        self.create_subscription(SensorCombined, '/fmu/out/sensor_combined', self.imu, qos_profile_sensor_data)
        self.create_timer(1/self.task['control']['camera_hz'], self.poll, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.create_timer(.02, self.consume, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.create_timer(.5, self.status, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.tf = StaticTransformBroadcaster(self)
        self.dynamic_tf = TransformBroadcaster(self)
        transforms = []
        # Optical x right, y down, z forward. Physical extrinsics match settings.
        for name, xyz, quat in [('front',[1.,0.,0.],[-.5,.5,-.5,.5]),
                                 ('down',[0.,0.,0.],[math.sqrt(.5),-math.sqrt(.5),0.,0.])]:
            t = TransformStamped(); t.header.frame_id = 'stage4/base_link'
            t.child_frame_id = f'stage4/{name}_optical'
            t.transform.translation.x,t.transform.translation.y,t.transform.translation.z = xyz
            t.transform.rotation.x,t.transform.rotation.y,t.transform.rotation.z,t.transform.rotation.w = quat
            transforms.append(t)
        self.tf.sendTransform(transforms)

    def pose(self, msg):
        if msg.pose_frame != msg.POSE_FRAME_NED or msg.velocity_frame != msg.VELOCITY_FRAME_NED:
            return
        values = [*msg.position,*msg.velocity,*msg.q]
        if not all(math.isfinite(v) for v in values): return
        seconds = msg.timestamp_sample*1e-6
        if self.poses and seconds < self.poses[-1][0]: self.poses.clear()
        q = [*map(float,msg.q[1:]),float(msg.q[0])]
        out = Odometry(); out.header.stamp = stamp(seconds); out.header.frame_id = 'stage4/world'
        out.child_frame_id = 'stage4/base_link'
        out.pose.pose.position.x,out.pose.pose.position.y,out.pose.pose.position.z = enu(msg.position)
        quat = enu_flu_quaternion(q)
        out.pose.pose.orientation.x,out.pose.pose.orientation.y,out.pose.pose.orientation.z,out.pose.pose.orientation.w = quat
        # nav_msgs twist is expressed in child frame (FLU), not world ENU.
        x,y,z,w = q
        from stage4.contracts import quaternion_product
        body = quaternion_product(quaternion_product([-x,-y,-z,w],[*map(float,msg.velocity),0]),q)
        out.twist.twist.linear.x,out.twist.twist.linear.y,out.twist.twist.linear.z = body[0],-body[1],-body[2]
        if all(math.isfinite(v) for v in msg.angular_velocity):
            out.twist.twist.angular.x,out.twist.twist.angular.y,out.twist.twist.angular.z = map(float,
                [msg.angular_velocity[0],-msg.angular_velocity[1],-msg.angular_velocity[2]])
        self.poses.append((seconds,out)); self.pose_wall = time.monotonic()
        self.odom_pub.publish(out)
        transform=TransformStamped(); transform.header=out.header; transform.child_frame_id=out.child_frame_id
        transform.transform.translation.x,transform.transform.translation.y,transform.transform.translation.z = enu(msg.position)
        transform.transform.rotation=out.pose.pose.orientation
        self.dynamic_tf.sendTransform(transform)

    def imu(self, msg):
        out = Imu(); out.header.stamp = stamp(msg.timestamp*1e-6); out.header.frame_id = 'stage4/base_link'
        out.orientation_covariance[0] = -1.
        out.angular_velocity.x,out.angular_velocity.y,out.angular_velocity.z = map(float,[msg.gyro_rad[0],-msg.gyro_rad[1],-msg.gyro_rad[2]])
        out.linear_acceleration.x,out.linear_acceleration.y,out.linear_acceleration.z = map(float,[msg.accelerometer_m_s2[0],-msg.accelerometer_m_s2[1],-msg.accelerometer_m_s2[2]])
        self.imu_pub.publish(out)

    def poll(self):
        if self.future is None:
            requests = [dict(camera_name=name, image_type=0, pixels_as_float=False, compress=True)
                        for name in ('FrontCamera','DownCamera')]
            requests += [dict(camera_name=name,image_type=2,pixels_as_float=True,compress=False)
                         for name in DEPTH_CAMERAS]
            self.future = self.pool.submit(rpc, 'simGetImages', requests, 'PX4', False, timeout=2)

    def consume(self):
        if self.future is None or not self.future.done(): return
        future,self.future = self.future,None
        try:
            frames = future.result()
            if len(frames) != 7 or not self.poses: raise ValueError('Missing RGB/depth images or pose')
            times = [int(f['time_stamp'])*1e-9 for f in frames]
            limit = self.task['control']['max_pair_skew_s']
            if min(times) <= 0 or max(times)-min(times) > limit: raise ValueError('RGB/depth timestamp skew')
            proximity=depth_proximity(frames[2:])
            if times[0] <= self.last_stamp: raise ValueError('Repeated/backward camera timestamp')
            pose_time,pose = min(self.poses,key=lambda p: abs(p[0]-times[0]))
            skew = abs(pose_time-times[0])
            if skew > limit or time.monotonic()-self.pose_wall > .5:
                raise ValueError(f'Image/PX4 clock or pose mismatch: skew={skew:.6f}s')
            for name,frame,seconds in zip(self.images,frames[:2],times[:2]):
                image = PILImage.open(BytesIO(bytes(frame['image_data_uint8']))).convert('RGB')
                out = Image(); out.header.stamp = stamp(seconds); out.header.frame_id = f'stage4/{name}_optical'
                out.width,out.height = image.size; out.encoding = 'rgb8'; out.step = out.width*3
                out.data = image.tobytes()
                live_dir=self.directory/'webui'; live_dir.mkdir(exist_ok=True)
                live_file=live_dir/f'{name}.tmp.jpg'
                image.save(live_file,format='JPEG',quality=80)
                live_file.replace(live_dir/f'{name}.jpg')
                if self.count == 0:
                    check_dir=self.directory/'camera-check'; check_dir.mkdir(exist_ok=True)
                    image.save(check_dir/f'{name}.png')
                self.images[name].publish(out)
                info = CameraInfo(); info.header = out.header; info.width,info.height = image.size
                focal = out.width/2  # FOV 90 degrees, square pixels.
                info.distortion_model = 'plumb_bob'; info.d = [0.]*5
                info.k = [focal,0.,out.width/2,0.,focal,out.height/2,0.,0.,1.]
                info.r = [1.,0.,0.,0.,1.,0.,0.,0.,1.]
                info.p = [focal,0.,out.width/2,0.,0.,focal,out.height/2,0.,0.,0.,1.,0.]
                self.infos[name].publish(info)
            import copy
            observation = copy.deepcopy(pose); observation.header.stamp = stamp(times[0])
            self.observation_pub.publish(observation)
            self.depth_pub.publish(String(data=json.dumps(dict(observation_time_s=times[0],fractions=proximity))))
            self.last_stamp = times[0]; self.published_wall = time.monotonic(); self.count += 1
            self.error = ''; self.skew = skew
        except Exception as exc:
            self.error = str(exc)

    def status(self):
        data = dict(pairs=self.count, pair_age_s=time.monotonic()-self.published_wall if self.published_wall else None,
                    pose_skew_s=getattr(self,'skew',None), error=self.error,
                    time_source='AirSim image time_stamp / PX4 timestamp_sample; no wall-clock restamping')
        self.status_pub.publish(String(data=json.dumps(data)))
        from stage4.contracts import atomic_json
        atomic_json(self.directory/'sensors.json',data)


def main():
    rclpy.init(); node = Sensors()
    try: rclpy.spin(node)
    finally:
        node.pool.shutdown(wait=False,cancel_futures=True); node.destroy_node(); rclpy.try_shutdown()


if __name__ == '__main__': main()
