from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from simulation_wait import SimulationWait


class SimulationWaitTests(unittest.TestCase):
    def make(self):
        clock=[0.]; sim=[10.]; control=Mock()
        gate=SimulationWait('',sample=lambda:sim[0],control=control,clock=lambda:clock[0])
        return gate,clock,sim,control

    def test_uses_simulated_seconds_and_restores_after_pause(self):
        gate,clock,sim,control=self.make();runtime=Mock();events=[]
        gate.begin(runtime,lambda name,**data:events.append(name))
        clock[0]=100.;sim[0]=12.9;gate.tick();control.assert_not_called()
        clock[0]=101.;sim[0]=13.01;gate.tick()
        self.assertTrue(gate.paused);control.assert_called_once_with(True)
        clock[0]=102.;sim[0]=13.1;gate.finish()
        self.assertFalse(gate.paused);self.assertFalse(gate.active)
        self.assertEqual([c.args for c in control.call_args_list],[(True,),(False,)])
        self.assertEqual(events,['qwen_sim_window','simulation_paused','simulation_resumed'])
        self.assertEqual([c.args for c in runtime.simulation_pause_changed.call_args_list],[(True,),(False,)])

    def test_fast_request_never_pauses_or_resumes_world(self):
        gate,clock,sim,control=self.make();gate.begin(None,lambda *a,**k:None)
        clock[0]=2;sim[0]=12;gate.tick();gate.finish();control.assert_not_called()

    def test_pause_ack_failure_still_records_restore_ownership(self):
        gate,clock,sim,control=self.make();gate.begin(None,lambda *a,**k:None)
        control.side_effect=RuntimeError('ack lost');clock[0]=4;sim[0]=14
        with self.assertRaises(RuntimeError):gate.tick()
        self.assertTrue(gate.paused)
        control.side_effect=None;sim[0]=14.1;gate.finish()
        self.assertFalse(gate.paused)
