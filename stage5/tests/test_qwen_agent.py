from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qwen_agent import QwenAgent,QwenHTTPError


class QwenTests(unittest.TestCase):
    def model(self):return QwenAgent({'QWEN_BASE_URL':'http://localhost:18080/v1','QWEN_MODEL':'qwen-local'})
    def test_summary_uses_read_only_prompt_without_action_examples(self):
        session=MagicMock();response=session.__enter__.return_value.post.return_value
        response.ok=True;response.json.return_value={'choices':[{'message':{'content':'{"summary":"结束"}'}}]}
        with patch('qwen_agent.requests.Session',return_value=session):
            value=self.model().request('summary',{'outcome':'failed'},[],2)
        self.assertEqual(value['summary'],'结束')
        system=session.__enter__.return_value.post.call_args.kwargs['json']['messages'][0]['content']
        self.assertIn('不能验收',system)
        self.assertNotIn('modify_stage',system)
        self.assertIs(session.__enter__.return_value.post.call_args.kwargs['json']['enable_thinking'], False)
        self.assertIs(session.__enter__.return_value.trust_env, False)
        session.__enter__.return_value.proxies.update.assert_not_called()

    def test_http_failure_does_not_expose_body_or_headers(self):
        session=MagicMock();response=session.__enter__.return_value.post.return_value
        response.ok=False;response.status_code=451;response.text='private server data'
        with patch('qwen_agent.requests.Session',return_value=session):
            with self.assertRaises(QwenHTTPError) as error:self.model().request('plan',{},[],2)
        self.assertEqual(error.exception.status,451)
        self.assertNotIn('private',str(error.exception))

    def test_planning_prompt_explains_allocation_and_recovery_limits(self):
        session=MagicMock();response=session.__enter__.return_value.post.return_value
        response.ok=True;response.json.return_value={'choices':[{'message':{'content':'{}'}}]}
        payload={'execution_guidance':{'suggested_follow_budget':31}}
        with patch('qwen_agent.requests.Session',return_value=session):
            self.model().request('plan',payload,[],2)
        messages=session.__enter__.return_value.post.call_args.kwargs['json']['messages']
        self.assertIn('budget31',messages[0]['content'])
        self.assertIn('不具备转头',messages[0]['content'])
        self.assertIn('suggested_follow_budget',messages[1]['content'][0]['text'])




class ReportHistoryTests(unittest.TestCase):
    def test_history_keeps_previous_input_and_exact_answer_without_execution_json(self):
        import copy
        session=MagicMock();response=session.__enter__.return_value.post.return_value
        response.ok=True
        output='{"action":"redo", "assessment":"保留完整判断", "allocation":{"budget":10,"timeout":20}}'
        response.json.return_value={'choices':[{'message':{'content':output}}],
                                    'usage':{'prompt_tokens':123,'completion_tokens':25,'total_tokens':148}}
        model=QwenAgent({'QWEN_BASE_URL':'http://localhost/v1','QWEN_MODEL':'test'})
        raw={'task':'跟随10秒','plan':{'stages':[{'id':'follow','goal':'跟随'}]},'current_index':0,
             'stage_reports':[{'status':'failed','reason':'tracking_unavailable','progress':{'valid_follow_s':3.2},
                               'observation':{'tracking':None,'detections':[{'secret_debug':'long'}]},
                               'judgment':{'stage_status':'failed','probabilities':{'brake':1}}}],
             'observation':{'detections':[{'secret_debug':'long'}]}}
        before=copy.deepcopy(raw)
        with patch('qwen_agent.requests.Session',return_value=session):
            model.request('review',raw,[{'png':b'old'},{'png':b'latest'}],2)
            first_parts=session.__enter__.return_value.post.call_args.kwargs['json']['messages'][1]['content']
            self.assertEqual(len(first_parts),2)
            self.assertTrue(first_parts[1]['image_url']['url'].endswith('bGF0ZXN0'))
            model.request('review',raw,[],2)
        request=model.last_request['input']
        self.assertEqual(request['history'][1]['content'],output)
        self.assertEqual(request['history'][0]['content']['stage_report']['progress']['valid_follow_s'],3.2)
        self.assertNotIn('history',request['history'][0]['content'])
        self.assertNotIn('secret_debug',str(request))
        self.assertNotIn('probabilities',str(request))
        self.assertEqual(raw,before)
        self.assertEqual(model.last_metrics['usage']['prompt_tokens'],123)
        self.assertEqual(model.last_metrics['history_turns'],1)


if __name__ == '__main__':
    unittest.main()
