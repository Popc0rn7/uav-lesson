"""板端迁移的传感器语义、运行身份与 PC/板端恢复边界；不访问设备。"""
import importlib.util
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]/'airsim'
sys.path.insert(0,str(HERE))
import board_backend
import cloud_wire
import runtime

ROOT=HERE.parents[2]
spec=importlib.util.spec_from_file_location('board_manager',ROOT/'robopi/stage3/manage.py')
manager=importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


def message(points):
    data=cloud_wire.encode(points)
    return NS(header=NS(frame_id=cloud_wire.FRAME),is_bigendian=False,height=1,width=len(points)//3,
              point_step=12,row_step=len(data),data=data,
              fields=[NS(name=k,offset=i*4,datatype=7,count=1) for i,k in enumerate('xyz')])


class CloudTests(unittest.TestCase):
    def test_relaxed_timing_only_changes_consistent_planning_budget(self):
        import planner_config
        import yaml
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)/'base.yaml';relaxed=Path(temporary)/'relaxed.yaml'
            task=HERE/'task.forest10.json'
            planner_config.generate(task,base)
            planner_config.generate(task,relaxed,'robopi-relaxed')
            a=yaml.safe_load(base.read_text());b=yaml.safe_load(relaxed.read_text())
            self.assertEqual(a['super_planner']['replan_forward_dt'],.1)
            self.assertEqual(b['super_planner']['replan_forward_dt'],.1)
            self.assertEqual(b['super_planner'].pop('replan_wall_limit'),.35)
            self.assertEqual(a,b)
            planner_config.generate(task,relaxed,'robopi-forward-200ms')
            b=yaml.safe_load(relaxed.read_text())
            self.assertEqual(b['super_planner'].pop('replan_wall_limit'),.35)
            self.assertEqual(b['super_planner']['replan_forward_dt'],.2)
            b['super_planner']['replan_forward_dt']=.1
            self.assertEqual(a,b)
            with self.assertRaises(ValueError):planner_config.generate(task,relaxed,'unknown')
        with self.assertRaises(ValueError):runtime.up(dict(compute='docker',planner_timing='robopi-relaxed'),Path('/unused'))
        with self.assertRaises(ValueError):runtime.up(dict(compute='docker',planner_timing='robopi-forward-200ms'),Path('/unused'))

    def test_dds_discovers_local_agent_and_remote_board(self):
        from uav_dds import write_profile
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'dds.xml'
            write_profile('172.30.10.1','172.30.10.2',output)
            root=ET.parse(output)
            ns={'d':'http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles'}
            peers=root.findall('.//d:initialPeersList/d:locator/d:udpv4/d:address',ns)
            self.assertEqual([p.text for p in peers],['172.30.10.1','172.30.10.2'])
            self.assertEqual(root.find('.//d:interfaceWhiteList/d:address',ns).text,'172.30.10.1')
            write_profile('172.30.10.1','172.30.10.2',output,loopback=True)
            root=ET.parse(output)
            self.assertEqual([p.text for p in root.findall('.//d:interfaceWhiteList/d:address',ns)],['172.30.10.1','127.0.0.1'])

    def test_raw_wire_preserves_order_and_float32_values(self):
        points=[1.,-2.,3.,float('inf'),0.,0.]
        self.assertEqual(cloud_wire.decode(message(points)),tuple(points))
        self.assertEqual(cloud_wire.decode(message([])),())

    def test_wrong_frame_layout_endian_and_truncation_rejected(self):
        for change in [dict(is_bigendian=True),dict(data=b''),dict(point_step=16),dict(height=2)]:
            m=message([1,2,3]);m.__dict__.update(change)
            with self.assertRaises(ValueError):cloud_wire.decode(m)
        m=message([1,2,3]);m.header.frame_id='world'
        with self.assertRaises(ValueError):cloud_wire.decode(m)
        with self.assertRaises(ValueError):cloud_wire.encode([1,2])

    def test_split_registration_matches_direct_registration(self):
        import numpy as np
        from geometry import register
        from task_config import load_task
        task=load_task(HERE/'task.forest10.json')
        points=[1.,0.,0.,2.,3.,4.,.1,0.,0.,60.,0.,0.]
        pose=(np.array([10.,20.,2.]),np.eye(3))
        np.testing.assert_array_equal(register(points,pose,task['lidar']),
                                      register(cloud_wire.decode(message(points)),pose,task['lidar']))


