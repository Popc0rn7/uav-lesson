#!/usr/bin/env python3
"""PC：复用已经验证的 OHOS dist，仅导入目标 ELF；Python 始终来自本仓库源码。"""
import argparse
import json
from pathlib import Path
import shutil
from package_runtime import BUILD, NATIVE, check_elf, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', required=True, choices=('qwen', 'dino'))
    parser.add_argument('--dist', type=Path, required=True)
    args = parser.parse_args()
    for name in NATIVE[args.service]:
        check_elf(args.dist / name)
    for name in NATIVE[args.service]:
        source = args.dist / name
        dest = BUILD / args.service / name
        if dest.exists() and digest(dest) != digest(source):
            raise FileExistsError(f'已有不同产物，请先备份确认：{dest}')
    for name in NATIVE[args.service]:
        dest = BUILD / args.service / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.dist / name, dest)
    (BUILD / args.service / 'NATIVE_SOURCE.json').write_text(json.dumps({
        'dist': str(args.dist.resolve()), 'sha256': {name: digest(args.dist / name)
        for name in NATIVE[args.service]}}, indent=2) + '\n')
    print(f'已导入 {args.service} 目标产物；请运行 package_runtime.py 装配上传包')


if __name__ == '__main__':
    main()
