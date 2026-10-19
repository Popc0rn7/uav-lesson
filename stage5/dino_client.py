#!/usr/bin/env python3
"""PC：机载 RGB 或本地图像 → multipart /detect；无需第三方 Python 依赖。"""
import argparse
import base64
import html
import json
import math
import mimetypes
import os
from pathlib import Path
import struct
import time
import urllib.error
import urllib.request
import uuid
import zlib

HERE = Path(__file__).resolve().parent


def configuration():
    from dotenv import dotenv_values
    values = dotenv_values(HERE.parent / '.env')
    config = {**{k:v for k,v in values.items() if v is not None}, **os.environ}
    # 与主仓库一致：相机由课程本机桥提供，不从环境文件选择另一个现场。
    config.update(STAGE5_RGB_URL='http://127.0.0.1:8189/rgb',
                  STAGE5_DEPTH_URL='http://127.0.0.1:8189/depth')
    return config


def annotation(response, image, filename, mock=False, estimates=None):
    w, h = response['width'], response['height']
    if not isinstance(w, int) or not isinstance(h, int) or w <= 0 or h <= 0:
        raise ValueError('检测响应 width/height 必须为正整数')
    mime = mimetypes.guess_type(filename)[0] or 'image/png'
    uri = f'data:{mime};base64,' + base64.b64encode(image).decode()
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                f'<image width="{w}" height="{h}" href="{uri}" preserveAspectRatio="none"/>']
    for index, item in enumerate(response['detections']):
        x1, y1, x2, y2 = item['box_xyxy']
        score = item['score']
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x1, y1, x2, y2, score)):
            raise ValueError('box_xyxy 或 score 非有限数值')
        if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h and 0 <= score <= 1):
            raise ValueError('box_xyxy 或 score 超出响应坐标范围')
        label = html.escape(f'{item["label"]} {score:.3f}')
        if estimates is not None:
            estimate = estimates['targets'][index]
            label += f' / {estimate["range_m"]:.2f} m' if estimate['range_m'] is not None else ' / no depth'
        elements.extend([f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="none" stroke="#00ff60" stroke-width="3"/>',
                         f'<text x="{x1}" y="{max(18, y1-6)}" fill="#00ff60" font-size="18" stroke="black" stroke-width=".4">{label}</text>'])
    if mock:
        elements.append('<text x="12" y="28" fill="yellow" font-size="24">MOCK: sample boxes, not recognition</text>')
    return '\n'.join(elements + ['</svg>'])


def opener():
    # 本地传感器和用户提供的检测服务直接访问，避免代理接管 localhost。
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def chunk(kind, data):
    return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))


def raw_frame(source, timeout):
    with opener().open(source, timeout=timeout) as response:
        raw = response.read()
    if len(raw) < 4:
        raise ValueError('相机响应不完整')
    size = struct.unpack('!I', raw[:4])[0]
    metadata = json.loads(raw[4:4 + size])
    pixels = raw[4 + size:]
    age = time.monotonic() - metadata['received']
    if not 0 <= age <= 2:
        raise ValueError(f'相机帧已陈旧（{age:.2f}s），请恢复仿真时钟')
    metadata['age_at_capture_s'] = age
    return metadata, pixels


def camera_png(source, timeout, captured=None):
    metadata, pixels = captured or raw_frame(source, timeout)
    w, h, step = metadata['width'], metadata['height'], metadata['step']
    if metadata['format'] != 'RGB_INT8' or step < w * 3 or len(pixels) != step * h:
        raise ValueError('相机帧格式或长度错误，要求 RGB_INT8')
    rows = b''.join(b'\0' + pixels[y * step:y * step + w * 3] for y in range(h))
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', w, h, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
    return png, metadata


def paired_frames(rgb_source, depth_source, timeout, max_skew):
    deadline = time.monotonic() + 3
    while True:
        rgb, depth = raw_frame(rgb_source, timeout), raw_frame(depth_source, timeout)
        if abs(rgb[0]['sim_time'] - depth[0]['sim_time']) <= max_skew:
            return rgb, depth
        if time.monotonic() >= deadline:
            raise ValueError('RGB/D 时间差超限，无法取得配对帧')
        time.sleep(.01)


