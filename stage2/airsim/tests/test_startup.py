"""QGC 未完成解锁条件时，仍应能完成场景初始化。"""
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import race


class StartupTest(unittest.TestCase):
    def test_reset_restarts_with_original_configuration(self):
        state = {'config': dict(settings_input='/tmp/settings.json', image='sha256:test',
                                window_mode='maximized')}
        args = SimpleNamespace(display=':1')
        with patch.object(race.process_manager, 'px4', return_value=SimpleNamespace(stdout='arming_state: 1')), \
                patch.object(race, 'rpc', return_value=False), \
                patch.object(race, 'shutdown') as stop, patch.object(race, 'up') as start:
            race.reset_race(state, args)
            stop.assert_called_once_with(state)
            start.assert_called_once_with(args)
            self.assertEqual(args.settings, Path('/tmp/settings.json'))
            self.assertEqual(args.image, 'sha256:test')
            self.assertEqual(args.window_mode, 'maximized')

    def test_race_reset_refuses_armed_vehicle(self):
        with patch.object(race.process_manager, 'px4', return_value=SimpleNamespace(stdout='arming_state: 2')), \
                patch.object(race, 'rpc') as rpc:
            with self.assertRaisesRegex(RuntimeError, '解除解锁'):
                race.reset_race({}, 0)
            rpc.assert_not_called()

    def test_race_reset_refuses_api_control(self):
        with patch.object(race.process_manager, 'px4', return_value=SimpleNamespace(stdout='arming_state: 1')), \
                patch.object(race, 'rpc', return_value=True) as rpc:
            with self.assertRaisesRegex(RuntimeError, 'API 控制'):
                race.reset_race({}, 0)
            rpc.assert_called_once_with({}, 'isApiControlEnabled', 'PX4')

    def test_listener_timeout_during_level_change_is_not_fatal(self):
        with patch.object(race, 'check_ready', side_effect=subprocess.TimeoutExpired('listener', 6)):
            self.assertFalse(race.ready({}, require_preflight=False))

    def test_failed_preflight_allows_scene_but_blocks_flight(self):
        def px4(state, module, *args):
            output = {'sensor_combined': '    timestamp: 1\n    timestamp: 2\n',
                      'vehicle_local_position': 'xy_valid: True\nz_valid: True',
                      'check': 'Preflight check: FAILED'}[args[0]]
            return SimpleNamespace(returncode=0, stdout=output)

        with patch.object(race.process_manager, 'host_alive', return_value=True), \
                patch.object(race.process_manager, 'owned_container', return_value={'State': {'Running': True}}), \
                patch.object(race.process_manager, 'px4', side_effect=px4), \
                patch.object(race, 'rpc', side_effect=lambda state, method, *args:
                             True if method == 'ping' else {'kinematics_estimated': {}}):
            self.assertTrue(race.ready({}, require_preflight=False))
            self.assertFalse(race.ready({}))


if __name__ == '__main__':
    unittest.main()
