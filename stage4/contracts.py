"""Pure Python task, coordinate and action contracts (no ROS/model imports)."""
import math

PREFIX = '/stage4/uav1'
LIMITS = {'fwd': (0., 5.), 'down': (-5., 5.), 'yaw': (-1.1, 1.1)}
DEFAULTS = dict(speed_m_s=8., acceleration_m_s2=4., yaw_rate_rad_s=.5,
                vertical_speed_up_m_s=2., vertical_speed_down_m_s=1., vertical_acceleration_m_s2=3.,
                position_tolerance_m=.6, yaw_tolerance_rad=math.radians(5),
                stable_s=.15, takeoff_timeout_s=45., action_timeout_s=30.,
                mission_timeout_s=1800., max_steps=200, observation_timeout_s=5.,
                max_pair_skew_s=.1, camera_hz=5., success_distance_m=20.)


def vector(value, length):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f'Expected {length} numbers')
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        raise ValueError('Expected finite numbers')
    return list(map(float, value))


def validate_action(action):
    if not isinstance(action, dict) or set(action) != set(LIMITS):
        raise ValueError('action requires fwd/down/yaw')
    result = {}
    for key, (lower, upper) in LIMITS.items():
        value = action[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f'Invalid action {key}: {value!r}')
        result[key] = float(value)
    return result


def validate_task(task):
    for key in ('start_ned_m', 'spawn_ned_m', 'target_ned_m'):
        task[key] = vector(task[key], 3)
    task['start_quaternion_xyzw'] = vector(task['start_quaternion_xyzw'], 4)
    if abs(math.dist(task['start_quaternion_xyzw'], [0]*4)-1) > .01:
        raise ValueError('Start quaternion must be normalized')
    if not isinstance(task['object_description'], str) or not task['object_description'].strip():
        raise ValueError('Empty object description')
    config = DEFAULTS | task.get('control', {})
    if set(config) != set(DEFAULTS):
        raise ValueError('Unknown control setting')
    for key, value in config.items():
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'Invalid positive control setting: {key}')
    if type(config['max_steps']) is not int:
        raise ValueError('max_steps must be an integer')
    bounds=dict(speed_m_s=8.,acceleration_m_s2=8.,yaw_rate_rad_s=.5,
                vertical_speed_up_m_s=2.,vertical_speed_down_m_s=1.,vertical_acceleration_m_s2=3.)
    for key,maximum in bounds.items():
        if config[key]>maximum: raise ValueError(f'{key} must be ≤{maximum}')
    height = task['spawn_ned_m'][2] - task['start_ned_m'][2]
    if not .5 <= height <= 10:
        raise ValueError('Initial observation must be 0.5–10 m above configured ground spawn')
    task['control'] = config
    return task


def enu(ned):
    return [float(ned[1]), float(ned[0]), -float(ned[2])]


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def yaw_xyzw(q):
    x, y, z, w = q
    return math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))


def quaternion_product(a, b):
    x,y,z,w = a; X,Y,Z,W = b
    return [w*X+x*W+y*Z-z*Y, w*Y-x*Z+y*W+z*X,
            w*Z+x*Y-y*X+z*W, w*W-x*X-y*Y-z*Z]


def enu_flu_quaternion(q):
    # world NED → ENU, body FRD → FLU; input/output xyzw.
    s = math.sqrt(.5)
    return quaternion_product(quaternion_product([s,s,0,0], q), [1,0,0,0])


def prompt(position_ned, quaternion_xyzw, target_ned, description):
    # Full inverse quaternion rotation, matching the old scipy implementation.
    x,y,z,w = quaternion_xyzw
    delta = [b-a for a,b in zip(position_ned, target_ned)]
    body = quaternion_product(quaternion_product([-x,-y,-z,w], [*delta,0]), [x,y,z,w])
    direction = ''
    if math.hypot(*delta[:2]) >= .01:
        angle = math.degrees(math.atan2(body[1], body[0]))
        if -15 <= angle <= 15: direction = 'straight ahead '
        elif 15 < angle <= 60: direction = 'forward-right '
        elif 60 < angle <= 120: direction = 'to your right '
        elif 120 < angle <= 180: direction = 'to your right rear '
        elif -60 <= angle < -15: direction = 'forward-left '
        elif -120 <= angle < -60: direction = 'to your left '
        else: direction = 'to your left rear '
    return f'<image>\nFly {direction}and find the target. {description}\nAction: '


def action_target(position_ned, yaw, action):
    action = validate_action(action)
    heading = wrap(yaw + action['yaw'])
    forward = action['fwd'] if abs(action['yaw']) < .25 else 0.
    return [position_ned[0]+forward*math.cos(heading),
            position_ned[1]+forward*math.sin(heading), position_ned[2]+action['down']], heading


def atomic_json(path, data):
    import json
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    temporary.replace(path)
