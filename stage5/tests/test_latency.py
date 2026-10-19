import json
from pathlib import Path
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from latency import record, summarize


class LatencyTests(unittest.TestCase):
    def test_concurrent_records_and_summary_units(self):
        with tempfile.TemporaryDirectory() as directory:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda i: record(directory, 'dino_request', i/1000), range(1, 101)))
            result = summarize(directory)
            self.assertFalse(result['historical_reconstruction'])
            self.assertEqual(result['unit'], 'ms')
            self.assertEqual(result['components']['dino_request'], dict(count=100, min=1., median=50.5, p95=95., max=100.))

    def test_old_run_only_reports_available_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'qwen-1-metrics.json').write_text(json.dumps({'http_elapsed_s': 2.452}))
            (path/'bootstrap.jsonl').write_text('\n'.join(json.dumps(row) for row in [
                {'event': 'takeoff_dispatched', 'wall_s': 2.6}, {'event': 'takeoff_complete', 'wall_s': 20.7}]))
            result = summarize(path)
            self.assertTrue(result['historical_reconstruction'])
            self.assertEqual(result['components']['qwen_http']['median'], 2452.)
            self.assertEqual(result['components']['takeoff_to_hover']['median'], 18100.)
            self.assertNotIn('dino_request', result['components'])
