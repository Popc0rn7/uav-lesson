#!/usr/bin/env python3
"""PC ROS 环境：两次文本往返及非法请求检查；只调用板端本地模型。"""
import json
import time
import uuid
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


def main():
    rclpy.init()
    node=Node('stage1_chat_regression')
    publisher=node.create_publisher(String,'/uav/robopi_01/chat/request',10)
    responses={}
    def receive(message):
        value=json.loads(message.data)
        if value.get('id'):responses[value['id']]=value
    subscription=node.create_subscription(String,'/uav/robopi_01/chat/response',receive,10)
    def wait(predicate,seconds):
        deadline=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>deadline:raise RuntimeError('ROS 聊天验收超时，不自动重发')
            rclpy.spin_once(node,timeout_sec=.1)
    def request(prompt,expected):
        key=uuid.uuid4().hex
        publisher.publish(String(data=json.dumps(dict(id=key,prompt=prompt),ensure_ascii=False)))
        started=time.monotonic()
        wait(lambda:key in responses,330)
        response=responses[key]
        if response.get('status')!=expected:raise RuntimeError('非预期回复：'+json.dumps(response,ensure_ascii=False))
        if expected=='ok' and not response.get('output','').strip():raise RuntimeError('空模型回复')
        return dict(response=response,seconds=time.monotonic()-started)
    try:
        wait(lambda:publisher.get_subscription_count()>0 and node.count_publishers('/uav/robopi_01/chat/response')>0,15)
        results=[request('只回答数字：1+1等于几？','ok'),request('中国的首都是哪里？请简短回答。','ok')]
        results.append(request('','invalid'))
        print('STAGE1_RESULT:'+json.dumps(dict(passed=True,results=results),ensure_ascii=False))
    finally:
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()


if __name__=='__main__':main()
