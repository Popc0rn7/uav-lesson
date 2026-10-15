"""理想共光心 RGB/D 的框内深度估计；不估计车体中心或世界坐标。"""
import math
from collections import Counter
from pathlib import Path
import statistics
import struct
import xml.etree.ElementTree as ET


def calibration(path=None):
    path = path or Path(__file__).resolve().parents[1] / 'stage2/models/x500_experiment/model.sdf'
    tree = ET.parse(path)
    rgb = tree.find('.//sensor[@name="orbbec_rgb"]')
    depth = tree.find('.//sensor[@name="orbbec_depth"]')
    if rgb is None or depth is None:
        raise ValueError('缺少 RGB/D 标定配置')
    if tuple(map(float, rgb.findtext('pose').split())) != tuple(map(float, depth.findtext('pose').split())):
        raise ValueError('本融合仅支持当前共光心、同朝向的仿真 RGB/D')

    def intrinsics(sensor):
        width = int(sensor.findtext('camera/image/width'))
        height = int(sensor.findtext('camera/image/height'))
        hfov = float(sensor.findtext('camera/horizontal_fov'))
        focal = width / (2 * math.tan(hfov / 2))
        return dict(width=width, height=height, fx=focal, fy=focal,
                    cx=width / 2, cy=height / 2)

    return dict(rgb=intrinsics(rgb), depth=intrinsics(depth),
                near_m=float(depth.findtext('camera/clip/near')),
                far_m=float(depth.findtext('camera/clip/far')),
                depth_convention='optical_axis', frame='camera_flu',
                axes='x forward, y left, z up', units='m')


def project_box(box, response_width, response_height, model):
    r, d = model['rgb'], model['depth']
    x1, y1, x2, y2 = box
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
        raise ValueError('框包含非有限数值')
    if not (0 <= x1 < x2 <= response_width and 0 <= y1 < y2 <= response_height):
        raise ValueError('框超出检测响应坐标范围')
    # 响应坐标先恢复到 RGB 原图，再按同一条光线映射到深度像素。
    def point(x, y):
        rx = x * r['width'] / response_width
        ry = y * r['height'] / response_height
        return ((rx-r['cx'])/r['fx']*d['fx']+d['cx'],
                (ry-r['cy'])/r['fy']*d['fy']+d['cy'])
    return (*point(x1, y1), *point(x2, y2))


