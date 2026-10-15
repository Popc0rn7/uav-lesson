import copy
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_runtime import FlightRuntime
from task_runner import FatalControl
from test_task_runner import stage


class Flight:
    def __init__(self):
        self.armed=True;self.mode=4;self.heartbeat_at=time.monotonic();self.sent=[]
    def snapshot(self):return dict(p=np.array([0.,0.,-2.5]),q=np.array([1.,0.,0.,0.]),age=0.)
    def poll(self):self.heartbeat_at=time.monotonic()
    def start_stream(self,yaw):pass
    def send(self,v,yaw):self.sent.append(list(v))
    def hold(self):self.mode=4
    def command(self,*args):self.mode=6
    def close(self):pass


class Perception:
    def __init__(self):self.generation=0;self.visible=True;self.target_x=8
    def configure(self,text):self.generation+=1;return self.generation
    def snapshot(self):
        tracking=dict(target={'position_camera_flu_m':[self.target_x,0,-2]},target_ned=[self.target_x,0,-.5],velocity_ned=[.7,0,0],
                      at=time.monotonic(),sim_time=1.,confirmed=True,clearance_m=20.) if self.visible else None
        return dict(at=time.monotonic(),generation=self.generation,tracking=tracking,
                    local_space={'motion_candidates':{'forward_1m':{'status':'unknown'}},'front_clearance_m':20.})
    def image(self):return None
    def close(self):pass


class Actor:
    def __init__(self,*args,**kwargs):
        self.attempts=0;self.budget=20;self.pending=False;self.states=[];self.wrong_tag=False;self.status='running'
    def offer(self,state,at):self.states.append(state);self.attempts=1
    def read(self):
        tag={k:self.states[-1][k] for k in ('plan_revision','stage_id','attempt')}
        if self.wrong_tag:tag['attempt']=-1
        return dict(source='jev',stale=False,actionable=True,effective_maneuver='hold_course',
                    maneuver='hold_course',risk=0,stage_status=self.status,**tag)
    def close(self,wait=True):pass
    def stats(self):return dict(attempts=self.attempts,calls=self.attempts,errors=0)


