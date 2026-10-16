"""可选旁路计时；未设置 UAV_PROFILE_DIR 时不创建文件。"""
import json
import os
from pathlib import Path
import time


class Recorder:
    def __init__(self, name):
        directory = os.environ.get('UAV_PROFILE_DIR')
        self.stream = None
        if directory:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            self.stream = (path/(name+'.jsonl')).open('a', buffering=1)

    def emit(self, kind, **values):
        if self.stream is not None:
            self.stream.write(json.dumps(dict(kind=kind, mono_ns=time.monotonic_ns(),
                                               **values), separators=(',', ':'))+'\n')
