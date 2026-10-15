from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from depth_fusion import calibration, fuse, project_box


class DepthFusionTests(unittest.TestCase):
    def setUp(self):
        self.model = calibration()
        self.rgb = dict(width=640, height=360, sim_time=10)
        self.depth = dict(width=640, height=400, sim_time=10, format='R_FLOAT32', step=2560)
        self.response = dict(width=640, height=360,
            detections=[dict(label='car', score=.8, box_xyxy=[280, 140, 360, 220])])

    def run_depth(self, value, **kwargs):
        return fuse(self.response, self.rgb, self.depth, struct.pack('<f', value)*640*400,
                    self.model, **kwargs)

    def test_center_and_different_response_resolution(self):
        target = self.run_depth(5)['targets'][0]
        self.assertEqual(target['position_m'], [5, 0, 0])
        self.assertEqual(target['range_m'], 5)
        first = project_box([280, 140, 360, 220], 640, 360, self.model)
        scaled = project_box([560, 280, 720, 440], 1280, 720, self.model)
        self.assertEqual(first, scaled)

    def test_pixel_ray_conversion_and_sign(self):
        self.response['detections'][0]['box_xyxy'] = [360, 180, 440, 260]
        target = self.run_depth(5)['targets'][0]
        expected = -80/self.model['rgb']['fx']*5
        self.assertAlmostEqual(target['position_m'][1], expected)
        self.assertLess(target['position_m'][2], 0)
        self.assertGreater(target['bearing_right_deg'], 0)

    def test_invalid_depth_cannot_produce_position(self):
        for value in (float('nan'), float('inf'), 0, self.model['far_m'], self.model['far_m']+1):
            with self.subTest(value=value):
                result = self.run_depth(value)
                self.assertFalse(result['usable_for_control'])
                self.assertIsNone(result['targets'][0]['position_m'])

    def test_unsynchronized_and_mock_not_actionable(self):
        self.depth['sim_time'] = 10.2
        result = self.run_depth(5)
        self.assertEqual(result['targets'][0]['status'], 'unsynchronized')
        self.depth['sim_time'] = 10
        self.assertFalse(self.run_depth(5, response_source='mock')['usable_for_control'])

    def test_wrong_calibration_size_rejected(self):
        self.depth['width'] = 320
        with self.assertRaises(ValueError):
            self.run_depth(5)

    def test_near_occluder_and_far_surface_remain_ambiguous(self):
        row = struct.pack('<f', 3)*320 + struct.pack('<f', 12)*320
        result = fuse(self.response, self.rgb, self.depth, row*400, self.model)
        target = result['targets'][0]
        self.assertEqual(target['status'], 'mixed_depth')
        self.assertEqual(len(target['depth_evidence']['distance_clusters']), 2)
        self.assertIsNone(target['position_m'])

    def test_far_return_is_information(self):
        target = self.run_depth(float('inf'))['targets'][0]
        self.assertEqual(target['status'], 'too_far')
        self.assertEqual(target['distance_lower_bound_m'], 20)
        self.assertEqual(target['depth_evidence']['too_far_fraction'], 1)


if __name__ == '__main__':
    unittest.main()
