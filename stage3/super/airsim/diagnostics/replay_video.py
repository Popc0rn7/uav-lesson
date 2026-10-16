#!/usr/bin/env python3
"""PC 离线：从实际飞行报告生成遥测回放，不还原未保存的相机画面。"""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter


def replay(report, output, fps, cloud_dir=None):
    if any(output.with_suffix(suffix).exists() for suffix in ('.mp4','.png','.json')):
        raise FileExistsError(output)
    data = json.loads(report.read_text())
    rows = data['records']
    if len(rows) < 2:
        raise ValueError('缺少实际飞行遥测，不能生成回放')
    stamps = np.array([r['sim_s'] for r in rows])
    if np.any(np.diff(stamps) < 0) or stamps[-1] <= stamps[0]:
        raise ValueError('回放要求单次连续仿真时间，拒绝跨复位拼接')
    positions = np.array([r['p'] for r in rows])
    speeds = np.linalg.norm([r['v'] for r in rows], axis=1)
    times = stamps-stamps[0]
    cloud_files = sorted(cloud_dir.glob('*.npz'), key=lambda p:int(p.stem)) if cloud_dir else []
    cloud_stamps = np.array([int(p.stem)/1e9 for p in cloud_files])
    fig = plt.figure(figsize=(10, 6), dpi=100)
    grid = fig.add_gridspec(2, 2, width_ratios=[1.4, 1])
    world = fig.add_subplot(grid[:, 0], projection='3d')
    height = fig.add_subplot(grid[0, 1]); speed = fig.add_subplot(grid[1, 1])
    world.set(xlabel='East (m)', ylabel='North (m)', zlabel='Up (m)')
    low, high = positions.min(axis=0), positions.max(axis=0)
    world.set_xlim(low[0]-4, high[0]+4); world.set_ylim(low[1]-4, high[1]+4)
    world.set_zlim(min(0, low[2]-1), max(8, high[2]+2)); world.view_init(25, -65)
    trail, = world.plot([], [], [], color='tab:blue', label='PX4 estimated path')
    drone, = world.plot([], [], [], 'o', color='tab:blue', markersize=7)
    reference, = world.plot([], [], [], 'x', color='tab:orange', markersize=7, label='Commanded position')
    world.legend(loc='upper left', fontsize=8)
    height.plot(times, positions[:, 2], color='tab:blue'); height.set_ylabel('Height (m)')
    speed.plot(times, speeds, color='tab:blue'); speed.set_ylabel('Speed (m/s)'); speed.set_xlabel('Simulation seconds')
    for axis in (height, speed):
        axis.set_xlim(0, times[-1]); axis.grid(alpha=.25)
    hc = height.axvline(0, color='black'); sc = speed.axvline(0, color='black')
    status = fig.text(.02, .035, '', fontsize=9)
    fig.suptitle('Recorded PX4 telemetry replay — not AirSim camera footage', fontsize=12)
    fig.subplots_adjust(bottom=.17, top=.88, wspace=.35, hspace=.3)
    scatter = None; cloud_index = -1
    writer = FFMpegWriter(fps=fps, codec='libx264', extra_args=['-crf', '23', '-pix_fmt', 'yuv420p'])
    with writer.saving(fig, str(output), dpi=100):
        for t in np.arange(0, times[-1]+.5/fps, 1/fps):
            i = min(len(rows)-1, max(0, int(np.searchsorted(times, t, side='right')-1)))
            # Display recorded samples; do not invent intermediate aircraft attitude.
            p = positions[i]; trail.set_data_3d(*positions[:i+1].T); drone.set_data_3d([p[0]], [p[1]], [p[2]])
            ref = rows[i].get('reference')
            reference.set_data_3d(*([[v] for v in ref] if ref else [[], [], []]))
            hc.set_xdata([t, t]); sc.set_xdata([t, t])
            if len(cloud_files):
                k = int(np.searchsorted(cloud_stamps, stamps[i], side='right')-1)
                if k >= 0 and k != cloud_index:
                    with np.load(cloud_files[k]) as saved:
                        points = saved['points']
                    if scatter is not None: scatter.remove()
                    scatter = world.scatter(*points.T, s=.5, c='gray', alpha=.2, depthshade=False)
                    cloud_index = k
                note = f' | Last cloud age: {stamps[i]-cloud_stamps[k]:.2f} sim s' if k >= 0 else ' | Waiting for recorded clouds'
            else:
                note = ' | Obstacle clouds were not saved in this run'
            text = rows[i].get('control', '')
            status.set_text(f't={t:.1f}s | speed={speeds[i]:.2f} m/s | {text[:65]}\nRecorded samples only'+note)
            if not data['summary']['success']:
                status.set_text(status.get_text()+'\nFailure report ends before cleanup landing; use camera video for landing.')
            if t == 0: fig.savefig(output.with_suffix('.png'), dpi=100)
            writer.grab_frame()
    plt.close(fig)
    output.with_suffix('.json').write_text(json.dumps(dict(source=str(report), fps=fps,
        simulation_seconds=float(times[-1]), frames=int(len(np.arange(0, times[-1]+.5/fps, 1/fps))),
        recorded_cloud_frames=len(cloud_files), camera_footage=False,
        limitation='PX4估计位姿回放；无机体姿态或未保存障碍物的还原，取最近已记录样本。失败任务报告不包含收尾降落位姿。'), indent=2, ensure_ascii=False))
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--fps', type=int, default=8); parser.add_argument('--cloud-dir', type=Path)
    args = parser.parse_args()
    if not 1 <= args.fps <= 20: parser.error('fps 范围 1～20')
    replay(args.report, args.output, args.fps, args.cloud_dir)


if __name__ == '__main__': main()
