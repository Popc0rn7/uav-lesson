from pathlib import Path
import sys
import unittest
import threading
import time
from types import SimpleNamespace
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from follow import camera_to_ned, target_surface, allow_follow, Flight
from depth_fusion import calibration


class FollowTests(unittest.TestCase):
    def test_setpoint_stream_survives_blocking_main_loop_and_stops_motion(self):
        flight=Flight.__new__(Flight)
        flight.stream_stop=threading.Event();flight.stream_lock=threading.Lock()
        flight.stream_thread=None;flight.stream_command=None
        sent=[]
        flight._send=lambda velocity,yaw:sent.append((time.monotonic(),list(velocity),yaw))
        flight.link=SimpleNamespace(close=lambda:None)
        try:
            flight.start_stream(.7)
            flight.send([1,0,0],.7)
            time.sleep(.4)
        finally:flight.close()
        self.assertGreater(len(sent),10)
        self.assertTrue(any(row[1]==[1,0,0] for row in sent))
        self.assertEqual(sent[-1][1],[0,0,0])
        self.assertAlmostEqual(sent[-1][2],.7)

    def test_camera_flu_to_body_frd_and_ned(self):
        own=dict(p=np.array([1.,2.,-3.]),q=np.array([1.,0.,0.,0.]))
        np.testing.assert_allclose(camera_to_ned([8,1,-2],own),[9.186,1,-1.025])
        own['q']=np.array([2**-.5,0,0,2**-.5])
        np.testing.assert_allclose(camera_to_ned([8,1,-2],own),[2,10.186,-1.025],atol=1e-8)

    def test_red_tracker_uses_image_and_depth(self):
        model=calibration()
        rgb=np.zeros((360,640,3),dtype=np.uint8)
        rgb[170:190,310:330]=[200,30,20]
        depth=np.full((400,640),8,dtype='<f4')
        rm=dict(width=640,height=360,format='RGB_INT8',step=1920)
        dm=dict(width=640,height=400,format='R_FLOAT32',step=2560)
        target=target_surface((rm,rgb.tobytes()),(dm,depth.tobytes()),model)
        self.assertEqual(target['box_xyxy'],[310,170,330,190])
        self.assertAlmostEqual(target['position_camera_flu_m'][0],8)
        rgb[170:190,310:330]=[30,200,20]
        self.assertIsNone(target_surface((rm,rgb.tobytes()),(dm,depth.tobytes()),model))

    def test_bad_image_calibration_rejected(self):
        with self.assertRaises(ValueError):
            target_surface((dict(width=10,height=10,format='RGB_INT8'),b''),
                (dict(width=10,height=10,format='R_FLOAT32'),b''),calibration())

    def test_jev_pause_danger_or_stale_prevents_following(self):
        judgment=dict(actionable=True,effective_maneuver='hold_course',risk=.5)
        observation=dict(confirmed=True,clearance_m=10)
        self.assertTrue(allow_follow(judgment,observation))
        self.assertFalse(allow_follow(dict(judgment,effective_maneuver='brake'),observation))
        self.assertFalse(allow_follow(dict(judgment,actionable=False),observation))
        self.assertFalse(allow_follow(dict(judgment,risk=1.9),observation))
        self.assertFalse(allow_follow(judgment,dict(observation,clearance_m=1)))


if __name__=='__main__':unittest.main()
