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
    def test_ab_limits_observe_but_invalid_commands_still_land(self):
        from task_config import load_task
        from mars_quadrotor_msgs.msg import PositionCommand
        for filename in ('task.forest10-ab.json', 'task.forest5-ab-observe.json'):
            task = load_task(HERE/'airsim'/filename)
            landed=[];events=[]
            bridge = SimpleNamespace(mode='track', airsim_task=task, corridor=False,
                p=[19.9,48.,7.], speed_limit=task['speed_m_s']+1., limit_violations=(),
                profile=SimpleNamespace(emit=lambda kind,**values:events.append((kind,values))),
                get_logger=lambda:SimpleNamespace(warning=lambda text:None),
                get_clock=lambda:SimpleNamespace(now=lambda:SimpleNamespace(nanoseconds=1000000000)),
                land=landed.append)
            msg=PositionCommand();msg.header.frame_id='world';msg.header.stamp.sec=1
            msg.position.x=20.00217;msg.position.y=48.;msg.position.z=7.
            Bridge.accept(bridge,msg)
            self.assertEqual(landed,[])
            self.assertEqual(bridge.sample[0][0],20.00217)
            self.assertEqual(bridge.limit_violations,('task_bounds',))
            # Exercise all other envelope checks as well, rather than only the
            # millimetre overrun that originally terminated the flight.
            msg.position.x=25.;msg.velocity.x=20.;msg.acceleration.x=10.
            Bridge.accept(bridge,msg)
            self.assertEqual(landed,[])
            self.assertEqual(set(bridge.limit_violations),{'task_bounds','reference_speed',
                'reference_acceleration','tracking_error'})
            task['trajectory_limits_action']='land'
            Bridge.accept(bridge,msg)
            self.assertIn('limits=',landed.pop())
            task['trajectory_limits_action']='observe'
            msg.position.x=float('nan')
            Bridge.accept(bridge,msg)
            self.assertIn('non-finite',landed.pop())
            msg.position.x=20.;msg.header.stamp.sec=0
            Bridge.accept(bridge,msg)
            self.assertIn('stamp age=',landed.pop())

    def test_lidar_observation_preserves_flight_and_records_recovery(self):
        events=[];land=[]
        bridge=SimpleNamespace(cloud_at=10.,cloud_loss_at=None,lidar_loss_action='observe',mode='track',
            profile=SimpleNamespace(emit=lambda kind,**values:events.append((kind,values))),
            get_logger=lambda:SimpleNamespace(warning=lambda text:None,info=lambda text:None),land=land.append)
        self.assertFalse(Bridge.lidar_watchdog(bridge,11.,True))
        self.assertEqual(land,[])
        self.assertEqual(events[0][0],'cloud_loss_started')
        bridge.cloud_at=12.
        self.assertFalse(Bridge.lidar_watchdog(bridge,12.1,True))
        self.assertEqual(events[-1][1]['gap_wall_s'],2.)
        bridge.lidar_loss_action='land'
        self.assertTrue(Bridge.lidar_watchdog(bridge,13.,True))
        self.assertEqual(land,['lidar cloud timeout'])

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
