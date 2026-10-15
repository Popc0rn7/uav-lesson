from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_runtime import Perception
from test_agent_runtime import Flight


class PerceptionTests(unittest.TestCase):
    def patches(self,client):
        rgb=({'received':time.monotonic(),'sim_time':1},b'')
        patches=[patch('agent_runtime.DinoClient',return_value=client),
                 patch('agent_runtime.paired_frames',return_value=(rgb,rgb)),
                 patch('agent_runtime.camera_png',return_value=(b'png',rgb[0])),
                 patch('agent_runtime.target_surface',return_value=None),
                 patch('agent_runtime.forward_clearance',return_value=20.),
                 patch('agent_runtime.build',return_value={'motion_candidates':{}}),
                 patch('agent_runtime.fuse',return_value={'targets':[{'label':'a car','status':'too_far'}]})]
        for item in patches:item.start();self.addCleanup(item.stop)

    def test_late_detection_from_old_configuration_is_discarded(self):
        first=threading.Event();release_first=threading.Event();second=threading.Event();release_second=threading.Event()
        class Client:
            calls=0
            def detect(self,*args,**kwargs):
                self.calls+=1
                (first if self.calls==1 else second).set()
                (release_first if self.calls==1 else release_second).wait(2)
                return {'detections':[]},0
        client=Client();self.patches(client)
        sensor=Perception({'DINO_DETECT_URL':'test','STAGE5_RGB_URL':'test','STAGE5_DEPTH_URL':'test'},Flight())
        try:
            self.assertTrue(first.wait(1))
            sensor.configure('a different red box.')
            release_first.set()
            self.assertTrue(second.wait(1))
            self.assertIsNone(sensor.image())
            self.assertNotIn('generation',sensor.snapshot())
        finally:
            release_first.set();release_second.set();sensor.close();sensor.thread.join(1)

    def test_too_far_evidence_survives_without_tracking(self):
        class Client:
            def detect(self,*args,**kwargs):return {'detections':[]},0
        self.patches(Client())
        sensor=Perception({'DINO_DETECT_URL':'test','STAGE5_RGB_URL':'test','STAGE5_DEPTH_URL':'test'},Flight())
        try:
            until=time.monotonic()+1
            while sensor.image() is None and time.monotonic()<until:time.sleep(.01)
            observation=sensor.snapshot()
            self.assertIsNone(observation['tracking'])
            self.assertEqual(observation['semantic_targets'][0]['status'],'too_far')
        finally:sensor.close();sensor.thread.join(1)


if __name__=='__main__':unittest.main()
