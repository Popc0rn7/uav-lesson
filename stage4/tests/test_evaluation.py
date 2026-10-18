import unittest
from stage4.evaluation import Evaluation, DEPTH_CAMERAS, depth_proximity


class EvaluationTests(unittest.TestCase):
    def test_oracle_is_sticky_but_does_not_stop_without_model(self):
        e=Evaluation([0,0,0]); e.initialize([30,0,0])
        self.assertIsNone(e.after_action([10,0,0],{})); self.assertTrue(e.oracle_success)
        self.assertFalse(e.success)
        self.assertIsNone(e.after_action([30,0,0],{})); self.assertTrue(e.oracle_success)
        self.assertIn('too far',e.stop([30,0,0])); self.assertTrue(e.early_end); self.assertFalse(e.success)

    def test_success_distance_boundary_and_oracle_strict_boundary(self):
        e=Evaluation([0,0,0]); e.initialize([30,0,0]); e.after_action([20,0,0],{})
        self.assertFalse(e.oracle_success)
        self.assertEqual(e.stop([20,0,0]),'model requested stop'); self.assertTrue(e.success)

    def test_ten_nondecreasing_values_including_equal_are_terminal(self):
        e=Evaluation([0,0,0]); e.initialize([30,0,0])
        for n in range(8): self.assertIsNone(e.after_action([30,0,0],{}))
        self.assertEqual(e.after_action([30,0,0],{}),'target distance nondecreasing')
        self.assertTrue(e.legacy_collision)

    def test_progress_resets_distance_window_and_stuck_counter(self):
        e=Evaluation([0,0,0]); e.initialize([30,0,0])
        for n in range(20): self.assertIsNone(e.after_action([29-n*.1,0,0],{}))
        self.assertEqual(e.stuck_count,0)

    def test_stuck_is_horizontal_and_triggers_on_sixteenth_update(self):
        e=Evaluation([0,0,0]); e.initialize([30,0,0])
        # Alternating altitude prevents the independent nondecreasing rule.
        for n in range(15): self.assertIsNone(e.after_action([30,0,n%2],{}))
        self.assertEqual(e.after_action([30,0,1],{}),'stuck')

    def test_depth_quantization_and_fraction_boundary(self):
        def frames(values): return [dict(width=len(values),height=1,image_data_float=values) for _ in DEPTH_CAMERAS]
        safe=depth_proximity(frames([.78]+[10.]*9))
        self.assertEqual(safe['FrontCamera'],.1)
        e=Evaluation([0,0,0]); e.initialize([30,0,0]); self.assertIsNone(e.after_action([29,0,0],safe))
        near=depth_proximity(frames([.78,.78]+[10.]*8))
        self.assertEqual(e.after_action([28,0,0],near),'depth proximity')
        self.assertEqual(depth_proximity(frames([.785]*10))['FrontCamera'],0.)
        with self.assertRaises(ValueError): depth_proximity(frames([float('nan')]))
        with self.assertRaises(ValueError): depth_proximity(frames([1.])[:2])
