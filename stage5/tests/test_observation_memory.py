from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stage5.airsim.observation_memory import summarize_observations


def frame(at, seen=False, generation=1):
    return dict(received=at, generation=generation, detections=[dict(
        accepted=True, score=.7, label='yellow pickup', box_xyxy=[0, 0, 10, 10])] if seen else [])


class MemoryTests(unittest.TestCase):
    def test_fifteen_empty_frames_are_counted_but_only_candidate_is_sent(self):
        frames = [frame(6.1+i*.2, seen=i == 14) for i in range(16)]
        result = summarize_observations(frames, 1, 10)
        self.assertEqual(result['summary'], 'Recent 4s: 15 out of 16 frames had no accepted detection.')
        self.assertEqual(len(result['candidate_observations']), 1)
        self.assertEqual(result['candidate_observations'][0]['detections'], frames[14]['detections'])
        self.assertAlmostEqual(result['candidate_observations'][0]['age_s'], 1.1)
        self.assertNotIn('temporal_status', str(result))

    def test_rejected_detection_does_not_become_candidate_memory(self):
        rejected = frame(9, True); rejected['detections'][0]['accepted'] = False
        result = summarize_observations([rejected, frame(9.5)], 1, 10)
        self.assertEqual(result['no_detection_frames'], 2)
        self.assertEqual(result['candidate_observations'], [])

    def test_expired_future_and_other_stage_frames_are_excluded(self):
        result = summarize_observations([frame(1, True), frame(11, True), frame(9, True, generation=2), frame(9.5)], 1, 10)
        self.assertEqual(result['observed_frames'], 1)
        self.assertEqual(result['candidate_observations'], [])

    def test_raw_candidate_fields_are_preserved_without_mutating_input(self):
        original = frame(9, True)
        original['semantic_targets'] = [{'status': 'mixed_depth', 'position_m': None}]
        result = summarize_observations([original], 1, 10)
        record = result['candidate_observations'][0]
        self.assertEqual(record['semantic_targets'], original['semantic_targets'])
        record['detections'][0]['score'] = 0
        self.assertEqual(original['detections'][0]['score'], .7)

    def test_no_frames_does_not_invent_missing_observations(self):
        result = summarize_observations([], 1, 10)
        self.assertEqual(result['summary'], 'Recent 4s: 0 out of 0 frames had no accepted detection.')
