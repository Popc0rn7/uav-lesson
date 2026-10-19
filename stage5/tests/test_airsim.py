"""离线契约回归，不连接 Editor、Docker、飞控或模型。"""
import copy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
import os
from unittest.mock import patch

import numpy as np
from PIL import Image

from stage5.airsim.config import load, settings, camera_model
from stage5.airsim.frames import decode_pair, camera_info
from stage5.airsim import runtime


class AirSimContracts(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'AIRSIM_MOUNTAINS': '/tmp/stage5-test/demo/Binaries/Linux/demo-Linux-Shipping'})
        env.start()
        self.addCleanup(env.stop)
        self.config = load(Path(__file__).resolve().parents[1]/'airsim/runtime.demo.json')

    def test_px4_identity_and_native_camera_defaults(self):
        generated = settings(self.config)
        self.assertEqual(generated['ApiServerPort'], 41451)
        self.assertEqual(list(generated['Vehicles']), ['Drone1'])
        vehicle = generated['Vehicles']['Drone1']
        self.assertEqual(vehicle['VehicleType'], 'PX4Multirotor')
        self.assertEqual(vehicle['VehicleSysID'], 6)
        self.assertEqual(vehicle['TcpPort'], 4565)
        self.assertEqual((vehicle['ControlPortLocal'], vehicle['ControlPortRemote']), (14546, 14586))
        self.assertEqual([vehicle[k] for k in ('X', 'Y', 'Z')], self.config['spawn_ned_m'])
        self.assertNotIn('Cameras',vehicle)
        camera = generated['CameraDefaults']
        self.assertFalse(any(k in camera for k in ('X','Y','Z','Pitch','Roll','Yaw')))
        self.assertEqual([(c['ImageType'], c['Width'], c['Height'], c['FOV_Degrees'])
                          for c in camera['CaptureSettings']], [(0, 640, 360, 90), (1, 640, 400, 90)])
        self.assertNotIn('Lidar', vehicle['Sensors'])
        self.assertNotIn('SimpleFlight', json.dumps(generated))

    def test_native_mount_never_publishes_fabricated_stage2_extrinsics(self):
        self.assertAlmostEqual(camera_model()['position_body_flu_m'][0], .186)
        model = camera_model(self.config)
        self.assertIsNone(model['position_body_flu_m'])
        self.assertIsNone(model['orientation_body_flu_rpy_rad'])
        self.assertEqual(model['rgb']['fx'], 320)
        self.assertEqual(model['depth']['fx'], 320)

    def pair(self):
        data = BytesIO()
        Image.new('RGB', (2, 2), (255, 20, 3)).save(data, format='PNG')
        return [dict(time_stamp=1_000_000_000, image_type=0, width=2, height=2, message='', image_data_uint8=data.getvalue()),
                dict(time_stamp=1_000_000_000, image_type=1, width=2, height=2, message='', image_data_float=[3, 20, 0, float('inf')])]

    def model(self):
        model = copy.deepcopy(camera_model())
        for key in ('rgb', 'depth'):
            model[key].update(width=2, height=2)
        return model

    def test_png_color_order_planar_metres_and_depth_limit(self):
        rgb, depth, stamps, stats = decode_pair(self.pair(), self.model())
        self.assertEqual(rgb[:3], bytes((255, 20, 3)))
        values = np.frombuffer(depth, dtype='<f4')
        self.assertEqual(values[0], 3)
        self.assertTrue(np.isposinf(values[1]))
        self.assertTrue(np.isnan(values[2]))
        self.assertTrue(np.isposinf(values[3]))
        self.assertEqual(stats['valid_fraction'], .25)
        self.assertEqual(stamps, [1_000_000_000]*2)

    def test_invalid_frame_contracts_rejected(self):
        variants = [('timestamp', lambda p: p[1].update(time_stamp=1_100_000_000)),
                    ('size', lambda p: p[1].update(width=3)),
                    ('depth_type', lambda p: p[1].update(image_type=2)),
                    ('payload', lambda p: p[1].update(image_data_float=[])),
                    ('server_error', lambda p: p[0].update(message='camera missing'))]
        for name, mutate in variants:
            with self.subTest(name=name):
                pair = self.pair()
                mutate(pair)
                with self.assertRaises(ValueError):
                    decode_pair(pair, self.model())
        with self.assertRaises(ValueError):
            decode_pair(self.pair(), self.model(), previous_ns=1_000_000_000)

    def test_camera_info_uses_each_stream_intrinsics(self):
        model = camera_model()
        for key in ('rgb', 'depth'):
            matrices = camera_info(model[key])
            self.assertEqual(matrices['k'][0], model[key]['fx'])
            self.assertEqual(matrices['k'][5], model[key]['cy'])
        self.assertNotEqual(camera_info(model['rgb']), camera_info(model['depth']))

    def test_prepare_does_not_touch_editor_or_connect(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, 'call') as call:
            result = runtime.prepare(self.config, Path(directory))
            self.assertFalse(result['installed'])
            call.assert_not_called()
            self.assertTrue(Path(result['settings']).is_file())

    def test_foreign_container_is_never_adopted(self):
        state = dict(run_id='ours', config=self.config, px4_id='original')
        foreign = dict(Id='original', Config=dict(Labels={runtime.LABEL: 'other'}))
        with patch.object(runtime, 'container', return_value=foreign):
            with self.assertRaises(RuntimeError):
                runtime.owned(state, 'px4')

    def test_install_yaw_change_only_accepts_known_previous_settings(self):
        for unknown_change in (False, True):
            with tempfile.TemporaryDirectory() as directory, patch.object(runtime, 'free_port'):
                root = Path(directory); target = root/'editor.json'
                config = {**self.config, 'editor_settings': str(target), 'spawn_yaw_deg': 180}
                previous = settings({**config, 'spawn_yaw_deg': 0})
                if unknown_change:
                    previous['ClockSpeed'] = 2
                target.write_text(json.dumps(previous)); original = target.read_bytes()
                if unknown_change:
                    with self.assertRaises(RuntimeError):
                        runtime.prepare(config, root/'prepared', install=True)
                    self.assertEqual(target.read_bytes(), original)
                else:
                    runtime.prepare(config, root/'prepared', install=True)
                    self.assertEqual(json.loads(target.read_text())['Vehicles']['Drone1']['Yaw'], 180)
                    self.assertEqual(next(root.glob('editor.json.stage5-*.bak')).read_bytes(), original)

    def test_install_spawn_change_preserves_backup_and_rejects_unknown_settings(self):
        for unknown_change in (False, True):
            with tempfile.TemporaryDirectory() as directory, patch.object(runtime, 'free_port'):
                root = Path(directory); target = root/'editor.json'
                previous = settings(self.config)
                if unknown_change: previous['ClockSpeed'] = 2
                target.write_text(json.dumps(previous)); original = target.read_bytes()
                config = {**self.config, 'editor_settings': str(target), 'spawn_ned_m': [1., 2., -3.]}
                if unknown_change:
                    with self.assertRaises(RuntimeError): runtime.prepare(config, root/'prepared', install=True)
                    self.assertEqual(target.read_bytes(), original)
                else:
                    runtime.prepare(config, root/'prepared', install=True)
                    self.assertEqual(json.loads(target.read_text())['Vehicles']['Drone1']['Z'], -3.)
                    self.assertEqual(next(root.glob('editor.json.stage5-*.bak')).read_bytes(), original)

    def test_failed_arming_confirmation_blocks_down(self):
        state = dict(run_id='ours', config=self.config, px4_id='original')
        with patch.object(runtime, 'owned', return_value={'State': {'Running': True}}), \
             patch.object(runtime, 'px4', return_value=type('Result', (), {'stdout': 'arming_state: 2'})()), \
             patch.object(runtime, 'archive') as archive:
            with self.assertRaises(RuntimeError):
                runtime.shutdown(state, Path('/unused'), force=False)
            archive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
