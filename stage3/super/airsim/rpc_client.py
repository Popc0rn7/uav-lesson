"""PC：对本机 AirSim 的 MessagePack RPC 调用；每次调用使用独立连接。"""
import socket

import msgpack

def rpc(method,*args,timeout=10):
    with socket.create_connection(('127.0.0.1',41451),timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(msgpack.packb([0,1,method,list(args)],use_bin_type=True))
        u=msgpack.Unpacker(raw=False)
        while True:
            b=s.recv(65536)
            if not b: raise RuntimeError('RPC closed')
            u.feed(b)
            for r in u:
                if r[0]==1 and r[1]==1:
                    if r[2] is not None: raise RuntimeError(str(r[2]))
                    return r[3]
