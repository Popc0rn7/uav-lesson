"""统一闭环延迟拟合必须恢复已知位移，不跨失流或为静止参考捏造延迟。"""
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'airsim/diagnostics'))
from response_latency import fit


class LatencyTests(unittest.TestCase):
    def signal(self,t):return np.column_stack([np.sin(t*.9),np.sin(t*1.7),np.cos(t*.6)])

    def test_known_delay_on_fixed_common_support(self):
        t=np.arange(10,40,.01);result=fit(t,self.signal(t-.12),t,self.signal(t),[[10,40]])
        self.assertTrue(result['valid'])
        self.assertAlmostEqual(result['best_shift_sim_s'],.12)
        self.assertLess(result['best_shift_rms'],1e-5)
        self.assertGreater(result['relative_rms_improvement'],.99)

    def test_stationary_is_not_zero_delay_evidence(self):
        t=np.arange(10,40,.01);r=fit(t,np.zeros((len(t),3)),t,np.zeros((len(t),3)),[[10,40]])
        self.assertFalse(r['valid']);self.assertIn('excitation',r['reason'])

    def test_short_tracking_window_has_no_fabricated_fit(self):
        t=np.arange(10,40,.01)
        self.assertFalse(fit(t,self.signal(t),t,self.signal(t),[[10,10.5]])['valid'])

    def test_gap_reduces_common_support_without_fake_delay(self):
        t=np.arange(10,40,.01);keep=(t<20)|(t>23)
        full=fit(t,self.signal(t-.12),t,self.signal(t),[[10,40]])
        gapped=fit(t[keep],self.signal(t[keep]-.12),t,self.signal(t),[[10,40]])
        self.assertLess(gapped['samples'],full['samples'])
        self.assertAlmostEqual(gapped['best_shift_sim_s'],.12)


if __name__=='__main__':unittest.main()
