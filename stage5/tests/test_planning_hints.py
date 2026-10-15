from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from planning_hints import guidance


class PlanningHintsTests(unittest.TestCase):
    def test_missing_geometry_keeps_approach_and_enough_requests(self):
        hint = guidance({}, default_duration_s=10)
        self.assertEqual(hint['suggested_follow_timeout_s'], 55)
        self.assertEqual(hint['suggested_follow_budget'], 31)

    def test_estimate_uses_closing_speed_and_inherited_qualified_progress(self):
        observation = {'own_position_ned_m': [0, 0, -2], 'tracking': {
            'target_ned': [18, 0, 0], 'velocity_ned': [.7, 0, 0]}}
        hint = guidance(observation, {'duration_s': 10, 'horizontal_distance_m': 8,
                                     'above_m': 2}, progress={'valid_follow_s': 4})
        self.assertAlmostEqual(hint['horizontal_goal_error_m'], 10)
        self.assertAlmostEqual(hint['estimated_approach_s'], 27)
        self.assertEqual(hint['remaining_qualified_follow_s'], 6)
        self.assertGreaterEqual(hint['suggested_follow_budget']*2,
                                hint['suggested_follow_timeout_s'])

    def test_target_too_fast_has_no_finite_catchup_promise(self):
        hint = guidance({'tracking': {'velocity_ned': [1.3, 0, 0]}})
        self.assertIsNone(hint['suggested_follow_timeout_s'])
        self.assertIsNone(hint['estimated_approach_s'])


if __name__ == '__main__': unittest.main()
