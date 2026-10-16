"""录像视角只能移动相机；验证车辆局部 NED 到外部相机全局 NED 的转换。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
from scipy.spatial.transform import Rotation

HERE=Path(__file__).resolve().parents[1]/'airsim'
sys.path.insert(0,str(HERE))
from flight_video import camera_pose,configure,encode


class FlightVideoTests(unittest.TestCase):
    def test_camera_points_at_vehicle_and_keeps_spawn_offset(self):
        p=camera_pose(dict(x_val=10,y_val=20,z_val=-2),[42.6,160.11,0])
        np.testing.assert_allclose(list(p['position'].values()),[47.6,177.11,-8])
        q=p['orientation'];rotation=Rotation.from_quat([q['x_val'],q['y_val'],q['z_val'],q['w_val']])
        direction=np.array([5.,3.,6.]);direction/=np.linalg.norm(direction)
        np.testing.assert_allclose(rotation.apply([1,0,0]),direction,atol=1e-12)

    def test_setup_preserves_flight_settings_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            source=HERE/'settings.forest-fast.json';out=Path(d)/'settings.json'
            configure(source,out);a=json.loads(source.read_text());b=json.loads(out.read_text())
            camera=b.pop('ExternalCameras')['uav_review']
            self.assertEqual(a,b);self.assertEqual(camera['CaptureSettings'][0]['Width'],640)
            with self.assertRaises(FileExistsError):configure(source,out)

    def test_encode_rejects_clock_reset_before_running_ffmpeg(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'frames.jsonl').write_text('\n'.join(json.dumps(dict(file=f'{i}.png',sim_ns=stamp))
                                                     for i,stamp in enumerate([100,90])))
            with self.assertRaises(ValueError):encode(root,root/'video.mp4')


if __name__=='__main__':unittest.main()
