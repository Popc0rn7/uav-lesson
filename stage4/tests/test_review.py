from types import SimpleNamespace
import unittest
import numpy as np

from stage4.review import tracking


class ReviewTests(unittest.TestCase):
    def test_quaternion_sign_flip_is_not_a_half_turn(self):
        q=np.array([2**-.5,0,0,2**-.5])
        reference={'timestamp':np.array([0,200])}
        measured={'timestamp':np.array([100]),'timestamp_sample':np.array([100])}
        for i in range(4):
            reference[f'q_d[{i}]']=np.array([q[i],-q[i]])
            measured[f'q[{i}]']=np.array([q[i]])
        log=SimpleNamespace(data_list=[
            SimpleNamespace(name='vehicle_attitude_setpoint',multi_id=0,data=reference),
            SimpleNamespace(name='vehicle_attitude',multi_id=0,data=measured)])
        result=tracking(log,[{'sim_s':0},{'sim_s':.0002}])
        self.assertLess(result['attitude_error_deg']['maximum'],.001)


if __name__=='__main__': unittest.main()
