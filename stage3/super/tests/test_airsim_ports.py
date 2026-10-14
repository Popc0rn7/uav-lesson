"""PC：端口检查必须区分 TIME_WAIT、监听者及权限错误。"""
import errno
import importlib.util
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "airsim_runtime", Path(__file__).resolve().parents[1] / "airsim/runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class PortTests(unittest.TestCase):
    def test_listener_rejected(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with self.assertRaisesRegex(RuntimeError, "已占用"):
                runtime.check_port(socket.SOCK_STREAM, listener.getsockname()[1])

    def test_real_time_wait_recognized(self):
        # 不设置 SO_REUSEADDR，复现旧场景关闭后的不可立即复用连接。
        with socket.socket() as server, socket.socket() as client:
            server.bind(("127.0.0.1", 0))
            server.listen()
            port = server.getsockname()[1]
            client.connect(("127.0.0.1", port))
            conn, _ = server.accept()
            conn.close()
            self.assertEqual(client.recv(1), b"")
        self.assertIn("06", runtime.tcp_states(port))
        with self.assertRaisesRegex(RuntimeError, "TIME_WAIT.*等待超时"):
            runtime.check_port(socket.SOCK_STREAM, port, time_wait_timeout_s=0)

    def test_retries_until_released(self):
        with patch.object(runtime.socket, "socket") as factory, \
                patch.object(runtime, "tcp_states", return_value=["06"]), \
                patch.object(runtime.time, "sleep") as sleep:
            factory.return_value.__enter__.return_value.bind.side_effect = [
                OSError(errno.EADDRINUSE, "busy"), None]
            runtime.check_port(socket.SOCK_STREAM, 4560)
            sleep.assert_called_once_with(.5)

    def test_permission_error_preserved(self):
        with patch.object(runtime.socket, "socket") as factory:
            factory.return_value.__enter__.return_value.bind.side_effect = PermissionError(
                errno.EACCES, "denied")
            with self.assertRaisesRegex(RuntimeError, "无法检查 TCP.*denied"):
                runtime.check_port(socket.SOCK_STREAM, 4560)


if __name__ == "__main__":
    unittest.main()
