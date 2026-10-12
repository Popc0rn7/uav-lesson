#!/usr/bin/env python3
"""PC：60 秒 Gazebo 扫描与实时率验收，结果保存在 /tmp。"""
import argparse
import json
import time
from pathlib import Path
from urllib.request import urlopen


def read():
    with urlopen('http://127.0.0.1:8096/state',timeout=3) as response:
        return json.load(response)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-hz',type=float,default=10.)
    parser.add_argument('--duration',type=float,default=60.)
    args=parser.parse_args()
    deadline=time.monotonic()+60
    while True:
        try:
            first=read()
            if first['scans'] and first['pose'] is not None:break
        except OSError:pass
        if time.monotonic()>deadline:raise SystemExit('Gazebo monitor/sensors timeout')
        time.sleep(.2)
    start=time.monotonic();last=first;rtfs=[];gap=0.
    while time.monotonic()-start<args.duration:
        time.sleep(.2);last=read()
        if last['started']!=first['started']:
            raise SystemExit('Gazebo reset during scan check; rerun on a single cold-start instance')
        rtfs.append(last['real_time_factor'])
        gap=max(gap,time.monotonic()-last['scan_at'])
    duration=time.monotonic()-start
    hz=(last['scans']-first['scans'])/duration
    avg=sum(rtfs)/len(rtfs)
    report=dict(passed=hz>=args.expected_hz*.9 and avg>=.8 and last['max_scan_gap_s']<=.5,
                scan_hz=hz,expected_scan_hz=args.expected_hz,mean_real_time_factor=avg,max_scan_gap_s=last['max_scan_gap_s'],
                points_per_frame=last['points'],duration_s=duration,pose=last['pose'])
    Path('/tmp/stage3-gazebo-scan.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
