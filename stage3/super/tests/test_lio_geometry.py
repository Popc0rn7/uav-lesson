import math
import unittest
import numpy as np
from lio_geometry import multiply,matrix,enu_flu_to_ned_frd,course_alignment


class LioFrames(unittest.TestCase):
    def test_known_course_heading_becomes_px4_north(self):
        h=math.sqrt(.5)
        self.assertTrue(np.allclose(enu_flu_to_ned_frd([0,0,h,h]),[1,0,0,0]))
        self.assertTrue(np.allclose(matrix([0,0,h,h])@np.array([1,0,0]),[0,1,0]))
    def test_full_attitude_frame_change(self):
        a=np.array([[0,1,0],[1,0,0],[0,0,-1]])
        b=np.diag([1,-1,-1]);rng=np.random.default_rng(4)
        for _ in range(20):
            q=rng.normal(size=4);q/=np.linalg.norm(q)
            w,x,y,z=enu_flu_to_ned_frd(q)
            self.assertTrue(np.allclose(matrix([x,y,z,w]),a@matrix(q)@b))
    def test_anchor_preserves_gravity_with_noisy_first_attitude(self):
        q=np.array([.1,.2,.3,.9]);q/=np.linalg.norm(q)
        anchor=course_alignment(q)
        self.assertTrue(np.allclose(matrix(anchor)@np.array([0,0,1]),[0,0,1]))
        forward=matrix(multiply(anchor,q))@np.array([1,0,0])
        self.assertAlmostEqual(math.atan2(forward[1],forward[0]),math.pi/2)

if __name__=='__main__':unittest.main()
