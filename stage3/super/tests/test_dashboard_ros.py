"""ROS 隔离检查：独立仪表盘无控制发布器、不保留整轮参考历史。"""
import io
import contextlib
import json
from pathlib import Path
import sys
import unittest
import tempfile
import time
from unittest.mock import Mock,patch

try:
    import rclpy
except ImportError as exc:
    raise unittest.SkipTest('需要 Humble + PX4/SUPER 消息环境') from exc

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'airsim'))
from verify_stack import Probe
from dashboard import Dashboard
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from mars_quadrotor_msgs.msg import PositionCommand
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import PointCloud2
from px4_msgs.msg import VehicleStatus
import verify_stack


class DashboardRosTests(unittest.TestCase):
    def test_readonly_live_conversion_and_no_mission_publisher(self):
        rclpy.init();ui=Dashboard(stream=io.StringIO());node=Probe(ui,telemetry_only=True)
        try:
            self.assertIsNone(node.request)
            node.save('control',String(data='track: tracking SUPER'))
            msg=Odometry();msg.header.stamp.sec=1;msg.twist.twist.linear.x=3.;msg.twist.twist.linear.y=4.
            node.save('odom',msg)
            node.save('sent',PositionCommand());node.display(dict(speed_m_s=8.),force=True)
            self.assertEqual(ui.metrics()['tracking_peak_speed_m_s'],5.)
            self.assertEqual(node.references,[])
            self.assertIn('实际速度 5.00',ui.stream.getvalue())
        finally:node.destroy_node();rclpy.shutdown()

    def test_collision_monitor_only_checks_flight(self):
        from types import SimpleNamespace
        node=SimpleNamespace(latest={},baseline_collision=1,contacts=[],collision=False)
        with patch('verify_stack.rpc',return_value=dict(has_collided=True,time_stamp=2)) as call:
            for mode in ('land: requested landing','idle: local_ready; send takeoff'):
                node.latest['control']=String(data=mode)
                Probe.poll_collision(node)
            call.assert_not_called()
            node.latest['control']=String(data='track: tracking SUPER')
            Probe.poll_collision(node)
            call.assert_called_once()
            self.assertTrue(node.collision)
            self.assertEqual(node.contacts,[dict(data=dict(has_collided=True,time_stamp=2))])

    def test_task_cli_keeps_dashboard_and_success_report_in_isolated_ros(self):
        real_path=Path;calls=0;route_calls=0
        class SimulatedProbe(Probe):
            def __init__(self,*a,**kw):
                super().__init__(*a,**kw);self.request=Mock()
            def poll_collision(self):pass
        def spin(node,timeout_sec):
            nonlocal calls,route_calls
            calls+=1;time.sleep(.055)
            started=node.request.publish.called
            if started:route_calls+=1
            done=route_calls>=6
            c=Clock();c.clock.sec=100;c.clock.nanosec=calls*60_000_000
            node.save('clock',c)
            ref=PositionCommand();ref.header.stamp=c.clock;ref.velocity.x=3.;ref.velocity.y=4.
            node.save('sent',ref);node.save('cmd',ref)
            control='track: tracking SUPER' if started and not done else 'idle: local_ready'
            node.save('control',String(data=control))
            status='complete: landed/disarmed' if done else 'takeoff; waypoint=1/2' if route_calls==1 else 'route; waypoint=1/2' if started else 'idle; waypoint=1/2'
            node.save('task',String(data=status))
            odom=Odometry();odom.header.stamp=c.clock
            odom.pose.pose.position.x=1.91  # 超过旧 0.8 m 门限仍正常完成，误差只作为指标
            odom.twist.twist.linear.x=3. if started and not done else 0.;odom.twist.twist.linear.y=4. if started and not done else 0.
            node.save('odom',odom)
            vehicle=VehicleStatus();vehicle.arming_state=VehicleStatus.ARMING_STATE_DISARMED if done or not started else VehicleStatus.ARMING_STATE_ARMED
            node.save('vehicle',vehicle)
            cloud=PointCloud2();cloud.width=1
            for key in ('cloud','map','inflated'):node.save(key,cloud)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=io.StringIO()
            task=json.loads((real_path(__file__).resolve().parents[1]/'airsim/task.low.json').read_text())
            def path(value):return root if str(value)=='/run/airsim' else real_path(value)
            with patch('verify_stack.Probe',SimulatedProbe),patch('verify_stack.load_task',return_value=task), \
                 patch('verify_stack.Path',side_effect=path),patch('verify_stack.rclpy.spin_once',side_effect=spin), \
                 patch('sys.argv',['verify_stack.py','fly','--dashboard','plain']),contextlib.redirect_stdout(output):
                verify_stack.main()
            report=json.loads(next(root.glob('fly-task-*.json')).read_text())
            self.assertAlmostEqual(report['summary']['max_tracking_error_m'],1.91);
            self.assertTrue(report['summary']['success']);self.assertTrue(report['summary']['disarmed_confirmed'])
            self.assertEqual(report['summary']['dashboard_window']['tracking_peak_speed_m_s'],5.)
            self.assertIn('最终遥测快照',output.getvalue());self.assertIn('报告：',output.getvalue())


if __name__=='__main__':unittest.main()
