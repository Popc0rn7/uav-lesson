"""AirSim 单机任务配置；路线为出生点相对 ENU，安装外参为机体 FRD。"""
import json
import math
from pathlib import Path


def load_task(path):
    task = json.loads(Path(path).read_text())
    task.setdefault('goal_mode', 'carrot')
    if task['goal_mode'] not in ('carrot', 'direct'):
        raise ValueError('goal_mode 必须为 carrot 或 direct')
    def vector(value, size):
        return isinstance(value, list) and len(value) == size and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in value)
    if not vector(task['spawn_ned_m'], 3) or not math.isfinite(task['spawn_yaw_deg']):
        raise ValueError('出生位置/朝向无效')
    if not vector(task['bounds_enu_min_m'], 3) or not vector(task['bounds_enu_max_m'], 3):
        raise ValueError('任务边界无效')
    if any(a >= b for a, b in zip(task['bounds_enu_min_m'], task['bounds_enu_max_m'])):
        raise ValueError('任务边界必须 min < max')
    if not task['waypoints_enu_m'] or not all(vector(p, 3) and inside(task, p) for p in task['waypoints_enu_m']):
        raise ValueError('航点必须是任务边界内的 ENU XYZ')
    for key in ('speed_m_s', 'max_acc_m_s2', 'takeoff_height_m', 'carrot_distance_m',
                'carrot_refresh_m', 'waypoint_tolerance_m', 'goal_tolerance_m',
                'leg_timeout_s', 'mission_timeout_s'):
        if not isinstance(task[key], (int, float)) or isinstance(task[key], bool) or not math.isfinite(task[key]) or task[key] <= 0:
            raise ValueError(key + ' 必须为正数')
    if task['carrot_refresh_m'] >= task['carrot_distance_m']:
        raise ValueError('carrot 刷新距离必须小于前瞻距离')
    if not 0 < task['speed_m_s'] <= 15 or not 0 < task['max_acc_m_s2'] <= 8:
        raise ValueError('当前任务支持速度 (0, 15] m/s、加速度 (0, 8] m/s²')
    if not .5 <= task['takeoff_height_m'] <= 10 or not math.isfinite(task['hold_after_takeoff_s']) or task['hold_after_takeoff_s'] < 0:
        raise ValueError('起飞高度/悬停时间无效')
    if not inside(task, [0, 0, task['takeoff_height_m']]):
        raise ValueError('起飞目标必须在任务边界内')
    ground, ceil = task['virtual_ground_height_m'], task['virtual_ceil_height_m']
    if not all(math.isfinite(x) for x in (ground,ceil)) or not ground < 0 < task['takeoff_height_m'] < ceil:
        raise ValueError('虚拟地面/天花板必须覆盖起飞空间')
    if task['finish'] not in ('land', 'hover'):
        raise ValueError('finish 必须为 land 或 hover')
    if task['waypoint_mode'] not in ('stop', 'pass'):
        raise ValueError('waypoint_mode 必须为 stop 或 pass')
    lidar = task['lidar']
    if not vector(lidar['position_frd_m'], 3) or not vector(lidar['rotation_rpy_deg'], 3):
        raise ValueError('雷达外参无效')
    if not 0 < lidar['range_min_m'] < lidar['range_max_m'] <= lidar['settings']['Range']:
        raise ValueError('雷达过滤范围无效')
    if not .01 <= lidar['voxel_m'] <= .2:
        raise ValueError('雷达降采样应为 0.01～0.2 m')
    if lidar['settings'].get('DataFrame') != 'SensorLocalFrame':
        raise ValueError('点云必须为 SensorLocalFrame')
    return task


def inside(task, point):
    return all(a <= x <= b for a, x, b in zip(task['bounds_enu_min_m'], point, task['bounds_enu_max_m']))


def apply_settings(settings, task):
    if task.get('camera_defaults'):
        settings['CameraDefaults'] = task['camera_defaults']
    vehicle = settings['Vehicles']['PX4']
    vehicle.update(dict(zip(('X', 'Y', 'Z'), task['spawn_ned_m'])))
    vehicle.update(Yaw=task['spawn_yaw_deg'], Roll=0, Pitch=0)
    lidar = dict(task['lidar']['settings'])
    lidar.update(dict(zip(('X', 'Y', 'Z'), task['lidar']['position_frd_m'])))
    lidar.update(dict(zip(('Roll', 'Pitch', 'Yaw'), task['lidar']['rotation_rpy_deg'])))
    vehicle.setdefault('Sensors', {})[task['lidar']['name']] = lidar
    return settings
