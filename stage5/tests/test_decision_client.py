import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decision_client import DecisionClient, DecisionHTTPError, Choice, Score, Noul
from dino_client import configuration


class DecisionClientTests(unittest.TestCase):
    def client(self, backend):
        config = dict(JEV_BACKEND=backend, JEV_BASE_URL='http://model.test/v1', JEV_API_KEY='test-key')
        if backend == 'vllm':
            directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
            root = Path(directory.name)
            (root/'head.json').write_text(json.dumps(dict(slots={'ranges':{'choice':[0,16], 'noul':[16,18]}},
                verbalizer_ids=list(range(18)), bias=[0]*18)))
            (root/'calibration.json').write_text(json.dumps({'per_kind':{'choice':1.,'noul':1.}}))
            config.update(JEV_DECISION_HEAD=str(root/'head.json'), JEV_CALIBRATION=str(root/'calibration.json'))
        client = DecisionClient(config, 1)
        self.addCleanup(client.close)
        client.session.post = Mock()
        return client

    def response(self, value):
        response = Mock(ok=True); response.json.return_value = value
        return response

    def test_typesafe_native_contract(self):
        client = self.client('typesafe')
        client.session.post.return_value = self.response(dict(answers={'action':dict(type='choice',choice='brake',
            probabilities={'go':.2,'brake':.8}, confidence=.6)}, usage={'input_tokens':4,'output_tokens':2}))
        result = client.system_one(state={'x':1},model='jev-latest',questions={
            'action':Choice(instructions='choose',criteria={'go':'move','brake':'hold'})})
        self.assertEqual(result.answers['action'].choice,'brake')
        args = client.session.post.call_args
        self.assertEqual(args.args[0],'http://model.test/v1/systemone')
        self.assertEqual(args.kwargs['json']['questions']['action']['type'],'choice')
        self.assertEqual(result.usage.input_tokens,4)

    def test_vllm_probability_readout_and_rubric_mapping(self):
        client = self.client('vllm')
        def reply(url, *, json, timeout):
            ids = json['allowed_token_ids']
            values = [-2.,-1.,0.] if len(ids)==3 else [-2.,0.]
            return self.response(dict(choices=[{'logprobs':{'top_logprobs':[
                {f'token_id:{token}':value for token,value in zip(ids,values)}]}}],
                usage={'prompt_tokens':10,'completion_tokens':1}))
        client.session.post.side_effect = reply
        result = client.system_one(state={'position':[0,0,0]}, model='jev-decision', questions={
            'maneuver':Choice(instructions='choose',criteria={'go':'move','brake':'hold'}),
            'risk':Score(instructions='risk',criteria=['open','uncertain','obstacle']),
            'uncertain':Noul(instructions='ambiguous?',criteria={'false':'clear','true':'uncertain'})})
        self.assertEqual(result.answers['maneuver'].choice,'brake')
        self.assertAlmostEqual(sum(result.answers['maneuver'].probabilities.values()),1)
        self.assertGreater(result.answers['risk'].score,1)
        self.assertLess(result.answers['risk'].score,2)
        self.assertGreater(result.answers['uncertain'].noul,.8)
        self.assertEqual(result.usage.input_tokens,30)
        for call in client.session.post.call_args_list:
            self.assertEqual(call.args[0],'http://model.test/v1/completions')
            self.assertEqual(call.kwargs['json']['model'],'jev-decision')
            self.assertEqual(call.kwargs['json']['max_tokens'],1)
            self.assertLessEqual(call.kwargs['timeout'],1)
        self.assertIn('[kind] choice',client.session.post.call_args_list[1].kwargs['json']['prompt'])

    def test_head_bias_and_temperature_are_applied(self):
        client = self.client('vllm')
        client.head['bias'][0] = 4.
        client.temperatures['choice'] = 2.
        client.session.post.return_value = self.response({'choices':[{'logprobs':{'top_logprobs':[
            {'token_id:0':-2.,'token_id:1':0.}]}}]})
        result=client.system_one(state={},model='jev-decision',questions={
            'a':Choice(instructions='?',criteria={'a':'a','b':'b'})})
        self.assertEqual(result.answers['a'].choice,'a')
        self.assertAlmostEqual(result.answers['a'].probabilities['a'],1/(1+__import__('math').exp(-1)))

    def test_missing_logprobs_rejected(self):
        client = self.client('vllm')
        client.session.post.return_value = self.response({'choices':[{'logprobs':{'top_logprobs':[{}]}}]})
        with self.assertRaises(KeyError):
            client.system_one(state={},model='jev-decision',questions={'a':Choice(instructions='?',criteria={'a':'a','b':'b'})})

    def test_http_failure_preserves_status_without_body(self):
        client = self.client('typesafe')
        client.session.post.return_value=Mock(ok=False,status_code=429)
        with self.assertRaises(DecisionHTTPError) as caught:
            client.system_one(state={},model='jev',questions={})
        self.assertEqual(caught.exception.status,429)
        self.assertFalse(hasattr(caught.exception,'body'))

    def test_camera_env_is_not_exposed_as_configuration(self):
        with patch.dict('os.environ', {'STAGE5_RGB_URL':'http://wrong','STAGE5_DEPTH_URL':'http://wrong'}):
            config=configuration()
        self.assertEqual(config['STAGE5_RGB_URL'],'http://127.0.0.1:8189/rgb')
        self.assertEqual(config['STAGE5_DEPTH_URL'],'http://127.0.0.1:8189/depth')


if __name__ == '__main__':
    unittest.main()
