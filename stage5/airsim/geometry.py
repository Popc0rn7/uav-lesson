"""AirSim 相机外参与三种车队相对目标点；控制坐标统一 PX4 NED。"""
import numpy as np


def follow_goal(point, heading, stage):
    point, heading = np.asarray(point, dtype=float), np.asarray(heading, dtype=float)
    if not np.isfinite(point).all() or not np.isfinite(heading).all() or np.linalg.norm(heading) < .1:
        raise ValueError('跟随目标或方向无效')
    direction = heading / np.linalg.norm(heading)
    mode = stage.get('following_mode', 'rear_above')
    goal = point.copy()
    if mode == 'rear_above':
        goal[:2] -= stage['horizontal_distance_m'] * direction
    elif mode == 'left_alongside':
        goal[:2] += stage['horizontal_distance_m'] * np.array([direction[1], -direction[0]])
    elif mode != 'directly_overhead':
        raise ValueError('未知跟随方式')
    goal[2] -= stage['above_m']
    return goal


def pose_at_capture(positions, attitudes, stamp, max_skew=.05):
    """只从飞控估计历史选采集时刻附近的姿态；不使用场景车辆真值。"""
    if not positions or not attitudes:
        return None
    pos = min(positions, key=lambda row: abs(row[0]-stamp))
    att = min(attitudes, key=lambda row: abs(row[0]-stamp))
    if max(abs(pos[0]-stamp), abs(att[0]-stamp)) > max_skew:
        return None
    return dict(p=list(pos[1]), q=list(att[1]), position_sim_s=pos[0], attitude_sim_s=att[0],
                max_skew_s=max(abs(pos[0]-stamp), abs(att[0]-stamp)))


def camera_point_ned(point_flu, pose, model):
    from follow import rotation
    camera_frd = np.asarray(point_flu) * [1, -1, -1]
    body_frd = np.asarray(model['rotation_camera_frd_to_body_frd']) @ camera_frd + model['position_body_frd_m']
    return np.asarray(pose['p']) + rotation(pose['q']) @ body_frd
