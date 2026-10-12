#!/usr/bin/env python3
"""ROS Docker：按点云来源生成两个 RViz 配置。"""
import os
from pathlib import Path

for name in ('cloud_points.rviz', 'cloud_voxels.rviz'):
    source = Path(__file__).with_name(name).read_text()
    source = source.replace('stage2_depth', os.environ['CLOUD_FRAME'])
    source = source.replace('/stage2/depth', os.environ['CLOUD_PREFIX'])
    if os.environ['CLOUD_FRAME'] == 'mid360s_sensor':
        source = source.replace('Depth point cloud', 'MID-360S approximation').replace('Depth surface voxels', 'MID-360S surface voxels')
        source = source.replace('Axis: X', 'Axis: Z').replace('Min Value: 0.15', 'Min Value: -5')
        source = source.replace('Distance: 18', 'Distance: 30').replace('X: 6', 'X: 0')
    Path('/tmp', name).write_text(source)
