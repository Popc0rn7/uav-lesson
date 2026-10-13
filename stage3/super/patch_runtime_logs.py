#!/usr/bin/env python3
"""PC：将算法源码中的运行日志路径移到容器 /tmp；重复执行无副作用。"""
from pathlib import Path


def patch(super_source=None, lio_source=None):
    sources = []
    if super_source is not None:
        for package in ('super_planner', 'rog_map'):
            directory = Path(super_source) / package
            sources.extend(directory.rglob('*.hpp'))
            sources.extend(directory.rglob('*.h'))
    if lio_source is not None:
        sources.extend([Path(lio_source) / 'include/common_lib.h',
                        Path(lio_source) / 'src/laserMapping.cpp'])
    for path in sources:
        content = path.read_text()
        updated = content.replace('string(ROOT_DIR) + "log/"', 'string("/tmp/stage3-super/")')
        updated = updated.replace('string(ROOT_DIR) + "Log/"', 'string("/tmp/stage3-fastlio/")')
        updated = updated.replace('root_dir + "/Log/', 'string("/tmp/stage3-fastlio/") + "')
        if updated != content:
            path.write_text(updated)


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    patch(root / 'thirdparty/super_gazebo_ws/src',
          root / 'thirdparty/fast_lio_ws/src/FAST_LIO')