class BoardRuntimeTests(unittest.TestCase):
    def test_up_runs_one_pc_container_and_no_algorithm_container(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            binary=directory/'scene';binary.write_bytes(b'\x7fELF');binary.chmod(0o700)
            settings=directory/'settings.json';settings.write_text(json.dumps({'Vehicles':{'PX4':{'VehicleType':'PX4Multirotor'}}}))
            config=dict(compute='robopi',target='explicit',super_task=str(HERE/'task.low.json'),
                        pc_address='172.30.10.1',board_address='172.30.10.2',
                        binary=str(binary),scene_dir=str(directory),scene_args=['Scene'],settings=str(settings),
                        image='combined',container='px4',ros_container='old-compute',startup_timeout_s=10,no_display=True)
            def initialize(state):state['board']=dict(target='explicit',remote='/release',run='/run')
            def execute(*args,**kwargs):
                return subprocess.CompletedProcess(args,0,'1\n' if args[:3]==('docker','image','inspect') else 'pc-id\n','')
            process=NS(pid=42,poll=lambda:None)
            with patch.object(runtime,'command',side_effect=execute) as commands, \
                 patch.object(runtime,'inspect_container',return_value=None), \
                 patch.object(runtime,'check_ports'),patch.object(runtime,'check_port'), \
                 patch.object(runtime.Path,'is_file',return_value=True), \
                 patch.object(runtime,'start_ticks',return_value='ticks'),patch.object(runtime,'capture_provenance',return_value={}), \
                 patch.object(runtime,'listen_owned',return_value=True),patch.object(runtime,'ready',return_value=True), \
                 patch.object(runtime.subprocess,'Popen',return_value=process), \
                 patch.object(runtime.virtual_display,'start',return_value=dict(display=':123')), \
                 patch.object(board_backend,'selected',return_value=dict(remote='/release')), \
                 patch.object(board_backend,'network_preflight') as network_check, \
                 patch.object(board_backend,'preflight'),patch.object(board_backend,'initialize',side_effect=initialize), \
                 patch.object(board_backend,'start') as board_start, \
                 patch.object(runtime,'ros_action',return_value=subprocess.CompletedProcess([],0,'OK','')):
                runtime.up(config,directory)
            network_check.assert_called_once_with('explicit','172.30.10.1','172.30.10.2')
            runs=[c.args for c in commands.call_args_list if c.args[:2]==('docker','run')]
            self.assertEqual(len(runs),1)
            self.assertIn('/lesson-airsim/run_pc_nodes.sh',runs[0])
            state=json.loads((directory/'state.json').read_text())
            self.assertNotIn('ros_container',state)
            self.assertEqual(state['config']['target'],'explicit')
            self.assertEqual(state['phase'],'ready')
            board_start.assert_called_once()

    def test_board_loss_still_cleans_pc_and_keeps_stopping(self):
        with tempfile.TemporaryDirectory() as temporary:
            state=dict(board={},run_dir=temporary,container='pc',phase='ready')
            state['board']=dict(target='explicit')
            info=dict(Id='pc-id',State=dict(Running=True))
            with patch.object(runtime,'owned_container',side_effect=[info,None]), \
                 patch.object(runtime,'owned_ros',return_value=None),patch.object(runtime,'host_alive',return_value=False), \
                 patch.object(runtime,'stop_host') as stop_host, \
                 patch.object(board_backend,'stop',side_effect=RuntimeError('HDC offline')), \
                 patch.object(runtime,'command',return_value=subprocess.CompletedProcess([],0,'','')) as commands:
                with self.assertRaisesRegex(RuntimeError,'stopping'):
                    runtime.shutdown(state,Path(temporary),force=True)
                stop_host.assert_called_once()
                self.assertEqual(state['phase'],'stopping')
                self.assertTrue(any(c.args[:2]==('docker','rm') for c in commands.call_args_list))

    def test_hdc_cancel_failure_does_not_prevent_px4_land(self):
        with tempfile.TemporaryDirectory() as temporary:
            state=dict(board=dict(target='explicit'),run_dir=temporary,owner='ours')
            with patch.object(runtime,'owned_container',return_value=dict(State=dict(Running=True))), \
                 patch.object(board_backend,'action',side_effect=RuntimeError('offline')), \
                 patch.object(runtime,'px4',return_value=subprocess.CompletedProcess([],0,'','')) as land:
                with self.assertRaisesRegex(RuntimeError,'取消未确认'):runtime.request_land(state)
                land.assert_called_once_with(state,'commander','land')
                self.assertTrue((Path(temporary)/'land.request.json').exists())

    def test_hdc_zero_without_remote_exit_marker_rejected(self):
        with patch.object(board_backend.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'Success','')):
            with self.assertRaisesRegex(RuntimeError,'退出码'):board_backend.shell('explicit','false')


    def test_release_bundle_dereferences_shared_sources_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);work=root/'work';install=work/'install'
            install.mkdir(parents=True)
            (install/'native.so').write_bytes(b'target fixture')
            digest=hashlib.sha256(b'target fixture').hexdigest()
            (work/'build-evidence.json').write_text(json.dumps(dict(files={'native.so':digest},soabi='target')))
            (work/'build-input.json').write_text('{}')
            with patch.object(board_backend,'WORK',work):
                release=board_backend.bundle(root/'release')
            self.assertFalse((root/'release/app/super_px4.py').is_symlink())
            self.assertEqual((root/'release/app/super_px4.py').read_bytes(),(ROOT/'stage3/super/super_px4.py').read_bytes())
            def local_shell(target, script, **kwargs):
                return subprocess.check_output(['sh','-c',script],text=True,stderr=subprocess.PIPE).strip()
            with patch.object(board_backend,'shell',side_effect=local_shell):
                self.assertEqual(board_backend.verify('fixture',str(root/'release'),release),release)
                (root/'release/install/native.so').write_bytes(b'corrupt')
                with self.assertRaises(subprocess.CalledProcessError):
                    board_backend.verify('fixture',str(root/'release'),release)

    def test_display_with_reused_pid_is_not_stopped(self):
        display=dict(process=dict(pid=77,ticks='old'))
        with patch.object(runtime.virtual_display,'identity',return_value=dict(pid=77,ticks='new')), \
             patch.object(runtime.virtual_display.os,'kill') as kill:
            runtime.virtual_display.stop(display)
            kill.assert_not_called()

    def test_pid_reuse_is_not_considered_owned(self):
        with patch.object(manager,'identity',return_value=dict(pid=7,ticks='new')):
            self.assertFalse(manager.alive(dict(pid=7,ticks='old')))

    def test_run_metadata_cannot_select_other_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            (directory/'run.json').write_text(json.dumps(dict(owner=directory.name,release='/unrelated')))
            with self.assertRaisesRegex(RuntimeError,'release'):manager.metadata(directory)


if __name__=='__main__':unittest.main()
