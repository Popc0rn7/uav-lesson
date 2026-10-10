#!/usr/bin/env python3
"""ROS Docker：Gazebo 原生点云 → PointCloud2 与单帧表面体素。"""
import argparse
import json
import math
import struct
import time
import urllib.request

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import Point
from sensor_msgs.msg import PointCloud2, PointField
from visualization_msgs.msg import Marker
from std_msgs.msg import String
from rclpy.serialization import serialize_message


def read_xyz(meta, payload):
    """遵循点/行步长、字段偏移与端序；Gazebo FLOAT32/64 枚举为 6/7。"""
    width, height = meta['width'], meta['height']
    step, row = meta['point_step'], meta['row_step']
    if not (0 < width * height <= 1_000_000 and step > 0 and row >= width * step):
        raise ValueError('点云尺寸或步长无效')
    if len(payload) != height * row:
        raise ValueError('点云载荷长度与行步长不符')
    fields = {f['name']: f for f in meta['fields']}
    columns = []
    endian = '>' if meta['is_bigendian'] else '<'
    for axis in ('x', 'y', 'z'):
        field = fields[axis]
        if field['count'] != 1 or field['datatype'] not in (6, 7):
            raise ValueError('XYZ 必须为单个浮点字段')
        dtype = np.dtype(endian + ('f4' if field['datatype'] == 6 else 'f8'))
        offset = field['offset']
        if offset < 0 or offset + dtype.itemsize > step:
            raise ValueError('XYZ 字段越过点步长')
        columns.append(np.ndarray((height, width), dtype=dtype, buffer=payload,
                                  offset=offset, strides=(row, step)).reshape(-1))
    xyz = np.column_stack(columns)
    xyz = xyz[np.isfinite(xyz).all(axis=1)]
    # 极端坐标不进入整数栅格。
    if xyz.size and np.abs(xyz).max() > 1_000_000:
        raise ValueError('点云坐标超出支持范围')
    return np.asarray(xyz, dtype='<f4')


def voxel_centers(xyz, size, limit):
    """以传感器原点对齐固定格网；负坐标使用 floor，非取整截断。"""
    keys = np.unique(np.floor(xyz.astype(np.float64) / size).astype(np.int64), axis=0)
    if len(keys) > limit:
        raise ValueError(f'体素 {len(keys)} 超过预算 {limit}，请增大 --voxel-size')
    return (keys.astype(np.float64) + .5) * size


