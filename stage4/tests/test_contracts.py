import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stage4.contracts import (DEFAULTS, action_target, enu, enu_flu_quaternion,
                              prompt, validate_action, validate_task, yaw_xyzw)
from stage4.motion import Motion, InferenceGate
from stage4.prepare_task import prepare


class ContractsTests(unittest.TestCase):
    def test_action_geometry_and_original_yaw_branch(self):
        p,yaw=action_target([1,2,-3],math.pi/2,dict(fwd=2,down=-1,yaw=0))
        self.assertAlmostEqual(p[0],1); self.assertAlmostEqual(p[1],4); self.assertEqual(p[2],-4)
        p,yaw=action_target([1,2,-3],0,dict(fwd=5,down=1,yaw=.25))
        self.assertEqual(p,[1,2,-2]); self.assertEqual(yaw,.25)

    def test_frames_and_quaternion_round_trip(self):
        self.assertEqual(enu([1,2,3]),[2,1,-3])
        for angle in (0,.5,-1.,math.pi):
            q=[0,0,math.sin(angle/2),math.cos(angle/2)]
            converted=enu_flu_quaternion(q)
            self.assertAlmostEqual(math.sin(yaw_xyzw(converted)),math.sin(math.pi/2-angle))
            restored=enu_flu_quaternion(converted)
            self.assertAlmostEqual(abs(sum(a*b for a,b in zip(q,restored))),1.)

    def test_prompt_rotates_world_into_body(self):
        q=[0,0,math.sqrt(.5),math.sqrt(.5)]
        self.assertIn('straight ahead',prompt([0,0,0],q,[0,10,0],'table'))
        self.assertIn('to your left ',prompt([0,0,0],q,[10,0,0],'table'))
        self.assertEqual(prompt([0,0,0],[0,0,0,1],[10,0,0],'table'),
                         '<image>\nFly straight ahead and find the target. table\nAction: ')

    def test_invalid_actions_do_not_become_stop(self):
        for action in ({},dict(fwd=float('nan'),down=0,yaw=0),dict(fwd=True,down=0,yaw=0),dict(fwd=6,down=0,yaw=0)):
            with self.assertRaises(ValueError): validate_action(action)

    def test_reference_speed_acceleration_and_yaw_limits(self):
        motion=Motion([0,0,0],[5,2,-4],3,-3,0,DEFAULTS)
        samples=[motion.sample(motion.duration*i/1000) for i in range(1001)]
        self.assertLessEqual(max(math.dist(s[1],[0,0,0]) for s in samples),DEFAULTS['speed_m_s']+.00001)
        self.assertLessEqual(max(math.dist(s[2],[0,0,0]) for s in samples),DEFAULTS['acceleration_m_s2']+.00001)
        self.assertLessEqual(max(abs(s[4]) for s in samples),.50001)
        self.assertEqual(samples[-1][0],[5,2,-4]); self.assertTrue(samples[-1][-1])

    def test_late_and_cancelled_response_never_executes(self):
        gate=InferenceGate(); gate.begin('a')
        self.assertFalse(gate.accept('b')); self.assertTrue(gate.accept('a'))
        gate.begin('b'); gate.cancel(); self.assertFalse(gate.accept('b'))
        with self.assertRaises(RuntimeError): gate.begin('c')

    def test_fast_horizontal_motion_keeps_vertical_limits(self):
        horizontal=Motion([0,0,0],[4.9,0,0],0,0,0,DEFAULTS)
        self.assertLess(horizontal.duration,2.7)
        for dz,speed in ((-5.,2.),(5.,1.)):
            motion=Motion([0,0,0],[4.9,0,dz],0,0,0,DEFAULTS)
            samples=[motion.sample(motion.duration*i/1000) for i in range(1001)]
            self.assertLessEqual(max(abs(s[1][2]) for s in samples),speed+.00001)
            self.assertLessEqual(max(abs(s[2][2]) for s in samples),3.00001)

    def test_prepare_without_model_imports_and_target_correction(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            files={'data/uav_dataset/seen_valset_splits/Carla_Town05.json':[{'json':'Carla_Town05/a/merged_data.json','frame':1}],
                'dataset_raw/Carla_Town05/a/merged_data.json':dict(trajectory_raw_detailed=[dict(position=[1,2,-2],orientation=[0,0,0,1])],
                    conversations=[dict(value='target 0 degrees from you. table Please control drone')]),
                'dataset_raw/Carla_Town05/a/mark.json':dict(target=dict(position=[10,20,0])),
                'data/meta/map_spawnarea_info.json':dict(Carla_Town05=[[9,19,-.5,0,0,0,0,0,0,10,20,1,1,0,0,0,'table',1]])}
            for path,data in files.items():
                dest=root/path; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_text(json.dumps(data))
            task=prepare(root)
            self.assertEqual(task['target_ned_m'],[10,20,1]); self.assertEqual(task['object_description'],'table')
            self.assertEqual(task['spawn_ned_m'],[1,2,0])
            task['control']['speed_m_s']=9
            with self.assertRaises(ValueError): validate_task(task)


if __name__=='__main__': unittest.main()
