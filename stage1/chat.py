"""PC：交互式 ROS 2 聊天，直接执行，无需构建自定义消息。"""
import json
import time
import uuid

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

REQUEST_TOPIC = '/uav/robopi_01/chat/request'
RESPONSE_TOPIC = '/uav/robopi_01/chat/response'


def main():
    rclpy.init()
    node = Node('chat_pc')
    publisher = node.create_publisher(String, REQUEST_TOPIC, 10)
    pending = {}

    def receive(message):
        try:
            response = json.loads(message.data)
            if isinstance(response, dict) and response.get('id') == pending.get('id'):
                pending['response'] = response
        except ValueError:
            pass

    subscription = node.create_subscription(String, RESPONSE_TOPIC, receive, 10)
    try:
        deadline = time.monotonic() + 15
        while publisher.get_subscription_count() == 0 or node.count_publishers(RESPONSE_TOPIC) == 0:
            if time.monotonic() >= deadline:
                raise RuntimeError('15 秒内未发现板端节点，请检查 DDS 域、网络和节点状态')
            rclpy.spin_once(node, timeout_sec=0.1)
        while rclpy.ok():
            prompt = input('问题（输入 /quit 退出）：')
            if prompt == '/quit':
                break
            if not prompt.strip():
                continue
            pending.clear()
            pending['id'] = uuid.uuid4().hex
            message = String()
            message.data = json.dumps({'id': pending['id'], 'prompt': prompt}, ensure_ascii=False)
            publisher.publish(message)
            deadline = time.monotonic() + 330
            while 'response' not in pending and time.monotonic() < deadline and rclpy.ok():
                rclpy.spin_once(node, timeout_sec=0.1)
            response = pending.get('response')
            if response is None:
                print('通信超时；不自动重发，板端请求可能仍在执行。')
            elif response.get('status') == 'ok':
                print(response.get('output', ''))
            else:
                print(response.get('status'), response.get('error', ''))
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
