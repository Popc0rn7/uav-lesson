#!/usr/bin/env python3
"""PC：将 stage1/robopi 和模型目录部署到固定板端目录。"""
import hashlib
from pathlib import Path
import shlex
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
TARGET = ""  # 留空使用 HDC 默认设备；多设备时填写 connect key。
BOARD = ROOT / "stage1/robopi"
REMOTE_STAGE = "/data/local/workspace/stage1"
MODEL = ROOT / "artifacts/models/Qwen3.6-35B-A3B/qwen3.6-35b-a3b_w4a8_256_256k_b1_1chip_2cores"
REMOTE_MODEL = "/data/local/workspace/models/" + MODEL.name


def require_file(path):
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"缺少文件或文件为空：{path}")
    with path.open('rb') as stream:
        if stream.read(80).startswith(b'version https://git-lfs.github.com/spec/v1'):
            raise ValueError(f"文件仍为 Git LFS 指针：{path}")
    return path


def collect_files():
    files = []
    for name in ("serve.sh", "ros_env.sh", "chat_node.py", "backend.py",
                 "qwen_infer/qwen_ohos_infer", "qwen_infer/run.sh",
                 "qwen_infer/server.py", "qwen_infer/requirements-server.txt",
                 "qwen_infer/lib/libhoumo_infer.so", "qwen_infer/lib/libtokenizer_lib.so",
                 "qwen_infer/LICENSE"):
        files.append((require_file(BOARD / name), REMOTE_STAGE + "/" + name))
    if not MODEL.is_dir():
        raise FileNotFoundError(f"缺少模型目录：{MODEL}")
    require_file(MODEL / "hmquant/quant_embedding.bin")
    files.extend((require_file(path), REMOTE_MODEL + "/" + str(path.relative_to(MODEL)))
                 for path in sorted(MODEL.rglob('*')) if path.is_file())
    return files


def hdc(*args, timeout=60):
    result = subprocess.run(["hdc", *(["-t", TARGET] if TARGET else []), *args],
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


def main():
    # 本地文件全部检查通过后才连接设备；不依赖打包脚本或 manifest。
    files = collect_files()
    quote = shlex.quote
    for source, destination in files:
        with source.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        dest = quote(destination)
        # 相同文件可重复部署；不同文件拒绝覆盖，不自动停止服务或替换模型。
        output = shell(f'if [ -e {dest} ] || [ -L {dest} ]; then sha256sum {dest}; else echo UAV_MISSING; fi', timeout=3600)
        if 'UAV_MISSING' not in output.splitlines():
            if not any(line.split()[:1] == [checksum] for line in output.splitlines()):
                raise RuntimeError(f"板端已有不同文件，停止部署并检查：{destination}")
            print(f"相同文件，跳过：{destination}")
            continue
        shell("mkdir -p " + quote(str(Path(destination).parent)))
        hdc("file", "send", str(source), destination, timeout=3600)
        shell(f'test "$(sha256sum {dest} | cut -d " " -f 1)" = {quote(checksum)}', timeout=3600)
    shell("chmod 700 " + quote(REMOTE_STAGE + "/qwen_infer/qwen_ohos_infer"))
    print("传输和校验完成。板端启动：cd " + REMOTE_STAGE + " && sh serve.sh")


if __name__ == "__main__":
    main()
