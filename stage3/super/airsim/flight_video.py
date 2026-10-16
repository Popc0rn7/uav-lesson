#!/usr/bin/env python3
"""PC：独立第三人称相机抓帧与离线编码；不发布飞行控制或修改飞机位姿。"""
import argparse
import json
import math
from pathlib import Path
import statistics
import subprocess
import time
from rpc_client import rpc

CAMERA = 'uav_review'


def configure(source, output):
    if output.exists():
        raise FileExistsError(output)
    settings = json.loads(source.read_text())
    settings.setdefault('ExternalCameras', {})[CAMERA] = dict(
        X=0, Y=0, Z=-5, Pitch=-25, Roll=0, Yaw=0,
        CaptureSettings=[dict(ImageType=0, Width=640, Height=360, FOV_Degrees=80)])
    output.write_text(json.dumps(settings, indent=2)+'\n')


def camera_pose(local_position, spawn):
    # Vehicle API uses vehicle-local NED; an external camera uses global NED.
    offset = [-5., -3., -6.]
    position = {key: float(local_position[key])+spawn[i]+offset[i]
                for i, key in enumerate(('x_val', 'y_val', 'z_val'))}
    pitch = -math.atan2(6, math.hypot(5, 3))
    yaw = math.atan2(3, 5)
    cp, sp, cy, sy = math.cos(pitch/2), math.sin(pitch/2), math.cos(yaw/2), math.sin(yaw/2)
    return dict(position=position, orientation=dict(w_val=cp*cy, x_val=-sp*sy,
                                                    y_val=sp*cy, z_val=cp*sy))


