from pathlib import Path
import sys
import threading
import time
import base64
import json
import struct
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_runtime import Perception
from test_agent_runtime import Flight


class PerceptionTests(unittest.TestCase):
    def test_preview_is_request_frame_and_rejects_old_generation(self):
        sensor=Perception.__new__(Perception)
        sensor.lock=threading.Lock();sensor.generation=2
        rgb=({'received':123.,'sim_time':7.},b'')
        depth=({'width':2,'height':2,'step':8},struct.pack('<4f',1,2,3,4))
        with tempfile.TemporaryDirectory() as directory:
            sensor.output=Path(directory)
            sensor.publish_request_preview(rgb,depth,b'exact submitted image',2)
            path=sensor.output/'preview.json';data=json.loads(path.read_text())
            self.assertEqual(base64.b64decode(data['rgb']),b'exact submitted image')
            self.assertEqual(data['source'],'dino_request')
            self.assertEqual(data['image_sent_to'],'dino')
            self.assertEqual(data['received'],123.)
            original=path.read_bytes()
            sensor.publish_request_preview(rgb,depth,b'old request',1)
            self.assertEqual(path.read_bytes(),original)

    def test_background_tracking_does_not_refresh_web_images(self):
        class Client:
            calls=0
            def detect(self,*args,**kwargs):
                self.calls+=1
                return {'detections':[]},0
        client=Client();self.patches(client)
        with patch.object(Perception,'publish_request_preview') as preview:
            sensor=Perception({'DINO_DETECT_URL':'test','STAGE5_RGB_URL':'test','STAGE5_DEPTH_URL':'test'},Flight())
            try:
                until=time.monotonic()+1
                while sensor.image() is None and time.monotonic()<until:time.sleep(.01)
                time.sleep(.25)
                self.assertEqual(client.calls,1)
                self.assertEqual(preview.call_count,2)  # 送检帧，以及同帧返回的检测框。
            finally:sensor.close();sensor.thread.join(1)

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
