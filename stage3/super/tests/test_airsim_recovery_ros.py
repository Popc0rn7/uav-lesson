"""无 PX4/Agent 的隔离 ROS 测试：人工 land 不得被任务重新切回 Offboard。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
import numpy as np

try:
    import rclpy
except ImportError as exc:
    raise unittest.SkipTest('需要隔离的 Humble + PX4/SUPER 消息环境') from exc

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE/'airsim'))
from super_px4 import Bridge
from waypoint_task import Waypoints
from std_msgs.msg import String


class CancelTests(unittest.TestCase):
    def test_direct_goal_stays_at_far_endpoint(self):
        from task_config import load_task
        from geometry_msgs.msg import PoseStamped
        task = load_task(HERE/'airsim/task.forest10-ab.json')
        sent = []
        mission = SimpleNamespace(task=task, anchor=None, index=0, carrot=None,
            position=np.array([0., 0., 2.]), velocity=np.zeros(3), hold_started=None,
            goals=SimpleNamespace(publish=sent.append),
            get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(
                to_msg=lambda: PoseStamped().header.stamp)))
        Waypoints.target(mission, 1.)
        mission.position = np.array([-5., 50., 3.])
        Waypoints.target(mission, 2.)
        self.assertEqual(len(sent), 1)
        p = sent[0].pose.position
        np.testing.assert_allclose([p.x,p.y,p.z], task['waypoints_enu_m'][0])
        self.assertEqual(mission.index, 0)

    def test_operator_cancel_during_prestream(self):
        with tempfile.TemporaryDirectory() as directory:
            task=Path(directory)/'task.json'
            task.write_text((HERE/'airsim/task.low.json').read_text())
            rclpy.init(args=['--ros-args','-p','airsim_task_config:='+str(task),'-p','task_config:='+str(task)])
            bridge=Bridge();mission=Waypoints()
            try:
                bridge.mode='prestream';bridge.sample=bridge.goal=[1,2,3]
                mission.mode='route'
                (task.parent/'land.request.json').write_text(json.dumps(dict(owner='test')))
                bridge.tick();mission.tick()
                self.assertEqual(bridge.mode,'land')
                self.assertIsNone(bridge.sample)
                self.assertIsNone(bridge.goal)
                self.assertTrue(mission.mode.startswith('failed:'))
                mission.mode='idle';mission.control='idle: local_ready'
                mission.request(String(data='start'))
                self.assertTrue(mission.mode.startswith('failed:'))
                bridge.mode='idle'
                bridge.tick()
                self.assertIn('cancelled',bridge.reason)
            finally:
                bridge.destroy_node();mission.destroy_node();rclpy.shutdown()


if __name__=='__main__': unittest.main()
