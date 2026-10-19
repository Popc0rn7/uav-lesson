"""Run exported NPZ cases through the OHOS native worker, checking golden outputs."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from tensor_io import schema


def main():
    here = Path(__file__).resolve().parent
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--bundle', type=Path, default=here/'bundle')
    cli.add_argument('--binary', type=Path, default=here/'grounding_dino_infer')
    cli.add_argument('--device', type=int, default=0)
    cli.add_argument('--repeat', type=int, default=3)
    cli.add_argument('--outputs-dir', type=Path, help='Save raw NPU outputs for diagnosis')
    cli.add_argument('--report', type=Path, default=here/'validation.json')
    args = cli.parse_args()
    if args.repeat < 1 or args.device < 0:
        cli.error('repeat >= 1 and device >= 0 required')
    bundle = args.bundle.resolve()
    manifest = json.loads((bundle/'bundle.json').read_text())
    def checked(name):
        path = (bundle/name).resolve()
        if not path.is_relative_to(bundle):
            raise ValueError(f'Unsafe bundle path: {name}')
        return path
    for name, expected in manifest['files'].items():
        digest = hashlib.sha256()
        with checked(name).open('rb') as stream:
            for block in iter(lambda: stream.read(8*1024*1024), b''):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(f'Bundle checksum mismatch: {name}')
    if not manifest['cases']:
        raise ValueError('No validation cases')
    rows = []
    with tempfile.TemporaryDirectory(prefix='dino-validation-') as temp:
        directory = Path(temp)
        command = [str(args.binary.resolve()), 'inspect', str(checked(manifest['model'])), temp, str(args.device)]
        subprocess.run(command, check=True, timeout=300, env={**os.environ, 'LD_PRELOAD': ''})
        inputs, outputs = schema(directory/'inputs.tsv'), schema(directory/'outputs.tsv')
        if {n for n, _, _ in inputs} != set(manifest['input_names']) or {n for n, _, _ in outputs} != set(manifest['output_names']):
            raise ValueError('Native model interface differs from manifest')
        for case in manifest['cases']:
            with np.load(checked(case['inputs']), allow_pickle=False) as data:
                for i, (name, dtype, shape) in enumerate(inputs):
                    if data[name].shape != shape:
                        raise ValueError(f'Shape mismatch: {name}')
                    np.asarray(data[name], dtype=dtype).tofile(directory/f'input_{i}.bin')
                floating = {n: data['ref__'+n].copy() for n, _, _ in outputs}
            command[1] = 'run'
            subprocess.run(command+[str(args.repeat)], check=True, timeout=600, env={**os.environ, 'LD_PRELOAD': ''})
            row = {'case': case['inputs'], 'outputs': {}}
            saved = {}
            with np.load(checked(case['golden']), allow_pickle=False) as golden:
                for i, (name, dtype, shape) in enumerate(outputs):
                    actual = np.fromfile(directory/f'output_{i}.bin', dtype=dtype).reshape(shape).astype(np.float64)
                    saved[name] = actual
                    ref = golden[name].astype(np.float64)
                    # Allow identical signed infinities for masked text logits, reject NaNs.
                    finite = np.isfinite(actual) & np.isfinite(ref)
                    delta = np.abs(actual[finite]-ref[finite])
                    passed = not np.isnan(actual).any() and bool(np.allclose(actual, ref, atol=1e-4, rtol=1e-3))
                    ff = np.isfinite(actual) & np.isfinite(floating[name])
                    row['outputs'][name] = {'passed': passed,
                        'golden_max_abs': float(delta.max()) if delta.size else 0.,
                        'float_max_abs': float(np.max(np.abs(actual[ff]-floating[name][ff]))) if ff.any() else None}
            if args.outputs_dir:
                args.outputs_dir.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(args.outputs_dir/case['inputs'], **saved)
            rows.append(row)
    report = {'passed': all(o['passed'] for r in rows for o in r['outputs'].values()),
              'cases': rows, 'repeat': args.repeat, 'atol': 1e-4, 'rtol': 1e-3,
              'note': 'Golden consistency only; detection quality needs original images and prompts.'}
    args.report.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
