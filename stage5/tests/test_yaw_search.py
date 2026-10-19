import math
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_runtime import FlightRuntime
from follow import follow_questions
from stage5.airsim.yaw_search import YawScan
from test_agent_runtime import Flight, Perception, Actor
from test_task_runner import stage


class YawTests(unittest.TestCase):
    def test_no_feedback_never_claims_rotation_finished(self):
        scan = YawScan(0)
        for _ in range(2000):
            command = scan.step(0, .02)
            self.assertLessEqual(command, math.radians(15)+1e-8)
        self.assertEqual(scan.travel, 0)

    def test_wraparound_and_pause_do_not_fabricate_coverage(self):
        scan = YawScan(math.radians(179))
        scan.step(math.radians(179), .02)
        scan.step(math.radians(-179), .02)
        self.assertAlmostEqual(math.degrees(scan.travel), 2)
        scan.pause(1.)
        scan.step(2., .02)
        self.assertAlmostEqual(math.degrees(scan.travel), 2)

    def runtime(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        flight, sensor = Flight(), Perception(); sensor.visible = False
        sensor.reset_association = Mock()
        for item in (patch('agent_runtime.Flight', return_value=flight), patch('agent_runtime.Perception', return_value=sensor),
                     patch('agent_runtime.Tactician', Actor), patch('agent_runtime.target_command'), patch('agent_runtime.fcntl.flock')):
            item.start(); self.addCleanup(item.stop)
        runtime = FlightRuntime({'STAGE5_BACKEND': 'airsim'}, directory.name, time.monotonic()+120)
        self.addCleanup(runtime.close)
        current = stage(skill='follow_vehicle', following_mode='rear_above',
                        allowed_skills=['hold_course', 'brake', 'reacquire', 'scan_yaw'], allocation={'budget': 30, 'timeout': 60})
        runtime.start(current, {'valid_follow_s': 0., 'observed_s': 0.}, {'plan_revision': 1, 'stage_id': 'follow', 'attempt': 1}, Path(directory.name))
        for _ in range(3):
            runtime.service(); runtime.step()
        original = runtime.actor.read
        runtime.actor.read = lambda: {**original(), 'maneuver': 'scan_yaw', 'effective_maneuver': 'scan_yaw', 'actionable': True}
        runtime.last_tick = time.monotonic()-.1
        return runtime, flight, sensor

    def test_jev_can_scan_without_tracking_and_old_eight_second_abort(self):
        runtime, flight, sensor = self.runtime()
        runtime.no_tracking_since = time.monotonic()-9
        self.assertIsNone(runtime.step())
        self.assertTrue(runtime.search_active)
        self.assertGreater(runtime.yaw, 0)
        np.testing.assert_allclose(flight.sent[-1], [0, 0, 0])
        sensor.reset_association.assert_not_called()
        self.assertTrue(runtime.actor.states[-1]['execution_health']['active_search_available'])
        self.assertIn('scan_yaw', follow_questions(runtime.current, simple=True)['maneuver'].criteria)

    def test_candidate_does_not_override_jev_turn_decision(self):
        runtime, flight, sensor = self.runtime(); runtime.step()
        original = sensor.snapshot
        sensor.snapshot = lambda: {**original(), 'detections': [{'label': 'pickup', 'score': .9}]}
        runtime.step()
        self.assertTrue(runtime.search_active)
        np.testing.assert_allclose(flight.sent[-1], [0, 0, 0])

    def test_stale_image_or_decision_stops_scan(self):
        for stale_image in (True, False):
            runtime, flight, sensor = self.runtime(); runtime.step()
            if stale_image:
                original = sensor.snapshot
                sensor.snapshot = lambda: {**original(), 'at': time.monotonic()-2}
            else:
                original = runtime.actor.read
                runtime.actor.read = lambda: {**original(), 'stale': True}
            runtime.step()
            self.assertFalse(runtime.search_active)
            np.testing.assert_allclose(flight.sent[-1], [0, 0, 0])
            runtime.close()

    def test_no_fixed_circle_or_thirty_second_search_end(self):
        runtime, flight, sensor = self.runtime()
        runtime.search_scan.travel = 4*math.pi
        runtime.search_elapsed_s = 31
        runtime.no_tracking_since = time.monotonic()-40
        self.assertIsNone(runtime.step())
        self.assertTrue(runtime.search_active)

    def test_jev_can_stop_turning_before_finding_target(self):
        runtime, flight, sensor = self.runtime()
        runtime.step()
        original = runtime.actor.read
        runtime.actor.read = lambda: {**original(), 'maneuver': 'brake', 'effective_maneuver': 'brake'}
        runtime.step()
        self.assertFalse(runtime.search_active)

    def test_search_has_no_fixed_altitude_boundary(self):
        runtime, flight, sensor = self.runtime()
        runtime.config['AIRSIM_MIN_NED_Z'] = -10.
        own = dict(p=np.array([0., 0., -8.]), q=np.array([1., 0., 0., 0.]), age=0.)
        flight.snapshot = lambda: own
        runtime.service()
        own['p'][2] = -10.1
        runtime.service()
        self.assertFalse(runtime.frozen)

    def test_proxy_approach_moves_without_heading_but_never_counts_following(self):
        runtime, flight, sensor = self.runtime()
        runtime.current['allowed_skills'].append('approach_target')
        sensor.visible = True
        snapshot = sensor.snapshot
        def current():
            value = snapshot()
            value['tracking'].update(control_proxy=True, direction_confirmed=False, target_ned=[20., 0., -2.5])
            return value
        sensor.snapshot = current
        decision = runtime.actor.read
        runtime.actor.read = lambda: {**decision(), 'maneuver': 'approach_target', 'effective_maneuver': 'approach_target'}
        self.assertIsNone(runtime.step())
        self.assertGreater(flight.sent[-1][0], 0)
        self.assertEqual(flight.sent[-1][2], 0)
        self.assertEqual(runtime.progress['valid_follow_s'], 0)
        self.assertEqual(runtime.stats_samples, [])
        # 实测深度恢复且已达8米间距时停止接近，不累计跟随。
        sensor.snapshot = snapshot
        runtime.last_tick = time.monotonic()-.1
        runtime.step()
        np.testing.assert_allclose(flight.sent[-1], [0, 0, 0])

    def test_measured_target_can_approach_without_motion_heading(self):
        runtime, flight, sensor = self.runtime()
        runtime.current['allowed_skills'].append('approach_target')
        sensor.visible = True; sensor.target_x = 15
        decision = runtime.actor.read
        runtime.actor.read = lambda: {**decision(), 'maneuver': 'approach_target', 'effective_maneuver': 'approach_target'}
        runtime.step()
        self.assertGreater(flight.sent[-1][0], 0)
        self.assertEqual(flight.sent[-1][2], 0)
        self.assertEqual(runtime.progress['valid_follow_s'], 0)

    def test_airsim_stage_result_goes_to_qwen_without_semantic_veto(self):
        for result_status in ('done', 'failed'):
            runtime, flight, sensor = self.runtime()
            runtime.current['skill'] = 'observe_target'; sensor.visible = False
            original = runtime.actor.read
            runtime.actor.read = lambda: {**original(), 'stage_status': result_status,
                'stage_reason': 'tracking_lost', 'decision_evidence': dict(tracking_confirmed=False)}
            self.assertEqual(runtime.step()['status'], result_status)
            self.assertIsNone(runtime.rejected_stage_status)
            runtime.close()

    def test_hold_course_approaches_when_relative_motion_geometry_missing(self):
        runtime, flight, sensor = self.runtime()
        sensor.visible = True; sensor.target_x = 20
        original = runtime.actor.read
        runtime.actor.read = lambda: {**original(), 'maneuver': 'hold_course', 'effective_maneuver': 'hold_course', 'risk': 1.9}
        runtime.step()
        self.assertGreater(flight.sent[-1][0], 0)
        self.assertEqual(flight.sent[-1][2], 0)
        self.assertEqual(runtime.progress['valid_follow_s'], 0)
        self.assertEqual(runtime.stats_samples, [])

    def test_qwen_may_choose_stage_without_yaw_action(self):
        from stage5.airsim.mission_runtime import supported_stage
        current = stage(skill='follow_vehicle', following_mode='rear_above',
                        allowed_skills=['hold_course', 'brake'])
        supported_stage(current)


if __name__ == '__main__':
    unittest.main()
