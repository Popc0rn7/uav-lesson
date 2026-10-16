#!/usr/bin/env python3
"""临时 NET_RAW 容器：被动采集 lo/TCP4560；不连接 AirSim accept。"""
import argparse
import ctypes
import json
from pathlib import Path
import socket
import struct
import time


def attach_filter(sock,port):
    class Filter(ctypes.Structure):
        _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(Filter))]
    # Ethernet IPv4 / unfragmented TCP / either port; unrelated traffic is rejected in kernel.
    instructions=[(0x28,0,0,12),(0x15,0,9,0x800),(0x30,0,0,23),(0x15,0,7,6),
                  (0x28,0,0,20),(0x45,5,0,0x3fff),(0xb1,0,0,14),(0x48,0,0,14),
                  (0x15,3,0,port),(0x48,0,0,16),(0x15,1,0,port),(0x06,0,0,0),(0x06,0,0,65535)]
    filters=(Filter*len(instructions))(*(Filter(*i) for i in instructions))
    program=Program(len(filters),filters)
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.setsockopt(sock.fileno(),socket.SOL_SOCKET,26,ctypes.byref(program),ctypes.sizeof(program)):
        raise OSError(ctypes.get_errno(),'SO_ATTACH_FILTER failed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.seconds<=120: parser.error('seconds 必须为 1～120')
    started=time.monotonic();cpu=time.process_time()
    meta=dict(timestamp_source='kernel SO_TIMESTAMPNS / CLOCK_REALTIME',port=4560,
              packet_count=0,kernel_packets=0,kernel_drops=0,calibrations=[],scope='host loopback IPv4 TCP4560 only')
    with socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(0x0800)) as sock:
        attach_filter(sock,4560)
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4*1024*1024)
        sock.setsockopt(socket.SOL_SOCKET,35,1)
        sock.bind(('lo',0));sock.settimeout(.25)
        with args.output.open('wb') as output:
            output.write(struct.pack('<IHHIIII',0xa1b23c4d,2,4,0,0,65535,1))
            calibration_at=0
            while time.monotonic()-started<args.seconds:
                if time.monotonic()-calibration_at>=1:
                    meta['calibrations'].append(dict(wall_ns=time.time_ns(),mono_ns=time.monotonic_ns()))
                    calibration_at=time.monotonic()
                try: packet,ancillary,flags,address=sock.recvmsg(65535,256)
                except socket.timeout: continue
                if address[2]==socket.PACKET_OUTGOING: continue  # lo 的本地双份只保留 HOST 副本。
                stamp=None
                for level,kind,data in ancillary:
                    if level==socket.SOL_SOCKET and kind==35:
                        sec,nsec=struct.unpack('@ll',data[:struct.calcsize('@ll')]);stamp=sec*10**9+nsec
                if stamp is None: raise RuntimeError('缺少内核时间戳，拒绝把用户态调度延迟伪装成网络时间')
                output.write(struct.pack('<IIII',stamp//10**9,stamp%10**9,len(packet),len(packet)))
                output.write(packet);meta['packet_count']+=1
        data=sock.getsockopt(263,6,12)
        meta['kernel_packets'],meta['kernel_drops']=struct.unpack('II',data[:8])
    meta.update(wall_seconds=time.monotonic()-started,cpu_seconds=time.process_time()-cpu)
    meta['single_core_cpu_fraction']=meta['cpu_seconds']/meta['wall_seconds']
    args.output.with_suffix('.capture.json').write_text(json.dumps(meta,indent=2))


if __name__=='__main__': main()
