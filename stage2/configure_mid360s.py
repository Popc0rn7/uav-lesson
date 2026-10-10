#!/usr/bin/env python3
"""PC 课前：配置实验 SDF 的 MID-360S 几何近似；重新启动仿真后生效。"""
import argparse
import math
from pathlib import Path
import xml.etree.ElementTree as ET

PRESETS = {'light': (256, 16, 5), 'balanced': (512, 16, 10), 'detail': (512, 32, 10)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preset', choices=PRESETS, default='balanced')
    parser.add_argument('--range', type=float, default=40, dest='far')
    parser.add_argument('--model', type=Path, default=Path(__file__).parent/'models/mid360s/model.sdf')
    parser.add_argument('--output', type=Path, help='写入另一 SDF；不覆盖原模型')
    args = parser.parse_args()
    if not (math.isfinite(args.far) and 1 <= args.far <= 100):
        parser.error('几何截止量程需为 1–100 m，不代表所有材质的实机探测距离')
    tree = ET.parse(args.model, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    sensor = tree.find(".//sensor[@name='mid360s_approx']")
    if sensor is None:
        parser.error('指定 SDF 不含 mid360s_approx')
    h, v, rate = PRESETS[args.preset]
    for key, value in {'ray/scan/horizontal/samples': h,
                       'ray/scan/horizontal/max_angle': math.pi-2*math.pi/h,
                       'ray/scan/vertical/samples': v, 'update_rate': rate,
                       'ray/range/max': args.far}.items():
        node = sensor.find(key)
        if node is None:
            parser.error(f'SDF 配置缺失：{key}')
        node.text = str(value)
    ET.indent(tree, space='  ')
    target = args.output or args.model
    tree.write(target, encoding='utf-8', xml_declaration=True)
    print(f'{target}: {args.preset} {h}×{v} @ {rate} Hz = {h*v*rate} 射线/仿真秒；0.1–{args.far:g} m')
    print(f'当前 Harmonic GPU 雷达实测点步长为 32 B：原始点云约 {h*v*32*rate/1e6:.3f} MB/仿真秒（不含 HTTP/DDS 开销）')
    print('需要停止并重新启动仿真（只读挂载时无需重建镜像）；光学原点和质量/惯量变化后的飞行应重新验收。')


if __name__ == '__main__':
    main()
