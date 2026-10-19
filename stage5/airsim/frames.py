"""AirSim Scene/DepthPlanar → Stage 2 原始帧；仅转换传感器数据。"""
from io import BytesIO
import math


def decode_pair(frames, model, previous_ns=0):
    import numpy as np
    from PIL import Image
    if len(frames) != 2:
        raise ValueError('需要 RGB/DepthPlanar 两帧')
    stamps = [int(f['time_stamp']) for f in frames]
    if min(stamps) <= previous_ns or abs(stamps[0]-stamps[1]) > 50_000_000:
        raise ValueError('相机时间重复、回跳或 RGBD 时间差超过50ms')
    for frame, key, image_type in zip(frames, ('rgb', 'depth'), (0, 1)):
        if frame.get('message') or frame['image_type'] != image_type:
            raise ValueError(f'AirSim 相机错误：{frame.get("message", "image_type")}')
        if (frame['width'], frame['height']) != (model[key]['width'], model[key]['height']):
            raise ValueError(f'{key} 分辨率与标定不符，请核对实际加载的 settings')
    # AirSim 未压缩 Scene 是 BGR；用 PNG 显式解码，避免红蓝互换。
    image = Image.open(BytesIO(bytes(frames[0]['image_data_uint8']))).convert('RGB')
    if image.size != (model['rgb']['width'], model['rgb']['height']):
        raise ValueError('PNG 尺寸与元数据不符')
    values = np.asarray(frames[1]['image_data_float'], dtype='<f4')
    if values.size != model['depth']['width']*model['depth']['height']:
        raise ValueError('DepthPlanar float32 载荷长度错误')
    # 平面深度是光轴距离（米）；20m 是课程有效量程，不修改 UE 原始渲染距离。
    values = values.copy()
    values[np.isnan(values) | (values <= model['near_m'])] = np.nan
    values[values >= model['far_m']] = np.inf
    valid = np.isfinite(values)
    stats = dict(valid_fraction=float(valid.mean()),
                 valid_min_m=float(values[valid].min()) if valid.any() else None,
                 valid_max_m=float(values[valid].max()) if valid.any() else None)
    return image.tobytes(), values.tobytes(), stamps, stats


def camera_info(intrinsics):
    fx, fy = intrinsics['fx'], intrinsics['fy']
    cx, cy = intrinsics['cx'], intrinsics['cy']
    if not all(math.isfinite(v) and v > 0 for v in (fx, fy, cx, cy)):
        raise ValueError('相机内参无效')
    return dict(k=[fx, 0., cx, 0., fy, cy, 0., 0., 1.],
                p=[fx, 0., cx, 0., 0., fy, cy, 0., 0., 0., 1., 0.])
