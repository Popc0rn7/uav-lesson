import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from stage4 import runtime


class RuntimeTests(unittest.TestCase):
    def test_px4_acceleration_follows_task_override(self):
        task=dict(spawn_ned_m=[0,0,0],start_quaternion_xyzw=[0,0,0,1],
                  control=dict(acceleration_m_s2=4.))
        with patch.object(runtime.host,'runtime_settings',return_value=dict(Vehicles=dict(PX4=dict(Parameters={})))):
            settings=runtime.settings({},task)
        self.assertEqual(settings['Vehicles']['PX4']['Parameters'],dict(MPC_ACC_HOR=4.,MPC_ACC_HOR_MAX=4.))

    def test_manual_standby_requires_disarmed_and_valid_position(self):
        with tempfile.TemporaryDirectory() as folder:
            state={'run_dir':folder}
            for arming,nav,valid,expected in ((1,0,True,True),(2,0,True,False),(1,14,True,False),(1,0,False,False)):
                calls=[]
                def px4(state,module,*args):
                    calls.append((module,*args))
                    output=(f'    arming_state: {arming}\n    nav_state: {nav}\n' if args==('vehicle_status',) else
                            f'    xy_valid: {valid}\n    z_valid: {valid}\n')
                    return subprocess.CompletedProcess([],0,output,'')
                with patch.object(runtime.host,'px4',side_effect=px4): runtime.prepare_px4(state)
                self.assertEqual(('commander','mode','auto:loiter') in calls,expected)
    def test_scene_crash_is_not_reported_as_px4_readiness_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'airsim-console.log'
            path.write_text('Unhandled Exception: SIGSEGV\nFVulkanPipelineStateCacheManager')
            error=runtime.host.scene_startup_error(folder)
            self.assertIn('Vulkan',str(error)); self.assertIn(str(path),str(error))
    def test_final_collision_check_separates_flight_impact_from_touchdown(self):
        report=dict(landing_started_sim_s=10.,task_success=True,chain_completed=True)
        touchdown=dict(has_collided=True,time_stamp=11_000_000_000)
        self.assertTrue(runtime.reconcile_collision(report.copy(),touchdown,0)['task_success'])
        impact=dict(has_collided=True,time_stamp=9_000_000_000)
        result=runtime.reconcile_collision(report.copy(),impact,0)
        self.assertFalse(result['task_success']); self.assertTrue(result['flight_collision'])
        self.assertTrue(runtime.reconcile_collision(report.copy(),impact,9_000_000_000)['task_success'])

    def test_non_super_ros_workload_mounts_and_snapshots(self):
        host=runtime.host; calls=[]
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder); binary=directory/'scene'; binary.write_bytes(b'\x7fELF'); binary.chmod(0o700)
            config=dict(scene_dir=folder,binary=str(binary),settings='unused.json',image='px4',ros_image='ros',
                        container='stage4-px4',ros_container='stage4-ros',scene_args=[],startup_timeout_s=10)
            workload=dict(task={'name':'test'},settings={'Vehicles':{}},env=['AEROVLA_API_URL'])
            def command(*args,**kwargs):
                calls.append(tuple(map(str,args)))
                return subprocess.CompletedProcess(args,0,'identity','')
            class Process:
                pid=12345
                def poll(self): return None
            with patch.dict(os.environ,{'DISPLAY':':99','AEROVLA_API_URL':'http://test/infer'}), \
                 patch.object(host,'command',side_effect=command), \
                 patch.object(host,'inspect_container',return_value=None), \
                 patch.object(host,'check_ports'),patch.object(host,'check_port'), \
                 patch.object(host,'capture_provenance',return_value={}), \
                 patch.object(host,'start_ticks',return_value='1'), \
                 patch.object(host,'listen_owned',return_value=True), \
                 patch.object(host,'ready',return_value=True), \
                 patch.object(host,'host_alive',return_value=True), \
                 patch.object(host.subprocess,'Popen',return_value=Process()):
                host.up(config,directory,ros_entrypoint='/lesson/stage4/run_nodes.sh',
                        ros_check=lambda state:subprocess.CompletedProcess([],0,'ready',''),ros_runtime=workload)
            state=json.loads((directory/'state.json').read_text())
            self.assertEqual(state['phase'],'ready')
            run_dir=Path(state['run_dir'])
            self.assertEqual((run_dir/'run-id').read_text(),state['owner'])
            self.assertEqual(json.loads((run_dir/'task.json').read_text()),workload['task'])
            runs=[args for args in calls if args[:2]==('docker','run')]
            self.assertEqual(len(runs),2)
            self.assertIn('AIRSIM_SUPER=1',runs[0])
            self.assertIn('/lesson/stage4/run_nodes.sh',runs[1])
            self.assertIn('AEROVLA_API_URL',runs[1])
            self.assertFalse(any('/super_ws' in arg for arg in runs[1]))


if __name__=='__main__': unittest.main()