class RuntimeTests(unittest.TestCase):
    def test_done_without_qualified_following_is_rejected(self):
        runtime,flight,sensor,directory=self.runtime();self.start(runtime,directory)
        runtime.actor.status='done'
        self.assertIsNone(runtime.step())
        self.assertEqual(runtime.rejected_stage_status['rejected'],'completion evidence not met')


    def test_failure_without_supporting_tracking_loss_is_not_stage_end(self):
        runtime,flight,sensor,directory=self.runtime();self.start(runtime,directory)
        original=runtime.actor.read
        runtime.actor.read=lambda:{**original(),'stage_status':'failed','stage_reason':'tracking_lost',
                                   'actionable':False,'effective_maneuver':'brake'}
        self.assertIsNone(runtime.step())
        self.assertEqual(runtime.rejected_stage_status['reason'],'tracking_lost')
        self.assertEqual(flight.sent[-1],[0.,0.,0.])

    def test_expected_pause_does_not_trigger_telemetry_stale_fault(self):
        runtime,flight,sensor,directory=self.runtime()
        runtime.simulation_pause_changed(True)
        flight.snapshot=lambda:None
        runtime.service()
        self.assertFalse(runtime.frozen)
        runtime.simulation_pause_changed(False)
        runtime.resume_until=time.monotonic()-1
        with self.assertRaises(FatalControl):runtime.service()


    def test_persistent_tracking_loss_is_bounded_and_reported(self):
        runtime, flight, sensor, directory = self.runtime()
        sensor.visible = False
        self.start(runtime, directory)
        runtime.no_tracking_since = time.monotonic()-9
        result = runtime.step()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'tracking_unavailable')
        self.assertEqual(flight.sent[-1], [0.,0.,0.])
        self.assertFalse(result['execution_health']['active_search_available'])


    def runtime(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        flight=Flight();sensor=Perception()
        patches=[patch('agent_runtime.Flight',return_value=flight),patch('agent_runtime.Perception',return_value=sensor),
                 patch('agent_runtime.Tactician',Actor),patch('agent_runtime.target_command'),
                 patch('agent_runtime.fcntl.flock')]
        for item in patches:item.start();self.addCleanup(item.stop)
        runtime=FlightRuntime({},temporary.name,time.monotonic()+30)
        self.addCleanup(runtime.close)
        runtime.images=lambda:[]
        return runtime,flight,sensor,Path(temporary.name)

    def start(self,runtime,directory,current=None):
        runtime.start(current or stage(),{'valid_follow_s':0.,'observed_s':0.},
                      {'plan_revision':1,'stage_id':'follow','attempt':1},directory)
        for _ in range(3):
            runtime.service();runtime.step()  # 等待新的Hold/Offboard心跳，而非使用上个阶段缓存。

    def test_missing_target_is_submitted_to_jev_and_never_moves(self):
        runtime,flight,sensor,directory=self.runtime();sensor.visible=False
        self.start(runtime,directory)
        runtime.step()
        self.assertEqual(runtime.actor.states[-1]['observed']['target_candidates'],[])
        self.assertFalse(runtime.actor.states[-1]['observed']['target_visible'])
        self.assertEqual(flight.sent[-1],[0.,0.,0.])

    def test_late_previous_attempt_decision_cannot_move_aircraft(self):
        runtime,flight,sensor,directory=self.runtime()
        self.start(runtime,directory);runtime.actor.wrong_tag=True
        runtime.step()
        self.assertEqual(flight.sent[-1],[0.,0.,0.])
        self.assertEqual(runtime.progress['valid_follow_s'],0.)

    def test_observe_skill_does_not_follow_even_with_bad_maneuver(self):
        runtime,flight,sensor,directory=self.runtime()
        current=stage(skill='observe_target',allowed_skills=['brake','reacquire'])
        self.start(runtime,directory,current);runtime.step()
        self.assertEqual(flight.sent[-1],[0.,0.,0.])
        self.assertEqual(runtime.progress['valid_follow_s'],0.)

    def test_jev_done_is_reported_for_qwen_without_local_acceptance(self):
        runtime,flight,sensor,directory=self.runtime();self.start(runtime,directory)
        runtime.actor.status='done'
        runtime.progress['valid_follow_s']=runtime.current['duration_s']
        report=runtime.end(runtime.step())
        self.assertEqual(report['status'],'done')
        self.assertEqual(report['progress']['valid_follow_s'],runtime.current['duration_s'])
        self.assertEqual(report['jev_calls'],1)
        self.assertFalse(runtime.active);self.assertEqual(flight.mode,4)

    def test_control_fault_freezes_execution(self):
        runtime,flight,sensor,directory=self.runtime()
        flight.armed=False
        with self.assertRaises(FatalControl):runtime.service()
        self.assertTrue(runtime.frozen)
        self.assertEqual(flight.sent[-1],[0,0,0])

    def test_approaching_time_is_not_qualified_following(self):
        runtime,flight,sensor,directory=self.runtime();sensor.target_x=18
        self.start(runtime,directory);runtime.step()
        self.assertGreater(runtime.progress['enabled_follow_s'],0)
        self.assertEqual(runtime.progress['valid_follow_s'],0)
        self.assertGreater(flight.sent[-1][0],0)

    def test_cached_previous_offboard_is_not_new_stage_confirmation(self):
        runtime,flight,sensor,directory=self.runtime()
        runtime.start(stage(),{'valid_follow_s':0.,'observed_s':0.},
                      {'plan_revision':1,'stage_id':'follow','attempt':1},directory)
        flight.mode=6;runtime.service();runtime.step()
        self.assertFalse(runtime.offboard_seen)
        self.assertIsNone(runtime.mode_requested_at)


if __name__=='__main__':unittest.main()
