"""离线 PCAP/TCP 重组与 HIL_SENSOR → 同 time_usec HIL_ACTUATOR_CONTROLS 配对。"""
from collections import Counter, OrderedDict
import ipaddress
import struct


def packets(path):
    with path.open('rb') as source:
        header=source.read(24)
        modes={b'\xd4\xc3\xb2\xa1':('<',1000),b'\xa1\xb2\xc3\xd4':('>',1000),
               b'\x4d\x3c\xb2\xa1':('<',1),b'\xa1\xb2\x3c\x4d':('>',1)}
        if header[:4] not in modes: raise ValueError('仅支持 classic PCAP，不支持 pcapng')
        endian,factor=modes[header[:4]]
        link=struct.unpack(endian+'I',header[20:24])[0]
        if link!=1: raise ValueError('仅支持 Ethernet PCAP（本工具 lo 抓包使用此格式）')
        while record:=source.read(16):
            if len(record)!=16: raise ValueError('PCAP 包头被截断')
            sec,fraction,size,original=struct.unpack(endian+'IIII',record)
            if size>65535: raise ValueError('PCAP 包过长')
            packet=source.read(size)
            if len(packet)!=size: raise ValueError('PCAP 包被截断')
            if len(packet)<54 or packet[12:14]!=b'\x08\x00': continue
            ip=14;ihl=(packet[ip]&15)*4
            if packet[ip+9]!=6 or ihl<20 or struct.unpack('!H',packet[ip+6:ip+8])[0]&0x3fff: continue
            tcp=ip+ihl
            if len(packet)<tcp+20: continue
            sport,dport,seq=struct.unpack('!HHI',packet[tcp:tcp+8])
            if 4560 not in (sport,dport): continue
            offset=(packet[tcp+12]>>4)*4
            total=struct.unpack('!H',packet[ip+2:ip+4])[0]
            if offset<20 or len(packet)<ip+total: continue
            key=(str(ipaddress.ip_address(packet[ip+12:ip+16])),sport,
                 str(ipaddress.ip_address(packet[ip+16:ip+20])),dport)
            yield sec*10**9+fraction*factor,key,seq,packet[tcp+13],packet[tcp+offset:ip+total]


class Reassembly:
    def __init__(self):
        self.next=None;self.pending={};self.duplicates=0;self.resets=0

    def feed(self,seq,data,syn=False):
        if syn:
            self.next=seq+1;self.pending.clear();seq+=1
        if not data: return b''
        if self.next is None: self.next=seq  # 中途抓包，从第一个可见字节开始同步 MAVLink。
        # 单次 ≤120 s 抓包可能跨 TCP 32-bit wrap。
        base=self.next&~0xffffffff
        seq=min((base+seq,base+seq+(1<<32),base+seq-(1<<32)),key=lambda x:abs(x-self.next))
        if seq<self.next:
            self.duplicates+=1;data=data[self.next-seq:];seq=self.next
        if not data:return b''
        self.pending[seq]=data
        if len(self.pending)>1024 or sum(map(len,self.pending.values()))>4*1024*1024:
            self.resets+=1;self.pending.clear();self.next=seq+len(data)
            return b''
        output=[]
        while self.pending:
            first=min(self.pending)
            if first>self.next:break
            block=self.pending.pop(first)
            block=block[max(0,self.next-first):]
            output.append(block);self.next+=len(block)
        return b''.join(output)


def decode(path):
    from pymavlink.dialects.v20 import common
    streams={};parsers={};counts=Counter();pending=OrderedDict();seen=set();pairs=[]
    bad=0;reordered_times=0
    for wall,key,seq,flags,payload in packets(path):
        if not payload and not flags&2:continue
        stream=streams.setdefault(key,Reassembly())
        if flags&2 or key not in parsers:
            parsers[key]=common.MAVLink(None);parsers[key].robust_parsing=True
        data=stream.feed(seq,payload,bool(flags&2))
        if not data:continue
        for msg in parsers[key].parse_buffer(data) or []:
            kind=msg.get_type();counts[kind]+=1
            if kind=='BAD_DATA':bad+=1;continue
            if kind=='HIL_SENSOR' and key[1]==4560:
                pending.setdefault(int(msg.time_usec),wall)
                if len(pending)>100000:pending.popitem(last=False)
            elif kind=='HIL_ACTUATOR_CONTROLS' and key[3]==4560:
                stamp=int(msg.time_usec)
                if stamp not in pending or stamp in seen:continue
                delta=wall-pending[stamp]
                if delta<0:reordered_times+=1;continue
                seen.add(stamp)
                pairs.append(dict(sim_us=stamp,sensor_wall_ns=pending[stamp],actuator_wall_ns=wall,
                                  sensor_to_reply_wall_ms=delta/1e6))
    return dict(scope='传感器发送到同 time_usec 执行器回复的主机观测耗时，含 PX4 运算，不是纯网络单向延迟；不包含回复后 AirSim 物理应用延迟',
                counts=dict(counts),pairs=pairs,unmatched_sensor_count=len(set(pending)-seen),
                bad_mavlink_fragments=bad,negative_pairs=reordered_times,
                tcp_duplicates=sum(s.duplicates for s in streams.values()),
                tcp_reassembly_resets=sum(s.resets for s in streams.values()),
                tcp_unfilled_segments=sum(len(s.pending) for s in streams.values()),
                timestamp_pairing='exact time_usec only; no nearest-time invented matches')