class DinoClient:
    def __init__(self, url='http://127.0.0.1:8000/detect', timeout=60):
        self.url, self.timeout = url, timeout

    def detect(self, image, filename='camera.png', text='a car.'):
        boundary = 'stage5-' + uuid.uuid4().hex
        mime = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        # filename 由本程序生成，避免任意文件名进入 multipart 头。
        suffix = Path(filename).suffix.lower()
        safe_name = 'image' + (suffix if suffix in ('.png', '.jpg', '.jpeg', '.webp', '.ppm') else '.bin')
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="text"\r\n\r\n{text}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{safe_name}"\r\n'
                f'Content-Type: {mime}\r\n\r\n').encode() + image + f'\r\n--{boundary}--\r\n'.encode()
        request = urllib.request.Request(self.url, data=body,
            headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
        started = time.perf_counter()
        with opener().open(request, timeout=self.timeout) as response:
            result = json.loads(response.read())
        return result, time.perf_counter() - started


def main():
    config = configuration()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=config.get('DINO_DETECT_URL', 'http://127.0.0.1:8000/detect'))
    parser.add_argument('--source', default=config.get('STAGE5_RGB_URL', 'http://127.0.0.1:8189/rgb'), help='Stage 2 原始 RGB 帧协议')
    parser.add_argument('--image', type=Path, help='使用本地图像替代机载相机')
    parser.add_argument('--depth-source', default=config.get('STAGE5_DEPTH_URL', 'http://127.0.0.1:8189/depth'))
    parser.add_argument('--no-depth', action='store_true', help='仅检测 RGB；本地图像自动禁用深度融合')
    parser.add_argument('--max-skew', type=float, default=float(config.get('RGBD_MAX_SKEW_S', '.05')))
    parser.add_argument('--max-age', type=float, default=float(config.get('RGBD_MAX_AGE_S', '.5')))
    parser.add_argument('--voxel-size', type=float, default=float(config.get('VOXEL_SIZE_M', '.25')))
    parser.add_argument('--voxel-stride', type=int, default=int(config.get('VOXEL_PIXEL_STRIDE', '8')))
    parser.add_argument('--text', default=config.get('DINO_TEXT', 'a person. a car.'))
    parser.add_argument('--timeout', type=float, default=float(config.get('DINO_TIMEOUT', '60')))
    parser.add_argument('--mock', action='store_true', help='使用用户示例响应，不访问检测服务；框不代表实际识别')
    parser.add_argument('--output', type=Path, help='新的输出目录；默认 /tmp/stage5-dino-<随机 ID>')
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('timeout 必须大于零')
    if not math.isfinite(args.max_skew) or args.max_skew <= 0:
        parser.error('max-skew 必须大于零')
    if not math.isfinite(args.max_age) or args.max_age <= 0:
        parser.error('max-age 必须大于零')
    if not math.isfinite(args.voxel_size) or not .1 <= args.voxel_size <= 1 or not 1 <= args.voxel_stride <= 32:
        parser.error('voxel-size 须为 0.1～1 m，voxel-stride 须为 1～32')
    directory = args.output or Path('/tmp') / ('stage5-dino-' + uuid.uuid4().hex[:10])
    directory.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    try:
        depth = None
        if args.image:
            image, filename, metadata = args.image.read_bytes(), args.image.name, {'source': str(args.image)}
        else:
            if args.no_depth:
                image, metadata = camera_png(args.source, min(args.timeout, 5))
            else:
                rgb, depth = paired_frames(args.source, args.depth_source, min(args.timeout, 5), args.max_skew)
                image, metadata = camera_png(args.source, min(args.timeout, 5), rgb)
                (directory / 'depth.f32').write_bytes(depth[1])
                (directory / 'depth_capture.json').write_text(json.dumps(depth[0], indent=2) + '\n')
            filename = 'camera.png'
        image_path = directory / ('input' + Path(filename).suffix.lower())
        image_path.write_bytes(image)
        metadata.update(text=args.text, endpoint=args.url, image_file=image_path.name,
                        response_source='mock' if args.mock else 'http')
        (directory / 'capture.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
        if args.mock:
            response, elapsed = json.loads((HERE / 'mock_detection.json').read_text()), 0.0
        else:
            response, elapsed = DinoClient(args.url, args.timeout).detect(image, filename, args.text)
        (directory / 'detection.json').write_text(json.dumps(response, ensure_ascii=False, indent=2) + '\n')
        (directory / 'annotated.svg').write_text(annotation(response, image, filename, args.mock))
        if depth is not None:
            from depth_fusion import calibration, fuse
            model = calibration()
            targets = fuse(response, metadata, depth[0], depth[1], model,
                           args.max_skew, metadata['response_source'])
            targets['observation_age_s'] = time.monotonic() - metadata['received']
            targets['usable_for_control'] = targets['usable_for_control'] and targets['observation_age_s'] <= args.max_age
            (directory / 'annotated.svg').write_text(annotation(response, image, filename, args.mock, targets))
            (directory / 'calibration.json').write_text(json.dumps(model, indent=2) + '\n')
            from voxel_scene import build, ply
            scene = build(depth[0], depth[1], model, args.voxel_size, args.voxel_stride)
            scene['observation_age_s'] = time.monotonic() - depth[0]['received']
            scene['fresh'] = scene['observation_age_s'] <= args.max_age
            targets['observation_age_s'] = time.monotonic() - metadata['received']
            targets['usable_for_control'] = targets['usable_for_control'] and targets['observation_age_s'] <= args.max_age
            (directory / 'targets.json').write_text(json.dumps(targets, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
            print(json.dumps(targets, ensure_ascii=False, indent=2))
            (directory / 'voxels.ply').write_text(ply(scene))
            (directory / 'voxel_scene.json').write_text(json.dumps(scene, indent=2, allow_nan=False) + '\n')
            print(json.dumps({k: v for k, v in scene.items() if k != 'occupied_points_m'}, ensure_ascii=False, indent=2))
        (directory / 'timing.json').write_text(json.dumps({'detect_s': elapsed,
            'e2e_s': time.perf_counter() - started}, indent=2) + '\n')
        print(json.dumps(response, ensure_ascii=False, indent=2))
        print(f'Detect: {elapsed:.3f} 秒；E2E: {time.perf_counter() - started:.3f} 秒')
        print(f'图像、原始响应和取帧元数据：{directory}')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        detail = exc.read(4096).decode(errors='replace') if isinstance(exc, urllib.error.HTTPError) else str(exc)
        (directory / 'error.txt').write_text(detail + '\n')
        raise SystemExit(f'检测失败：{detail}\n诊断与已获取图像：{directory}') from exc


if __name__ == '__main__':
    main()
