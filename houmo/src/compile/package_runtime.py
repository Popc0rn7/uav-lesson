#!/usr/bin/env python3
"""PC：从受维护源码、目标 ELF 和模型缓存装配完整上传目录。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
HOUMO = ROOT / 'houmo'
SOURCE = HOUMO / 'src'
BUILD = HOUMO / 'build'
DEPLOY = HOUMO / 'deploy'
sys.path.insert(0, str(SOURCE / 'stage1'))
from service_config import read_ports

QWEN_MODEL = HOUMO / 'models/Qwen3.6-35B-A3B/qwen3.6-35b-a3b_w4a8_256_256k_b1_1chip_2cores'
DINO_MODEL = HOUMO / 'models/GroundingDINO-tiny-360p'
DINO_SHA256 = '37170971fdd04800cc4b4dadda6d408e8eecb00e60542fae7b35ba1c59a7e4ea'
RUNTIME = {
    'qwen': ('run.py', 'run.sh', 'server.py', 'models.json', 'requirements-server.txt', 'vqa_client.py', 'LICENSE'),
    'dino': ('run.sh', 'server.py', 'pipeline.py', 'bert_tokenizer.py', 'image_resize.py', 'tensor_io.py', 'client.py', 'requirements-board.txt', 'LICENSE'),
}
NATIVE = {'qwen': ('qwen_ohos_infer', 'lib/libhoumo_infer.so', 'lib/libtokenizer_lib.so'),
          'dino': ('grounding_dino_infer',)}
DIRECTORY = {'qwen': 'qwen_infer', 'dino': 'grounding_dino_infer'}
COMMON = {'qwen': ('serve.sh', 'ros_env.sh', 'chat_node.py', 'backend.py', 'service_config.py'),
          'dino': ('serve_dino.sh', 'service_config.py')}


def require_file(path):
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f'缺少文件或为空：{path}')
    with path.open('rb') as stream:
        if stream.read(80).startswith(b'version https://git-lfs.github.com/spec/v1'):
            raise ValueError(f'文件仍为 LFS 指针：{path}')
    return path


def check_elf(path):
    with require_file(path).open('rb') as stream:
        header = stream.read(20)
    if header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != 183:
        raise ValueError(f'需要 AArch64 ELF64 小端产物：{path}')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def assemble(service):
    if service == 'aerovla':
        import aerovla_package
        return aerovla_package.assemble(sys.modules[__name__])
    ports = read_ports(ROOT / '.env')
    model = QWEN_MODEL if service == 'qwen' else DINO_MODEL
    model_files = ('hmquant/quant_embedding.bin',) if service == 'qwen' else ('model.hmm', 'tokenizer/tokenizer.json')
    for name in model_files:
        require_file(model / name)
    if service == 'qwen' and not any(model.glob('*_visual_m*.hmm')):
        raise FileNotFoundError('Qwen 缺少 VQA *_visual_m*.hmm')
    if service == 'dino' and digest(model / 'model.hmm') != DINO_SHA256:
        raise ValueError('DINO 模型不匹配已记录的 360p 基线')
    app = Path('stage1') / DIRECTORY[service]
    inputs = [(SOURCE / service / name, app / name) for name in RUNTIME[service]]
    inputs += [(BUILD / service / name, app / name) for name in NATIVE[service]]
    inputs += [(SOURCE / 'stage1' / name, Path('stage1') / name) for name in COMMON[service]]
    for path, _ in inputs:
        require_file(path)
    for name in NATIVE[service]:
        check_elf(BUILD / service / name)
    model_dest = DEPLOY / 'models' / model.name
    links = [(model_dest, model)] if service == 'qwen' else [
        (model_dest / name, model / name) for name in model_files]
    for dest, target in links:
        if dest.exists() or dest.is_symlink():
            if not dest.is_symlink() or dest.resolve() != target.resolve():
                raise FileExistsError(f'已有不同模型文件，拒绝替换：{dest}')
    # 只更新生成目录内明确列出的文件，不复制源码树或根 .env。
    files = []
    for source, relative in inputs:
        dest = DEPLOY / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        files.append(dest)
    env = DEPLOY / 'stage1/.env'
    env.write_text(''.join(f'{key}={value}\n' for key, value in ports.items()))
    files.append(env)
    record = DEPLOY / app / 'SOURCE.json'
    record.write_text(json.dumps({'service': service, 'source': f'houmo/src/{service}',
        'native': f'houmo/build/{service}', 'sha256': {
            str(path.relative_to(DEPLOY)): digest(path) for path in files}}, indent=2) + '\n')
    files.append(record)
    for dest, target in links:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.is_symlink():
            dest.symlink_to(target.resolve(), target_is_directory=target.is_dir())
    if service == 'qwen':
        files.extend(require_file(path) for path in sorted(model_dest.rglob('*')) if path.is_file())
    else:
        files.extend(model_dest / name for name in model_files)
    return [(path, '/data/local/workspace/' + str(path.relative_to(DEPLOY))) for path in files]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', choices=('qwen', 'dino', 'aerovla', 'all'), default='all')
    args = parser.parse_args()
    for service in ('qwen', 'dino', 'aerovla') if args.service == 'all' else (args.service,):
        print(f'{service}: {len(assemble(service))} 个上传文件，已装配到 {DEPLOY}')


if __name__ == '__main__':
    main()
