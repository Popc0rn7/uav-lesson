#!/usr/bin/env python3
"""PC：落地后注入可删除的碰撞探针，验证接触传感器确实工作。"""
import json
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen


def state():
    with urlopen('http://127.0.0.1:8096/state',timeout=3) as response:return json.load(response)


def main():
    deadline=time.monotonic()+60
    while True:
        try:
            current=state()
            if current['world']=='corridor' and current['pose'] is not None:break
        except OSError:pass
        if time.monotonic()>deadline:raise SystemExit('corridor monitor startup timeout')
        time.sleep(.2)
    while True:
        status=subprocess.run(['docker','exec','uav-stage3-sitl','/opt/px4-gazebo/bin/px4-listener','vehicle_status','-n','1'],check=True,capture_output=True,text=True).stdout
        if 'arming_state: 1' in status:break
        if 'arming_state: 2' in status:raise SystemExit('contact fixture requires Disarmed')
        if time.monotonic()>deadline:raise SystemExit('PX4 Disarmed startup timeout')
        time.sleep(.2)
    name='x500_contact_probe'
    xml="<sdf version='1.9'><model name='x500_contact_probe'><pose>3.08 5 1 0 0 0</pose><link name='link'><inertial><mass>1</mass><inertia><ixx>.1</ixx><iyy>.1</iyy><izz>.1</izz></inertia></inertial><collision name='collision'><geometry><box><size>.3 .3 .3</size></box></geometry></collision></link></model></sdf>"
    before=len(state()['contacts']);passed=False
    try:
        subprocess.run(['docker','exec','uav-stage3-sitl','gz','service','-s','/world/corridor/create',
            '--reqtype','gz.msgs.EntityFactory','--reptype','gz.msgs.Boolean','--timeout','3000',
            '--req',f'name: "{name}", sdf: {json.dumps(xml)}'],check=True)
        end=time.monotonic()+10
        while time.monotonic()<end:
            current=state()
            if any(name in c['collision1'] or name in c['collision2'] for c in current['contacts']):
                passed=True;break
            time.sleep(.1)
    finally:
        subprocess.run(['docker','exec','uav-stage3-sitl','gz','service','-s','/world/corridor/remove',
            '--reqtype','gz.msgs.Entity','--reptype','gz.msgs.Boolean','--timeout','3000',
            '--req',f'name: "{name}", type: MODEL'],check=True)
    result=dict(passed=passed,contacts_before=before,contacts_after=len(state()['contacts']))
    Path('/tmp/stage3-contact-check.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));raise SystemExit(0 if passed else 1)


if __name__=='__main__':main()
