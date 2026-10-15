#!/usr/bin/env python3
"""PC：生成无需外部资源的街区与匀速绕圈目标车。"""
import math
from pathlib import Path
import xml.etree.ElementTree as ET

RADIUS = 24.0
SPEED = 2.0
WORLD = Path(__file__).with_name('street.sdf')


def add(parent, tag, value=None, **attrs):
    node = ET.SubElement(parent, tag, attrs)
    if value is not None:
        node.text = str(value)
    return node


def box(world, name, position, size, color, yaw=0, collision=True):
    model = add(world, 'model', name=name)
    add(model, 'static', 'true')
    add(model, 'pose', f'{position[0]} {position[1]} {position[2]} 0 0 {yaw}')
    link = add(model, 'link', name='body')
    for kind in (('collision', 'visual') if collision else ('visual',)):
        part = add(link, kind, name=kind)
        add(add(add(part, 'geometry'), 'box'), 'size', ' '.join(map(str, size)))
        if kind == 'visual':
            material = add(part, 'material')
            add(material, 'ambient', color)
            add(material, 'diffuse', color)
    return model, link


def generate():
    sdf = ET.Element('sdf', version='1.9')
    world = add(sdf, 'world', name='stage5_street')
    physics = add(world, 'physics', name='physics', type='ignored')
    add(physics, 'max_step_size', .004)
    add(physics, 'real_time_factor', 1)
    add(world, 'gravity', '0 0 -9.81')
    coords = add(world, 'spherical_coordinates')
    for tag, value in dict(surface_model='EARTH_WGS84', world_frame_orientation='ENU',
                           latitude_deg=47.397971, longitude_deg=8.546164, elevation=0).items():
        add(coords, tag, value)
    for filename, name in [('physics', 'Physics'), ('user-commands', 'UserCommands'),
                           ('scene-broadcaster', 'SceneBroadcaster'), ('imu', 'Imu'),
                           ('air-pressure', 'AirPressure'), ('navsat', 'NavSat'),
                           ('magnetometer', 'Magnetometer')]:
        add(world, 'plugin', filename=f'gz-sim-{filename}-system',
            name=f'gz::sim::systems::{name}')
    sensors = add(world, 'plugin', filename='gz-sim-sensors-system',
                  name='gz::sim::systems::Sensors')
    add(sensors, 'render_engine', 'ogre2')
    scene = add(world, 'scene')
    add(scene, 'ambient', '.7 .7 .7 1')
    add(scene, 'background', '.65 .8 .95 1')
    light = add(world, 'light', name='sun', type='directional')
    add(light, 'pose', '0 0 50 0 0 0')
    add(light, 'diffuse', '.9 .9 .9 1')
    add(light, 'direction', '-.4 -.2 -1')
    box(world, 'ground', (0, 0, -.1), (100, 100, .2), '.35 .48 .32 1')
    # 重叠的切向路面形成环路；所有装饰平面都不参与碰撞。
    for i in range(96):
        angle = 2 * math.pi * i / 96
        xy = (RADIUS * math.cos(angle), RADIUS * math.sin(angle))
        box(world, f'road_{i}', (*xy, .012), (2.0, 10, .02), '.16 .18 .2 1',
            angle + math.pi / 2, False)
        if i % 4 == 0:
            box(world, f'lane_mark_{i}', (*xy, .027), (1.2, .15, .008),
                '.95 .85 .3 1', angle + math.pi / 2, False)
    palette = ['.68 .73 .8 1', '.8 .65 .5 1', '.6 .7 .65 1', '.78 .72 .64 1']
    for i, (x, y, height) in enumerate([(-8, -8, 7), (-8, 8, 10),
                                       (8, -8, 5), (8, 8, 8),
                                       (-38, -15, 6), (-38, 15, 9),
                                       (38, -15, 8), (38, 15, 5),
                                       (-15, -38, 7), (15, -38, 6),
                                       (-15, 38, 5), (15, 38, 9)]):
        box(world, f'building_{i}', (x, y, height / 2), (9, 9, height), palette[i % 4])
        box(world, f'roof_{i}', (x, y, height + .1), (9.4, 9.4, .2), '.3 .33 .38 1')
        # 朝向道路的亮色窗带，提供后续视觉任务的背景纹理。
        for z in range(2, height, 2):
            box(world, f'windows_{i}_{z}', (x, y - 4.51, z), (6, .03, .7),
                '.2 .45 .6 1', collision=False)
    car, link = box(world, 'target_car', (RADIUS, 0, .65), (2.4, 1.2, 1),
                    '.95 .08 .04 1', math.pi / 2)
    car.find('static').text = 'false'
    add(link, 'gravity', 'false')
    inertial = add(link, 'inertial')
    add(inertial, 'mass', 10)
    inertia = add(inertial, 'inertia')
    for tag, value in [('ixx', 2.033333), ('iyy', 5.633333), ('izz', 6),
                       ('ixy', 0), ('ixz', 0), ('iyz', 0)]:
        add(inertia, tag, value)
    # 车头标记与车身同属一个 link，车头沿模型 +X。
    front = add(link, 'visual', name='front_marker')
    add(front, 'pose', '1.21 0 0 0 0 0')
    add(add(add(front, 'geometry'), 'box'), 'size', '.03 .9 .6')
    mat = add(front, 'material')
    add(mat, 'ambient', '1 1 .7 1')
    add(mat, 'diffuse', '1 1 .7 1')
    velocity = add(car, 'plugin', filename='gz-sim-velocity-control-system',
                   name='gz::sim::systems::VelocityControl')
    # 等无人机起飞并取到首帧后，由 target-start 开始行驶。
    add(velocity, 'initial_linear', '0 0 0')
    add(velocity, 'initial_angular', '0 0 0')
    add(velocity, 'topic', '/stage5/target/cmd_vel')
    pose = add(car, 'plugin', filename='gz-sim-pose-publisher-system',
               name='gz::sim::systems::PosePublisher')
    add(pose, 'publish_model_pose', 'true')
    add(pose, 'publish_link_pose', 'false')
    add(pose, 'use_pose_vector_msg', 'true')
    add(pose, 'update_frequency', 20)
    ET.indent(sdf)
    ET.ElementTree(sdf).write(WORLD, encoding='utf-8', xml_declaration=True)
    print(WORLD)


if __name__ == '__main__':
    generate()