def messages(meta, xyz, centers, size, frame="stage2_depth"):
    cloud = PointCloud2()
    stamp = round(meta['sim_time'] * 1_000_000_000)
    cloud.header.stamp.sec, cloud.header.stamp.nanosec = divmod(stamp, 1_000_000_000)
    # 数值完全沿用 Gazebo 原生坐标，不称为 ROS optical frame 或 world。
    cloud.header.frame_id = frame
    cloud.height, cloud.width = 1, len(xyz)
    cloud.fields = [PointField(name=axis, offset=i*4, datatype=PointField.FLOAT32, count=1)
                    for i, axis in enumerate(('x', 'y', 'z'))]
    cloud.point_step, cloud.row_step = 12, len(xyz)*12
    cloud.is_bigendian, cloud.is_dense = False, True
    cloud.data = xyz.tobytes()
    marker = Marker()
    marker.header = cloud.header
    marker.ns, marker.id = 'surface_voxels', 0
    marker.type, marker.action = Marker.CUBE_LIST, Marker.ADD
    marker.pose.orientation.w = 1.
    marker.scale.x = marker.scale.y = marker.scale.z = size
    marker.color.r, marker.color.g, marker.color.b, marker.color.a = .65, .38, .95, 1.
    # 每帧替换同一 marker；停止发布后不把旧格子留成地图。
    marker.lifetime.sec = 3
    marker.points = [Point(x=float(p[0]), y=float(p[1]), z=float(p[2])) for p in centers]
    return cloud, marker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='http://127.0.0.1:8093')
    parser.add_argument('--voxel-size', type=float, default=.1)
    parser.add_argument('--max-voxels', type=int, default=100_000)
    parser.add_argument('--fps', type=float, default=5)
    parser.add_argument('--frame', default='stage2_depth')
    parser.add_argument('--topic-prefix', default='/stage2/depth')
    parser.add_argument('--min-distance', type=float, default=.001)
    parser.add_argument('--max-distance', type=float, default=1000)
    args = parser.parse_args()
    if not (0 <= args.min_distance < args.max_distance <= 1000 and args.frame
            and args.topic_prefix.startswith('/') and not args.topic_prefix.endswith('/')):
        parser.error('距离需为有限的 0–1000 m 区间，frame 非空，topic-prefix 为绝对话题前缀')
    if not (math.isfinite(args.voxel_size) and .01 <= args.voxel_size <= 2
            and 0 < args.fps <= 30 and 1 <= args.max_voxels <= 200_000):
        parser.error('voxel-size 需为 0.01–2 m，fps 为 (0,30]，max-voxels 为 1–200000')
    rclpy.init()
    node = Node('stage2_rviz_cloud_bridge')
    cloud_pub = node.create_publisher(PointCloud2, args.topic_prefix + '/points', qos_profile_sensor_data)
    voxel_pub = node.create_publisher(Marker, args.topic_prefix + '/voxels', qos_profile_sensor_data)
    stats_pub = node.create_publisher(String, args.topic_prefix + '/stats', qos_profile_sensor_data)
    first_publish = time.monotonic()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last, last_error, frames = None, 0., 0
    try:
        while rclpy.ok():
            started = time.monotonic()
            try:
                with opener.open(args.source.rstrip('/') + '/points', timeout=2) as response:
                    wire = response.read(64*1024*1024+1)
                if not 4 <= len(wire) <= 64*1024*1024:
                    raise ValueError('接收帧长度错误')
                size = struct.unpack('!I', wire[:4])[0]
                if size > 65536 or size > len(wire)-4:
                    raise ValueError('接收帧头错误')
                meta = json.loads(wire[4:4+size])
                if meta['version'] != 1:
                    raise ValueError('接收桥协议错误')
                if time.monotonic() - meta['received'] > 3:
                    raise ValueError('点云停更超过 3 秒')
                if meta['count'] != last:
                    xyz = read_xyz(meta, wire[4+size:])
                    distance = np.linalg.norm(xyz, axis=1)
                    xyz = xyz[(distance >= args.min_distance) & (distance <= args.max_distance)]
                    centers = voxel_centers(xyz, args.voxel_size, args.max_voxels)
                    cloud, marker = messages(meta, xyz, centers, args.voxel_size, args.frame)
                    cloud_pub.publish(cloud)
                    voxel_pub.publish(marker)
                    last = meta['count']
                    frames += 1
                    stats = dict(sim_time=meta['sim_time'], source_frame=meta['source_frame'],
                                 input_points=meta['width']*meta['height'], valid_points=len(xyz),
                                 voxels=len(centers), raw_frame_bytes=len(wire),
                                 cloud_serialized_bytes=len(serialize_message(cloud)),
                                 voxel_serialized_bytes=len(serialize_message(marker)),
                                 receive_fps=meta['rx_fps'],
                                 publish_fps=frames/max(.001, time.monotonic()-first_publish),
                                 processing_ms=(time.monotonic()-started)*1000)
                    stats_pub.publish(String(data=json.dumps(stats)))
                    if frames == 1 or frames % 50 == 0:
                        node.get_logger().info(f"源 {meta['width']}×{meta['height']} / {meta['source_frame']}；有效点 {len(xyz)}；表面体素 {len(centers)} / {args.voxel_size:g} m；仿真 {meta['sim_time']:.3f} s；处理发布 {(time.monotonic()-started)*1000:.1f} ms")
            except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
                if time.monotonic() - last_error > 3:
                    node.get_logger().warning(str(exc))
                    last_error = time.monotonic()
            rclpy.spin_once(node, timeout_sec=0)
            time.sleep(max(0, 1/args.fps - (time.monotonic()-started)))
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
