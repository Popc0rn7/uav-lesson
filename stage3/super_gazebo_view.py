#!/usr/bin/env python3
"""PC 图形桌面：连接现有物理世界，打开 Gazebo、点云 RViz 与地图 RViz。"""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
WS=ROOT/'thirdparty/super_gazebo_ws'


def run(*args):
    subprocess.run(list(map(str,args)),check=True)


def main(close=False,image='px4io/px4-sitl-gazebo:latest'):
    names=('uav-stage3-gazebo-view','uav-stage3-rviz-view','uav-stage3-rviz-map-view')
    if close:
        for name in names:
            if subprocess.run(['docker','inspect',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
                run('docker','stop','-t','5',name);run('docker','rm',name)
        return
    mounts=json.loads(subprocess.check_output(['docker','inspect','uav-stage3-sitl','--format','{{json .Mounts}}'],text=True))
    model_mounts={m['Destination']:m['Source'] for m in mounts}
    vehicle_source=model_mounts['/opt/px4-gazebo/share/gz/models/x500_experiment']
    sensor_source=model_mounts['/opt/px4-gazebo/share/gz/models/mid360s']
    ros_image=subprocess.check_output(['docker','inspect','uav-stage3-ros','--format','{{.Config.Image}}'],text=True).strip()
    display=os.environ.get('DISPLAY');auth=os.environ.get('XAUTHORITY')
    if not display or not auth or not Path(auth).is_file():raise SystemExit('需要 PC 图形桌面 DISPLAY/XAUTHORITY')
    shared=['--network','host','--user',f'{os.getuid()}:{os.getgid()}',
            '--mount','type=bind,source=/tmp/.X11-unix,target=/tmp/.X11-unix,readonly',
            '--mount',f'type=bind,source={Path(auth).resolve()},target=/tmp/desktop.xauth,readonly',
            '-e',f'DISPLAY={display}','-e','XAUTHORITY=/tmp/desktop.xauth','-e','QT_X11_NO_MITSHM=1',
            '--mount',f'type=bind,source={ROOT},target=/lesson,readonly']
    for name in names:
        if subprocess.run(['docker','inspect',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
            raise SystemExit(f'{name} 已存在；关闭后用 view-close 清理再打开')
    run('docker','run','-d','--init','--name',names[0],*shared,'--user','0:0','--device','/dev/dri/renderD128',
        '--tmpfs','/.gz:uid=1000,gid=1000','-e','GZ_PARTITION=uav-stage3',
        '--mount',f'type=bind,source={vehicle_source},target=/opt/px4-gazebo/share/gz/models/x500_experiment,readonly',
        '--mount',f'type=bind,source={sensor_source},target=/opt/px4-gazebo/share/gz/models/mid360s,readonly',
        '--entrypoint','bash',image,'-lc',
        'export GZ_SIM_RESOURCE_PATH=/opt/px4-gazebo/share/gz/models:/opt/px4-gazebo/share/gz/worlds; exec gz sim -g')
    for name,config,node in ((names[1],'super_gazebo_cloud.rviz','stage3_cloud_rviz'),
                             (names[2],'super_gazebo_map.rviz','stage3_map_rviz')):
        run('docker','run','-d','--init','--name',name,*shared,
            '--tmpfs','/.rviz2:uid=1000,gid=1000',
            '--mount',f'type=bind,source={WS},target=/super_ws,readonly',
            '-e','FASTRTPS_DEFAULT_PROFILES_FILE=/lesson/stage3/race_view_dds.xml',
            '--entrypoint','bash',ros_image,'-lc',
            'source /opt/ros/humble/setup.bash; source /super_ws/install/local_setup.bash; '
            f'exec rviz2 -d /lesson/stage3/{config} --ros-args -r __node:={node} -p use_sim_time:=true')
    for _ in range(15):
        result=subprocess.run(['docker','exec',names[0],'gz','service','-s','/gui/follow',
            '--reqtype','gz.msgs.StringMsg','--reptype','gz.msgs.Boolean','--timeout','500',
            '--req','data: "x500_experiment_0"'],capture_output=True,text=True)
        if 'data: true' in result.stdout:
            run('docker','exec',names[0],'gz','service','-s','/gui/follow/offset',
                '--reqtype','gz.msgs.Vector3d','--reptype','gz.msgs.Boolean','--timeout','1000',
                '--req','x: -8, y: 0, z: 6')
            break
        time.sleep(.5)
    # Harmonic GUI world controls may initialize the server in paused state.
    # The Stage 3 demo expects a running clock after opening its viewer.
    environment=subprocess.check_output(['docker','inspect','uav-stage3-sitl','--format','{{range .Config.Env}}{{println .}}{{end}}'],text=True)
    config=dict(line.split('=',1) for line in environment.splitlines() if '=' in line)
    world=config.get('PX4_GZ_WORLD','default')
    result=subprocess.run(['docker','exec','uav-stage3-sitl','gz','service','-s',f'/world/{world}/control',
        '--reqtype','gz.msgs.WorldControl','--reptype','gz.msgs.Boolean','--timeout','3000',
        '--req','pause: false'],capture_output=True,text=True,check=True)
    if 'data: true' not in result.stdout:raise SystemExit('Gazebo GUI 已打开，但恢复仿真时钟失败：'+result.stdout+result.stderr)
    for name in names[1:]:
        if subprocess.check_output(['docker','inspect',name,'--format','{{.State.Running}}'],text=True).strip()!='true':
            raise SystemExit(f'{name} 未保持运行；请检查 docker logs {name}')
