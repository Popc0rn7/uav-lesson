"""PC：生成显式接口与单播对端的 Fast DDS UDP profile，避免多网卡误选。"""
import argparse
import ipaddress
from pathlib import Path
import xml.etree.ElementTree as ET


def probe_interface(address):
    """只读检查 Linux/OHOS 上该 IPv4 的网卡与物理链路。"""
    import fcntl
    import socket
    import struct
    from pathlib import Path
    socket.inet_pton(socket.AF_INET,address)
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as channel:
        try:
            channel.bind((address,0))  # Refuse an address that disappeared after link loss.
        except OSError as exc:
            raise RuntimeError('本机未配置本次测试地址：'+address) from exc
        for _,name in socket.if_nameindex():
            try:
                value=fcntl.ioctl(channel.fileno(),0x8915,struct.pack('256s',name.encode()[:15]))
            except OSError:
                continue
            if socket.inet_ntoa(value[20:24])!=address:continue
            carrier=(Path('/sys/class/net')/name/'carrier').read_text().strip()
            if carrier!='1':raise RuntimeError('网卡物理链路未就绪：'+name)
            return dict(address=address,interface=name,carrier=1)
    raise RuntimeError('未找到该 IPv4 的活动网卡：'+address)


def write_profile(local, peer, output, *, loopback=False):
    local=str(ipaddress.IPv4Address(local));peer=str(ipaddress.IPv4Address(peer))
    root=ET.Element('profiles',xmlns='http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles')
    descriptors=ET.SubElement(root,'transport_descriptors')
    transport=ET.SubElement(descriptors,'transport_descriptor')
    for key,value in [('transport_id','uav_ethernet'),('type','UDPv4'),('sendBufferSize','4194304'),
                      ('receiveBufferSize','4194304'),('maxInitialPeersRange','32')]:
        ET.SubElement(transport,key).text=value
    whitelist=ET.SubElement(transport,'interfaceWhiteList')
    ET.SubElement(whitelist,'address').text=local
    if loopback:ET.SubElement(whitelist,'address').text='127.0.0.1'
    participant=ET.SubElement(root,'participant',profile_name='uav_ethernet',is_default_profile='true')
    rtps=ET.SubElement(participant,'rtps')
    builtin=ET.SubElement(rtps,'builtin')
    peers=ET.SubElement(builtin,'initialPeersList')
    # The Agent, clock, raw sensor bridge and verifier share one PC host;
    # board algorithms also need discovery between local participants.
    for address in ((local,peer,'127.0.0.1') if loopback else (local,peer)):
        locator=ET.SubElement(peers,'locator')
        ET.SubElement(ET.SubElement(locator,'udpv4'),'address').text=address
    ET.SubElement(ET.SubElement(rtps,'userTransports'),'transport_id').text='uav_ethernet'
    ET.SubElement(rtps,'useBuiltinTransports').text='false'
    ET.indent(root)
    Path(output).write_text(ET.tostring(root,encoding='unicode')+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local',required=True);parser.add_argument('--peer',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();write_profile(args.local,args.peer,args.output)
