"""PC 诊断环境：检查飞行轨迹导数和遥测失流拒绝。"""
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'airsim'))
try:
    from verify_offboard import Check, trajectory, circle_trajectory
except ModuleNotFoundError as exc:
    if exc.name == 'pymavlink':
        raise unittest.SkipTest('需要安装 pymavlink 的 AirSim 诊断环境') from exc
    raise


class OffboardTests(unittest.TestCase):
    def test_closed_trajectory(self):
        origin = [1., -2., -3.]
        for t in (0., 12.):
            p, v, _ = trajectory(t, origin)
            self.assertLess(math.dist(p, origin), 1e-10)
            self.assertLess(math.dist(v, [0, 0, 0]), 1e-10)

    def test_feedforward_matches_position_derivatives(self):
        dt = 1e-4
        for t in (1., 3., 6., 9., 11.):
            _, v, a = trajectory(t, [0., 0., -2.])
            pm, vm, _ = trajectory(t-dt, [0., 0., -2.])
            pp, vp, _ = trajectory(t+dt, [0., 0., -2.])
            for i in range(3):
                self.assertAlmostEqual((pp[i]-pm[i])/(2*dt), v[i], places=6)
                self.assertAlmostEqual((vp[i]-vm[i])/(2*dt), a[i], places=6)

    def test_missing_feedback_rejected(self):
        check = Check({})
        check.pump = Mock()
        with self.assertRaisesRegex(RuntimeError, '停流'):
            check.local()

    def test_circle_speed_acceleration_and_derivatives(self):
        origin=[0.,0.,-2.]
        dt=1e-4
        for speed in (1.,2.,3.):
            _,duration=circle_trajectory(0,origin,speed)
            for t in (0.,duration):
                (p,v,a),_=circle_trajectory(t,origin,speed)
                self.assertLess(math.dist(p,origin),1e-9)
                self.assertLess(math.dist(v,[0,0,0]),1e-9)
                self.assertLess(math.dist(a,[0,0,0]),1e-9)
            for t in (1.,2.5,4.,duration-1):
                (p,v,a),_=circle_trajectory(t,origin,speed)
                (pm,vm,_),_=circle_trajectory(t-dt,origin,speed)
                (pp,vp,_),_=circle_trajectory(t+dt,origin,speed)
                self.assertLessEqual(math.dist(p[:2],origin[:2]),4.000001)
                self.assertLessEqual(math.dist(v,[0,0,0]),speed+1e-6)
                self.assertLessEqual(math.dist(a,[0,0,0]),5.)
                for i in range(3):
                    self.assertAlmostEqual((pp[i]-pm[i])/(2*dt),v[i],places=6)
                    self.assertAlmostEqual((vp[i]-vm[i])/(2*dt),a[i],places=6)

    def test_reference_clock_follows_simulation_rate(self):
        check=Check({})
        check.pump=Mock()
        check.clock_samples=[(1.,100.),(2.,102.),(3.,104.)]
        with patch('verify_offboard.time.monotonic',return_value=3.5):
            self.assertAlmostEqual(check.simulation_time(),105.)
            self.assertAlmostEqual(check.clock_rate,2.)
        check.clock_reset=True
        with self.assertRaisesRegex(RuntimeError,'复位'):
            check.simulation_time()

    def test_envelope_does_not_interrupt_landing(self):
        check=Check({},speed=2)
        check.origin=[0,0,0]
        check.local=Mock(return_value=([7,0,-1],[0,0,0]))
        check.messages={'LOCAL_POSITION_NED':SimpleNamespace(time_boot_ms=100)}
        check.received={'LOCAL_POSITION_NED':0.}
        check.link=Mock()
        check.mode=Mock(return_value='LAND')
        check.armed=Mock(return_value=True)
        with patch('verify_offboard.time.sleep'):
            check.tick('land')
        self.assertTrue(check.records[-1]['outside_envelope'])
        with self.assertRaisesRegex(RuntimeError,'包络'):
            check.tick('circle')


if __name__ == '__main__':
    unittest.main()
