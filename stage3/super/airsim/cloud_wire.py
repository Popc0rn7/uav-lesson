"""AirSim 原始传感器帧的 ROS 线格式；不包含场景真值或配准位姿。"""
import struct

TOPIC = '/stage3/uav1/lidar_raw'
FRAME = 'airsim_lidar_sensor_frd'


def encode(points):
    if len(points) % 3:
        raise ValueError('AirSim point_cloud 必须为 XYZ 三元组')
    return struct.pack('<' + 'f' * len(points), *points)


def decode(message):
    if (message.header.frame_id != FRAME or message.is_bigendian or
            message.height != 1 or message.point_step != 12 or
            message.row_step != message.width * 12 or len(message.data) != message.row_step or
            [(f.name, f.offset, f.datatype, f.count) for f in message.fields] !=
            [('x', 0, 7, 1), ('y', 4, 7, 1), ('z', 8, 7, 1)]):
        raise ValueError('原始点云格式或传感器帧不匹配')
    return struct.unpack('<' + 'f' * (message.width * 3), bytes(message.data))
