from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import write_json
from webui import read_events


class EvidenceTests(unittest.TestCase):
    def test_invalid_snapshot_preserves_previous_complete_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'state.json'
            write_json(path, {'state': 'running'})
            previous = path.read_text()
            with self.assertRaises(ValueError):
                write_json(path, {'bad': float('nan')})
            self.assertEqual(path.read_text(), previous)

    def test_failed_replace_preserves_snapshot_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'state.json'
            write_json(path, {'state': 'running'})
            previous = path.read_text()
            with patch.object(Path, 'replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    write_json(path, {'state': 'finished'})
            self.assertEqual(path.read_text(), previous)
            self.assertFalse(path.with_name('state.json.tmp').exists())

    def test_partial_appended_event_does_not_hide_previous_events(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'events.jsonl').write_text('{"event":"stage_start"}\n{"event":')
            self.assertEqual(read_events(root), [{'event': 'stage_start'}])
