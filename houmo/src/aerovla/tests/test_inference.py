"""无需 TCIM/NPU/socket：校验模型输入、串行调用和 EOS 行为。"""
import base64
import io
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import service
from runner import AeroVLARunner


def request():
    return {'input_ids':[1,42],'pixel_values_shape':[1,6,224,224],
            'pixel_values_b64':base64.b64encode(np.zeros((1,6,224,224),dtype='<f4').tobytes()).decode()}


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.cfg={'vocab_size':32001,'max_new_tokens':8}

    def test_input_contract(self):
        value=request();ids,pixels=service.decode_request(value,self.cfg)
        self.assertEqual(ids,[1,42]);self.assertEqual(pixels.shape,(1,6,224,224))
        for key,bad in [('input_ids',[True]),('input_ids',[32001]),('input_ids',[]),
                        ('input_ids',[1]*800),('pixel_values_b64','!'),('pixel_values_shape',[1,3,224,224])]:
            altered={**value,key:bad}
            with self.assertRaises((ValueError,TypeError)):
                service.decode_request(altered,self.cfg)
        nan=np.full((1,6,224,224),np.nan,dtype='<f4')
        with self.assertRaises(ValueError):
            service.decode_request({**value,'pixel_values_b64':base64.b64encode(nan.tobytes()).decode()},self.cfg)

    def test_busy_rejected_and_health_can_respond(self):
        entered,release=threading.Event(),threading.Event()
        def generate(*args):
            entered.set();self.assertTrue(release.wait(3));return [7]
        runner=SimpleNamespace(cfg=self.cfg,generate=generate,
            parse_action=lambda ids:({'fwd':1,'down':0,'yaw':0},False,'sample'))
        handler=service.make_handler(runner)
        def make(path,body=None):
            value=object.__new__(handler);value.path=path;value.results=[]
            raw=json.dumps(body).encode() if body is not None else b''
            value.headers={'Content-Length':str(len(raw))};value.rfile=io.BytesIO(raw)
            value.connection=SimpleNamespace(settimeout=lambda seconds:None)
            value._send=lambda status,result:value.results.append((status,result))
            return value
        first=make('/infer',request());worker=threading.Thread(target=first.do_POST);worker.start()
        try:
            self.assertTrue(entered.wait(3))
            health=make('/health');health.do_GET();self.assertTrue(health.results[0][1]['busy'])
            competing=make('/infer',request());competing.do_POST();self.assertEqual(competing.results[0][0],503)
        finally:
            release.set();worker.join(4)
        self.assertEqual(first.results[0][0],200)

    def test_prefill_eos_does_not_run_decode(self):
        runner=AeroVLARunner.__new__(AeroVLARunner)
        runner.cfg={'vocab_size':4,'max_new_tokens':8,'eos_token_id':2}
        runner.emb=np.zeros((4,3),dtype=np.float16);runner.CHUNK=1
        runner._vision_embed=lambda pixels:None
        runner.build_inputs_embeds=lambda ids,img:np.zeros((1,3),dtype=np.float16)
        runner.bind_caches=lambda:None
        runner.prefill=SimpleNamespace(run=lambda:None,sync=lambda:None)
        runner.decode=SimpleNamespace(run=lambda:self.fail('EOS 后不应 decode'))
        with patch('runner._set'),patch('runner._logits',return_value=np.array([[[0,0,5,0]]])):
            self.assertEqual(runner.generate([1],None),[])


if __name__=='__main__':unittest.main()
