"""不连接设备：验证源码装配、模型交付边界和端口配置隔离。"""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_runtime as package


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source, self.build, self.deploy = root/'src', root/'build', root/'deploy'
        self.model = root/'cache/dino'
        self.model.mkdir(parents=True)
        (self.model/'tokenizer').mkdir()
        (self.model/'model.hmm').write_bytes(b'model')
        (self.model/'tokenizer/tokenizer.json').write_text('{}')
        (self.model/'not-for-upload.npz').write_bytes(b'diagnostic')
        (root/'.env').write_text('QWEN_PORT=9000\nDINO_PORT=9003\nAPI_KEY=private\n')
        for name in package.RUNTIME['dino']:
            path = self.source/'dino'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('original')
        for name in package.COMMON['dino']:
            path = self.source/'stage1'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('adapter')
        binary = self.build/'dino/grounding_dino_infer'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b'\x7fELF\x02\x01'+bytes(12)+(183).to_bytes(2,'little'))
        patches = dict(ROOT=root, SOURCE=self.source, BUILD=self.build, DEPLOY=self.deploy,
                       DINO_MODEL=self.model, DINO_SHA256=hashlib.sha256(b'model').hexdigest())
        context = patch.multiple(package, **patches)
        context.start()
        self.addCleanup(context.stop)

    def test_complete_package_and_secret_isolation(self):
        files = package.assemble('dino')
        for source, destination in files:
            source.relative_to(self.deploy)
            self.assertTrue(source.is_file())
            self.assertEqual(destination, '/data/local/workspace/'+str(source.relative_to(self.deploy)))
        self.assertEqual((self.deploy/'stage1/.env').read_text(), 'QWEN_PORT=9000\nDINO_PORT=9003\nAEROVLA_PORT=8084\n')
        model = self.deploy/'models/dino'
        self.assertTrue((model/'model.hmm').is_symlink())
        self.assertFalse((model/'not-for-upload.npz').exists())

    def test_reassembly_uses_source_and_preserves_other_service(self):
        package.assemble('dino')
        other = self.deploy/'stage1/qwen_infer/server.py'
        other.parent.mkdir()
        other.write_text('other service')
        (self.source/'dino/server.py').write_text('updated')
        package.assemble('dino')
        self.assertEqual((self.deploy/'stage1/grounding_dino_infer/server.py').read_text(), 'updated')
        self.assertEqual(other.read_text(), 'other service')

    def test_invalid_native_refused_before_assembly(self):
        (self.build/'dino/grounding_dino_infer').write_bytes(b'linux x86 binary')
        with self.assertRaises(ValueError):
            package.assemble('dino')
        self.assertFalse(self.deploy.exists())

    def test_changed_model_refused(self):
        (self.model/'model.hmm').write_bytes(b'wrong model')
        with self.assertRaises(ValueError):
            package.assemble('dino')
        self.assertFalse(self.deploy.exists())

    def test_port_collision_refused(self):
        (package.ROOT/'.env').write_text('QWEN_PORT=9000\nDINO_PORT=9000\n')
        with self.assertRaises(ValueError):
            package.assemble('dino')
        self.assertFalse(self.deploy.exists())

    def test_existing_model_file_not_overwritten(self):
        model = self.deploy/'models/dino/model.hmm'
        model.parent.mkdir(parents=True)
        model.write_bytes(b'unknown')
        with self.assertRaises(FileExistsError):
            package.assemble('dino')
        self.assertEqual(model.read_bytes(), b'unknown')


class AeroVlaPackageTests(unittest.TestCase):
    def test_missing_graphs_reported_together(self):
        with tempfile.TemporaryDirectory() as td, patch.object(package, 'ROOT', Path(td)):
            with self.assertRaises(FileNotFoundError) as caught:
                package.assemble('aerovla')
            for name in ('vision','prefill','decode'):
                self.assertIn('aerovla_'+name+'.hmm',str(caught.exception))
            self.assertFalse((Path(td)/'deploy').exists())

    def test_runtime_only_package(self):
        import json
        import aerovla_package as aerovla
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'src';deploy=root/'deploy';model=root/'houmo/models/AeroVLA'
            for name in aerovla.GRAPHS:
                path=model/'models'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'graph-fixture')
            for name in aerovla.ASSETS:
                path=model/'assets'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
            (model/'assets/assets.json').write_text(json.dumps({'vision_input_shape':[1,6,224,224],
                'vision_output_shape':[1,256,4096],'vocab_size':32001,'num_bins':99,'max_new_tokens':8}))
            for name in aerovla.RUNTIME:
                path=source/'aerovla'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('runtime')
            for name in ('serve_aerovla.sh','service_config.py'):
                path=source/'stage1'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('adapter')
            for name in ('reference_hf/weights','golden/tensor','samples/request.json'):
                path=model/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('not for upload')
            (root/'.env').write_text('SECRET=do-not-upload\nAEROVLA_PORT=8094\n')
            binding=root/'build/aerovla/tcim_python'
            for name in ('BUILD.json','tcim_lite/__init__.py','tcim_lite/runtime.py','tcim_lite/imageops.py',
                         'tcim_lite/pytcim.cpython-312-aarch64-linux-ohos.so'):
                path=binding/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(b'\x7fELF\x02\x01'+bytes(12)+(183).to_bytes(2,'little') if path.suffix=='.so' else b'fixture')
            with patch.multiple(package,ROOT=root,SOURCE=source,DEPLOY=deploy,BUILD=root/'build'):
                files=package.assemble('aerovla')
            self.assertEqual(len(files),21)
            for path,destination in files:
                self.assertTrue(path.is_file());path.relative_to(deploy)
                self.assertTrue(destination.startswith('/data/local/workspace/'))
                self.assertNotIn('reference_hf',str(path));self.assertNotIn('golden',str(path))
            self.assertNotIn('SECRET',(deploy/'stage1/.env').read_text())
            self.assertIn('AEROVLA_PORT=8094',(deploy/'stage1/.env').read_text())


if __name__ == '__main__':
    unittest.main()