def record(state_directory, output, seconds, fps):
    state_file = state_directory/'state.json'
    state = json.loads(state_file.read_text())
    if state['phase'] != 'ready':
        raise RuntimeError('需要已就绪的本入口实例；先 up，不由录像器启动或控制飞机')
    run = Path(state['run_dir'])
    settings = json.loads((run/'settings.json').read_text())
    if CAMERA not in settings.get('ExternalCameras', {}):
        raise RuntimeError('本次 settings 没有独立录像相机；先 configure，再 down/up')
    task = json.loads((run/'task.json').read_text())
    output.mkdir(parents=True, exist_ok=False)
    frames = output/'frames'
    frames.mkdir()
    rows, costs = [], []
    start = due = time.monotonic()
    request = dict(camera_name=CAMERA, image_type=0, pixels_as_float=False, compress=True)
    errors = 0
    with (output/'frames.jsonl').open('w', buffering=1) as stream:
        try:
            while time.monotonic()-start < seconds and not (output/'stop').exists():
                current = json.loads(state_file.read_text())
                if current['owner'] != state['owner'] or current['phase'] != 'ready':
                    break
                if time.monotonic() < due:
                    time.sleep(min(.1, due-time.monotonic()))
                    continue
                began = time.monotonic()
                try:
                    vehicle = rpc('simGetVehiclePose', 'PX4', timeout=3)
                    pose = camera_pose(vehicle['position'], task['spawn_ned_m'])
                    rpc('simSetCameraPose', CAMERA, pose, '', True, timeout=3)
                    responses = rpc('simGetImages', [request], '', True, timeout=3)
                    if len(responses) != 1:
                        raise RuntimeError('相机响应数量无效')
                    frame = responses[0]
                    data = bytes(frame['image_data_uint8'])
                    if data[:8] != b'\x89PNG\r\n\x1a\n' or frame['width'] <= 0 or frame['height'] <= 0:
                        raise RuntimeError('相机未返回有效 PNG')
                    path = frames/f'{len(rows):06d}.png'
                    path.write_bytes(data)
                    cost = time.monotonic()-began
                    row = dict(file=str(path.relative_to(output)), sim_ns=int(frame['time_stamp']),
                               wall_elapsed_s=time.monotonic()-start, capture_wall_s=cost,
                               width=frame['width'], height=frame['height'],
                               vehicle_local_ned=vehicle['position'], camera_global_ned=pose,
                               received_wall_ns=time.time_ns())
                    stream.write(json.dumps(row)+'\n')
                    rows.append(row); costs.append(cost); errors = 0
                except (OSError, RuntimeError, ValueError, KeyError) as exc:
                    errors += 1
                    with (output/'errors.jsonl').open('a') as log:
                        log.write(json.dumps(dict(elapsed_s=time.monotonic()-start, error=str(exc)))+'\n')
                    if errors >= 3:
                        raise RuntimeError('连续三次抓帧失败，停止录像；飞行任务不受录像器接管') from exc
                due = max(due+1/fps, time.monotonic())
        finally:
            result = dict(owner=state['owner'], frames=len(rows), requested_wall_fps=fps,
                          wall_seconds=time.monotonic()-start, camera=CAMERA,
                          capture_wall_s=dict(median=statistics.median(costs), maximum=max(costs),
                                              p95=sorted(costs)[round((len(costs)-1)*.95)]) if costs else None)
            (output/'summary.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)


def encode(source, output, gamma=1.):
    if output.exists() or output.with_suffix('.json').exists():
        raise FileExistsError(output)
    rows = [json.loads(x) for x in (source/'frames.jsonl').read_text().splitlines()]
    if len(rows) < 2:
        raise ValueError('至少需要两帧，不能把缺测编码成视频')
    concat = source/'frames.ffconcat'
    lines = ['ffconcat version 1.0']
    for i, row in enumerate(rows):
        path = str((source/row['file']).resolve()).replace("'", "'\\''")
        file_line = "file '"+path+"'"
        lines.extend([file_line, 'option framerate 1000'])
        duration = (rows[i+1]['sim_ns']-row['sim_ns'])/1e9 if i+1 < len(rows) else .1
        if duration <= 0:
            raise ValueError('相机时间戳重复或倒退；拒绝伪造时间轴')
        lines.append(f'duration {duration:.9f}')
    lines.extend([file_line, 'option framerate 1000'])
    concat.write_text('\n'.join(lines)+'\n')
    filters = f"eq=gamma={gamma},drawtext=text='AirSim RGB | sim elapsed %{{pts\\:hms}}':fontsize=16:fontcolor=white:box=1:boxcolor=black@0.5:x=8:y=8"
    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'warning', '-n',
                    '-safe', '0', '-f', 'concat', '-i', str(concat), '-r', '20',
                    '-vf', filters, '-t', str((rows[-1]['sim_ns']-rows[0]['sim_ns'])/1e9+.1),
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart', str(output)], check=True)
    output.with_suffix('.json').write_text(json.dumps(dict(source=str(source), source_frames=len(rows),
        source_sim_seconds=(rows[-1]['sim_ns']-rows[0]['sim_ns'])/1e9, display_gamma=gamma,
        first_sim_ns=rows[0]['sim_ns'], last_sim_ns=rows[-1]['sim_ns'],
        timeline='AirSim image timestamps; hold captured frames, no optical-flow interpolation',
        camera_footage=True), indent=2))
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    setup = sub.add_parser('configure'); setup.add_argument('settings', type=Path); setup.add_argument('output', type=Path)
    rec = sub.add_parser('record'); rec.add_argument('--state-dir', type=Path, required=True)
    rec.add_argument('--output', type=Path, required=True); rec.add_argument('--seconds', type=float, default=180)
    rec.add_argument('--fps', type=float, default=2)
    enc = sub.add_parser('encode'); enc.add_argument('source', type=Path); enc.add_argument('output', type=Path)
    enc.add_argument('--gamma',type=float,default=1.,help='仅调整输出显示亮度，原始PNG保持原样')
    args = parser.parse_args()
    if args.action == 'configure': configure(args.settings, args.output)
    elif args.action == 'encode':
        if not .5 <= args.gamma <= 3:parser.error('gamma 范围 0.5～3')
        encode(args.source, args.output,args.gamma)
    else:
        if not 1 <= args.seconds <= 1800 or not .2 <= args.fps <= 5:
            parser.error('录像 seconds 范围 1～1800，fps 范围 0.2～5')
        record(args.state_dir, args.output, args.seconds, args.fps)


if __name__ == '__main__': main()
