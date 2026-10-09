"""RoboPi：ROS 2 文本推理桥，依赖板端已适配的 rclpy/std_msgs。"""
import json
from queue import Empty, Queue
from threading import Thread

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import String

from backend import infer, InferenceError

REQUEST_TOPIC = '/uav/robopi_01/chat/request'
RESPONSE_TOPIC = '/uav/robopi_01/chat/response'
MAX_PROMPT_BYTES = 16384


class ChatNode(Node):
    def __init__(self):
        super().__init__('qwen_chat', namespace='/uav/robopi_01')
        self.publisher = self.create_publisher(String, RESPONSE_TOPIC, 10)
        self.subscription = self.create_subscription(String, REQUEST_TOPIC, self.receive, 10)
        self.results = Queue()
        self.worker = None
        self.create_timer(0.1, self.publish_results)

    def send(self, request_id, status, **payload):
        message = String()
        message.data = json.dumps({'id': request_id, 'status': status, **payload}, ensure_ascii=False)
        self.publisher.publish(message)

    def receive(self, message):
        request_id = None
        try:
            if len(message.data.encode('utf-8')) > MAX_PROMPT_BYTES + 1024:
                raise ValueError('请求过长')
            request = json.loads(message.data)
            if not isinstance(request, dict):
                raise ValueError('请求必须为 JSON 对象')
            request_id = request.get('id')
            if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
                request_id = None
                raise ValueError('id 必须为 1–128 字符字符串')
            prompt = request.get('prompt')
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode('utf-8')) > MAX_PROMPT_BYTES:
                raise ValueError('prompt 必须非空且不超过 16 KiB')
        except (ValueError, TypeError) as error:
            self.send(request_id, 'invalid', error=str(error))
            return
        if self.worker is not None:
            self.send(request_id, 'busy', error='已有推理请求运行中，请稍后重试')
            return
        self.worker = Thread(target=self.run_request, args=(request_id, prompt), daemon=False)
        self.worker.start()

    def run_request(self, request_id, prompt):
        try:
            result = {'status': 'ok', **infer(prompt)}
        except InferenceError as error:
            result = {'status': error.status, 'error': str(error)}
        except Exception as error:
            result = {'status': 'error', 'error': str(error)}
        self.results.put((request_id, result))

    def publish_results(self):
        try:
            request_id, result = self.results.get_nowait()
        except Empty:
            return
        self.worker.join()
        self.worker = None
        self.send(request_id, **result)


def main():
    rclpy.init()
    node = ChatNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RuntimeError:
        # Humble 的信号关闭可能在 wait set 创建期间撤销 context。
        if rclpy.ok():
            raise
    finally:
        # 等待本次 HTTP 请求返回；ROS 节点退出不停止常驻模型服务。
        if node.worker is not None:
            node.worker.join()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
