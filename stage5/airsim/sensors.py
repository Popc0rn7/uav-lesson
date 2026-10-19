"""Docker 2：AirSim RGBD → ROS Image/CameraInfo 与原始 HTTP；无飞行接口。"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from px4_msgs.msg import SensorCombined, VehicleLocalPosition, VehicleStatus, VehicleAttitude
from sensor_msgs.msg import Image, CameraInfo
from geometry_msgs.msg import TransformStamped
from tf2_ros import StaticTransformBroadcaster

from stage3.super.airsim.rpc_client import rpc
from stage5.evidence import write_json
from stage5.airsim.config import camera_model
from stage5.airsim.frames import decode_pair, camera_info
from stage5.airsim.geometry import pose_at_capture

DIRECTORY = Path('/run/stage5')


class Sensors(Node):
    def __init__(self):
        super().__init__('stage5_airsim_sensors')
        self.config = json.loads((DIRECTORY/'config.json').read_text())
        self.model = camera_model(self.config)
        self.lock = threading.Lock()
        self.latest = {}
        self.times = deque(maxlen=120)
        self.count = self.last_stamp = 0
        self.published_wall = 0
        self.error = 'waiting for RGBD'
        self.telemetry = {}
        self.telemetry_at = {}
        self.clock_samples = deque(maxlen=1000)
        self.position_samples = deque(maxlen=1000)
        self.attitude_samples = deque(maxlen=1000)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.images = {k: self.create_publisher(Image, f'/stage5/camera/{k}/image_raw', qos_profile_sensor_data)
                       for k in ('rgb', 'depth')}
        self.infos = {k: self.create_publisher(CameraInfo, f'/stage5/camera/{k}/camera_info', qos_profile_sensor_data)
                      for k in self.images}
        self.create_subscription(SensorCombined, '/fmu/out/sensor_combined', self.clock, qos_profile_sensor_data)
        self.create_subscription(VehicleLocalPosition, '/fmu/out/vehicle_local_position_v1', self.position, qos_profile_sensor_data)
        self.create_subscription(VehicleStatus, '/fmu/out/vehicle_status_v4', self.vehicle, qos_profile_sensor_data)
        self.create_subscription(VehicleAttitude, '/fmu/out/vehicle_attitude', self.attitude, qos_profile_sensor_data)
        self.create_timer(1/self.config['camera_hz'], self.poll)
        self.create_timer(.02, self.consume)
        self.create_timer(.5, self.status)
        self.tf = StaticTransformBroadcaster(self)
        t = TransformStamped()
        t.header.frame_id = 'stage5/base_link'
        t.child_frame_id = 'stage5/front_optical'
        if self.model['position_body_flu_m'] is not None:
            t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = self.model['position_body_flu_m']
            t.transform.rotation.x, t.transform.rotation.y = -.5, .5
            t.transform.rotation.z, t.transform.rotation.w = -.5, .5
            self.tf.sendTransform(t)

    def clock(self, msg):
        self.clock_samples.append(msg.timestamp*1e-6)
        self.telemetry['clock_sim_s'] = msg.timestamp*1e-6
        self.telemetry_at['clock'] = time.monotonic()

    def position(self, msg):
        values = [float(msg.x), float(msg.y), float(msg.z)]
        if msg.xy_valid and msg.z_valid and all(math.isfinite(v) for v in values):
            self.position_samples.append(((getattr(msg, 'timestamp_sample', 0) or msg.timestamp)*1e-6, values))
        self.telemetry.update(position_ned_m=values if all(math.isfinite(v) for v in values) else None,
                              xy_valid=bool(msg.xy_valid and all(math.isfinite(v) for v in values[:2])),
                              z_valid=bool(msg.z_valid and math.isfinite(values[2])))
        self.telemetry_at['position'] = time.monotonic()

    def attitude(self, msg):
        q = [float(v) for v in msg.q]
        if all(math.isfinite(v) for v in q) and .99 < math.sqrt(sum(v*v for v in q)) < 1.01:
            self.attitude_samples.append(((getattr(msg, 'timestamp_sample', 0) or msg.timestamp)*1e-6, q))

    def vehicle(self, msg):
        self.telemetry.update(armed=msg.arming_state == VehicleStatus.ARMING_STATE_ARMED,
                              nav_state=int(msg.nav_state), system_id=int(msg.system_id))
        self.telemetry_at['vehicle'] = time.monotonic()

    def poll(self):
        if self.future is None:
            requests = [dict(camera_name='front_center', image_type=kind, pixels_as_float=kind == 1, compress=kind == 0)
                        for kind in (0, 1)]
            self.future = self.pool.submit(rpc, 'simGetImages', requests, self.config['vehicle_name'], False,
                                          host=self.config['rpc_host'], port=self.config['rpc_port'], timeout=3)

    def consume(self):
        if self.future is None or not self.future.done():
            return
        future, self.future = self.future, None
        try:
            rgb, depth, stamps, stats = decode_pair(future.result(), self.model, self.last_stamp)
            # 不用收包墙钟盖章；记录与 HIL 同源时钟的实际偏差。
            if not self.clock_samples:
                raise ValueError('等待 PX4 HIL 时钟')
            skew = min(abs(s-stamps[0]*1e-9) for s in self.clock_samples)
            lag = self.clock_samples[-1]-min(stamps)*1e-9
            if skew > .1 or lag > .5 or time.monotonic()-self.telemetry_at.get('clock', 0) > 1:
                raise ValueError(f'RGBD/PX4 时钟未对齐：{skew:.6f}s')
            now = time.monotonic()
            self.times.append(now)
            fps = (len(self.times)-1)/(now-self.times[0]) if len(self.times)>1 else 0.
            self.count += 1
            pair = {}
            for key, pixels, stamp, fmt, bpp, encoding in (
                ('rgb', rgb, stamps[0], 'RGB_INT8', 3, 'rgb8'),
                ('depth', depth, stamps[1], 'R_FLOAT32', 4, '32FC1')):
                intrinsics = self.model[key]
                width, height = intrinsics['width'], intrinsics['height']
                meta = dict(version=1, count=self.count, pair_id=self.count, topic=f'/stage5/camera/{key}/image_raw',
                            width=width, height=height, step=width*bpp, format=fmt, sim_time=stamp*1e-9,
                            capture_time_ns=stamp, received=now, rx_fps=fps, source='airsim',
                            depth_convention='optical_axis', px4_clock_skew_s=skew,
                            capture_lag_sim_s=lag)
                meta['px4_pose'] = pose_at_capture(self.position_samples, self.attitude_samples, stamp*1e-9)
                pair[key] = (meta, pixels)
                out = Image()
                out.header.stamp.sec, out.header.stamp.nanosec = divmod(stamp, 1_000_000_000)
                out.header.frame_id = 'stage5/front_optical'
                out.width, out.height, out.step, out.encoding = width, height, width*bpp, encoding
                out.is_bigendian = False
                out.data = pixels
                self.images[key].publish(out)
                info = CameraInfo()
                info.header, info.width, info.height = out.header, width, height
                info.distortion_model, info.d = 'plumb_bob', [0.]*5
                matrices = camera_info(intrinsics)
                info.k, info.p = matrices['k'], matrices['p']
                info.r = [1., 0., 0., 0., 1., 0., 0., 0., 1.]
                self.infos[key].publish(info)
            with self.lock:
                self.latest = pair
            self.last_stamp = max(stamps)
            self.published_wall, self.error = now, ''
            self.depth_stats, self.skew = stats, skew
        except Exception as exc:
            self.error = str(exc)

    def status(self):
        now = time.monotonic()
        ages = {k: now-v for k, v in self.telemetry_at.items()}
        fresh = all(ages.get(k, 100) < 1 for k in ('clock', 'position', 'vehicle'))
        age = now-self.published_wall if self.published_wall else None
        data = dict(pairs=self.count, pair_age_s=age, error=self.error, telemetry=self.telemetry,
                    telemetry_age_s=ages, px4_clock_skew_s=getattr(self, 'skew', None),
                    depth=getattr(self, 'depth_stats', {}),
                    healthy=bool(fresh and self.telemetry.get('system_id') == 6 and
                                 self.telemetry.get('xy_valid') and self.telemetry.get('z_valid') and
                                 self.count >= 3 and age is not None and age < 1 and not self.error))
        write_json(DIRECTORY/'sensors.json', data)


def main():
    rclpy.init()
    node = Sensors()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            key = self.path.split('?', 1)[0].lstrip('/')
            with node.lock:
                frame = node.latest.get(key)
            if key == 'calibration':
                body, mime = json.dumps(node.model).encode(), 'application/json'
            elif key not in ('rgb', 'depth'):
                self.send_error(404)
                return
            elif frame is None or time.monotonic()-frame[0]['received'] > 2:
                self.send_error(503, 'waiting for fresh RGBD')
                return
            else:
                header = json.dumps(frame[0], allow_nan=False).encode()
                body, mime = struct.pack('!I', len(header))+header+frame[1], 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', node.config['raw_port']), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        rclpy.spin(node)
    finally:
        server.shutdown()
        server.server_close()
        node.pool.shutdown(wait=False, cancel_futures=True)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
