import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from planner import validate_plan,generate
from follow import follow_questions
from tactics import Tactician
from test_tactics import FakeClient,state
from types import SimpleNamespace
import time


def plan():
    return dict(version=1,mission='跟随红车',stages=[dict(id='follow_vehicle',goal='后上方跟随红车',
        skill='follow_red_vehicle',dino_text='a red car. a red box.',horizontal_distance_m=8,
        above_m=2,duration_s=5,completion_criteria='累计有效跟随5秒',failure_criteria='持续丢失',
        allowed_skills=['hold_course','brake','reacquire'])])


class PlannerTests(unittest.TestCase):
    def test_rejects_unsupported_or_out_of_bounds_plan(self):
        self.assertEqual(validate_plan(plan())['stages'][0]['above_m'],2)
        for field,value in [('skill','search_bridge'),('above_m',float('nan')),
                            ('horizontal_distance_m',100),('duration_s',True),('dino_text','')]:
            candidate=copy.deepcopy(plan());candidate['stages'][0][field]=value
            with self.assertRaises(ValueError):validate_plan(candidate)
        with self.assertRaises(ValueError):validate_plan({'unsupported_reason':'没有桥搜索技能'})
        with self.assertRaises(ValueError):validate_plan(plan(),max_seconds=4)

    def test_vlm_receives_image_and_returns_validated_plan(self):
        session=MagicMock()
        response=session.__enter__.return_value.post.return_value
        response.ok=True
        response.json.return_value={'choices':[{'message':{'content':json.dumps(plan())}}]}
        with patch('planner.requests.Session',return_value=session):
            result=generate({'QWEN_BASE_URL':'http://localhost:9999/v1','QWEN_MODEL':'test-vlm'},'跟随红车',b'PNG',5)
        self.assertEqual(result,plan())
        self.assertIs(session.__enter__.return_value.trust_env, False)
        session.__enter__.return_value.proxies.update.assert_not_called()
        args=session.__enter__.return_value.post.call_args
        self.assertEqual(args.args[0],'http://localhost:9999/v1/chat/completions')
        self.assertIs(args.kwargs['json']['enable_thinking'], False)
        self.assertTrue(args.kwargs['json']['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))

    def test_requires_explicit_model_configuration(self):
        with self.assertRaises(ValueError):generate({},'跟随',b'PNG',5)

    def test_stage_status_disables_motion_for_completed_or_blocked(self):
        class StageClient(FakeClient):
            def system_one(self,**kwargs):
                response=super().system_one(**kwargs)
                response.answers['stage_status']=SimpleNamespace(choice='completed')
                return response
        actor=Tactician({},client=StageClient(maneuver='hold_course'))
        actor.questions=follow_questions(plan()['stages'][0])
        self.addCleanup(actor.close)
        actor.offer(state(),time.monotonic())
        judgment=actor.wait_result()
        self.assertEqual(judgment['stage_status'],'completed')
        self.assertFalse(judgment['actionable'])
        self.assertEqual(judgment['effective_maneuver'],'brake')


if __name__=='__main__':unittest.main()
