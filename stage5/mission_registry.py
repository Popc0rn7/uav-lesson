"""本工作树最新 mission 的本地索引；不包含配置或凭据。"""
import hashlib
import json
from pathlib import Path
import tempfile

WORKSPACE = Path(__file__).resolve().parents[1]
WORKSPACE_ID = hashlib.sha256(str(WORKSPACE).encode()).hexdigest()[:12]
REGISTRY = Path(tempfile.gettempdir()) / f'uav-stage5-{WORKSPACE_ID}-latest.json'


def register(directory):
    value = dict(directory=str(Path(directory).resolve()), workspace=str(WORKSPACE))
    # 每次写入使用独立临时文件，避免并发启动互相覆盖半份JSON。
    with tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8', dir=REGISTRY.parent,
        prefix=REGISTRY.name + '.', delete=False,
    ) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream)
    try:
        temporary.replace(REGISTRY)
    finally:
        temporary.unlink(missing_ok=True)


def latest(registry=REGISTRY, root=None):
    try:
        value = json.loads(registry.read_text(encoding='utf-8'))
        directory = Path(value['directory'])
        if value.get('workspace') == str(WORKSPACE) and (directory / 'task.json').is_file():
            return directory
    except (OSError, ValueError, KeyError, TypeError):
        pass

    # 兼容升级前已启动的默认临时任务，只按task.json初次写入时间排序。
    candidates = []
    for directory in (root or Path(tempfile.gettempdir())).glob('stage5-mission-*'):
        try:
            task = directory / 'task.json'
            value = json.loads(task.read_text(encoding='utf-8'))
            if isinstance(value.get('task'), str):
                candidates.append((task.stat().st_mtime_ns, directory))
        except (OSError, ValueError, AttributeError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None
