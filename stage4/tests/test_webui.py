import json
from pathlib import Path
import tempfile
import time
import unittest
from stage4.webui import snapshot


class WebUITests(unittest.TestCase):
    def test_tracks_current_run_and_world_coordinates_without_truth(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); run=root/'first'; run.mkdir()
            def write(name,data): (run/name).write_text(json.dumps(data))
            (root/'state.json').write_text(json.dumps(dict(run_dir=str(run),phase='ready')))
            write('task.json',dict(spawn_ned_m=[10,20,0],target_ned_m=[15,22,-2]))
            write('origin.json',dict(px4_origin_ned=[1,1,0]))
            write('control.json',dict(position_ned=[3,3,-2],velocity_ned=[3,4,0],wall_time=time.time()))
            (run/'inference.jsonl').write_text(json.dumps(dict(http_seconds=.3,elapsed_seconds=.28))+'\n{"partial":')
            data=snapshot(root)
            self.assertEqual(data['position_world_ned'],[12,22,-2]); self.assertEqual(data['distance_m'],3)
            self.assertEqual(data['speed_m_s'],5); self.assertEqual(data['inference_count'],1)
            self.assertFalse(data['stale'])
            next_run=root/'second'; next_run.mkdir()
            (root/'state.json').write_text(json.dumps(dict(run_dir=str(next_run),phase='starting')))
            data=snapshot(root)
            self.assertTrue(data['stale']); self.assertEqual(data['inference_count'],0)
            self.assertEqual(data['run_id'],'second')

    def test_waits_without_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(snapshot(Path(folder))['phase'],'waiting')

    def test_pending_observation_does_not_show_previous_prompt_or_action(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); run=root/'first'; run.mkdir()
            (root/'state.json').write_text(json.dumps(dict(run_dir=str(run),phase='ready')))
            (run/'task.json').write_text(json.dumps(dict(target_ned_m=[10,0,0])))
            observation=dict(step=2,estimated_world_ned=[1,0,0],quaternion_xyzw=[0,0,0,1],prompt_preview='new prompt')
            (run/'observation.json').write_text(json.dumps(observation))
            old=dict(step=1,prompt='old prompt',action=dict(fwd=5,down=0,yaw=0))
            (run/'inference.jsonl').write_text(json.dumps(old)+'\n')
            data=snapshot(root)
            self.assertEqual(data['inference'],{}); self.assertEqual(data['observation'],observation)
            self.assertEqual(data['observation_distance_m'],9)
            new=dict(step=2,prompt='new prompt',action=dict(fwd=1,down=0,yaw=0))
            with (run/'inference.jsonl').open('a') as output: output.write(json.dumps(new)+'\n')
            self.assertEqual(snapshot(root)['inference'],new)
