from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from webui import make_handler, airsim_packet


class PreviewTests(unittest.TestCase):
    def test_airsim_card_requires_fresh_live_sensor_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);state=directory/'state.json';sensors=directory/'sensors.json'
            value=dict(run_id='live-run',run_dir=str(directory),phase='ready')
            state.write_text(json.dumps(value))
            sensors.write_text(json.dumps(dict(healthy=True,pair_age_s=.1,pairs=42,
                telemetry={'armed':False},telemetry_age_s={'clock':.01})))
            self.assertTrue(airsim_packet(state)['live'])
            with patch('webui.time.time',return_value=sensors.stat().st_mtime+10):
                stale=airsim_packet(state)
                self.assertFalse(stale['live'])
                self.assertAlmostEqual(stale['pair_age_s'],10.1)
            value['phase']='stopped';state.write_text(json.dumps(value))
            self.assertFalse(airsim_packet(state)['live'])

    def test_no_airsim_run_has_no_scene_card(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(airsim_packet(Path(temporary)/'missing.json'))

    def get(self,directory,etag=None):
        handler=object.__new__(make_handler(directory))
        handler.path='/api/preview';handler.headers={'If-None-Match':etag} if etag else {}
        handler.wfile=BytesIO()
        handler.send_response=Mock();handler.send_header=Mock();handler.end_headers=Mock()
        handler.do_GET()
        token=next((args[0][1] for args in handler.send_header.call_args_list if args[0][0]=='ETag'),None)
        return handler,token

    def test_unchanged_snapshot_has_no_image_body_then_new_request_updates(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            path=directory/'preview.json'
            path.write_text(json.dumps({'rgb':'first request'}))
            first,etag=self.get(directory)
            self.assertEqual(json.loads(first.wfile.getvalue())['preview']['rgb'],'first request')
            repeated,_=self.get(directory,etag)
            repeated.send_response.assert_called_once_with(304)
            self.assertEqual(repeated.wfile.getvalue(),b'')
            path.write_text(json.dumps({'rgb':'second request image'}))
            changed,new_etag=self.get(directory,etag)
            changed.send_response.assert_called_once_with(200)
            self.assertNotEqual(new_etag,etag)
            self.assertEqual(json.loads(changed.wfile.getvalue())['preview']['rgb'],'second request image')
