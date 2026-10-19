#!/usr/bin/env python3
"""PC：编译应用私有的 OHOS Python 3.12 pytcim，不替换板端全局运行库。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from uav_env import configured_path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-include',type=Path,required=True,help='已核验目标 Python 3.12 开发头文件')
    parser.add_argument('--pybind11-include',type=Path,required=True)
    parser.add_argument('--python-library',type=Path,help='目标 libpython3.12.so.1.0；默认从头文件所属前缀推导')
    args=parser.parse_args()
    sdk=configured_path('OHOS_SDK')
    tcim=configured_path('TCIM_RUNTIME_PATH','houmo/deps/tcim')
    python=args.python_include.resolve();pybind=args.pybind11_include.resolve()
    python_library=(args.python_library or python.parent.parent/'lib/libpython3.12.so.1.0').resolve()
    for path in (sdk/'build/cmake/ohos.toolchain.cmake',python/'Python.h',python/'pyconfig.h',
                 pybind/'pybind11/pybind11.h',tcim/'python/pytcim.cc',python_library):
        if not path.is_file():raise FileNotFoundError(path)
    work=ROOT/'houmo/build/aerovla/tcim-python-cmake'
    subprocess.run(['cmake','-S',str(Path(__file__).parent/'tcim_python'),'-B',str(work),
        '-DCMAKE_TOOLCHAIN_FILE='+str(sdk/'build/cmake/ohos.toolchain.cmake'),
        '-DOHOS_ARCH=arm64-v8a','-DCMAKE_BUILD_TYPE=Release',
        '-DTARGET_PYTHON_LIBRARY='+str(python_library),'-DTCIM_ROOT='+str(tcim),'-DTARGET_PYTHON_INCLUDE='+str(python),'-DPYBIND11_INCLUDE='+str(pybind)],check=True)
    subprocess.run(['cmake','--build',str(work),'--parallel','2'],check=True)
    package=ROOT/'houmo/build/aerovla/tcim_python/tcim_lite';package.mkdir(parents=True,exist_ok=True)
    for path in (tcim/'python/tcim_lite').glob('*.py'):shutil.copy2(path,package/path.name)
    binary=work/'pytcim.cpython-312-aarch64-linux-ohos.so';shutil.copy2(binary,package/binary.name)
    subprocess.run([str(sdk/'llvm/bin/llvm-readelf'),'-h','-d',str(binary)],check=True)
    def digest(path):
        with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
    (package.parent/'BUILD.json').write_text(json.dumps({'SOABI':'cpython-312-aarch64-linux-ohos',
        'sdk':str(sdk),'python_include':str(python),'pybind11_include':str(pybind),
        'source_sha256':digest(tcim/'python/pytcim.cc'),
        'tcim_sha256':digest(tcim/'lib/libtcim_runtime_lite.so'),
        'binary_sha256':digest(package/binary.name)},indent=2)+'\n')
    print('私有 TCIM Python 绑定已构建：'+str(package))


if __name__=='__main__':main()
