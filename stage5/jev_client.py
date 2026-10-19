#!/usr/bin/env python3
"""PC：DINO＋深度＋体素 → Jev 异步战术建议；不发布飞行命令。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from dino_client import configuration
from tactics import Tactician, build_state

HERE = Path(__file__).resolve().parent
MISSION = '跟随指定车辆，在车辆后方保持10米水平距离；未知运动方向时先确认，不假定后方已知。'


def main():
    config = configuration()
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--observe', action='store_true', help='重新调用 DINO 并获取 RGB/D、体素')
    source.add_argument('--observation', type=Path, help='使用已有 client 输出目录')
    parser.add_argument('--dry-run', action='store_true', help='只保存 Jev 输入，不访问 Jev，无需 SDK 或密钥')
    parser.add_argument('--mission', default=config.get('JEV_MISSION', MISSION))
    parser.add_argument('--count', type=int, default=1, help='最多观测轮数；默认单次')
    parser.add_argument('--output', type=Path, help='新的结果目录')
    args = parser.parse_args()
    if not 1 <= args.count <= 100 or args.observation and args.count != 1:
        parser.error('count 须为 1～100，已有观测只支持单次')
    directory = args.output
    if directory:
        directory.mkdir(parents=True, exist_ok=False)
    else:
        directory = Path(tempfile.mkdtemp(prefix='stage5-jev-'))
    actor = None
    failed = False
    try:
        if not args.dry_run:
            actor = Tactician(config)
        for index in range(args.count):
            if actor and actor.attempts >= actor.budget:
                print('达到 Jev 调用预算，结束')
                break
            observation = args.observation
            if args.observe:
                observation = directory / f'observation-{index+1:03d}'
                result = subprocess.run([sys.executable, str(HERE/'dino_client.py'), '--output', str(observation)],
                                        capture_output=True, text=True)
                if result.returncode:
                    raise RuntimeError(f'感知失败；诊断文件位于 {observation}')
            targets = json.loads((observation/'targets.json').read_text())
            voxels = json.loads((observation/'voxel_scene.json').read_text())
            capture = json.loads((observation/'capture.json').read_text())
            state = build_state(targets, voxels, capture, args.mission)
            stem = directory / f'jev-{index+1:03d}'
            stem.with_suffix('.state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
            if args.dry_run:
                judgment = dict(source='dry_run', execution_mode='advisory_only', actionable=False)
            elif time.monotonic()-capture['received'] > actor.ttl:
                judgment = dict(source='stale_observation', maneuver='brake', actionable=False)
            elif targets['frame_skew_s'] > float(config.get('RGBD_MAX_SKEW_S', '.05')):
                judgment = dict(source='unsynchronized', maneuver='brake', actionable=False)
            elif actor.offer(state, capture['received']):
                judgment = actor.wait_result()
            else:
                judgment = actor.read()
            stem.with_suffix('.judgment.json').write_text(json.dumps(judgment, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
            print(json.dumps(judgment, ensure_ascii=False, indent=2))
            if judgment['source'] in ('error', 'timeout'):
                failed = True
                break
            if index+1 < args.count:
                time.sleep(1/float(config.get('JEV_CALL_HZ', '1')))
        if actor:
            stats = actor.stats()
            (directory/'stats.json').write_text(json.dumps(stats, indent=2)+'\n')
            print(json.dumps(stats, ensure_ascii=False))
        print(f'Jev 输入与建议：{directory}')
        if failed:
            raise SystemExit(1)
    except ImportError:
        raise SystemExit('Jev运行依赖缺失；PC仓库根目录执行 uv sync --extra stage5') from None
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        # 此处异常为配置/本地输入诊断；SDK 异常在 worker 中只保存类型。
        raise SystemExit(f'{type(exc).__name__}: {exc}\n诊断目录：{directory}') from exc
    finally:
        if actor:
            actor.close()


if __name__ == '__main__':
    main()
