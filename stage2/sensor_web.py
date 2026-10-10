#!/usr/bin/env python3
"""PC 处理接收桥提供的原始 RGBD，提供仅本机可访问的 WebUI（NumPy/Pillow 编码，无第三方 Web 框架）。"""
import argparse
from collections import deque
import io
import json
from pathlib import Path
import signal
import struct
from types import SimpleNamespace
import urllib.request
import urllib.error
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from PIL import Image as PILImage


def encode(msg, depth, near, far):
    fmt = msg.format
    w, h = msg.width, msg.height
    channels = {'RGB_INT8': 3, 'BGR_INT8': 3, 'RGBA_INT8': 4, 'R_FLOAT32': 4}
    if w <= 0 or h <= 0 or fmt not in channels or (depth and fmt != 'R_FLOAT32') or (not depth and fmt == 'R_FLOAT32'):
        raise ValueError(f'不支持的图像: {w}×{h} {fmt}')
    step = msg.step or w * channels[fmt]
    if step < w * channels[fmt] or len(msg.data) < step * h:
        raise ValueError('图像载荷或行步长错误')
    stats = {'source_width': w, 'source_height': h, 'format': fmt}
    if depth:
        values = np.ndarray((h, w), dtype='<f4', buffer=msg.data, strides=(step, 4))
        valid = np.isfinite(values) & (values > 0)
        good = values[valid]
        stats.update(valid_samples=int(valid.sum()), min_m=float(good.min()) if good.size else None,
                     max_m=float(good.max()) if good.size else None)
        t = np.clip((np.where(valid, values, near)-near)/(far-near), 0, 1)
        pixels = np.stack((34+134*t, 211-126*t, 238+9*t), axis=-1).astype(np.uint8)
        pixels[~valid] = (12, 17, 25)
    else:
        pixels = np.ndarray((h, w, channels[fmt]), dtype=np.uint8, buffer=msg.data,
                            strides=(step, channels[fmt], 1))[:, :, :3]
        if fmt == 'BGR_INT8':
            pixels = pixels[:, :, ::-1]
    output = io.BytesIO()
    PILImage.fromarray(np.ascontiguousarray(pixels)).save(output, format='JPEG', quality=85)
    return output.getvalue(), stats


def rate(samples):
    return (len(samples)-1)/(samples[-1]-samples[0]) if len(samples)>1 and samples[-1]>samples[0] else 0.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='http://127.0.0.1:8089')
    parser.add_argument('--port', type=int, default=8090)
    parser.add_argument('--fps', type=float, default=20)
    parser.add_argument('--near', type=float, default=.2)
    parser.add_argument('--far', type=float, default=19.1)
    args = parser.parse_args()
    if not (0 < args.fps <= 30 and 0 <= args.near < args.far and 0 < args.port < 65536):
        parser.error('帧率、深度范围或端口无效')
    lock = threading.Lock()
    state = {name: {'topic': '', 'count': 0, 'error': None, 'rx_fps': 0.} for name in ('rgb', 'depth')}
    pictures = {}
    out_times = {name: deque(maxlen=120) for name in state}
    stop = threading.Event()

    def worker(name):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        last_count = None
        while not stop.is_set():
            started = time.monotonic()
            try:
                with opener.open(args.source.rstrip('/')+'/'+name, timeout=2) as response:
                    wire = response.read(64*1024*1024+1)
                if len(wire)<4 or len(wire)>64*1024*1024:
                    raise ValueError('原始帧长度无效')
                size = struct.unpack('!I', wire[:4])[0]
                if size>65536 or size>len(wire)-4:
                    raise ValueError('原始帧头长度无效')
                meta = json.loads(wire[4:4+size])
                if meta['version']!=1:
                    raise ValueError('不支持的接收桥协议')
                if meta['count']!=last_count:
                    msg = SimpleNamespace(**meta, data=wire[4+size:])
                    encode_started = time.monotonic()
                    picture, stats = encode(msg, name == 'depth', args.near, args.far)
                    finished = time.monotonic()
                    with lock:
                        pictures[name] = picture
                        out_times[name].append(finished)
                        state[name].update(stats, received=meta['received'],
                                           encode_ms=(finished-encode_started)*1000,
                                           transfer_ms=(encode_started-started)*1000,
                                           topic=meta['topic'], rx_fps=meta['rx_fps'], sim_time=meta['sim_time'],
                                           count=state[name]['count']+1, error=None)
                    last_count = meta['count']
            except (ValueError, OverflowError, KeyError, TypeError, OSError, urllib.error.URLError) as exc:
                with lock:
                    state[name]['error'] = str(exc)
            stop.wait(max(0, 1/args.fps-(time.monotonic()-started)))

    page = Path(__file__).with_name('sensor_web.html').read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split('?', 1)[0]
            code, content_type = 200, 'application/json'
            if path == '/':
                body, content_type = page, 'text/html; charset=utf-8'
            elif path == '/api/status':
                with lock:
                    info = {k: dict(v, age_s=time.monotonic()-v['received'] if 'received' in v else None)
                            for k, v in state.items()}
                    for name in info:
                        info[name].update(encode_fps=rate(out_times[name]))
                body = json.dumps(dict(streams=info, near=args.near, far=args.far, fps=args.fps), allow_nan=False).encode()
            elif path in ('/rgb.jpg', '/depth.jpg'):
                with lock:
                    name = path[1:-4]
                    body = pictures.get(name)
                    frame = dict(state[name])
                if body is None:
                    code, body = 503, b'{"error":"waiting for sensor"}'
                else:
                    content_type = 'image/jpeg'
            else:
                code, body = 404, b'{}'
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            if content_type == 'image/jpeg':
                self.send_header('X-Frame-Count', str(frame['count']))
                self.send_header('X-Frame-Age-Ms', str((time.monotonic()-frame['received'])*1000))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    def shutdown(*_):
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threads = [threading.Thread(target=worker, args=(name,), daemon=True) for name in state]
    for thread in threads:
        thread.start()
    print(f'WebUI: http://127.0.0.1:{args.port} | Raw source: {args.source}', flush=True)
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()
        for thread in threads:
            thread.join(timeout=2)


if __name__ == '__main__':
    main()
