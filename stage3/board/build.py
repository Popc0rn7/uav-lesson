#!/usr/bin/env python3
"""PC：显式 SDK/目标快照的 OpenHarmony SUPER 构建；不下载或修改基础环境。"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT/'artifacts/robopi-stage3'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def files_digest(directory):
    return {str(p.relative_to(directory)): digest(p) for p in sorted(directory.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def prepare_source(source):
    command=['git','-C',str(source),'apply']
    for patch in sorted((Path(__file__).parent/'patches').glob('*.patch')):
        if subprocess.run(command+['--reverse','--check',str(patch.resolve())],capture_output=True).returncode==0:
            continue
        # Apply only a patch whose exact contexts still match; never reset local work.
        subprocess.run(command+['--check',str(patch.resolve())],check=True)
        subprocess.run(command+[str(patch.resolve())],check=True)


def configure(config):
    required = ('sdk', 'deps', 'python_deps', 'host_python', 'target_metadata', 'px4_source')
    paths = {k:Path(config[k]).expanduser().resolve() for k in required}
    # Preserve a venv's interpreter path: resolving its symlink loses site-packages.
    paths['host_python']=Path(config['host_python']).expanduser().absolute()
    for key, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f'{key}: {path}')
    for name in ('cmake', 'ninja'):
        if not shutil.which(name):
            raise RuntimeError('缺少主机工具：'+name)
    if config.get('target_verified') is not True:
        raise RuntimeError('需先核对当前设备与依赖快照，再显式设置 target_verified=true')
    metadata = json.loads(paths['target_metadata'].read_text())
    abi = metadata.get('SOABI')
    if not isinstance(abi, str) or '312' not in abi or 'aarch64' not in abi:
        raise RuntimeError('需要本次板端 Python 3.12 AArch64 SOABI 证据')
    pinned = '57f88be3c01a8c593c23507e4ca136767115ca22'
    revision = subprocess.check_output(['git','-C',str(paths['px4_source']),'rev-parse','HEAD'],text=True).strip()
    if revision != pinned or subprocess.check_output(['git','-C',str(paths['px4_source']),'status','--porcelain'],text=True).strip():
        raise RuntimeError('px4_msgs 需与 develop/docker 固定提交一致且工作树干净：'+pinned)
    # These target dependencies must exist; never resolve a host package instead.
    for name in ('rclcpp','pcl_conversions','tf2_ros'):
        if not (paths['deps']/'install/share'/name/'cmake').is_dir():
            raise FileNotFoundError('目标 ROS 依赖缺失：'+name)
    return paths, abi


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    args=parser.parse_args()
    if args.jobs<1:parser.error('jobs 必须为正数')
    config=json.loads(args.config.read_text())
    if args.dry_run:
        print(json.dumps(dict(config=config, output=str(WORK), packages=['px4_msgs','mars_quadrotor_msgs','rog_map','super_planner']),indent=2))
        return
    paths,abi=configure(config)
    env=os.environ.copy()
    overlay=WORK/'install'
    env.update(OHOS_SDK_NATIVE=str(paths['sdk']), UAV_BOARD_DEPS=str(paths['deps']),
               UAV_BOARD_OVERLAY=str(overlay), ROS_DISTRO='humble',
               PYTHONPATH=str(paths['deps']/'install/lib/python3.12/site-packages'),
               AMENT_PREFIX_PATH=str(overlay)+':'+str(paths['deps']/'install'))
    source=ROOT/'submodules/SUPER'
    prepare_source(source)
    packages=[('px4_msgs',paths['px4_source']),
              ('mars_quadrotor_msgs',source/'mars_uav_sim/mars_quadrotor_msgs'),
              ('rog_map',source/'rog_map'),('super_planner',source/'super_planner')]
    print('核验源码与目标依赖哈希…',flush=True)
    dependency_files=files_digest(paths['deps'])
    python_files=dependency_files if paths['python_deps']==paths['deps'] else files_digest(paths['python_deps'])
    metadata=dict(config=config,soabi=abi,sources={n:files_digest(p) for n,p in packages},
                  deps=dependency_files, python_deps=python_files,
                  sdk=json.loads((paths['sdk']/'oh-uni-package.json').read_text()),
                  toolchain_sha256=digest(Path(__file__).with_name('toolchain.cmake')))
    metadata['sources']['build-adapters']=files_digest(Path(__file__).parent)
    WORK.mkdir(parents=True,exist_ok=True)
    fingerprint=hashlib.sha256(json.dumps(metadata,sort_keys=True).encode()).hexdigest()
    old=WORK/'build-input.json'
    if old.exists():
        previous=json.loads(old.read_text())['metadata']
        previous_abi={k:v for k,v in previous.items() if k!='sources'}
        current_abi={k:v for k,v in metadata.items() if k!='sources'}
        if previous_abi!=current_abi:
            raise RuntimeError('SDK/目标依赖已变化；先保留旧构建产物并使用新的构建目录')
    old.write_text(json.dumps(dict(fingerprint=fingerprint,metadata=metadata),indent=2))
    include=paths['python_deps']/'out/include/python3.12'
    numpy=paths['python_deps']/'out/lib/python3.12/site-packages/numpy/_core/include'
    for p in (include,numpy):
        if not p.is_dir():raise FileNotFoundError(p)
    # The image contains two PNG releases; its generic symlink points at 1.6.43
    # while PCL and png.h require 1.6.50 with PNG16_0 symbol versions.
    png_header=paths['deps']/'out/include/png.h'
    png_version=re.search(r'#define\s+PNG_LIBPNG_VER_STRING\s+"(1\.6\.(\d+))"',png_header.read_text())
    if not png_version:raise RuntimeError('无法确认目标 PNG 头文件版本')
    png=paths['deps']/('out/lib/libpng16.so.16.'+png_version[2]+'.0')
    if not png.is_file():raise FileNotFoundError('缺少与目标 PNG 头文件匹配的库：'+str(png))
    for name,src in packages:
        print('配置/构建目标包：'+name,flush=True)
        build=WORK/'build'/name
        command=['cmake','-S',str(src),'-B',str(build),'-G','Ninja',
                 '-DCMAKE_TOOLCHAIN_FILE='+str(Path(__file__).with_name('toolchain.cmake')),
                 '-DCMAKE_MODULE_PATH='+str(Path(__file__).parent/'cmake'),
                 '-DCMAKE_PREFIX_PATH='+ ';'.join(map(str,[overlay,paths['deps']/'install',paths['deps']/'out'])),
                 '-DCMAKE_INSTALL_PREFIX='+str(overlay),'-DCMAKE_BUILD_TYPE=Release','-DBUILD_TESTING=OFF',
                 '-DCMAKE_SKIP_RPATH=ON','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                 '-DPython3_EXECUTABLE='+str(paths['host_python']),'-DPYTHON_EXECUTABLE='+str(paths['host_python']),
                 '-DPYTHON_SOABI='+abi,'-DPYTHON_INCLUDE_DIR='+str(include),
                 '-DPYTHON_LIBRARY='+str(paths['python_deps']/'out/lib/libpython3.12.so'),
                 '-DPythonExtra_INCLUDE_DIRS='+str(include)+';'+str(numpy),
                 '-D_numpy_h:FILEPATH='+str(numpy/'numpy/numpyconfig.h'),
                 '-DCMAKE_C_FLAGS=-I'+str(numpy)]
        command+=['-DPNG_LIBRARY_RELEASE:FILEPATH='+str(png)]
        if name in ('rog_map','super_planner'):
            # The SDK appends -O2 after upstream's -O3; retain the upstream
            # release optimization level without changing search deadlines.
            command+=['-DCMAKE_CXX_FLAGS_RELEASE:STRING=-O3 -DNDEBUG']
        if name=='super_planner':command+=['-DSUPER_ENABLE_STACKTRACE=OFF']
        subprocess.run(command,env=env,check=True)
        commands=json.loads((build/'compile_commands.json').read_text())
        host_prefix=str(paths['host_python'].parent.parent)
        if any(host_prefix+'/lib/python' in entry['command'] for entry in commands):
            raise RuntimeError('编译命令混入主机 Python/NumPy 头文件')
        subprocess.run(['cmake','--build',str(build),'-j',str(args.jobs)],env=env,check=True)
        subprocess.run(['cmake','--install',str(build)],env=env,check=True)
    # Private runtime dependency; never alter the board's system symlinks.
    shutil.copy2(png,overlay/'lib/libpng16.so.16')
    readelf=paths['sdk']/'llvm/bin/llvm-readelf'
    evidence={}
    for path in overlay.rglob('*'):
        if not path.is_file():continue
        with path.open('rb') as stream:magic=stream.read(4)
        if magic!=b'\x7fELF':continue
        result=subprocess.check_output([str(readelf),'-h','-d',str(path)],text=True)
        runtime_paths=[line for line in result.splitlines() if '(RPATH)' in line or '(RUNPATH)' in line]
        # The unmodified target PNG library uses a relocatable $ORIGIN only.
        allowed_origin=path==overlay/'lib/libpng16.so.16' and all(
            '(RUNPATH)' in line and line.rstrip().endswith('[$ORIGIN]') for line in runtime_paths)
        if 'AArch64' not in result or (runtime_paths and not allowed_origin):
            raise RuntimeError('目标 ELF 架构或 RPATH 错误：'+str(path))
        evidence[str(path.relative_to(overlay))]=result
    (WORK/'elf-audit.json').write_text(json.dumps(evidence,indent=2))
    (WORK/'build-evidence.json').write_text(json.dumps(dict(
        fingerprint=fingerprint,soabi=abi,
        features=['native-wall-cpu-profile-v1','clock-aware-replan-v1'],
        files=files_digest(overlay)),indent=2))
    print('交叉构建与 ELF 检查通过；仍需板端依赖解析、消息收发及飞行验收')


if __name__=='__main__':main()
