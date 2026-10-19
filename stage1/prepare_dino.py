#!/usr/bin/env python3
"""PC：从上游导入 DINO 已验证目标 ELF、复制模型并装配上传包。"""
import argparse
from pathlib import Path
import subprocess
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'houmo/src/compile'))
from package_runtime import DINO_MODEL, assemble


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='modelzoo 的 grounding_dino_ohos_infer 目录')
    args = parser.parse_args()
    source = args.source.resolve()
    model = source / '360p'
    for name in ('model.hmm', 'tokenizer/tokenizer.json'):
        if not (model / name).is_file():
            raise FileNotFoundError(model / name)
    if not DINO_MODEL.exists():
        DINO_MODEL.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(model, DINO_MODEL, symlinks=False,
                        ignore=shutil.ignore_patterns('__pycache__', '.git'))
    elif DINO_MODEL.is_symlink():
        raise ValueError('模型缓存必须是本仓库内的真实目录')
    subprocess.run([sys.executable, str(ROOT / 'houmo/src/compile/import_native.py'),
                    '--service', 'dino', '--dist', str(source / 'dist')], check=True)
    print(f'已装配 {len(assemble("dino"))} 个上传文件；Python 使用 houmo/src/dino')


if __name__ == '__main__':
    main()
