"""读取服务端口；仅解析明确列出的数字配置，不执行 .env 内容。"""
from pathlib import Path
import sys

DEFAULTS = {'QWEN_PORT': 8080, 'DINO_PORT': 8083, 'AEROVLA_PORT': 8084}


def read_ports(path=None):
    if path is None:
        here = Path(__file__).resolve().parent
        root = next((parent for parent in here.parents
                     if (parent / 'stage1/deploy.py').is_file()), None)
        path = root / '.env' if root is not None else here / '.env'
    values = dict(DEFAULTS)
    if Path(path).is_file():
        for line in Path(path).read_text().splitlines():
            key, sep, value = line.strip().partition('=')
            if sep and key.strip() in DEFAULTS:
                key, value = key.strip(), value.strip().strip('\"\'')
                if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
                    raise ValueError(f'{key} 必须为 1–65535 的端口号')
                values[key] = int(value)
    if len(set(values.values())) != len(values):
        raise ValueError('QWEN_PORT、DINO_PORT、AEROVLA_PORT 不能相同')
    return values


if __name__ == '__main__':
    print(read_ports()[sys.argv[1]])
