from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voxel_scene import build, check_move, key


class VoxelTests(unittest.TestCase):
    def setUp(self):
        self.model = dict(depth=dict(width=16, height=16, fx=8, fy=8, cx=8, cy=8),
                          near_m=.15, far_m=20)
        self.meta = dict(width=16, height=16, format='R_FLOAT32', step=64, sim_time=1)

    def test_surface_stops_free_ray(self):
        scene = build(self.meta, struct.pack('<f', 2)*256, self.model, stride=1)
        self.assertGreater(scene['occupied_count'], 0)
        self.assertTrue(all(p[0] < 2.3 for p in scene['occupied_points_m']))
        self.assertLess(scene['free_count'], build(self.meta, struct.pack('<f', float('inf'))*256,
                                                 self.model, stride=1)['free_count'])

    def test_nan_is_unknown_inf_is_far_free(self):
        scene = build(self.meta, struct.pack('<f', float('nan'))*256, self.model, stride=1)
        self.assertEqual(scene['free_count'], 0)
        self.assertEqual(scene['motion_candidates']['forward_1m']['status'], 'unknown')
        far = build(self.meta, struct.pack('<f', float('inf'))*256, self.model, stride=1)
        self.assertEqual(far['occupied_count'], 0)
        self.assertGreater(far['free_count'], 0)

    def test_swept_body_collides_with_thin_obstacle(self):
        occupied = {key((.8, .3, 0), .25)}
        self.assertEqual(check_move(occupied, set(), .25, [1, 0, 0])['status'], 'blocked')
        self.assertEqual(check_move(occupied, set(), .25, [0, -1, 0])['status'], 'unknown')

    def test_ground_below_body_does_not_block(self):
        occupied = {key((.8, 0, -2), .25)}
        free = {(x,y,z) for x in range(-8,12) for y in range(-8,8) for z in range(-8,8)}
        self.assertEqual(check_move(occupied, free, .25, [1, 0, 0])['status'], 'clear')


if __name__ == '__main__':
    unittest.main()
