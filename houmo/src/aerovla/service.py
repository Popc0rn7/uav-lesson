"""AeroVLA 模型 HTTP 服务：常驻加载、串行推理；输出不直接执行。"""
import argparse
import base64
import binascii
import json
import os
import uuid
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np

MAX_BODY = 4 * 1024 * 1024
SHAPE = [1, 6, 224, 224]


def decode_request(req, cfg):
    if not isinstance(req, dict) or req.get('pixel_values_shape') != SHAPE:
        raise ValueError('pixel_values_shape 必须为 [1,6,224,224]')
    ids = req.get('input_ids')
    if not isinstance(ids, list) or not ids or any(type(t) is not int or not 0 <= t < cfg['vocab_size'] for t in ids):
        raise ValueError('input_ids 必须为非空且不超词表的整数列表')
    if len(ids) + 256 + cfg['max_new_tokens'] > 1024:
        raise ValueError('输入与生成预算超过 1024-token KV cache')
    encoded = req.get('pixel_values_b64')
    if not isinstance(encoded, str):
        raise ValueError('pixel_values_b64 必须是纯 Base64 字符串')
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) != 1 * 6 * 224 * 224 * 4:
        raise ValueError('图像张量字节数不符，必须为 float32 little endian')
    pixels = np.frombuffer(raw, dtype='<f4').reshape(SHAPE)
    if not np.isfinite(pixels).all():
        raise ValueError('pixel_values 包含非有限值')
    return ids, pixels


def make_handler(runner):
    lock = threading.Lock()
    instance_id = uuid.uuid4().hex

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(obj, allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/health':
                self._send(200, {'status': 'ready', 'model': 'aerovla', 'busy': lock.locked(),
                                 'pid': os.getpid(), 'instance_id': instance_id})
            else:
                self._send(404, {'error': 'not found'})

        def do_POST(self):
            if self.path != '/infer':
                self._send(404, {'error': 'not found'})
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_BODY:
                    self._send(413, {'error': '请求必须为不超过 4 MiB 的非空 JSON'})
                    return
                self.connection.settimeout(30)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError('请求体未完整接收')
                req = json.loads(raw)
                ids, pixels = decode_request(req, runner.cfg)
            except (ValueError, TypeError, binascii.Error) as error:
                self._send(400, {'error': str(error)})
                return
            if not lock.acquire(blocking=False):
                self._send(503, {'error': 'model busy'})
                return
            try:
                gen = runner.generate(ids, pixels)
                action, stop, text = runner.parse_action(gen)
                self._send(200, {'action': action, 'should_stop': stop, 'text': text, 'gen_ids': gen})
            except Exception as error:
                self._send(500, {'error': str(error)})
            finally:
                lock.release()

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8084)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port 必须为 1–65535')
    # 先占用端口，避免已存在服务时再加载第二份模型。
    server = ThreadingHTTPServer((args.host, args.port), BaseHTTPRequestHandler)
    try:
        from runner import AeroVLARunner
        runner = AeroVLARunner()
        server.RequestHandlerClass = make_handler(runner)
        print(f'AeroVLA ready on {args.host}:{args.port}', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
