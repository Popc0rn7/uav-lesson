"""原生开赛必须先于课程控制；准备过程不能发送解锁或 Offboard。"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import race
import flight


class RaceLifecycleTest(unittest.TestCase):
    def test_prepared_rejects_controller_before_any_rpc(self):
        with patch.object(flight, 'rpc') as rpc, patch.object(flight, 'FlightCheck') as controller:
            with self.assertRaisesRegex(RuntimeError, '尚未开始原生比赛'):
                flight.fly({'race': {'phase': 'prepared'}})
            rpc.assert_not_called()
            controller.assert_not_called()

    def test_native_race_reset_rejects_controller(self):
        with patch.object(flight, 'rpc', return_value=False), patch.object(flight, 'FlightCheck') as controller:
            with self.assertRaisesRegex(RuntimeError, '结束或被复位'):
                flight.fly({'race': {'phase': 'racing'}})
            controller.assert_not_called()

    def test_start_confirms_native_tier_before_releasing_controller(self):
        state = {'race': {'phase': 'prepared'}}
        calls = []
        def rpc(state, method, *args):
            self.assertEqual(state['race']['phase'], 'prepared')
            calls.append((method, args))
            return True if method == 'simGetDisqualified' else None
        with patch.object(race.process_manager, 'px4', return_value=SimpleNamespace(stdout='arming_state: 1')) as px4, \
                patch.object(race, 'ready', return_value=True), \
                patch.object(race, 'rpc', side_effect=rpc), \
                patch.object(race.process_manager, 'write_state'):
            race.start_race(state)
            self.assertEqual(calls, [('simStartRace', (2,)), ('simGetDisqualified', ('drone_2',))])
            self.assertEqual(state['race']['phase'], 'racing')
            px4.assert_called_once_with(state, 'listener', 'vehicle_status')

    def test_failed_native_start_keeps_control_closed(self):
        state = {'race': {'phase': 'prepared'}}
        with patch.object(race.process_manager, 'px4', return_value=SimpleNamespace(stdout='arming_state: 1')), \
                patch.object(race, 'ready', return_value=True), patch.object(race, 'rpc', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '拒绝开赛'):
                race.start_race(state)
            self.assertEqual(state['race']['phase'], 'prepared')


if __name__ == '__main__':
    unittest.main()
