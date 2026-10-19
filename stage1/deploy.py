#!/usr/bin/env python3
"""PC：统一装配、校验并上传 Qwen / DINO / AeroVLA 模型运行包。"""
import argparse
import hashlib
from pathlib import Path
import shlex
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
TARGET = ""  # main() 从显式 --target 设置；不保存设备标识。
REMOTE_STAGE = "/data/local/workspace/stage1"

def collect_files(service="qwen", with_smoke=False):
    import sys
    sys.path.insert(0, str(ROOT / 'houmo/src/compile'))
    from package_runtime import assemble
    services = ('qwen', 'dino', 'aerovla') if service == 'all' else (service,)
    files = []
    for selected in services:
        files.extend(assemble(selected))
    if with_smoke:
        if 'aerovla' not in services:
            raise ValueError('--with-smoke 当前用于 AeroVLA 或 all')
        from aerovla_package import assemble_smoke
        import package_runtime
        files.extend(assemble_smoke(package_runtime))
    # 多模型共享 .env/service_config.py；重复目的路径必须对应同一内容。
    unique = {}
    for source, destination in files:
        if destination in unique and unique[destination] != source:
            if unique[destination].read_bytes() != source.read_bytes():
                raise ValueError('共享交付文件冲突：' + destination)
        unique[destination] = source
    return [(source, destination) for destination, source in unique.items()]


def hdc(*args, timeout=60):
    if not TARGET.strip():
        raise RuntimeError('请用 --target 显式选择本次目标设备')
    result = subprocess.run(["hdc", "-t", TARGET, *args],
                            check=True, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    print(result.stdout, end="")
    return result.stdout


def shell(command, timeout=60):
    marker = "UAV_RC_" + uuid.uuid4().hex
    output = hdc("shell", command + f"; rc=$?; echo {marker}:$rc", timeout=timeout)
    if f"{marker}:0" not in output.splitlines():
        raise RuntimeError("板端命令失败；请保留上面的诊断输出")
    return output


def deploy_files(files, target, executable=None):
    """按显式清单校验上传；相同文件跳过，不同文件拒绝覆盖。"""
    global TARGET
    TARGET = target
    import json, sys, tempfile
    with tempfile.TemporaryDirectory() as temporary:
        manifest = Path(temporary)/'checks.json'
        manifest.write_text(json.dumps(dict(checks=[dict(kind='tool', tool='hdc', version_option='-v'),
            dict(kind='hdc-identity', target=TARGET)])))
        subprocess.run([sys.executable, str(ROOT/'skills/hdc-master/scripts/preflight.py'),
                        '--manifest', str(manifest), '--timeout', '15'], check=True)
    quote = shlex.quote
    for source, destination in files:
        with source.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        dest = quote(destination)
        # 相同文件可重复部署；不同文件拒绝覆盖，不自动停止服务或替换模型。
        hash_command = 'sha256sum ' + dest
        if source.stat().st_size > 64 * 1024 * 1024:
            # Keep the HDC stream active during multi-GB reads and retain progress.
            code = """import hashlib,sys,time
p=sys.argv[1]; h=hashlib.sha256(); processed=0; last=time.monotonic()
with open(p,'rb') as f:
 while True:
  chunk=f.read(16*1024*1024)
  if not chunk:break
  h.update(chunk);processed+=len(chunk)
  if time.monotonic()-last>2:
   print('HASH_PROGRESS',processed,flush=True);last=time.monotonic()
print(h.hexdigest(),p,flush=True)
"""
            hash_command = 'python3 -u -B -c ' + quote(code) + ' ' + dest
        output = shell(f'if [ -e {dest} ] || [ -L {dest} ]; then {hash_command}; else echo UAV_MISSING; fi', timeout=3600)
        if 'UAV_MISSING' not in output.splitlines():
            if not any(line.split()[:1] == [checksum] for line in output.splitlines()):
                raise RuntimeError(f"板端已有不同文件，停止部署并检查：{destination}")
            print(f"相同文件，跳过：{destination}")
            continue
        shell("mkdir -p " + quote(str(Path(destination).parent)))
        hdc("file", "send", str(source), destination, timeout=3600)
        shell(f'test "$(sha256sum {dest} | cut -d " " -f 1)" = {quote(checksum)}', timeout=3600)
    if executable is not None:
        shell("chmod 700 " + quote(executable))


def main():
    global TARGET
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', choices=('qwen', 'dino', 'aerovla', 'all'), default='qwen')
    parser.add_argument('--with-smoke', action='store_true', help='额外上传 AeroVLA golden、smoke 与固定请求，不执行')
    parser.add_argument('--target', help='实际部署必须显式选择本次 HDC connect key')
    parser.add_argument('--check-local', action='store_true', help='只检查本地交付物，不连接设备')
    args = parser.parse_args()
    if not args.check_local and not args.target:
        parser.error('实际部署需要 --target')
    TARGET = args.target or ''
    # 本地文件全部检查通过后才连接设备；不依赖打包脚本或 manifest。
    try:
        files = collect_files(args.service, args.with_smoke)
    except (FileNotFoundError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    if args.check_local:
        print(f'{args.service} 本地交付物检查通过，共 {len(files)} 个文件；未连接设备')
        return
    deploy_files(files, TARGET)
    if args.service in ('qwen', 'all'):
        shell('chmod 700 ' + shlex.quote(REMOTE_STAGE + '/qwen_infer/qwen_ohos_infer'))
    if args.service in ('dino', 'all'):
        shell('chmod 700 ' + shlex.quote(REMOTE_STAGE + '/grounding_dino_infer/grounding_dino_infer'))
    print('传输和校验完成；尚未启动服务。启动入口见 houmo/README.md。')


if __name__ == "__main__":
    main()
