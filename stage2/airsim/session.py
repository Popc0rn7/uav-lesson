#!/usr/bin/env python3
"""PC：旧 rpclib 的单持久连接代理，避免每次查询关闭 TCP 会话。"""
import argparse
import json
from pathlib import Path
import socket

import msgpack


class Connection:
    def __init__(self):
        self.socket = socket.create_connection(('127.0.0.1', 41451), timeout=10)
        self.socket.settimeout(10)
        self.unpacker = msgpack.Unpacker(raw=False)
        self.request_id = 0

    def call(self, method, args):
        self.request_id += 1
        self.socket.sendall(msgpack.packb([0, self.request_id, method, args], use_bin_type=True))
        while True:
            data = self.socket.recv(65536)
            if not data:
                raise RuntimeError('场景 RPC 连接已关闭')
            self.unpacker.feed(data)
            for response in self.unpacker:
                if response[0] == 1 and response[1] == self.request_id:
                    if response[2] is not None:
                        raise RuntimeError(str(response[2]))
                    return response[3]


def rpc(state, method, *args):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(12)
        client.connect(str(Path(state['run_dir'])/'rpc.sock'))
        client.sendall((json.dumps([method, args])+'\n').encode())
        with client.makefile('rb') as stream:
            raw = stream.readline(4*1024*1024)
        response = json.loads(raw)
        if 'error' in response:
            raise RuntimeError(response['error'])
        return response['result']


def serve(path):
    backend = None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        path.chmod(0o600)
        server.listen(4)
        while True:
            client, _ = server.accept()
            with client:
                client.settimeout(12)
                try:
                    with client.makefile('rb') as stream:
                        method, args = json.loads(stream.readline(65536))
                    if backend is None:
                        backend = Connection()
                    result = backend.call(method, args)
                    response = {'result': result}
                except Exception as exc:
                    response = {'error': f'{type(exc).__name__}: {exc}'}
                try:
                    client.sendall((json.dumps(response)+'\n').encode())
                except OSError:
                    pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['serve'])
    parser.add_argument('socket', type=Path)
    args = parser.parse_args()
    serve(args.socket)
