#!/usr/bin/env python3
"""Docker：检查标准机真实 RGB/D 帧、时间戳、有效深度与内容。"""
import array
import argparse
import json
import math
from pathlib import Path
import struct
import time
import urllib.request
from depth_fusion import calibration


def frame(name, source='http://127.0.0.1:8189'):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'{source.rstrip("/")}/{name}', timeout=3) as response:
        raw = response.read()
    length = struct.unpack('!I', raw[:4])[0]
    return json.loads(raw[4:4+length]), raw[4+length:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='http://127.0.0.1:8189')
    parser.add_argument('--output', type=Path, default=Path('/tmp'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    model = calibration()
    near, far = model['near_m'], model['far_m']
    deadline = time.monotonic() + 60
    while True:
        try:
            first = {name: frame(name, args.source)[0] for name in ('rgb', 'depth')}
            break
        except OSError:
            if time.monotonic() > deadline:
                raise SystemExit('等待 RGB/D 超时；检查对应 Gazebo 或 AirSim 后端的相机日志')
            time.sleep(.5)
    time.sleep(5)
    result = {}
    for name in ('rgb', 'depth'):
        info, data = frame(name, args.source)
        elapsed = info['sim_time'] - first[name]['sim_time']
        assert elapsed > 0 and info['count'] - first[name]['count'] >= 10, f'{name} 帧停止'
        assert time.monotonic() - info['received'] < 2, f'{name} 数据陈旧'
        assert len(data) == info['step'] * info['height'], f'{name} 载荷长度错误'
        info['sim_fps'] = (info['count'] - first[name]['count']) / elapsed
        if name == 'rgb':
            assert (info['width'], info['height'], info['format']) == (640, 360, 'RGB_INT8')
            assert max(data) - min(data) > 30, 'RGB 内容为空或单色'
            (args.output/'stage5-rgb.ppm').write_bytes(b'P6\n640 360\n255\n' + data)
        else:
            assert (info['width'], info['height'], info['format']) == (640, 400, 'R_FLOAT32')
            depths = array.array('f', data)
            valid = [d for d in depths if math.isfinite(d) and near < d < far]
            assert len(valid) > len(depths) * .01, '深度有效像素不足'
            info['valid_fraction'] = len(valid) / len(depths)
            info['valid_min_m'], info['valid_max_m'] = min(valid), max(valid)
            pixels = bytes(int(255 * (1-min(d, far)/far)) if math.isfinite(d) and d > 0 else 0
                           for d in depths)
            (args.output/'stage5-depth.pgm').write_bytes(b'P5\n640 400\n255\n' + pixels)
        result[name] = info
    print(json.dumps(result, ensure_ascii=False, indent=2))
    (args.output/'camera-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f'PASS：标准机 RGB 与深度持续输出；报告与画面 {args.output}')


if __name__ == '__main__':
    main()
