import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mission_registry as registry


class RegistryTests(unittest.TestCase):
    def test_follows_new_custom_directory_and_keeps_workspace_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);pointer=root/'latest.json'
            for name in ('custom-one','custom-two'):
                run=root/name;run.mkdir();(run/'task.json').write_text('{"task":"test"}')
                with patch.object(registry,'REGISTRY',pointer):registry.register(run)
                self.assertEqual(registry.latest(pointer,root),run)
            value=json.loads(pointer.read_text());value['workspace']='different-workspace'
            pointer.write_text(json.dumps(value))
            self.assertIsNone(registry.latest(pointer,root))

    def test_existing_legacy_default_run_is_discovered_without_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);run=root/'stage5-mission-existing';run.mkdir()
            (run/'task.json').write_text('{"task":"running"}')
            self.assertEqual(registry.latest(root/'missing',root),run)
            (run/'task.json').write_text('{partial')
            self.assertIsNone(registry.latest(root/'missing',root))
