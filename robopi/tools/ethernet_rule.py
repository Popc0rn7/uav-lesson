#!/usr/bin/env python3
"""RoboPi：为已配置的测试源 IPv4 添加/撤销到 main 表的临时策略规则。

OpenHarmony 的默认 fwmark 规则可能先选 Wi-Fi 表，即使 socket bind 到以太网 IP。
本工具不设置地址、默认路由或防火墙；只匹配显式源 /32，保存本次所有权。
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import socket
import struct


def attribute(kind, data):
    result=struct.pack('HH',4+len(data),kind)+data
    return result+b'\0'*((-len(result))%4)


def request(kind, flags, body):
    with socket.socket(socket.AF_NETLINK,socket.SOCK_RAW,0) as channel:
        channel.bind((0,0));channel.settimeout(3)
        channel.send(struct.pack('IHHII',16+len(body),kind,flags,1,0)+body)
        result=[]
        while True:
            packet=channel.recv(65536);offset=0
            while offset+16<=len(packet):
                length,reply,_,sequence,_=struct.unpack_from('IHHII',packet,offset)
                if length<16 or offset+length>len(packet):raise RuntimeError('无效 netlink 消息')
                data=packet[offset+16:offset+length];offset+=(length+3)&~3
                if sequence!=1:continue
                if reply==3:return result
                if reply==2:
                    error=struct.unpack_from('i',data)[0]
                    if error:raise OSError(-error,os.strerror(-error))
                    return result
                result.append(data)


def rules():
    result=[]
    for data in request(34,0x301,struct.pack('BBBBBBBBI',socket.AF_INET,0,0,0,0,0,0,0,0)):
        header=struct.unpack_from('BBBBBBBBI',data);attrs={};offset=12
        while offset+4<=len(data):
            length,kind=struct.unpack_from('HH',data,offset)
            if length<4 or offset+length>len(data):raise RuntimeError('无效 rule attribute')
            attrs[kind]=data[offset+4:offset+length];offset+=(length+3)&~3
        result.append(dict(source=socket.inet_ntoa(attrs[2]) if 2 in attrs else None,
                           source_prefix=header[2],table=struct.unpack('I',attrs[15])[0] if 15 in attrs else header[4],
                           action=header[7],priority=struct.unpack('I',attrs[6])[0] if 6 in attrs else 0))
    return result


def change(source,priority,remove=False):
    body=struct.pack('BBBBBBBBI',socket.AF_INET,0,32,0,254,0,0,1,0)
    body+=attribute(2,socket.inet_aton(source))+attribute(6,struct.pack('I',priority))
    request(33 if remove else 32,5 if remove else 0x605,body)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['status','add','remove'])
    parser.add_argument('--source',required=True)
    parser.add_argument('--priority',type=int,default=10000)
    parser.add_argument('--state',type=Path,default=Path(__file__).with_suffix('.state.json'))
    args=parser.parse_args()
    source=str(ipaddress.IPv4Address(args.source))
    if not ipaddress.IPv4Address(source).is_private or not 1<=args.priority<11000:
        parser.error('需要私有测试地址及 1..10999 的空闲优先级')
    expected=dict(source=source,source_prefix=32,table=254,action=1,priority=args.priority)
    same=[r for r in rules() if r['priority']==args.priority]
    if args.action=='status':print(json.dumps(dict(expected=expected,observed=same)));return
    if same and same!=[expected]:raise RuntimeError('该优先级有其他规则，拒绝修改：'+str(same))
    if args.action=='add':
        if not same:
            change(source,args.priority)
            args.state.write_text(json.dumps(dict(rule=expected,created=True)))
        elif not args.state.exists():
            args.state.write_text(json.dumps(dict(rule=expected,created=False)))
    else:
        owned=json.loads(args.state.read_text())
        if owned!={'rule':expected,'created':True}:raise RuntimeError('没有本次创建记录，拒绝删除规则')
        if same:change(source,args.priority,remove=True)
        args.state.unlink()
    print(json.dumps(dict(expected=expected,observed=[r for r in rules() if r['priority']==args.priority])))


if __name__=='__main__':main()
