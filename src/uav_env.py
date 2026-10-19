"""PC：读取根 .env 的本机配置，不执行 shell，也不输出整份配置。"""
import os
from pathlib import Path
import shlex

ROOT = Path(__file__).resolve().parents[1]


def read_env(path=None):
    values = {}
    path = Path(path) if path is not None else ROOT / '.env'
    if path.is_file():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:].lstrip()
            key, sep, value = line.partition('=')
            if not sep:
                raise ValueError(f'{path.name}:{number} 应为 KEY=value')
            parts = shlex.split(value, comments=True)
            values[key.strip()] = ' '.join(parts)
    return {**values, **os.environ}


def configured_path(key, default=None):
    value = read_env().get(key) or default
    if not value:
        raise ValueError(f'请在根 .env 设置 {key}')
    path = Path(value).expanduser()
    # 主机 venv 的解释器不能 resolve，否则会丢失 venv 身份。
    return path.absolute() if path.is_absolute() else (ROOT / path).absolute()
