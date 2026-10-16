"""无 ROS 依赖的采样时刻配准；不使用 AirSim 场景真值。"""
import numpy as np
from scipy.spatial.transform import Rotation, Slerp


def interpolate(poses, stamp, max_gap=.05):
    for left, right in zip(poses, list(poses)[1:]):
        if left[0] <= stamp <= right[0]:
            gap = right[0] - left[0]
            if gap > max_gap or gap <= 0:
                return None
            ratio = (stamp - left[0]) / gap
            p = np.asarray(left[1]) * (1-ratio) + np.asarray(right[1]) * ratio
            r = Slerp([0, 1], Rotation.from_quat([left[2], right[2]]))([ratio]).as_matrix()[0]
            return p, r
    return None


def register(points, pose, lidar):
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    ranges = np.linalg.norm(points, axis=1)
    points = points[np.isfinite(points).all(axis=1) &
                    (ranges >= lidar['range_min_m']) & (ranges < lidar['range_max_m'])]
    if not len(points):
        return np.empty((0, 3), dtype='<f4')
    # AirSim sensor local / body FRD → ROS body FLU → world ENU.
    extrinsic = Rotation.from_euler('xyz', lidar['rotation_rpy_deg'], degrees=True).as_matrix()
    body_frd = points @ extrinsic.T + lidar['position_frd_m']
    body_flu = body_frd * [1, -1, -1]
    position, orientation = pose
    world = body_flu @ orientation.T + position
    _, indices = np.unique(np.floor(world / lidar['voxel_m']).astype(np.int64), axis=0, return_index=True)
    return np.asarray(world[indices], dtype='<f4')
