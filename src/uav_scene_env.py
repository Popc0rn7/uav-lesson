"""PC 环境配置：shell > 根 .env > 旧阶段 .env。"""
import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def configuration(legacy=None):
    values = dict(dotenv_values(legacy)) if legacy and Path(legacy).is_file() else {}
    values.update(dotenv_values(ROOT / '.env'))
    return {**{k: v for k, v in values.items() if v is not None}, **os.environ}


def scene_binary(name):
    value = configuration().get(name)
    if not value or not value.strip():
        raise ValueError(f'请在 {ROOT / ".env"} 或 shell 中设置 {name}（场景 Linux ELF 路径）')
    return (ROOT / Path(value).expanduser()).resolve()


def scene_package(binary):
    # Unreal Linux 包：<包根>/<项目>/Binaries/Linux/<ELF>。
    binary = Path(binary)
    if binary.parent.name != 'Linux' or binary.parent.parent.name != 'Binaries':
        raise ValueError(f'预期 <包根>/<项目>/Binaries/Linux/<ELF>，实际为 {binary}')
    return binary.parents[3]
