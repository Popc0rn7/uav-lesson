"""任务占锁时的人工恢复与资源身份边界。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'airsim'))
import runtime


class RecoveryTests(unittest.TestCase):
    def test_land_status_stop_available_during_task(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/'state.json').write_text(json.dumps(dict(phase='ready')))
            with runtime.management_lock(path,'task'):
                for action,force in [('status',False),('land',False),('stop',False),('down',True)]:
                    with runtime.management_lock(path,action,force): pass
                with self.assertRaisesRegex(RuntimeError,'stop'):
                    with runtime.management_lock(path,'down'): pass
                with self.assertRaises(RuntimeError):
                    with runtime.management_lock(path,'task'): pass

    def test_recoveries_are_serialized(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            with runtime.management_lock(path,'land'):
                with self.assertRaisesRegex(RuntimeError,'恢复命令'):
                    with runtime.management_lock(path,'stop'): pass

    def test_cannot_bypass_in_progress_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/'state.json').write_text(json.dumps(dict(phase='starting')))
            with runtime.management_lock(path,'up'):
                with self.assertRaisesRegex(RuntimeError,'初始化'):
                    with runtime.management_lock(path,'stop'): pass

    def test_land_latches_cancellation_before_command(self):
        with tempfile.TemporaryDirectory() as directory:
            state=dict(run_dir=directory,owner='ours',ros_container='ros')
            def send(*args):
                self.assertEqual(json.loads((Path(directory)/'land.request.json').read_text())['owner'],'ours')
                return subprocess.CompletedProcess([],0,'','')
            with patch.object(runtime,'owned_container',return_value={'State':{'Running':True}}), \
                    patch.object(runtime,'owned_ros',return_value={}), patch.object(runtime,'px4',side_effect=send), patch('builtins.print'):
                runtime.request_land(state)

    def test_wrong_owner_blocks_all_stop_operations(self):
        state=dict(container='px4',owner='ours')
        info=dict(Id='unrelated',Config=dict(Labels={runtime.LABEL:'theirs'}))
        with patch.object(runtime,'inspect_container',return_value=info),patch.object(runtime,'command') as command:
            with self.assertRaisesRegex(RuntimeError,'不属于'):
                runtime.shutdown(state,Path('/tmp'),force=True)
            command.assert_not_called()

    def test_force_continues_after_ros_stop_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            state=dict(run_dir=directory,container='px4',ros_container='ros',phase='ready')
            def execute(*args,**kwargs):
                if args[:2]==('docker','stop') and args[-1]=='ros-id':
                    raise subprocess.TimeoutExpired('docker stop',12)
                return subprocess.CompletedProcess(args,0,'logs','')
            with patch.object(runtime,'owned_container',side_effect=[dict(Id='px4-id',State=dict(Running=True)),None]), \
                    patch.object(runtime,'owned_ros',side_effect=[dict(Id='ros-id',State=dict(Running=True)),None]), \
                    patch.object(runtime,'host_alive',return_value=False),patch.object(runtime,'stop_host') as stop_host, \
                    patch.object(runtime,'command',side_effect=execute) as command:
                with self.assertRaisesRegex(RuntimeError,'stopped'):
                    runtime.shutdown(state,path,force=True)
                stop_host.assert_called_once()
                self.assertIn(('docker','rm','-f','px4-id'),[call.args for call in command.call_args_list])
                self.assertEqual(json.loads((path/'state.json').read_text())['phase'],'stopped')


if __name__=='__main__': unittest.main()
