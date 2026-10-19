"""Stage 5 AirSim 接入契约；RGBD 几何复用 Stage 2 唯一模型。"""
import json
import math
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    value = json.loads(Path(path).read_text())
    backend = value.get('scene_backend', 'editor')
    if backend not in ('editor', 'packaged'):
        raise ValueError('scene_backend必须为editor或packaged')
    if backend == 'packaged':
        env = {**{k:v for k,v in dotenv_values(ROOT/'.env').items() if v is not None}, **os.environ}
        env_name = value.get('binary_env', 'AIRSIM_MOUNTAINS')
        override = env.get('STAGE5_PACKAGE_DIR')
        executable = env.get(env_name)
        if override:
            package = Path(override).expanduser()
            if not package.is_absolute(): package = ROOT/package
        elif executable:
            binary = Path(executable).expanduser()
            if not binary.is_absolute(): binary = ROOT/binary
            binary = binary.resolve()
            if binary.parent.name != 'Linux' or binary.parent.parent.name != 'Binaries' or binary.suffix == '.sh':
                raise ValueError(f'{env_name}必须指向包内<项目>/Binaries/Linux/Shipping ELF，不是sh或包目录')
            value['project_name'] = binary.parents[2].name
            value['scene_binary'] = str(binary)
            package = binary.parents[3]
        elif value.get('package_dir'):
            package = Path(value['package_dir']).expanduser()
            if not package.is_absolute(): package = Path(path).resolve().parent/package
        else:
            raise ValueError(f'请在仓库根.env设置{env_name}=Shipping可执行文件完整路径')
        package = package.resolve()
        value['package_dir'] = str(package)
        project = value.get('project_name', 'demo')
        value['editor_settings'] = str(package/project/'Config/AirSim/settings.json')
        if not isinstance(value.get('scene_args', []), list) or any(not isinstance(v, str) for v in value.get('scene_args', [])):
            raise ValueError('scene_args必须是字符串列表')
    if value['rpc_host'] != '127.0.0.1':
        raise ValueError('当前仅支持宿主机场景与host网络Docker')
    for key in ('rpc_port', 'raw_port'):
        if type(value[key]) is not int or not 1024 <= value[key] <= 65535:
            raise ValueError(f'无效端口：{key}')
    if value['rpc_port'] == value['raw_port']:
        raise ValueError('RPC与原始图像端口必须不同')
    for key in ('px4_container', 'ros_container'):
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]+', value[key]):
            raise ValueError(f'无效容器名：{key}')
    if value['px4_container'] == value['ros_container']:
        raise ValueError('PX4 与 ROS 容器名必须不同')
    if not value['vehicle_name'] or not 0 < value['camera_hz'] <= 30:
        raise ValueError('车辆名或相机频率无效')
    if len(value['spawn_ned_m']) != 3 or not all(math.isfinite(v) for v in [*value['spawn_ned_m'], value['spawn_yaw_deg']]):
        raise ValueError('出生点必须为有限 NED 米坐标')
    xyz = value.get('camera_position_body_flu_m')
    if xyz is not None and (len(xyz) != 3 or not all(math.isfinite(v) for v in xyz)):
        raise ValueError('相机外参必须为有限机体 FLU 米坐标')
    return value


def camera_model(config=None):
    from stage5.depth_fusion import calibration
    model = calibration()
    if config is not None and config.get('camera_mount') == 'airsim_default':
        # 使用内置 front_center 的安装位置；采集统一90°FOV，避免沿用Gazebo内参。
        for key in ('rgb', 'depth'):
            model[key]['fx'] = model[key]['fy'] = model[key]['width']/2
        model['position_body_flu_m'] = None
        model['orientation_body_flu_rpy_rad'] = None
        model['mount_source'] = 'AirSim built-in front_center; extrinsics pending verification'
        return model
    tree = ET.parse(ROOT/'stage2/models/x500_experiment/model.sdf')
    link = tree.find('.//link[@name="camera_link"]')
    sensor = link.find('sensor[@name="orbbec_rgb"]')
    link_pose = list(map(float, link.findtext('pose').split()))
    sensor_pose = list(map(float, sensor.findtext('pose').split()))
    if any(link_pose[3:]+sensor_pose[3:]):
        raise ValueError('当前 AirSim 接入仅支持 Stage 2 水平前向相机')
    model['position_body_flu_m'] = [a+b for a, b in zip(link_pose[:3], sensor_pose[:3])]
    if config is not None and 'camera_position_body_flu_m' in config:
        model['position_body_flu_m'] = list(config['camera_position_body_flu_m'])
    model['orientation_body_flu_rpy_rad'] = [0, 0, 0]
    return model


def settings(config):
    model = camera_model(config)
    captures = []
    for name, image_type in [('rgb', 0), ('depth', 1)]:
        intrinsics = model[name]
        captures.append(dict(ImageType=image_type, Width=intrinsics['width'], Height=intrinsics['height'],
                             FOV_Degrees=math.degrees(2*math.atan(intrinsics['width']/(2*intrinsics['fx']))),
                             MotionBlurAmount=0))
    # 内参复用 Stage 2；AirSim 机体外形不同，允许配置显式安装位置，FLU→FRD。
    camera = dict(CaptureSettings=captures)
    if model['position_body_flu_m'] is not None:
        x, y, z = model['position_body_flu_m']
        camera.update(X=x, Y=-y, Z=-z, Pitch=0, Roll=0, Yaw=0)
    vehicle = dict(VehicleType='PX4Multirotor', AutoCreate=True, UseSerial=False, UseTcp=True,
                   LockStep=True, VehicleSysID=6, LocalHostIp='127.0.0.1', ControlIp='127.0.0.1',
                   TcpPort=4565, ControlPortLocal=14546, ControlPortRemote=14586,
                   X=config['spawn_ned_m'][0], Y=config['spawn_ned_m'][1], Z=config['spawn_ned_m'][2],
                   Yaw=config['spawn_yaw_deg'],
                   Parameters={'SENS_GPS0_DELAY': 200, 'MC_REF_FF': 1},
                   Sensors={'gps': dict(SensorType=3, Enabled=True, UpdateLatency=.2),
                            'Barometer': dict(SensorType=1, Enabled=True, PressureFactorSigma=.0001825)})
    result = dict(SettingsVersion=1.2, SimMode='Multirotor', ClockType='SteppableClock', ClockSpeed=1,
                  RpcEnabled=True, ApiServerPort=config['rpc_port'], LocalHostIp=config['rpc_host'],
                  Vehicles={config['vehicle_name']: vehicle})
    if model['position_body_flu_m'] is None:
        # 本插件对 Vehicles.*.Cameras 无条件 SpawnActor；省略位置会以NaN创建并崩溃。
        # CameraDefaults 只配置已存在的相机，不进入该创建分支。
        result['CameraDefaults'] = dict(CaptureSettings=captures)
    else:
        vehicle['Cameras'] = {'front_center': camera}
    return result
