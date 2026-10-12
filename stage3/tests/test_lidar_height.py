import unittest
import numpy as np
from lidar_height import estimate_height


class HeightGeometry(unittest.TestCase):
    def test_floor_with_walls_and_shrub(self):
        rng=np.random.default_rng(11)
        floor=np.column_stack((rng.uniform(-6,6,2400),rng.uniform(-6,6,2400),np.zeros(2400)))
        walls=np.column_stack((np.full(600,3.),rng.uniform(-6,6,600),rng.uniform(0,4,600)))
        shrub=np.column_stack((rng.uniform(-.5,.5,200),rng.uniform(2,3,200),np.full(200,.35)))
        world=np.vstack((floor,walls,shrub))
        for height,angle,sensor_z in ((.25,0.,.135),(1.95,.3,.135),(2.,-.4,.135),(.25,0.,.335),(1.95,.3,.335),(2.,-.4,.335)):
            with self.subTest(height=height,angle=angle):
                c,s=np.cos(angle),np.sin(angle)
                rotation=np.array([[c,0,s],[0,1,0],[-s,0,c]])
                sensor=np.array([0,0,height])+rotation@np.array([0,0,sensor_z])
                points=(world-sensor)@rotation+rng.normal(0,.003,world.shape)
                result=estimate_height(points,sensor_z=sensor_z)
                self.assertIsNotNone(result)
                self.assertAlmostEqual(result['height_m'],height,delta=.01)

    def test_no_dominant_ground(self):
        rng=np.random.default_rng(3)
        self.assertIsNone(estimate_height(rng.uniform(-4,4,(1000,3))))
        self.assertIsNone(estimate_height(np.zeros((10,3))))


if __name__=='__main__':unittest.main()
