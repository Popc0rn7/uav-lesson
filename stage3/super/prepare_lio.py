#!/usr/bin/env python3
"""PC：固定 FAST-LIO2 ROS2 与 Livox 消息源码，生成仿真消息构建入口。"""
from pathlib import Path
import shutil
import subprocess
from patch_lio_forward import apply as patch_forward

ROOT=Path(__file__).resolve().parents[2]
WS=ROOT/'thirdparty/fast_lio_ws'
SOURCES=[('https://github.com/hku-mars/FAST_LIO.git',WS/'src/FAST_LIO','a4743b095409588842a5b30ddfa27e29d2f99164','ROS2'),
         ('https://github.com/Livox-SDK/livox_ros_driver2.git',ROOT/'thirdparty/livox_driver_source','21445540f0d100dc86a7e6df312dd70bbdb4afdf','master')]

def main():
    for url,path,revision,branch in SOURCES:
        if not path.exists():
            path.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(['git','clone','--no-checkout','--depth','1',url,str(path)],check=True)
            subprocess.run(['git','-C',str(path),'fetch','--depth','1','origin',revision],check=True)
            subprocess.run(['git','-C',str(path),'checkout','--detach',revision],check=True)
        current=subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()
        if current!=revision:raise SystemExit(f'{path} revision {current} != pinned {revision}; use a clean pinned checkout')
    subprocess.run(['git','-C',str(SOURCES[0][1]),'submodule','update','--init','--recursive'],check=True)
    source=WS/'src/FAST_LIO/src/laserMapping.cpp'
    code=source.read_text()
    marker='// Stage3: expose filter velocity in ROS child-frame coordinates.'
    if marker not in code:
        anchor='    set_posestamp(odomAftMapped.pose);'
        if code.count(anchor)!=1:raise SystemExit('Pinned FAST-LIO velocity patch anchor changed')
        code=code.replace(anchor,anchor+'\n'+marker+"""
    const V3D body_velocity = state_point.rot.toRotationMatrix().transpose() * state_point.vel;
    odomAftMapped.twist.twist.linear.x = body_velocity(0);
    odomAftMapped.twist.twist.linear.y = body_velocity(1);
    odomAftMapped.twist.twist.linear.z = body_velocity(2);
""")
        source.write_text(code)
    if '// Stage3: accumulate initial non-repetitive scan coverage' not in code:
        anchor='                    ikdtree.Build(feats_down_world->points);'
        if code.count(anchor)!=1:raise SystemExit('Pinned FAST-LIO initial map anchor changed')
        code=code.replace(anchor,'''                    // Stage3: accumulate initial non-repetitive scan coverage.
                    // Launch stays stationary; IMU propagation remains active.
                    static PointVector bootstrap_points;
                    static double bootstrap_start = Measures.lidar_beg_time;
                    bootstrap_points.insert(bootstrap_points.end(), feats_down_world->points.begin(), feats_down_world->points.end());
                    if (Measures.lidar_end_time - bootstrap_start < 0.15) return;
                    ikdtree.Build(bootstrap_points);
                    bootstrap_points.clear();''')
        source.write_text(code)
    imu_source=WS/'src/FAST_LIO/src/IMU_Processing.hpp'
    imu_code=imu_source.read_text()
    # 200 Hz simulation IMU: use two seconds rather than ~50 ms to estimate
    # stationary gravity and gyro bias before enabling scan registration.
    initialized=imu_code.replace('#define MAX_INI_COUNT (10)', '#define MAX_INI_COUNT (400)')
    if initialized!=imu_code:
        imu_code=initialized
        imu_source.write_text(imu_code)
    if '// Stage3: initialize extrapolation input' not in imu_code:
        imu_code=imu_code.replace('  input_ikfom in;', """  input_ikfom in;
  // Stage3: initialize extrapolation input even when no interval survives clipping.
  in.acc << last_imu_->linear_acceleration.x, last_imu_->linear_acceleration.y, last_imu_->linear_acceleration.z;
  in.acc *= G_m_s2 / mean_acc.norm();
  in.gyro << last_imu_->angular_velocity.x, last_imu_->angular_velocity.y, last_imu_->angular_velocity.z;
""")
        imu_source.write_text(imu_code)
    imu_code=imu_source.read_text()
    if 'last_lidar_end_time_ = meas.lidar_end_time;' not in imu_code:
        imu_code=imu_code.replace('  last_imu_ = meas.imu.back();\n\n}', '  last_imu_ = meas.imu.back();\n  last_lidar_end_time_ = meas.lidar_end_time;\n  acc_s_last = Zero3d;\n\n}')
        imu_source.write_text(imu_code)
    if '// Stage3: propagation diagnostics' not in imu_code:
        imu_code=imu_code.replace('  /*** sort point clouds by offset time ***/', '''  // Stage3: propagation diagnostics (first ten frames only).
  static int diagnostic_frames = 0;
  if (diagnostic_frames++ < 10) std::cerr << "LIO propagation begin/end/imu/previous/gravity: " << pcl_beg_time << " " << pcl_end_time << " " << imu_beg_time << " " << imu_end_time << " " << last_lidar_end_time_ << " " << mean_acc.transpose() << std::endl;
  /*** sort point clouds by offset time ***/''')
        imu_source.write_text(imu_code)
    if '// Stage3: stationary simulation initialization covariance' not in imu_code:
        anchor='  init_P.setIdentity();'
        if imu_code.count(anchor)!=1:raise SystemExit('Pinned FAST-LIO covariance anchor changed')
        imu_code=imu_code.replace(anchor,anchor+'''
  // Stage3: stationary simulation initialization covariance.
  // Simulation-only prior after 400 stationary IMU samples; no truth feedback.
  init_P.block<3,3>(0,0) *= 1e-4;
  init_P.block<3,3>(3,3) *= 1e-6;
  init_P.block<3,3>(12,12) *= 1e-4;''')
        imu_code=imu_code.replace('init_P(15,15) = init_P(16,16) = init_P(17,17) = 0.0001;', 'init_P(15,15) = init_P(16,16) = init_P(17,17) = 1e-7;')
        imu_code=imu_code.replace('init_P(18,18) = init_P(19,19) = init_P(20,20) = 0.001;', 'init_P(18,18) = init_P(19,19) = init_P(20,20) = 1e-6;')
        imu_code=imu_code.replace('init_P(21,21) = init_P(22,22) = 0.00001;', 'init_P(21,21) = init_P(22,22) = 1e-7;')
        imu_source.write_text(imu_code)
    patch_forward(WS/'src/FAST_LIO')
    from patch_runtime_logs import patch as patch_logs
    patch_logs(lio_source=WS/'src/FAST_LIO')
    # FAST-LIO links the official message types. No SDK/hardware driver is needed
    # to consume simulated CustomMsg; keep the original schemas and license.
    target=WS/'src/livox_ros_driver2';target.mkdir(exist_ok=True)
    shutil.copytree(SOURCES[1][1]/'msg',target/'msg',dirs_exist_ok=True)
    shutil.copy2(SOURCES[1][1]/'LICENSE.txt',target/'LICENSE.txt') if (SOURCES[1][1]/'LICENSE.txt').exists() else shutil.copy2(SOURCES[1][1]/'LICENSE',target/'LICENSE')
    (target/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.8)
project(livox_ros_driver2)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME} "msg/CustomPoint.msg" "msg/CustomMsg.msg" DEPENDENCIES std_msgs)
ament_export_dependencies(rosidl_default_runtime)
ament_package()
''')
    (target/'package.xml').write_text('''<package format="3"><name>livox_ros_driver2</name><version>1.0.0</version><description>Official Livox message schemas only for simulation</description><maintainer email="course@example.invalid">UAV course</maintainer><license>MIT</license><buildtool_depend>ament_cmake</buildtool_depend><buildtool_depend>rosidl_default_generators</buildtool_depend><depend>std_msgs</depend><exec_depend>rosidl_default_runtime</exec_depend><member_of_group>rosidl_interface_packages</member_of_group></package>''')
    print('FAST-LIO2 and official Livox message schemas prepared at pinned revisions')

if __name__=='__main__':main()