def fuse(response, rgb_meta, depth_meta, depth_bytes, model, max_skew=.05,
         response_source='http'):
    r, d = model['rgb'], model['depth']
    for name, meta, expected in [('RGB', rgb_meta, r), ('depth', depth_meta, d)]:
        if (meta['width'], meta['height']) != (expected['width'], expected['height']):
            raise ValueError(f'{name} 尺寸与模型标定不符')
    if depth_meta['format'] != 'R_FLOAT32' or depth_meta['step'] < d['width']*4:
        raise ValueError('深度必须为小端 float32 原始帧')
    if len(depth_bytes) != depth_meta['step'] * d['height']:
        raise ValueError('深度帧长度错误')
    skew = abs(rgb_meta['sim_time'] - depth_meta['sim_time'])
    result = dict(frame=model['frame'], axes=model['axes'], units='m',
                  rgb_sim_time=rgb_meta['sim_time'], depth_sim_time=depth_meta['sim_time'],
                  frame_skew_s=skew, response_source=response_source,
                  usable_for_control=response_source == 'http' and skew <= max_skew,
                  targets=[])
    for item in response['detections']:
        target = dict(label=item['label'], score=item['score'], box_xyxy=item['box_xyxy'],
                      status='unsynchronized', position_m=None, range_m=None)
        result['targets'].append(target)
        if skew > max_skew:
            continue
        mapped = project_box(item['box_xyxy'], response['width'], response['height'], model)
        x1, y1, x2, y2 = mapped
        # 整个框保留近处遮挡与远处表面的证据，不只看中心的中位数。
        histogram = Counter()
        far_pixels = invalid_pixels = 0
        bx1, bx2 = max(0, math.floor(x1)), min(d['width'], math.ceil(x2))
        by1, by2 = max(0, math.floor(y1)), min(d['height'], math.ceil(y2))
        for y in range(by1, by2):
            for x in range(bx1, bx2):
                value = struct.unpack_from('<f', depth_bytes, y*depth_meta['step']+4*x)[0]
                if math.isfinite(value) and model['near_m'] < value < model['far_m']:
                    histogram[math.floor(value/.5)] += 1
                elif value == math.inf or math.isfinite(value) and value >= model['far_m']:
                    far_pixels += 1
                else:
                    invalid_pixels += 1
        box_total = sum(histogram.values()) + far_pixels + invalid_pixels
        clusters = []
        previous = None
        for bin_id, count in sorted(histogram.items()):
            if previous is None or bin_id > previous+1:
                clusters.append(dict(min_m=bin_id*.5, max_m=(bin_id+1)*.5, pixels=count))
            else:
                clusters[-1]['max_m'] = (bin_id+1)*.5
                clusters[-1]['pixels'] += count
            previous = bin_id
        for cluster in clusters:
            cluster['support_fraction'] = cluster['pixels']/box_total
        significant = [c for c in clusters if c['support_fraction'] >= .1 and c['pixels'] >= 20]
        evidence = dict(too_far_fraction=far_pixels/box_total if box_total else 0,
                        invalid_fraction=invalid_pixels/box_total if box_total else 0,
                        finite_fraction=sum(histogram.values())/box_total if box_total else 0,
                        distance_clusters=sorted(clusters, key=lambda c: -c['pixels'])[:6],
                        bin_size_m=.5, depth_limit_m=model['far_m'])
        target['depth_evidence'] = evidence
        if not histogram and evidence['too_far_fraction'] >= .9:
            target.update(status='too_far', distance_lower_bound_m=model['far_m'])
            continue
        if evidence['too_far_fraction'] >= .9:
            target.update(status='mostly_too_far', interpretation='most pixels beyond range; finite foreground surfaces retained; target distance unresolved')
            continue
        if len(significant) >= 2 or evidence['too_far_fraction'] >= .2 and significant:
            target.update(status='mixed_depth', interpretation='multiple visible surfaces or near occlusion; target distance unresolved')
            continue
        # 只取框中心 50% 区域，减少地面/背景污染；它仍然不是分割掩膜。
        cx, cy = (x1+x2)/2, (y1+y2)/2
        rx, ry = (x2-x1)/4, (y2-y1)/4
        left, right = max(0, math.floor(cx-rx)), min(d['width'], math.ceil(cx+rx))
        top, bottom = max(0, math.floor(cy-ry)), min(d['height'], math.ceil(cy+ry))
        total = max(0, right-left)*max(0, bottom-top)
        values = []
        for y in range(top, bottom):
            for x in range(left, right):
                value = struct.unpack_from('<f', depth_bytes, y*depth_meta['step']+4*x)[0]
                if math.isfinite(value) and model['near_m'] < value < model['far_m']:
                    values.append(value)
        target.update(depth_box_xyxy=list(mapped), depth_roi_xyxy=[left, top, right, bottom],
                      valid_pixels=len(values), valid_fraction=len(values)/total if total else 0)
        if len(values) < 20 or len(values) < total * .25:
            target['status'] = 'insufficient_depth'
            continue
        forward = statistics.median(values)
        mad = statistics.median(abs(v-forward) for v in values)
        target.update(depth_median_m=forward, depth_mad_m=mad)
        if mad > max(.3, .1*forward):
            target['status'] = 'mixed_depth'
            continue
        left_m = -(cx-d['cx'])/d['fx']*forward
        up_m = -(cy-d['cy'])/d['fy']*forward
        target.update(status='estimated_surface', position_m=[forward, left_m, up_m],
                      range_m=math.sqrt(forward**2+left_m**2+up_m**2),
                      bearing_right_deg=math.degrees(math.atan2(-left_m, forward)))
    result['usable_for_control'] = result['usable_for_control'] and any(
        target['status'] == 'estimated_surface' for target in result['targets'])
    return result
