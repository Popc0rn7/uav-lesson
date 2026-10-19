import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dino_client import configuration
from tactics import Tactician


class RootEnvironmentTests(unittest.TestCase):
    def test_only_root_env_is_loaded_and_shell_has_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stage=root/'stage5';stage.mkdir()
            (root/'.env').write_text('DINO_DETECT_URL=http://root/detect\nQWEN_MODEL="root model"\n')
            (stage/'.env').write_text('DINO_DETECT_URL=http://legacy/detect\nLEGACY_ONLY=ignored\n')
            (root/'.env.example').write_text('EXAMPLE_ONLY=ignored\n')
            with patch('dino_client.HERE',stage),patch.dict(os.environ,{},clear=True):
                config=configuration()
                self.assertEqual(config['DINO_DETECT_URL'],'http://root/detect')
                self.assertEqual(config['QWEN_MODEL'],'root model')
                self.assertNotIn('LEGACY_ONLY',config)
                self.assertNotIn('EXAMPLE_ONLY',config)
                with patch.dict(os.environ,{'DINO_DETECT_URL':'http://shell/detect'}):
                    self.assertEqual(configuration()['DINO_DETECT_URL'],'http://shell/detect')

    def test_tactician_uses_configured_vllm_client_without_api_key(self):
        with patch('decision_client.DecisionClient') as factory:
            actor=Tactician({'JEV_BACKEND':'vllm','JEV_BASE_URL':'http://model.test/v1'})
            try:
                self.assertEqual(actor.model,'jev-decision')
                self.assertEqual(factory.call_args.args[0]['JEV_BACKEND'],'vllm')
                factory.return_value.system_one.assert_not_called()
            finally:
                actor.close()
