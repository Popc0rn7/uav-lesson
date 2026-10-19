"""RoboPi：vision/prefill golden 比较；完整 decode 另经 HTTP 请求验证。"""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import time
import numpy as np

sys.path.insert(0, os.environ.get('TCIM_PYTHON_DIR', '/data/local/houmo/python'))


def compare(got, reference):
    if got.shape != reference.shape:
        raise ValueError(f'输出形状不符：{got.shape} != {reference.shape}')
    a,b = got.astype(np.float64).ravel(),reference.astype(np.float64).ravel()
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('输出或 golden 含 NaN/Inf')
    norms = np.linalg.norm(a)*np.linalg.norm(b)
    if norms == 0:
        raise ValueError('零向量不能计算有效 cosine')
    return float(np.dot(a,b)/norms)


def feed_from_golden(module, directory, prefix):
    names = [module.get_input_name(i) for i in range(module.get_num_inputs())]
    fed = set()
    for file in sorted(directory.glob('*.npy')):
        if not file.name.startswith(prefix) or not file.name.endswith('_input.npy'):
            continue
        key = file.name[len(prefix):-len('_input.npy')].lower()
        exact = [n for n in names if n.lower()==key]
        matches = exact or [n for n in names if key in n.lower() or n.lower() in key]
        if len(matches)!=1 or matches[0] in fed:
            raise ValueError(f'golden 输入未唯一匹配：{file.name} -> {matches}')
        name = matches[0]
        info = module.get_input_info(name)
        data = np.load(file,allow_pickle=False)
        if tuple(data.shape)!=tuple(info.shape):
            raise ValueError(f'{name} 输入形状不符：{data.shape} != {tuple(info.shape)}')
        module.set_input(name,data.astype(info.dtype))
        fed.add(name)
    if set(names)!=fed:
        raise ValueError('golden 缺少输入：'+', '.join(sorted(set(names)-fed)))
    return len(fed)


def run_graph(tcim, root, stage):
    started = time.monotonic()
    directory = root/'golden'/('vision' if stage=='vision' else 'llm/prefill')
    module = tcim.runtime.load(str(root/'models'/f'aerovla_{stage}.hmm'))
    inputs = feed_from_golden(module,directory,f'hmquant_{stage}_')
    module.run(); module.sync()
    output = module.get_output_name(0) if stage=='vision' else next(
        module.get_output_name(i) for i in range(module.get_num_outputs()) if 'logits' in module.get_output_name(i))
    got = module.get_output(output).numpy()
    suffix = 'image_embedding' if stage=='vision' else 'logits'
    reference = np.load(directory/f'hmquant_{stage}_{suffix}_output.npy',allow_pickle=False)
    cosine = compare(got,reference)
    result = {'stage':stage,'inputs':inputs,'shape':list(got.shape),'cosine':cosine,
              'passed':cosine>=0.98,'elapsed_s':time.monotonic()-started}
    print(json.dumps(result),flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-root', type=Path, default=Path(os.environ.get(
        'AEROVLA_MODEL_ROOT','/data/local/workspace/models/AeroVLA')))
    parser.add_argument('--report',type=Path)
    args = parser.parse_args()
    report = {'passed':False,'stages':[],'scope':'vision/prefill golden only; decode requires HTTP test'}
    try:
        import tcim_lite
        for stage in ('vision','prefill'):
            report['stages'].append(run_graph(tcim_lite,args.model_root,stage))
            gc.collect()
        report['passed'] = all(row['passed'] for row in report['stages'])
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        if args.report:
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(json.dumps(report,indent=2)+'\n')
        print('SMOKE_'+('PASS' if report['passed'] else 'FAIL'),flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
