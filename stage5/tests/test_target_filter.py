from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from target_filter import filter_candidates


class FilterTests(unittest.TestCase):
    def test_jev_cache_changes_when_tracking_disappears(self):
        from tactics import Tactician
        state = dict(mission='follow', observed=dict(target_candidates=[],
            target_response_source='http', local_space={'motion_candidates':{}},
            tracking={'confirmed':True}))
        before = Tactician.fingerprint(state)
        state['observed']['tracking'] = None
        self.assertNotEqual(before, Tactician.fingerprint(state))


    def test_rejects_weak_unrelated_and_duplicates_but_preserves_audit(self):
        values = [dict(label='a red car', score=.8, box_xyxy=[0,0,20,20]),
                  dict(label='a red box', score=.7, box_xyxy=[1,1,20,20]),
                  dict(label='a red car', score=.2, box_xyxy=[30,0,40,10]),
                  dict(label='a building', score=.9, box_xyxy=[50,0,60,10])]
        selected, audit = filter_candidates(values)
        self.assertEqual(len(selected), 1)
        self.assertEqual([x['rejection_reason'] for x in audit],
                         [None, 'duplicate_box', 'low_confidence', 'unsupported_semantics'])
        self.assertNotIn('accepted', values[0])

    def test_malformed_and_nonfinite_values_never_authorize_target(self):
        selected, audit = filter_candidates([
            dict(label='car', score=float('nan'), box_xyxy=[0,0,10,10]),
            dict(label='car', score=.9, box_xyxy=[10,0,0,10])])
        self.assertFalse(selected)
        self.assertTrue(all(not x['accepted'] for x in audit))
