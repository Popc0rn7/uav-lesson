#!/usr/bin/env python3
"""PC：SUPER Humble + PX4/Gazebo 双 Docker 的准备、启动与验收入口。"""
import argparse
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
WORKSPACE=ROOT/'thirdparty/super_gazebo_ws'
SOURCE=ROOT/'submodules/SUPER'
ROS='uav-stage3-ros'
SITL='uav-stage3-sitl'
IMAGE='uav-computer-ros-humble:local'


def run(*args, **kwargs):
    return subprocess.run(list(map(str,args)),check=True,**kwargs)


def exists(name):
    return subprocess.run(['docker','inspect',name],stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode==0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','build','lio-build','up','inspect','scan','verify','fault','contact-check','view','view-close','down'])
    parser.add_argument('--case',choices=['lidar','planner','clock'])
    parser.add_argument('--scene',choices=['default','corridor'])
    parser.add_argument('--localization',choices=['fastlio','px4'],help='走廊默认 PX4/GNSS；fastlio 为显式对照')
    parser.add_argument('--wall-landmarks',choices=['on','off'],help='可选实体墙面标记；FAST-LIO 默认 on，PX4 对照默认 off')
    parser.add_argument('--lidar',choices=['mid360','super360','mid360s'],default='mid360')
    parser.add_argument('--speed',type=int,choices=[2,5])
    parser.add_argument('--lidar-mount-z',type=float,default=.30,help='走廊雷达 link 相对 base_link 的安装高度（m）')
    parser.add_argument('--self-filter',choices=['on','off'],default='on',help='走廊点云自体回波过滤；不改变实体遮挡')
    parser.add_argument('--humble-image',help='覆盖 Dockerfile 固定的 Humble 基础镜像；教师记录摘要')
    parser.add_argument('--build-jobs',type=int,default=2,help='镜像与算法编译并发数，内存紧张时设为 1')
    parser.add_argument('--sitl-image',default='px4io/px4-sitl-gazebo:latest')
    args=parser.parse_args()
    if args.build_jobs < 1:parser.error('build-jobs 必须大于 0')
    if args.action=='prepare':
        run('python3',ROOT/'stage3/super/prepare_super.py')
        return
    run('docker','info','--format','{{.ServerVersion}}')
    if args.action=='lio-build':
        run('python3',ROOT/'stage3/super/prepare_lio.py')
        run('docker','image','inspect',IMAGE,stdout=subprocess.DEVNULL)
        run('docker','run','--rm','--network','none','--user',f'{os.getuid()}:{os.getgid()}',
            '--mount',f'type=bind,source={ROOT}/thirdparty/fast_lio_ws,target=/lio_ws',
            '--mount',f'type=bind,source={WORKSPACE},target=/super_ws',
            '--mount',f'type=bind,source={SOURCE},target=/super_ws/src,readonly',
            '--mount',f'type=bind,source={ROOT},target=/lesson,readonly',
            '-e',f'CMAKE_BUILD_PARALLEL_LEVEL={args.build_jobs}',
            '-e',f'MAKEFLAGS=-j{args.build_jobs}','--entrypoint','bash',IMAGE,'-lc',
            'set -e; source /opt/ros/humble/setup.bash; source /opt/px4_ws/install/local_setup.bash; cd /lio_ws; '
            'colcon build --packages-up-to fast_lio --executor sequential --cmake-args -DCMAKE_BUILD_TYPE=Release; '
            'source /lio_ws/install/local_setup.bash; cd /super_ws; '
            'colcon build --base-paths /lesson/stage3/super/ros_src --build-base build-prefilter --install-base install-prefilter --cmake-force-configure --cmake-args -DCMAKE_BUILD_TYPE=Release')
    elif args.action=='build':
        if not (SOURCE/'super_planner/CMakeLists.txt').is_file():parser.error('请先 prepare')
        (WORKSPACE/'src').mkdir(parents=True,exist_ok=True)
        build_args=['--build-arg',f'HUMBLE_IMAGE={args.humble_image}'] if args.humble_image else []
        run('docker','build','--network','host','--build-arg','http_proxy','--build-arg','https_proxy',
            '--build-arg',f'BUILD_JOBS={args.build_jobs}',
            *build_args,'-t',IMAGE,ROOT/'develop/docker')
        # Core build only: no MAVROS, ProjectAirSim, perfect_drone_sim or rendering demo.
        run('docker','run','--rm','--network','none','--user',f'{os.getuid()}:{os.getgid()}',
            '--mount',f'type=bind,source={WORKSPACE},target=/super_ws',
            '--mount',f'type=bind,source={SOURCE},target=/super_ws/src,readonly',
            '--mount',f'type=bind,source={ROOT},target=/lesson,readonly',
            '-e',f'CMAKE_BUILD_PARALLEL_LEVEL={args.build_jobs}','-e',f'MAKEFLAGS=-j{args.build_jobs}',
            '--entrypoint','bash',IMAGE,'-lc',
            'set -e; source /opt/ros/humble/setup.bash; source /opt/px4_ws/install/local_setup.bash; cd /super_ws; '
            'colcon build --base-paths /super_ws/src/super_planner /super_ws/src/rog_map '
            '/super_ws/src/mars_uav_sim/mars_quadrotor_msgs --packages-up-to super_planner --executor sequential '
            '--cmake-args -DCMAKE_BUILD_TYPE=Release; '
            'colcon build --base-paths /lesson/stage3/super/ros_src --build-base build-prefilter '
            '--install-base install-prefilter --cmake-args -DCMAKE_BUILD_TYPE=Release')
    elif args.action=='up':
        args.scene=args.scene or 'default'
        args.speed=args.speed or 2
        args.localization=args.localization or 'px4'
        use_lio=args.localization=='fastlio'
        args.wall_landmarks=args.wall_landmarks or ('on' if use_lio else 'off')
        ros_image=IMAGE
        if use_lio and (args.scene!='corridor' or args.lidar!='mid360'):parser.error('FAST-LIO2 当前只支持 corridor + mid360')
        if use_lio and not (ROOT/'thirdparty/fast_lio_ws/install/local_setup.bash').exists():parser.error('先执行 lio-build')
        if use_lio and not (WORKSPACE/'install-prefilter/stage3_lidar/lib/stage3_lidar/timed_lidar').is_file():parser.error('先执行 lio-build，构建时间分片雷达节点')
        if exists(ROS) or exists(SITL):parser.error('本任务容器已存在，请 inspect；确认落地后 down 再 up')
        if not (WORKSPACE/'install/local_setup.bash').is_file():parser.error('请先 build')
        if not Path('/dev/dri/renderD128').exists():parser.error('需要教师核实 GPU render 节点，当前固定 renderD128')
        run('docker','image','inspect',ros_image,stdout=subprocess.DEVNULL)
        run('docker','image','inspect',args.sitl_image,stdout=subprocess.DEVNULL)
        extra=[];ros_extra=[]
        sensor=ROOT/'stage2/models/mid360s'
        vehicle=ROOT/'stage2/models/x500_experiment'
        if args.scene=='corridor':
            if not (WORKSPACE/'install-prefilter/local_setup.bash').is_file():parser.error('请先 build C++ 雷达预处理器')
            run('python3',ROOT/'stage3/super/generate_gazebo_corridor.py','--lidar-mount-z',args.lidar_mount_z,*(['--temporal-scan'] if use_lio else []),*(['--wall-landmarks'] if args.wall_landmarks=='on' else []))
            vehicle=ROOT/'stage3/super/models/x500_super'
            extra=['--mount',f'type=bind,source={ROOT}/stage3/super/worlds/corridor.sdf,target=/opt/px4-gazebo/share/gz/worlds/corridor.sdf,readonly',
                   '-e','PX4_GZ_MODEL_POSE=0,0,0.24,0,0,1.57079632679',
                   '-e','PX4_PARAM_EKF2_BARO_CTRL=0',
                   '-e','PX4_PARAM_EKF2_EV_CTRL=2','-e','PX4_PARAM_EKF2_HGT_REF=3',
                   '-e','PX4_PARAM_EKF2_EVP_NOISE=0.05',
                   '-e','PX4_PARAM_EKF2_GPS_P_NOISE=0.05',
                   '-e','PX4_PARAM_SENS_GPS0_DELAY=0','-e','PX4_PARAM_SENS_GPS1_DELAY=0',
                   '-e','PX4_PARAM_MPC_XY_P=1.2']
            if args.lidar=='super360':sensor=ROOT/'stage3/super/models/super360'
            elif args.lidar=='mid360':sensor=ROOT/'stage3/super/models/mid360'
            height_source='lidar' if args.lidar=='super360' else 'px4'
            if height_source=='px4':
                extra.extend(['-e','PX4_PARAM_EKF2_BARO_CTRL=1','-e','PX4_PARAM_EKF2_EV_CTRL=0',
                              '-e','PX4_PARAM_EKF2_HGT_REF=0','-e','PX4_PARAM_EKF2_GPS_CTRL=5'])
            if use_lio:
                extra.extend(['-e','PX4_PARAM_EKF2_GPS_CTRL=0','-e','PX4_PARAM_EKF2_BARO_CTRL=1',
                              '-e','PX4_PARAM_EKF2_EV_CTRL=15','-e','PX4_PARAM_EKF2_HGT_REF=3','-e','PX4_PARAM_EKF2_EV_DELAY=0'])
                height_source='fastlio'
            extra.extend(['-e',f'STAGE3_WALL_LANDMARKS={str(args.wall_landmarks=="on").lower()}'])
            ros_extra=['-e','STAGE3_LOCALIZATION='+args.localization,'-e',f'STAGE3_WALL_LANDMARKS={str(args.wall_landmarks=="on").lower()}','-e','STAGE3_CORRIDOR=true','-e',f'STAGE3_SPEED={args.speed}.0',
                       '-e',f'STAGE3_LIDAR={args.lidar}','-e',f'STAGE3_HEIGHT_SOURCE={height_source}',
                       '-e',f'STAGE3_SENSOR_Z={args.lidar_mount_z+.035}',
                       '-e',f'STAGE3_SELF_FILTER={str(args.self_filter=="on").lower()}',
                       '-e',f'STAGE3_LIDAR_RANGE={69.9 if args.lidar!="mid360s" else 39.9}',
                       '-e',f'STAGE3_CONFIG=/lesson/stage3/super/super_corridor_{args.speed}.yaml',
                       '-e','SUPER_CENTER_Z_MIN=1.4']
        run('docker','run','-d','--init','--name',SITL,'--network','host','--device','/dev/dri/renderD128',*extra,
            '--mount',f'type=bind,source={vehicle},target=/opt/px4-gazebo/share/gz/models/x500_experiment,readonly',
            '--mount',f'type=bind,source={sensor},target=/opt/px4-gazebo/share/gz/models/mid360s,readonly',
            '--mount',f'type=bind,source={ROOT}/stage3/super/px4_start.sh,target=/stage3-start.sh,readonly',
            '--mount',f'type=bind,source={ROOT}/stage3/super,target=/lesson-stage3,readonly',
            '-e','HEADLESS=1','-e','EGL_PLATFORM=surfaceless','-e','GZ_PARTITION=uav-stage3',
            '-e','PX4_SYS_AUTOSTART=4001','-e','PX4_SIM_MODEL=gz_x500_experiment','-e',f'PX4_GZ_WORLD={args.scene}',
            '--entrypoint','/bin/sh',args.sitl_image,'/stage3-start.sh')
        run('docker','run','-d','--init','--name',ROS,'--network','host',
            '--mount',f'type=bind,source={ROOT},target=/lesson,readonly',
            '--mount',f'type=bind,source={WORKSPACE},target=/super_ws,readonly',
            '--mount',f'type=bind,source={SOURCE},target=/super_ws/src,readonly',
            *(['--mount',f'type=bind,source={ROOT}/thirdparty/fast_lio_ws,target=/lio_ws,readonly'] if use_lio else []),
            '-e','FASTRTPS_DEFAULT_PROFILES_FILE=/lesson/stage3/super/race_view_dds.xml',*ros_extra,
            ros_image,'bash','/lesson/stage3/super/run_super_nodes.sh')
    elif args.action=='scan':
        if not exists(ROS):parser.error('运行环境不存在，请先 up')
        env=subprocess.check_output(['docker','inspect',ROS,'--format','{{range .Config.Env}}{{println .}}{{end}}'],text=True)
        hz=60 if 'STAGE3_LOCALIZATION=fastlio' in env.splitlines() else (30 if 'STAGE3_LIDAR=mid360' in env.splitlines() else 10)
        run('python3',ROOT/'stage3/super/check_gazebo_scan.py','--expected-hz',hz)
    elif args.action=='contact-check':
        run('python3',ROOT/'stage3/super/check_gazebo_contact.py')
    elif args.action in ('view','view-close'):
        from super_gazebo_view import main as view
        view(close=args.action=='view-close',image=args.sitl_image)
    elif args.action in ('inspect','verify','fault'):
        if args.action=='fault' and not args.case:parser.error('fault 需要 --case')
        if not exists(ROS):parser.error('运行环境不存在，请先执行 up')
        environment=subprocess.check_output(['docker','inspect',ROS,'--format','{{range .Config.Env}}{{println .}}{{end}}'],text=True)
        config=dict(line.split('=',1) for line in environment.splitlines() if '=' in line)
        scene='corridor' if config.get('STAGE3_CORRIDOR')=='true' else 'default'
        speed=int(float(config.get('STAGE3_SPEED','2')))
        if args.scene is not None and args.scene!=scene:parser.error('scene 与运行配置不一致；需要 down 后重新 up')
        if args.speed is not None and args.speed!=speed:parser.error('speed 与运行配置不一致；需要 down 后重新 up')
        if args.localization is not None and args.localization!=config.get('STAGE3_LOCALIZATION','px4'):parser.error('localization 与运行配置不一致；需要 down 后重新 up')
        if args.wall_landmarks is not None and (args.wall_landmarks=='on')!=(config.get('STAGE3_WALL_LANDMARKS')=='true'):parser.error('wall-landmarks 与运行配置不一致；需要 down 后重新 up')
        args.scene,args.speed=scene,speed
        if args.action=='fault' and scene!='corridor':parser.error('fault 当前只支持 corridor')
        print(f'运行配置：scene={scene}, speed={speed} m/s, lidar={config.get("STAGE3_LIDAR","legacy")}, height={config.get("STAGE3_HEIGHT_SOURCE","lidar")}, localization={config.get("STAGE3_LOCALIZATION","px4")}, wall-landmarks={config.get("STAGE3_WALL_LANDMARKS","false")}',flush=True)
        program='inspect_super.py' if args.action=='inspect' else ('verify_super_corridor.py' if args.scene=='corridor' else 'verify_super_flight.py --fly')
        if args.action=='fault':program=f'check_super_fault.py --case {args.case}'
        run('docker','exec','-e','ROS_LOCALHOST_ONLY=0','-e','ROS_LOG_DIR=/tmp/stage3-ros-logs',ROS,'bash','-lc',
            'source /opt/ros/humble/setup.bash; source /opt/px4_ws/install/local_setup.bash; '
            'source /super_ws/install/local_setup.bash; '
            'if [ -f /lio_ws/install/local_setup.bash ]; then source /lio_ws/install/local_setup.bash; fi; '
            f'python3 -u /lesson/stage3/super/{program}')
    elif args.action=='down':
        # Refuse removal while flying; down is for already disarmed SITL.
        if exists(SITL) and subprocess.check_output(['docker','inspect',SITL,'--format','{{.State.Running}}'],text=True).strip()=='true':
            result=subprocess.run(['docker','exec',SITL,'/opt/px4-gazebo/bin/px4-listener','vehicle_status','-n','1'],
                                  capture_output=True,text=True,timeout=10,check=True)
            if 'arming_state: 1' not in result.stdout:parser.error('未确认 Disarmed；先降落，保留容器和日志')
        # Harmonic GUI retains entity IDs across server restarts. Reopen it for the new world.
        from super_gazebo_view import main as view
        view(close=True,image=args.sitl_image)
        for name in (ROS,SITL):
            if exists(name):
                run('docker','stop','-t','10',name)
                run('docker','rm',name)


if __name__=='__main__':
    try:main()
    except subprocess.CalledProcessError as exc:raise SystemExit(exc.returncode)
