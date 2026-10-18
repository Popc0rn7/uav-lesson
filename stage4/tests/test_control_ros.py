"""Run inside the existing ROS image; exercise the actual control-node entry."""
from concurrent.futures import Future
import json
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest

try:
    from stage4.control import Control
    from stage4.evaluation import Evaluation
    from stage4.motion import InferenceGate
except ImportError:
    Control=None


@unittest.skipIf(Control is None,'requires ROS image')
class ControlEvaluationTests(unittest.TestCase):
    def fake(self,folder,step=0):
        point=NS(x=0.,y=0.,z=0.); quat=NS(x=0.,y=0.,z=0.,w=1.)
        odom=NS(pose=NS(pose=NS(position=point,orientation=quat)))
        image=NS(encoding='rgb8',step=3,width=1,height=1,data=b'\x80\x00\xff')
        calls=[]; land=[]
        pool=NS(submit=lambda *args:(calls.append(args) or Future()))
        node=NS(pair=lambda:(1.,odom,[image,image],dict(fractions={'FrontCamera':0.})),
                task=dict(spawn_ned_m=[0,0,0],target_ned_m=[30,0,0],object_description='table',
                          instruction='0 degrees from you. table Please control'),
                origin=[0,0,0],config=dict(success_distance_m=20.,max_steps=2),
                step=step,run_id='test',directory=Path(folder),evaluation=None,evaluated_step=-1,
                gate=InferenceGate(),pool=pool,api=NS(infer=lambda:None),land=lambda *args:land.append(args))
        return node,calls,land

    def test_committed_ui_observation_matches_submitted_image_and_pose(self):
        with tempfile.TemporaryDirectory() as folder:
            node,calls,land=self.fake(folder)
            Control.inference(node)
            self.assertEqual(node.mode,'infer'); self.assertEqual(len(calls),1); self.assertFalse(land)
            observation=json.loads((Path(folder)/'observation.json').read_text())
            self.assertTrue(observation['submitted'])
            self.assertEqual(observation['estimated_world_ned'],calls[0][3])
            self.assertEqual((Path(folder)/'observations/0/front.png').read_bytes(),calls[0][-2])

    def test_depth_terminal_never_submits_another_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            node,calls,land=self.fake(folder,step=1)
            stamp,odom,images,depth=node.pair()
            node.pair=lambda:(stamp,odom,images,dict(fractions={'FrontCamera':.2}))
            node.evaluation=Evaluation([30,0,0]); node.evaluation.initialize([1,0,0])
            Control.inference(node)
            self.assertEqual(land,[('depth proximity',True)]); self.assertFalse(calls)
            self.assertFalse(json.loads((Path(folder)/'observation.json').read_text())['submitted'])

    def test_final_action_is_evaluated_before_step_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            node,calls,land=self.fake(folder,step=2)
            node.task['target_ned_m']=[0,0,0]
            node.evaluation=Evaluation([0,0,0]); node.evaluation.initialize([30,0,0])
            Control.inference(node)
            self.assertTrue(node.evaluation.oracle_success)
            self.assertEqual(land,[('step limit',True)]); self.assertFalse(calls)
