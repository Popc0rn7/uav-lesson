"""场景进程身份、失败留证与回收；不运行UE或连接模型。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from stage5.airsim import scene_process, runtime
from stage5.airsim.config import load


class SceneProcessTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'AIRSIM_MOUNTAINS': '/tmp/stage5-test/demo/Binaries/Linux/demo-Linux-Shipping'})
        env.start()
        self.addCleanup(env.stop)

    def test_identity_prevents_pid_reuse_and_foreign_executable_signals(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', '-settings=/tmp/test'])
        try:
            info = dict(pid=process.pid, start_ticks=scene_process.start_ticks(process.pid),
                        binary=str(Path(sys.executable).resolve()), settings_arg='-settings=/tmp/test')
            self.assertTrue(scene_process.alive(info))
            scene_process.stop({**info, 'start_ticks':'invalid'})
            self.assertIsNone(process.poll())
            scene_process.stop({**info, 'binary':'/not/our/executable'})
            self.assertIsNone(process.poll())
            scene_process.stop(info)
            process.wait(timeout=3)
            self.assertFalse(scene_process.alive(info))
        finally:
            if process.poll() is None: process.kill()
            process.wait()

    def test_missing_route_is_rejected_before_scene_start(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel in ('demo/Binaries/Linux/demo-Linux-Shipping', 'demo/Config/AirSim/settings.json',
                        'demo/Content/Paks/demo-LinuxNoEditor.pak'):
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('x');p.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError,'PickupConvoy3Route01.sav'):
                scene_process.validate(dict(package_dir=d))

    def test_configuration_needs_only_package_not_editor_project(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'STAGE5_PACKAGE_DIR':d}):
            config=load(Path(__file__).resolve().parents[1]/'airsim/runtime.demo.json')
            self.assertEqual(config['package_dir'],d)
            self.assertEqual(config['editor_settings'],str(Path(d)/'demo/Config/AirSim/settings.json'))

    def test_mountains_elf_reads_root_env_and_shell_overrides(self):
        config_path=Path(__file__).resolve().parents[1]/'airsim/runtime.demo.json'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'.env').write_text('AIRSIM_MOUNTAINS="packages/Mountains scene/demo/Binaries/Linux/demo-Linux-Shipping"\n')
            with patch('stage5.airsim.config.ROOT',root),patch.dict(os.environ,{},clear=True):
                cfg=load(config_path)
                self.assertEqual(cfg['package_dir'],str(root/'packages/Mountains scene'))
                self.assertEqual(cfg['scene_binary'],str(root/'packages/Mountains scene/demo/Binaries/Linux/demo-Linux-Shipping'))
                shell=root/'other/demo/Binaries/Linux/demo-Linux-Shipping'
                with patch.dict(os.environ,{'AIRSIM_MOUNTAINS':str(shell)}):
                    self.assertEqual(load(config_path)['package_dir'],str(root/'other'))

    def test_missing_mountains_path_has_actionable_error_and_no_example_fallback(self):
        config_path=Path(__file__).resolve().parents[1]/'airsim/runtime.demo.json'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'.env.example').write_text('AIRSIM_MOUNTAINS=/example/demo/Binaries/Linux/demo-Linux-Shipping\n')
            with patch('stage5.airsim.config.ROOT',root),patch.dict(os.environ,{},clear=True):
                with self.assertRaisesRegex(ValueError,'根.env设置AIRSIM_MOUNTAINS'):
                    load(config_path)
                with patch.dict(os.environ,{'AIRSIM_MOUNTAINS':'/package/run-stage5.sh'}):
                    with self.assertRaisesRegex(ValueError,'Shipping ELF'):
                        load(config_path)

    def test_repeated_up_returns_existing_healthy_run_without_launch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config={'scene_backend':'packaged'}
            (root/'state.json').write_text(json.dumps(dict(phase='ready',config=config)))
            with patch.object(runtime,'inspect',return_value={'ready':True}), patch.object(scene_process,'launch') as launch:
                self.assertEqual(runtime.start(config,root),{'ready':True})
                launch.assert_not_called()

    def test_shutdown_stops_only_scene_recorded_in_owned_state(self):
        with tempfile.TemporaryDirectory() as d:
            info={'pid':123,'managed':True}
            state=dict(phase='failed',scene=info,run_dir=d,config={})
            with patch.object(runtime,'owned',return_value=None), patch.object(scene_process,'stop') as stop:
                result=runtime.shutdown(state,Path(d)/'state.json')
                stop.assert_called_once_with(info)
                self.assertTrue(result['stopped'])
                self.assertEqual(state['phase'],'stopped')

    def test_dead_scene_invalidates_healthy_sensor_status(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'sensors.json').write_text(json.dumps({'healthy':True}))
            state=dict(phase='ready',scene={'pid':123},run_dir=d,run_id='test',config={'raw_port':8189})
            with patch.object(runtime,'owned',return_value={'State':{'Running':True}}), patch.object(scene_process,'alive',return_value=False):
                result=runtime.inspect(state)
            self.assertFalse(result['ready'])
            self.assertFalse(result['scene']['running'])

    def test_container_start_failure_keeps_scene_identity_for_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            config=load(Path(__file__).resolve().parents[1]/'airsim/runtime.demo.json')
            config['editor_settings']=str(root/'settings.json')
            (root/'settings.json').write_text(json.dumps(runtime.settings(config)))
            scene={'pid':999,'managed':True,'start_ticks':'123','binary':'test'}
            def command(*args,**kwargs):
                if args[:2]==('docker','run'):raise RuntimeError('container launch failed')
                return subprocess.CompletedProcess(args,0,json.dumps([{'Id':'test-image'}]),'')
            with patch.object(runtime,'container',return_value=None), patch.object(runtime,'free_port'), \
                    patch.object(runtime,'command',side_effect=command), patch.object(runtime,'archive'), \
                    patch.object(scene_process,'validate'), patch.object(scene_process,'launch',return_value=scene), \
                    patch.object(scene_process,'alive',return_value=True), patch.object(runtime,'editor_listener',return_value={'pid':999}):
                with self.assertRaisesRegex(RuntimeError,'container launch failed'):
                    runtime.start(config,root)
            state=json.loads((root/'state.json').read_text())
            self.assertEqual(state['phase'],'failed')
            self.assertEqual(state['scene'],scene)
            with patch.object(runtime,'owned',return_value=None),patch.object(scene_process,'stop') as stop:
                runtime.shutdown(state,root/'state.json')
                stop.assert_called_once_with(scene)

    def test_stop_failure_preserves_recoverable_state(self):
        with tempfile.TemporaryDirectory() as d:
            state=dict(phase='failed',scene={'pid':123},run_dir=d,config={})
            with patch.object(runtime,'owned',return_value=None), patch.object(scene_process,'stop',side_effect=RuntimeError('busy')):
                with self.assertRaisesRegex(RuntimeError,'部分回收失败'):
                    runtime.shutdown(state,Path(d)/'state.json')
            self.assertEqual(json.loads((Path(d)/'state.json').read_text())['phase'],'stopping')
