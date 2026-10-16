"""失流现场按板端同机时间关联，区分收到旧云与未收到云。"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

DIRECTORY = Path(__file__).resolve().parents[2]/'board'
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location('cloud_analysis', DIRECTORY/'analyse_cloud.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class CloudAnalysisTests(unittest.TestCase):
    def test_rejected_arrivals_and_fault_window_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            profile = run/'board-logs/profile'
            profile.mkdir(parents=True)
            def write(name, rows):
                (profile/name).write_text(''.join(json.dumps(r)+'\n' for r in rows))
            write('lidar.jsonl', [
                dict(kind='raw_received', mono_ns=10**9, stamp=1, sim_age_s=.02),
                dict(kind='queue_snapshot', mono_ns=2*10**9, pending=1, oldest_wall_s=.1),
                dict(kind='cloud_dropped', mono_ns=3*10**9, reason='no_bracket', stamp=1),
                dict(kind='raw_received', mono_ns=3_500_000_000, stamp=3, sim_age_s=.02)])
            write('control.jsonl', [
                dict(kind='cloud_received', mono_ns=2*10**9, accepted=True, sim_age_s=.1),
                dict(kind='cloud_received', mono_ns=2_400_000_000, accepted=False, sim_age_s=.6),
                dict(kind='land_requested', mono_ns=2_600_000_000, reason='lidar cloud timeout')])
            (run/'profile').mkdir()
            (run/'profile/raw.jsonl').write_text(''.join(json.dumps(dict(kind='raw_publish', stamp=stamp, mono_ns=ns))+'\n'
                                                       for stamp, ns in [(1, 80*10**9), (2, 80_200_000_000), (3, 82_500_000_000)]))
            result = analysis.analyse(run)
            self.assertEqual(result['control']['received'], 2)
            self.assertEqual(result['control']['accepted'], 1)
            fault = result['faults'][0]
            self.assertAlmostEqual(fault['last_fresh_gap_s'], .6)
            self.assertEqual(fault['drops'], [])  # 后来的丢弃不能解释之前的超时。
            self.assertEqual(fault['receive_gap']['pc_publish_events_inside_gap'], 1)
            self.assertAlmostEqual(fault['receive_gap']['board_gap_s'], 2.5)
            self.assertEqual(result['total']['drops'], {'no_bracket': 1})

    def test_missing_snapshots_are_not_silently_treated_as_empty_queues(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            profile = run/'board-logs/profile'
            profile.mkdir(parents=True)
            (profile/'lidar.jsonl').write_text(json.dumps(dict(kind='raw_received', mono_ns=1))+'\n')
            (profile/'control.jsonl').write_text('')
            with self.assertRaises(ValueError):
                analysis.analyse(run)


if __name__ == '__main__':
    unittest.main()
