#!/usr/bin/env python3
"""仿真 Docker 内的 Gazebo 接收桥，由两个 PC 展示入口自动启动/清理。

Gazebo Python 绑定只在仿真容器内可用，因此在这里订阅原始消息，
通过本机 HTTP 最新帧协议交给 PC sensor_web.py 或 ROS rviz_cloud_bridge.py。
不做图像编码、体素化或飞行控制；每路只缓存最新一帧，不积压队列。
协议：4 B 网络序 JSON 头长度 + UTF-8 元数据 + 原始载荷。
"""
import argparse
from collections import deque
import json
import signal
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rgb')
    parser.add_argument('--depth', default='/depth_camera')
    parser.add_argument('--points')
    parser.add_argument('--points-only', action='store_true')
    parser.add_argument('--port', type=int, default=8089)
    args = parser.parse_args()
    if args.points_only and not args.points:
        parser.error('--points-only 需要 --points')
    if not (args.points_only) and not args.rgb:
        parser.error('图像模式需要 --rgb')
    from gz.transport13 import Node
    from gz.msgs10.image_pb2 import Image, PixelFormatType
    from gz.msgs10.pointcloud_packed_pb2 import PointCloudPacked
    node, lock = Node(), threading.Lock()
    latest = {}
    counts = {'rgb': 0, 'depth': 0, 'points': 0}
    times = {name: deque(maxlen=120) for name in counts}
    callbacks = []

    def callback(name, topic):
        def receive(msg):
            now = time.monotonic()
            with lock:
                counts[name] += 1
                times[name].append(now)
                samples = times[name]
                fps = (len(samples)-1)/(samples[-1]-samples[0]) if len(samples)>1 and samples[-1]>samples[0] else 0
                metadata = dict(version=1, count=counts[name], topic=topic, width=msg.width,
                                height=msg.height, step=msg.step, format=PixelFormatType.Name(msg.pixel_format_type),
                                sim_time=msg.header.stamp.sec+msg.header.stamp.nsec*1e-9,
                                received=now, rx_fps=fps)
                latest[name] = (metadata, msg.data)
        return receive

    for name, topic in ([] if args.points_only else [('rgb', args.rgb), ('depth', args.depth)]):
        cb = callback(name, topic)
        callbacks.append(cb)
        if not node.subscribe(Image, topic, cb):
            raise RuntimeError(f'订阅失败: {topic}')

    if args.points:
        def receive_points(msg):
            now = time.monotonic()
            source_frame = next((v for item in msg.header.data if item.key == 'frame_id'
                                 for v in item.value), '')
            with lock:
                counts['points'] += 1
                times['points'].append(now)
                samples = times['points']
                fps = (len(samples)-1)/(samples[-1]-samples[0]) if len(samples)>1 and samples[-1]>samples[0] else 0
                metadata = dict(version=1, count=counts['points'], topic=args.points,
                                sim_time=msg.header.stamp.sec+msg.header.stamp.nsec*1e-9,
                                received=now, rx_fps=fps, source_frame=source_frame,
                                width=msg.width, height=msg.height, point_step=msg.point_step,
                                row_step=msg.row_step, is_bigendian=msg.is_bigendian,
                                fields=[dict(name=f.name, offset=f.offset, datatype=f.datatype, count=f.count)
                                        for f in msg.field])
                latest['points'] = (metadata, msg.data)
        callbacks.append(receive_points)
        if not node.subscribe(PointCloudPacked, args.points, receive_points):
            raise RuntimeError(f'订阅失败: {args.points}')

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = self.path.split('?', 1)[0].removeprefix('/')
            with lock:
                frame = latest.get(name)
            if name not in counts:
                self.send_error(404)
                return
            if frame is None:
                self.send_error(503, 'waiting for sensor')
                return
            metadata, pixels = frame
            header = json.dumps(metadata, allow_nan=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(4+len(header)+len(pixels)))
            self.end_headers()
            try:
                self.wfile.write(struct.pack('!I', len(header)))
                self.wfile.write(header)
                self.wfile.write(pixels)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f'Raw receiver: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
