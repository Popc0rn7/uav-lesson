#!/usr/bin/env python3
"""Docker 2：只读保存 AirSim RGB PNG，不申请飞行控制权。"""
import json
from pathlib import Path
import time
from rpc_client import rpc


def main():
    request = dict(camera_name='0', image_type=0, pixels_as_float=False, compress=True)
    frames = rpc('simGetImages', [request], 'PX4', False, timeout=10)
    if len(frames) != 1:
        raise RuntimeError('相机响应数量无效')
    frame = frames[0]
    data = bytes(frame['image_data_uint8'])
    if data[:8] != b'\x89PNG\r\n\x1a\n' or frame['width'] <= 0 or frame['height'] <= 0:
        raise RuntimeError('相机未返回有效 PNG')
    path = Path('/run/airsim') / f'camera-{time.time_ns()}.png'
    path.write_bytes(data)
    metadata = {key: frame.get(key) for key in ('width','height','time_stamp','camera_position','camera_orientation')}
    path.with_suffix('.json').write_text(json.dumps(metadata, indent=2))
    print(json.dumps(dict(path=str(path), width=frame['width'], height=frame['height'], bytes=len(data))))


if __name__ == '__main__':
    main()
