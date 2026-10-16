#!/usr/bin/env python3
"""独立响应测试的显式触发与只读就绪检查；碰撞仅用于中止测试。"""
import argparse
import json
from pathlib import Path
import sys
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rpc_client import rpc


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['inspect','run'])
    args=parser.parse_args()
    rclpy.init();node=Node('response_probe_'+str(time.time_ns()));latest={};received=0
    def status(msg):
        nonlocal latest,received
        latest=json.loads(msg.data);received=time.monotonic()
    node.create_subscription(String,'/diagnostics/status',status,10)
    pub=node.create_publisher(String,'/diagnostics/command',10)
    requested=False;last_collision=0;collision_stamp=None
    try:
        end=time.monotonic()+25
        while time.monotonic()<end:
            rclpy.spin_once(node,timeout_sec=.05)
            if latest.get('mode')=='idle' and latest.get('ready'):break
        else:raise RuntimeError('诊断 DDS/定位/预检未就绪：'+str(latest))
        if args.action=='inspect':print('diagnostic ready; disarmed');return
        pub.publish(String(data='start'));requested=True
        end=time.monotonic()+300
        while time.monotonic()<end:
            rclpy.spin_once(node,timeout_sec=.02)
            if time.monotonic()-received>1.5:raise RuntimeError('诊断控制器状态失流')
            if latest.get('mode')=='complete':
                path=Path(latest['report']);report=json.loads(path.read_text())
                print(json.dumps(report['summary'],indent=2,ensure_ascii=False));print('报告：'+str(path))
                if not report['summary']['success']:raise RuntimeError('响应测试失败：'+report['summary']['reason'])
                return
            if time.monotonic()-last_collision>.2 and latest.get('mode') not in ('land','complete'):
                data=rpc('simGetCollisionInfo','PX4',timeout=.3)
                if (collision_stamp is not None and data['has_collided'] and data['time_stamp']!=collision_stamp
                        and latest.get('mode')=='track'):
                    Path('/run/airsim/diagnostic-collision.json').write_text(json.dumps(data,indent=2))
                    pub.publish(String(data='collision'))
                collision_stamp=data['time_stamp'];last_collision=time.monotonic()
        raise RuntimeError('响应测试总等待超时；可用正常 runtime 的 land/stop 指向诊断状态目录恢复')
    except BaseException:
        if requested:
            pub.publish(String(data='land'))
            # 让请求送出；飞控节点仍独立执行降落，不随 probe 退出。
            for _ in range(5):rclpy.spin_once(node,timeout_sec=.05)
        raise
    finally:node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':main()
