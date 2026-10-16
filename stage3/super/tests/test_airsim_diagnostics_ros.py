"""无 Agent/PX4 的 ROS 域隔离检查：诊断控制必须显式触发且可中止。"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

try:
    import rclpy
except ImportError as exc:
    raise unittest.SkipTest('需要隔离的 Humble + PX4/SUPER 消息环境') from exc

HERE=Path(__file__).resolve().parents[1]/'airsim'
sys.path.insert(0,str(HERE/'diagnostics'))
from response_node import Response
from px4_msgs.msg import VehicleStatus
from std_msgs.msg import String


class ResponseTests(unittest.TestCase):
    def test_idle_no_control_and_cancel_latches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'response_profile.json').write_bytes((HERE/'diagnostics/response_profile.json').read_bytes())
            (root/'task.json').write_bytes((HERE/'task.low.json').read_bytes())
            rclpy.init();node=Response(root)
            try:
                node.sp_pub=Mock();node.hb_pub=Mock();node.cmd_pub=Mock()
                node.tick();node.sp_pub.publish.assert_not_called();node.cmd_pub.publish.assert_not_called()
                node.vehicle=VehicleStatus();node.vehicle.pre_flight_checks_pass=True
                node.vehicle.arming_state=VehicleStatus.ARMING_STATE_DISARMED
                node.p=[0.,0.,0.];node.v=[0.,0.,0.];node.yaw=0.;node.sample_s=0.
                with patch.object(node,'healthy',return_value=True):
                    (root/'land.request.json').write_text('{}')
                    node.request(String(data='start'));self.assertEqual(node.mode,'idle')
                    (root/'land.request.json').unlink()
                    node.request(String(data='start'));self.assertEqual(node.mode,'prestream')
                    (root/'land.request.json').write_text('{}')
                    node.tick();self.assertEqual(node.mode,'land')
                    node.request(String(data='start'));self.assertEqual(node.mode,'land')
                    node.sp_pub.publish.assert_not_called()
                    self.assertTrue(node.failed)
            finally:node.destroy_node();rclpy.shutdown()


if __name__=='__main__':unittest.main()
