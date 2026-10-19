#!/usr/bin/env python3
"""只输出一个允许的编译路径，供 build.sh 读取根 .env。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from uav_env import configured_path

DEFAULTS = {'HOUMO_MODELZOO_ROOT': 'houmo/deps/modelzoo',
            'TCIM_RUNTIME_PATH': 'houmo/deps/tcim',
            'OHOS_SDK': None, 'OHOS_TOOLCHAINS_DIR': None}

if __name__ == '__main__':
    key = sys.argv[1]
    if key not in DEFAULTS:
        raise ValueError('不允许输出该配置项')
    print(configured_path(key, DEFAULTS[key]))
