"""Stage 5 本地证据写入；读者只能看到完整的 JSON 快照。"""
import json
from pathlib import Path


def write_json(path, value):
    """原子替换单写者快照，不创建或覆盖其他目录。"""
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    try:
        temporary.write_text(payload, encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
