"""旧 ADRL 与 PX4 共用 1/1 时，转发 GCS 心跳不能覆盖飞控状态。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'stage3/super/airsim'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pymavlink import mavutil
from flight import FlightCheck


def heartbeat(autopilot, armed, custom_mode):
    msg = mavutil.mavlink.MAVLink_heartbeat_message(
        2, autopilot, 128 if armed else 0, custom_mode, 4, 3)
    msg._header.srcSystem = 1
    msg._header.srcComponent = 1
    return msg


class Link:
    def __init__(self, messages):
        self.messages = iter(messages)

    def recv_match(self, **kwargs):
        return next(self.messages, None)


class TelemetryTest(unittest.TestCase):
    def test_forwarded_gcs_heartbeat_does_not_change_mode_or_arming(self):
        px4 = heartbeat(mavutil.mavlink.MAV_AUTOPILOT_PX4, True, 6 << 16)
        gcs = heartbeat(mavutil.mavlink.MAV_AUTOPILOT_GENERIC, False, 0)
        check = FlightCheck({})
        check.link = Link([px4, gcs])
        check.pump()
        self.assertIs(check.messages['HEARTBEAT'], px4)
        self.assertTrue(check.armed())
        self.assertEqual(check.mode(), 'OFFBOARD')

    def test_gcs_alone_is_not_autopilot_readiness(self):
        check = FlightCheck({})
        check.link = Link([heartbeat(0, False, 0)])
        check.pump()
        self.assertNotIn('HEARTBEAT', check.messages)


class AcknowledgementTest(unittest.TestCase):
    def test_ack_for_other_client_cannot_confirm_our_command(self):
        from types import SimpleNamespace
        def ack(target):
            return SimpleNamespace(get_type=lambda: 'COMMAND_ACK', get_srcSystem=lambda: 1,
                get_srcComponent=lambda: 1, target_system=target,
                command=mavutil.mavlink.MAV_CMD_DO_SET_MODE, result=0)
        check = FlightCheck({})
        other = ack(134)
        check.link = Link([other])
        check.pump()
        self.assertNotIn(other.command, check.acks)
        ours = ack(245)
        check.link = Link([ours])
        check.pump()
        self.assertIs(check.acks[ours.command], ours)


class OwnershipTest(unittest.TestCase):
    def active_check(self, mode):
        check = FlightCheck({})
        check.link = Link([heartbeat(mavutil.mavlink.MAV_AUTOPILOT_PX4, True, mode)])
        check.control_active = True
        check.armed_seen = True
        return check

    def test_hold_takeover_blocks_setpoints_and_cleanup_land(self):
        from flight import ControlReleased
        check = self.active_check((4 << 16) | (3 << 24))
        with self.assertRaises(ControlReleased):
            check.send([0, 0, -2])
        self.assertEqual(check.yielded_mode, 'LOITER')
        self.assertEqual(check.setpoint_count, 0)
        with self.assertRaises(ControlReleased):
            check.land()
        # 外部后来再切回 Offboard，也不恢复这个已经退出的控制器。
        check.link = Link([heartbeat(mavutil.mavlink.MAV_AUTOPILOT_PX4, True, 6 << 16)])
        with self.assertRaises(ControlReleased):
            check.command(mavutil.mavlink.MAV_CMD_DO_SET_MODE, 1, 6)

    def test_handoff_during_landing_does_not_reissue_land(self):
        from flight import ControlReleased
        check = self.active_check((4 << 16) | (3 << 24))
        check.landing = True
        with self.assertRaises(ControlReleased):
            check.command(mavutil.mavlink.MAV_CMD_NAV_LAND)

    def test_stale_heartbeat_is_not_claimed_as_manual_takeover(self):
        import time
        from flight import ControlReleased
        check = self.active_check((4 << 16) | (3 << 24))
        check.pump()
        check.received['HEARTBEAT'] = time.monotonic()-5
        with self.assertRaises(RuntimeError) as caught:
            check.check_owner()
        self.assertNotIsInstance(caught.exception, ControlReleased)
        self.assertFalse(check.control_yielded)

    def test_denied_ack_aborts_mode_entry(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        check = FlightCheck({})
        check.command = Mock()
        check.send = Mock()
        command = mavutil.mavlink.MAV_CMD_DO_SET_MODE
        check.tick = Mock(side_effect=lambda *args: check.acks.update(
            {command: SimpleNamespace(result=mavutil.mavlink.MAV_RESULT_DENIED)}))
        with self.assertRaisesRegex(RuntimeError, '拒绝命令'):
            check.confirmed_command(command, [1, 6], [0, 0, -2], lambda: False, 'test')
        check.command.assert_called_once_with(command, 1, 6)


if __name__ == '__main__':
    unittest.main()
