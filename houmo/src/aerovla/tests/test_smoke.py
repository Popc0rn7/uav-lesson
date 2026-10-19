"""防止 golden smoke 忽略缺失输入或把非有限输出当成通过。"""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import smoke


class SmokeTests(unittest.TestCase):
    def test_compare_rejects_shape_and_nan(self):
        self.assertAlmostEqual(smoke.compare(np.array([1.,2.]),np.array([1.,2.])),1.)
        for a,b in ((np.zeros((1,2)),np.zeros((2,))),
                    (np.array([np.nan]),np.array([1.])),(np.zeros(2),np.zeros(2))):
            with self.assertRaises(ValueError):smoke.compare(a,b)

    def test_golden_requires_every_input_and_unique_match(self):
        values=[]
        module=SimpleNamespace(get_num_inputs=lambda:2,get_input_name=lambda i:('input_1','current_length')[i],
            get_input_info=lambda name:SimpleNamespace(shape=(1,),dtype=np.float32),
            set_input=lambda name,array:values.append(name))
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            np.save(path/'hmquant_prefill_input_1_input.npy',np.array([1.]))
            with self.assertRaises(ValueError):smoke.feed_from_golden(module,path,'hmquant_prefill_')
            np.save(path/'hmquant_prefill_current_length_input.npy',np.array([1.]))
            self.assertEqual(smoke.feed_from_golden(module,path,'hmquant_prefill_'),2)


if __name__=='__main__':unittest.main()
