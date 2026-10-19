"""AeroVLA 使用现有 TCIM Python runtime，无独立 C++ ELF。"""
import json
from pathlib import Path
import shutil

GRAPHS = ('aerovla_vision.hmm','aerovla_prefill.hmm','aerovla_decode.hmm')
ASSETS = ('assets.json','id2token.json','token_embedding.npy','meta_info.json')
RUNTIME = ('runner.py','service.py','client.py','requirements-board.txt','ORIGIN.json')


def assemble(package):
    root, source, deploy = package.ROOT, package.SOURCE, package.DEPLOY
    model = root/'houmo/models/AeroVLA'
    missing = [str(model/'models'/name) for name in GRAPHS if not (model/'models'/name).is_file()]
    if missing:
        raise FileNotFoundError('AeroVLA 缺少 HMM，不能装配可部署运行包：\n'+'\n'.join(missing))
    models = [model/'models'/name for name in GRAPHS] + [model/'assets'/name for name in ASSETS]
    for file in models:
        package.require_file(file)
    cfg=json.loads((model/'assets/assets.json').read_text())
    if cfg.get('vision_input_shape') != [1,6,224,224] or cfg.get('vision_output_shape') != [1,256,4096]:
        raise ValueError('AeroVLA 视觉接口不匹配')
    if cfg.get('vocab_size') != 32001 or cfg.get('num_bins') != 99 or not 1 <= cfg.get('max_new_tokens',0) <= 20:
        raise ValueError('AeroVLA 文本/动作配置不匹配')
    inputs=[(source/'aerovla'/name,Path('stage1/aerovla_infer')/name) for name in RUNTIME]
    inputs += [(source/'stage1'/name,Path('stage1')/name) for name in ('serve_aerovla.sh','service_config.py')]
    binding = package.BUILD/'aerovla/tcim_python'
    binding_files = ('BUILD.json','tcim_lite/__init__.py','tcim_lite/runtime.py',
                     'tcim_lite/imageops.py','tcim_lite/pytcim.cpython-312-aarch64-linux-ohos.so')
    for name in binding_files:
        path = package.require_file(binding/name)
        if path.suffix == '.so':
            package.check_elf(path)
        inputs.append((path,Path('stage1/aerovla_infer/tcim_python')/name))
    for path,_ in inputs:
        package.require_file(path)
    links=[(deploy/'models/AeroVLA'/p.relative_to(model),p) for p in models]
    for dest,target in links:
        if dest.exists() or dest.is_symlink():
            if not dest.is_symlink() or dest.resolve()!=target.resolve():
                raise FileExistsError(f'已有不同模型，拒绝替换：{dest}')
    ports=package.read_ports(root/'.env')
    files=[]
    for path,relative in inputs:
        dest=deploy/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dest);files.append(dest)
    env=deploy/'stage1/.env';env.write_text(''.join(f'{k}={v}\n' for k,v in ports.items()));files.append(env)
    record=deploy/'stage1/aerovla_infer/SOURCE.json'
    record.write_text(json.dumps({'service':'aerovla','source':'houmo/src/aerovla','sha256':{
        str(p.relative_to(deploy)):package.digest(p) for p in files}},indent=2)+'\n');files.append(record)
    for dest,target in links:
        dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.is_symlink():dest.symlink_to(target.resolve())
        files.append(dest)
    return [(p,'/data/local/workspace/'+str(p.relative_to(deploy))) for p in files]


def assemble_smoke(package):
    """只装配验收脚本及 golden/固定请求，不加载 NPU。"""
    root, deploy = package.ROOT, package.DEPLOY
    model = root/'houmo/models/AeroVLA'
    inputs = [(package.SOURCE/'aerovla/smoke.py', Path('stage1/aerovla_infer/smoke.py')),
              (model/'samples/request.json', Path('models/AeroVLA/samples/request.json'))]
    golden = sorted((model/'golden').rglob('*.npy'))
    if not golden:
        raise FileNotFoundError('缺少 AeroVLA golden')
    inputs.extend((p, Path('models/AeroVLA/golden')/p.relative_to(model/'golden')) for p in golden)
    for source,_ in inputs:
        package.require_file(source)
    files = []
    for source,relative in inputs:
        dest = deploy/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        if relative.suffix == '.py':
            shutil.copy2(source,dest)
        else:
            if dest.exists() or dest.is_symlink():
                if not dest.is_symlink() or dest.resolve()!=source.resolve():
                    raise FileExistsError(f'已有不同验收数据：{dest}')
            else:
                dest.symlink_to(source.resolve())
        files.append((dest,'/data/local/workspace/'+str(relative)))
    return files
