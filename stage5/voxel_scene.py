"""单帧相机 FLU 局部体素：深度端点占据，射线前段空闲，其余未知。"""
import math
import struct

MOVES = {'forward_1m': [1, 0, 0], 'forward_left_1m': [1, .75, 0],
         'forward_right_1m': [1, -.75, 0], 'left_1m': [0, 1, 0],
         'right_1m': [0, -1, 0], 'up_1m': [0, 0, 1]}


def key(point, size):
    return tuple(math.floor(v/size) for v in point)


def center(cell, size):
    return tuple((v+.5)*size for v in cell)


def segment_distance(point, start, end):
    delta = [b-a for a, b in zip(start, end)]
    length2 = sum(v*v for v in delta)
    t = max(0, min(1, sum((p-a)*v for p, a, v in zip(point, start, delta))/length2)) if length2 else 0
    return math.dist(point, [a+t*v for a, v in zip(start, delta)])


def check_move(occupied, free, size, delta, radius=.45, body=(-.186, 0, -.025)):
    end = tuple(a+b for a, b in zip(body, delta))
    # 保守计入体素半对角线；忽略起始机体已经占有的空间。
    inflated = radius + math.sqrt(3)*size/2
    bounds = [(math.floor((min(a,b)-inflated)/size), math.ceil((max(a,b)+inflated)/size))
              for a, b in zip(body, end)]
    counts = {'occupied': 0, 'free': 0, 'unknown': 0}
    for x in range(*bounds[0]):
        for y in range(*bounds[1]):
            for z in range(*bounds[2]):
                cell = (x, y, z)
                p = center(cell, size)
                if math.dist(p, body) <= inflated or segment_distance(p, body, end) > inflated:
                    continue
                state = 'occupied' if cell in occupied else 'free' if cell in free else 'unknown'
                counts[state] += 1
    status = 'blocked' if counts['occupied'] else 'unknown' if counts['unknown'] else 'clear'
    return dict(status=status, delta_camera_m=delta, swept_cells=counts,
                free_fraction=counts['free']/sum(counts.values()) if sum(counts.values()) else 0)


def build(meta, data, model, size=.25, stride=8, extent=8, radius=.45):
    d = model['depth']
    if (meta['width'], meta['height'], meta['format']) != (d['width'], d['height'], 'R_FLOAT32'):
        raise ValueError('体素输入与深度标定不符')
    if len(data) != meta['step']*meta['height'] or meta['step'] < 4*d['width']:
        raise ValueError('体素深度载荷长度错误')
    if not all(math.isfinite(v) and v > 0 for v in (size, extent, radius)) or stride < 1:
        raise ValueError('体素参数必须为正数')
    occupied, free = set(), set()
    counts = {'finite_return': 0, 'too_far': 0, 'invalid': 0}

    def inside(p):
        return 0 <= p[0] <= extent and abs(p[1]) <= extent/2 and abs(p[2]) <= extent/2

    for y in range(0, d['height'], stride):
        for x in range(0, d['width'], stride):
            depth = struct.unpack_from('<f', data, y*meta['step']+4*x)[0]
            ray = (1, -(x+.5-d['cx'])/d['fx'], -(y+.5-d['cy'])/d['fy'])
            valid = math.isfinite(depth) and model['near_m'] < depth < model['far_m']
            too_far = depth == math.inf or math.isfinite(depth) and depth >= model['far_m']
            if not valid and not too_far:
                counts['invalid'] += 1
                continue
            counts['finite_return' if valid else 'too_far'] += 1
            if valid:
                point = tuple(depth*v for v in ray)
                if inside(point):
                    occupied.add(key(point, size))
            # 理想 Gazebo +Inf：量程内沿射线没有表面，不代表远端目标身份已确定。
            limit = min(depth-size if valid else model['far_m']-size, extent)
            steps = max(0, math.floor((limit-model['near_m'])/(size/2)))
            for i in range(steps+1):
                distance = model['near_m']+i*size/2
                if distance > limit:
                    break
                point = tuple(distance*v for v in ray)
                if inside(point):
                    free.add(key(point, size))
    free.difference_update(occupied)
    points = [list(center(k, size)) for k in sorted(occupied)]
    body = tuple(model.get('body_center_camera_flu_m', [-.186, 0, -.025]))
    actions = {name: check_move(occupied, free, size, delta, radius, body)
               for name, delta in MOVES.items()}
    return dict(frame='camera_flu', axes='x forward, y left, z up', units='m',
                sim_time=meta['sim_time'], voxel_size_m=size, pixel_stride=stride,
                local_bounds_m=[[0, extent], [-extent/2, extent/2], [-extent/2, extent/2]],
                drone_radius_m=radius, body_center_camera_m=list(body),
                assumptions=['single frame; no world map', 'ideal Gazebo +Inf means no surface before far clip',
                             'initial body envelope assumed clear', 'sparse rays leave unobserved voxels unknown'],
                ray_counts=counts, occupied_count=len(occupied), free_count=len(free),
                nearest_surface_m=min((math.dist(p, body) for p in points), default=None),
                occupied_points_m=points, motion_candidates=actions)


def ply(scene):
    points = scene['occupied_points_m']
    header = ['ply', 'format ascii 1.0', 'comment camera_flu metres',
              f'element vertex {len(points)}', 'property float x', 'property float y', 'property float z', 'end_header']
    return '\n'.join(header + [' '.join(f'{v:.4f}' for v in p) for p in points]) + '\n'
