#!/usr/bin/env python3
"""PC：复制 AeroVLA 模型资源及参考 HF 权重，不执行转换、推理或仿真。"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'houmo/src/compile'))
from copy_resources import copy_tree
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='用户提供的 aerovla_infer 目录')
    parser.add_argument('--hmm-dir', type=Path, help='含 aerovla_vision/prefill/decode.hmm 的目录')
    parser.add_argument('--hf-source', type=Path, help='可选：合并 HF 权重，只作离线参考，不上传')
    args = parser.parse_args()
    source = args.source.resolve()
    target = ROOT/'houmo/models/AeroVLA'
    record_path = target/'RESOURCES.json'
    previous = json.loads(record_path.read_text()) if record_path.is_file() else {}
    records = list(previous.get('resources', []))
    def remember(record):
        records[:] = [r for r in records if r.get('destination') != record['destination']]
        records.append(record)
    for directory in ('assets','golden'):
        if not (source/directory).is_dir():
            raise FileNotFoundError(source/directory)
        remember(copy_tree(source/directory,target/directory))
    graphs = args.hmm_dir or source/'models'
    missing = [name for name in ('aerovla_vision.hmm','aerovla_prefill.hmm','aerovla_decode.hmm')
               if not (graphs/name).is_file()]
    if not missing:
        # 独立导入指定三图，不把原转换工作区混入运行模型目录。
        import shutil
        from copy_resources import digest
        for name in ('aerovla_vision.hmm','aerovla_prefill.hmm','aerovla_decode.hmm'):
            dest=target/'models'/name;dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.is_symlink():
                raise ValueError(f'HMM 必须为真实文件：{dest}')
            expected = digest(graphs/name)
            print(f'IMPORT {name}: {(graphs/name).stat().st_size} bytes', flush=True)
            if not dest.is_file() or digest(dest)!=expected:
                partial=dest.with_name(dest.name+'.copy-partial');shutil.copy2(graphs/name,partial)
                if digest(partial)!=expected:raise RuntimeError('HMM 复制摘要不一致')
                partial.replace(dest)
        remember({'source':str(graphs.resolve()),'destination':str((target/'models').relative_to(ROOT)),
                        'files':{name:{'sha256':digest(target/'models'/name),'bytes':(target/'models'/name).stat().st_size}
                                 for name in ('aerovla_vision.hmm','aerovla_prefill.hmm','aerovla_decode.hmm')}})
    if args.hf_source:
        remember(copy_tree(args.hf_source.resolve(), target/'reference_hf'))
    (target/'RESOURCES.json').write_text(json.dumps({'resources':records,'missing_hmm':missing},indent=2)+'\n')
    if missing:
        print('已保存现有资源；缺少 HMM：'+', '.join(missing),flush=True)
        return
    print('AeroVLA 资源复制校验完成；请运行 deploy_aerovla.py --check-local')


if __name__ == '__main__':
    main()
