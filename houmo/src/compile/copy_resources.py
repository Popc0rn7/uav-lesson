#!/usr/bin/env python3
"""PC：复制并逐文件校验模型与公共依赖；中断后可重复执行继续。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

ROOT = Path(__file__).resolve().parents[3]
SKIP = {'.git', '__pycache__', 'AeroVLA', 'build', 'build-ohos'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy_tree(source, destination):
    record = {}
    last = time.monotonic()
    print(f'COPY_VERIFY {destination.relative_to(ROOT)}', flush=True)
    for base, directories, names in os.walk(source):
        directories[:] = sorted(d for d in directories if d not in SKIP and not d.startswith('build-'))
        for name in sorted(names):
            src = Path(base) / name
            if not src.is_file():
                continue
            relative = src.relative_to(source)
            dest = destination / relative
            if dest.is_symlink():
                raise ValueError(f'目标必须是独立文件，不能是软链接：{dest}')
            checksum = digest(src)
            if not (dest.is_file() and dest.stat().st_size == src.stat().st_size and digest(dest) == checksum):
                dest.parent.mkdir(parents=True, exist_ok=True)
                partial = dest.with_name(dest.name + '.copy-partial')
                shutil.copy2(src, partial)
                if digest(partial) != checksum:
                    raise RuntimeError(f'复制摘要不一致：{relative}')
                partial.replace(dest)
            record[str(relative)] = {'bytes': dest.stat().st_size, 'sha256': checksum}
            if time.monotonic() - last > 10:
                print(f'VERIFIED {len(record)} files, {sum(v["bytes"] for v in record.values())} bytes', flush=True)
                last = time.monotonic()
    return {'source': str(source), 'destination': str(destination.relative_to(ROOT)), 'files': record}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qwen-source', type=Path, required=True)
    parser.add_argument('--dino-source', type=Path, required=True)
    parser.add_argument('--modelzoo-source', type=Path, required=True)
    args = parser.parse_args()
    records = []
    for source, dest in ((args.qwen_source, ROOT/'houmo/models/Qwen3.6-35B-A3B'),
                         (args.dino_source, ROOT/'houmo/models/GroundingDINO-tiny-360p')):
        records.append(copy_tree(source.resolve(), dest))
    modelzoo = args.modelzoo_source.resolve()
    for relative in ('cmake', 'utils/cpp/houmo_engine', 'models/llm/qwen3.5/cpp', '3rdparty'):
        records.append(copy_tree(modelzoo/relative, ROOT/'houmo/deps/modelzoo'/relative))
    shutil.copy2(modelzoo/'LICENSE', ROOT/'houmo/deps/modelzoo/LICENSE')
    records.append(copy_tree(modelzoo/'qwen_ohos_infer/deps/houmo', ROOT/'houmo/deps/tcim'))
    result = {'copied_on': time.strftime('%Y-%m-%d'), 'verified': True, 'resources': records}
    path = ROOT/'houmo/models/RESOURCES.json'
    path.write_text(json.dumps(result, indent=2)+'\n')
    print('ALL_VERIFIED', path, flush=True)


if __name__ == '__main__':
    main()
