#!/usr/bin/env python3
"""Docker 2：只读订阅真实 ROS 接口，验证图像大帧、CameraInfo、时钟及定位。"""
import json
from pathlib import Path
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Image, CameraInfo
from px4_msgs.msg import VehicleLocalPosition, VehicleStatus


def main():
    rclpy.init()
    node = Node('stage5_readonly_interface_probe')
    counts, first, latest = {}, {}, {}

    def save(key, msg):
        counts[key] = counts.get(key, 0)+1
        latest[key] = msg
        first.setdefault(key, msg)

    topics = [('clock', '/clock', Clock),
              ('position', '/fmu/out/vehicle_local_position_v1', VehicleLocalPosition),
              ('vehicle', '/fmu/out/vehicle_status_v4', VehicleStatus)]
    for key in ('rgb', 'depth'):
        topics += [(key, f'/stage5/camera/{key}/image_raw', Image),
                   (key+'_info', f'/stage5/camera/{key}/camera_info', CameraInfo)]
    for key, topic, kind in topics:
        node.create_subscription(kind, topic, lambda msg, k=key: save(k, msg), qos_profile_sensor_data)
    try:
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.1)
        result = dict(counts=counts, passed=False)
        if all(counts.get(key, 0) >= 3 for key, _, _ in topics):
            def clock_seconds(msg):
                return msg.clock.sec+msg.clock.nanosec*1e-9
            advance = clock_seconds(latest['clock'])-clock_seconds(first['clock'])
            armed = latest['vehicle'].arming_state == VehicleStatus.ARMING_STATE_ARMED
            valid = bool(latest['position'].xy_valid and latest['position'].z_valid)
            images = {}
            for key, width, height, encoding, bpp in [('rgb', 640, 360, 'rgb8', 3),
                                                     ('depth', 640, 400, '32FC1', 4)]:
                msg = latest[key]
                images[key] = dict(width=msg.width, height=msg.height, encoding=msg.encoding,
                                   valid=(msg.width == width and msg.height == height and
                                          msg.encoding == encoding and msg.step == width*bpp and
                                          len(msg.data) == width*height*bpp))
            result.update(clock_advance_s=advance, armed=armed, position_valid=valid, images=images,
                          camera_k={key: list(latest[key].k) for key in ('rgb_info', 'depth_info')},
                          passed=advance > 0 and not armed and valid and all(v['valid'] for v in images.values()))
        Path('/run/stage5/ros-verification.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2), flush=True)
        if not result['passed']:
            raise SystemExit('ROS接口验收失败，检查图像大帧传输、DDS和节点日志')
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
