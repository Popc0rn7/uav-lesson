#!/usr/bin/env python3
"""PC：生成带实体碰撞和接触传感器的 Gazebo corridor，以及 SUPER 雷达模型。"""
import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as E

ROOT = Path(__file__).resolve().parent


def child(parent, tag, text=None, **attrs):
    result = E.SubElement(parent, tag, attrs)
    if text is not None:
        result.text = str(text)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--temporal-scan',action='store_true')
    parser.add_argument('--wall-landmarks',action='store_true')
    parser.add_argument('--lidar-mount-z',type=float,default=.30)
    args=parser.parse_args()
    if not .10<=args.lidar_mount_z<=.60:parser.error('雷达安装高度须在 0.10～0.60 m')
    layout = json.loads((ROOT / 'corridor_layout.json').read_text())
    sdf = E.Element('sdf', version='1.9')
    world = child(sdf, 'world', name='corridor')
    physics = child(world, 'physics', type='ode')
    child(physics, 'max_step_size', .004)
    child(physics, 'real_time_factor', 1)
    child(world, 'gravity', '0 0 -9.81')
    child(world, 'magnetic_field', '6e-6 2.3e-5 -4.2e-5')
    child(world, 'atmosphere', type='adiabatic')
    scene = child(world, 'scene')
    child(scene, 'ambient', '.6 .6 .6 1')
    child(scene, 'background', '.65 .75 .85 1')
    child(scene, 'shadows', 'false')
    coords = child(world, 'spherical_coordinates')
    for tag, value in dict(surface_model='EARTH_WGS84', world_frame_orientation='ENU',
                           latitude_deg=47.397971, longitude_deg=8.546164, elevation=0).items():
        child(coords, tag, value)
    for name in ('Physics', 'UserCommands', 'SceneBroadcaster', 'Imu', 'AirPressure', 'NavSat', 'Magnetometer', 'Contact', 'Sensors'):
        filename = {'SceneBroadcaster':'scene-broadcaster', 'UserCommands':'user-commands', 'AirPressure':'air-pressure'}.get(name, name.lower())
        p = child(world, 'plugin', filename=f'gz-sim-{filename}-system', name=f'gz::sim::systems::{name}')
        if name == 'Sensors':
            child(p, 'render_engine', 'ogre2')
    light = child(world, 'light', type='directional', name='sun')
    child(light, 'pose', '0 0 500 0 0 0')
    child(light, 'direction', '-.3 .2 -1')
    child(light, 'diffuse', '.9 .9 .9 1')
    child(light, 'cast_shadows', 'false')

    def model(name, pose, shape, color, contact=True):
        m = child(world, 'model', name=name)
        child(m, 'static', 'true')
        child(m, 'pose', ' '.join(map(str, pose)) + ' 0 0 0')
        link = child(m, 'link', name='link')
        for kind in ('collision', 'visual'):
            part = child(link, kind, name=kind)
            geometry = child(part, 'geometry')
            obj = child(geometry, shape[0])
            for tag, value in shape[1].items():
                child(obj, tag, value)
            if kind == 'visual':
                material = child(part, 'material')
                child(material, 'ambient', color)
                child(material, 'diffuse', color)
        if contact:
            sensor = child(link, 'sensor', type='contact', name='contacts')
            child(sensor, 'always_on', 'true')
            child(sensor, 'update_rate', 100)
            child(sensor, 'topic', f'/stage3/contacts/{name}')
            child(child(sensor, 'contact'), 'collision', 'collision')

    model('ground', [0,50,-.1], ('box', {'size':'40 140 .2'}), '.32 .36 .3 1', False)
    for x, name in ((-3.1,'wall_left'), (3.1,'wall_right')):
        model(name, [x,50,2], ('box', {'size':'.2 100 4'}), '.7 .72 .76 1')
    for i, (x,y) in enumerate(layout['poles']):
        model(f'pole_{i}', [x,y,1.25], ('cylinder', {'radius':.1,'length':2.5}), '.9 .35 .1 1')
    # Same centres and envelope; closed cylinders approximate the original irregular PCD shrubs.
    for i, (x,y) in enumerate(layout['shrubs']):
        model(f'shrub_{i}', [x,y,.175], ('cylinder', {'radius':.5,'length':.35}), '.1 .55 .18 1')
    for y in (0,100):
        model(f'marker_{y}', [0,y,.012], ('box', {'size':'5 .12 .024'}), '.1 .5 1 1', False)
    if args.wall_landmarks:
        landmarks=json.loads((ROOT/'lio_landmarks.json').read_text())
        for i,center in enumerate(landmarks['centers']):
            model(f'lio_landmark_{i}',center,('box',{'size':' '.join(map(str,landmarks['size']))}),'.15 .45 .7 1')
    E.indent(sdf)
    worlds = ROOT / 'worlds'
    worlds.mkdir(exist_ok=True)
    E.ElementTree(sdf).write(worlds / 'corridor.sdf', encoding='utf-8', xml_declaration=True)

    tree = E.parse(ROOT.parent / 'stage2/models/mid360s/model.sdf')
    ray = tree.find('.//ray')
    values = {'scan/horizontal/samples':1200, 'scan/horizontal/min_angle':-math.pi,
              'scan/horizontal/max_angle':math.pi-math.radians(.3),
              'scan/vertical/samples':594, 'scan/vertical/min_angle':math.radians(-89),
              'scan/vertical/max_angle':math.radians(89), 'range/max':70,
              'noise/stddev':0}
    for path,value in values.items():
        ray.find(path).text=str(value)
    target = ROOT / 'models/super360'
    target.mkdir(parents=True,exist_ok=True)
    tree.write(target/'model.sdf',encoding='utf-8',xml_declaration=True)
    (target/'model.config').write_text('<model><name>SUPER GENERAL_360 on MID360 mount</name><version>1</version><sdf version="1.9">model.sdf</sdf></model>\n')
    # MID-360 FoV and angular raster backing the 200k samples/s MID_360 waveform.
    # Snapshot ray hits do not reproduce hardware firing time or reflectivity.
    mid=E.parse(ROOT.parent/'stage2/models/mid360s/model.sdf')
    ray=mid.find('.//ray')
    for path,value in {'scan/horizontal/samples':900,
                       'scan/horizontal/max_angle':math.pi-2*math.pi/900,
                       'scan/vertical/samples':148,'range/max':70}.items():
        ray.find(path).text=str(value)
    mid.find('.//sensor/update_rate').text='60' if args.temporal_scan else '30'
    if args.temporal_scan:
        ray.find('scan/horizontal/samples').text='1800'
        ray.find('scan/horizontal/max_angle').text=str(math.pi-2*math.pi/1800)
        ray.find('scan/vertical/samples').text='64'
    target=ROOT/'models/mid360'
    target.mkdir(parents=True,exist_ok=True)
    mid.write(target/'model.sdf',encoding='utf-8',xml_declaration=True)
    (target/'model.config').write_text('<model><name>MID-360 FoV regular GPU approximation</name><version>1</version><sdf version="1.9">model.sdf</sdf></model>\n')
    # Independent Stage 3 copy; retain Stage 2 model and physical occlusion.
    vehicle=E.parse(ROOT.parent/'stage2/models/x500_experiment/model.sdf')
    if args.temporal_scan:
        # SUPER consumes LiDAR/IMU, not these course extension cameras.
        # Retain geometry and low-rate images; Stage 2 remains at 30 Hz.
        for sensor in vehicle.findall('.//sensor'):
            if sensor.get('name','').startswith('orbbec_'):sensor.find('update_rate').text='5'
    vehicle.find(".//include[uri='model://mid360s']/pose").text=f'0 0 {args.lidar_mount_z} 0 0 0'
    if args.lidar_mount_z>.10:
        model=vehicle.getroot().find('model')
        mast=child(model,'link',name='lidar_mast')
        length=args.lidar_mount_z-.05
        child(mast,'pose',f'0 0 {.05+length/2} 0 0 0',relative_to='base_link')
        inertia=child(mast,'inertial');child(inertia,'mass',.03)
        tensor=child(inertia,'inertia')
        for axis in ('ixx','iyy','izz'):child(tensor,axis,.0001)
        for kind in ('visual','collision'):
            shape=child(child(child(mast,kind,name=f'mast_{kind}'),'geometry'),'cylinder')
            child(shape,'radius',.01);child(shape,'length',length)
        joint=child(model,'joint',name='LidarMastJoint',type='fixed')
        child(joint,'parent','base_link');child(joint,'child','lidar_mast')
    model=vehicle.getroot().find('model')
    link=child(model,'link',name='super_fcu_imu_link')
    child(link,'pose','0 0 0 0 0 0',relative_to='base_link')
    inertial=child(link,'inertial');child(inertial,'mass',.000001)
    tensor=child(inertial,'inertia')
    for axis in ('ixx','iyy','izz'):child(tensor,axis,1e-9)
    imu=child(link,'sensor',name='super_fcu_imu',type='imu')
    child(imu,'gz_frame_id','base_link');child(imu,'always_on','true');child(imu,'update_rate',200)
    settings=child(imu,'imu')
    for group,stddev in (('angular_velocity',.0008726646),('linear_acceleration',.00637)):
        fields=child(settings,group)
        for axis in ('x','y','z'):
            noise=child(child(fields,axis),'noise',type='gaussian')
            child(noise,'mean',0);child(noise,'stddev',stddev)
    joint=child(model,'joint',name='SuperFcuImuJoint',type='fixed')
    child(joint,'parent','base_link');child(joint,'child','super_fcu_imu_link')
    target=ROOT/'models/x500_super'
    target.mkdir(parents=True,exist_ok=True)
    vehicle.write(target/'model.sdf',encoding='utf-8',xml_declaration=True)
    (target/'model.config').write_text('<model><name>Stage 3 X500 lidar mount</name><version>1</version><sdf version="1.9">model.sdf</sdf></model>\n')
    print(f'Generated corridor, MID-360 FoV and GENERAL_360 profiles, lidar mount z={args.lidar_mount_z} m')


if __name__ == '__main__':
    main()
