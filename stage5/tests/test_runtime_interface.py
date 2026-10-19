"""SUPER兼容命令、任务互斥与独立恢复，不调用设备或付费API。"""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
import os
from unittest.mock import Mock,patch

from stage5.airsim import runtime


class RuntimeInterfaceTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'AIRSIM_MOUNTAINS': '/tmp/stage5-test/demo/Binaries/Linux/demo-Linux-Shipping'})
        env.start()
        self.addCleanup(env.stop)

    def test_recovery_and_status_are_available_during_task(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'state.json').write_text(json.dumps({'phase':'ready'}))
            with runtime.management_lock(root,'task'):
                for action in ('status','land','stop'):
                    with runtime.management_lock(root,action): pass
                with runtime.management_lock(root,'down',force=True): pass
                for action in ('up','task','down'):
                    with self.assertRaisesRegex(RuntimeError,'任务/管理命令'):
                        with runtime.management_lock(root,action): pass

    def test_recovery_does_not_race_startup_or_another_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'state.json';state.write_text(json.dumps({'phase':'starting'}))
            with runtime.management_lock(root,'up'):
                with self.assertRaisesRegex(RuntimeError,'正在初始化'):
                    with runtime.management_lock(root,'stop'): pass
            state.write_text(json.dumps({'phase':'ready'}))
            with runtime.management_lock(root,'land'):
                with self.assertRaisesRegex(RuntimeError,'另一个恢复'):
                    with runtime.management_lock(root,'stop'): pass

    def test_runtime_task_forwards_options_and_exit_status(self):
        from stage5.airsim import task
        with tempfile.TemporaryDirectory() as d,patch.object(task,'main',return_value=7) as call:
            self.assertEqual(runtime.main(['task','--state-dir',d,'--prompt-id','pickup_rear_follow','--budget','6']),7)
            call.assert_called_once_with(['run','--state-dir',d,'--prompt-id','pickup_rear_follow','--budget','6'])

    def test_dry_run_does_not_connect_or_launch(self):
        with patch.object(runtime,'command') as command, patch.object(runtime,'start') as start,redirect_stdout(StringIO()) as out:
            self.assertEqual(runtime.main(['up','--dry-run','--image','local:test']),0)
        self.assertEqual(json.loads(out.getvalue())['config']['px4_image'],'local:test')
        command.assert_not_called();start.assert_not_called()

    def test_stop_is_force_shutdown_and_writes_cancellation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=dict(run_id='ours',run_dir=d,phase='ready')
            (root/'state.json').write_text(json.dumps(state))
            with patch.object(runtime,'shutdown',return_value={'stopped':True}) as stop,redirect_stdout(StringIO()):
                runtime.main(['stop','--state-dir',d])
            self.assertTrue(stop.call_args.args[2])
            self.assertEqual(json.loads((root/'land.request.json').read_text())['reason'],'simulation_stop')

    def test_land_marks_cancel_before_flight_command(self):
        with tempfile.TemporaryDirectory() as d:
            state=dict(run_id='ours',run_dir=d)
            def land(*args):
                self.assertTrue((Path(d)/'land.request.json').exists())
                return Mock(stdout='requested')
            with patch.object(runtime,'px4',side_effect=land):
                self.assertTrue(runtime.request_land(state)['requested'])

    def test_cancelled_executor_does_not_override_land_with_hold(self):
        from stage5.airsim.mission_runtime import AirSimFlightRuntime
        from agent_errors import FatalControl
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'land.request.json').write_text('{}')
            instance=AirSimFlightRuntime.__new__(AirSimFlightRuntime)
            instance.config={'AIRSIM_RUN_DIR':d};instance.flight=Mock();instance.stop_convoy=Mock();instance.yaw=0
            with self.assertRaises(FatalControl):instance.service()
            instance.freeze()
            instance.flight.hold.assert_not_called()
            instance.flight.command.assert_not_called()
            self.assertTrue(instance.frozen)

    def test_takeoff_cancel_stops_before_next_poll(self):
        from stage5.airsim.task import await_hover
        flight=Mock()
        def cancel():raise RuntimeError('manual cancel')
        with self.assertRaisesRegex(RuntimeError,'manual cancel'):
            await_hover(flight,None,8,None,30,Mock(),cancel=cancel)
        flight.poll.assert_not_called()
