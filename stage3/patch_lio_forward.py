"""Reproducible patch: independent IMU propagation of the corrected FAST-LIO filter.

The scan-update filter and registered clouds stay unchanged. No ground truth,
PX4 state, or guessed constant velocity enters this propagation path.
"""
from pathlib import Path


def apply(source: Path):
    imu=source/'src/IMU_Processing.hpp'
    code=imu.read_text()
    if 'stage3_acceleration_scale' not in code:
        anchor='  Eigen::Matrix<double, 12, 12> Q;'
        if code.count(anchor)!=1:raise RuntimeError('FAST-LIO IMU scale patch anchor changed')
        code=code.replace(anchor,anchor+'\n  double stage3_acceleration_scale() const { return G_m_s2 / mean_acc.norm(); }')
        imu.write_text(code)
    mapping=source/'src/laserMapping.cpp'
    code=mapping.read_text()
    if '// Stage3: independent high-rate IMU propagation' in code:
        updated=code.replace('            stage3_reset_forward(Measures);','            if (effct_feat_num > 0) stage3_reset_forward(Measures);')
        if updated!=code:mapping.write_text(updated)
        return
    anchor='shared_ptr<ImuProcess> p_imu(new ImuProcess());'
    if code.count(anchor)!=1:raise RuntimeError('FAST-LIO propagation globals anchor changed')
    code=code.replace(anchor,anchor+'''

// Stage3: independent high-rate IMU propagation. rclcpp::spin is single-threaded.
// Copy the corrected filter after every scan, replay its buffered future IMU,
// and publish once per subsequent new IMU measurement. Main KF is untouched.
esekfom::esekf<state_ikfom, 12, input_ikfom> stage3_forward_kf;
rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr stage3_forward_pub;
sensor_msgs::msg::Imu::ConstSharedPtr stage3_forward_last;
double stage3_forward_time = -1, stage3_forward_correction = -1;
bool stage3_forward_ready = false;

void stage3_advance_forward(const sensor_msgs::msg::Imu::ConstSharedPtr &msg, bool publish)
{
    const double stamp = get_time_sec(msg->header.stamp);
    if (!stage3_forward_ready || stamp <= stage3_forward_time) return;
    double dt = stamp - stage3_forward_time;
    if (dt > 0.05 || stamp - stage3_forward_correction > 0.2) {
        stage3_forward_ready = false;
        return; // No long blind extrapolation on missing LiDAR/IMU.
    }
    input_ikfom input;
    const auto &a = msg->linear_acceleration, &b = stage3_forward_last->linear_acceleration;
    const auto &g = msg->angular_velocity, &h = stage3_forward_last->angular_velocity;
    input.acc << (a.x+b.x)*0.5, (a.y+b.y)*0.5, (a.z+b.z)*0.5;
    input.acc *= p_imu->stage3_acceleration_scale();
    input.gyro << (g.x+h.x)*0.5, (g.y+h.y)*0.5, (g.z+h.z)*0.5;
    stage3_forward_kf.predict(dt, p_imu->Q, input);
    stage3_forward_time = stamp;
    stage3_forward_last = msg;
    if (!publish || !stage3_forward_pub) return;
    const auto s = stage3_forward_kf.get_x();
    const auto covariance = stage3_forward_kf.get_P();
    nav_msgs::msg::Odometry out;
    out.header.stamp = msg->header.stamp;
    out.header.frame_id = "camera_init";
    out.child_frame_id = "body";
    out.pose.pose.position.x = s.pos(0); out.pose.pose.position.y = s.pos(1); out.pose.pose.position.z = s.pos(2);
    out.pose.pose.orientation.x = s.rot.coeffs()[0]; out.pose.pose.orientation.y = s.rot.coeffs()[1];
    out.pose.pose.orientation.z = s.rot.coeffs()[2]; out.pose.pose.orientation.w = s.rot.coeffs()[3];
    const V3D velocity = s.rot.toRotationMatrix().transpose() * s.vel;
    const V3D angular = input.gyro - s.bg;
    out.twist.twist.linear.x = velocity(0); out.twist.twist.linear.y = velocity(1); out.twist.twist.linear.z = velocity(2);
    out.twist.twist.angular.x = angular(0); out.twist.twist.angular.y = angular(1); out.twist.twist.angular.z = angular(2);
    // state_ikfom orders position before rotation; ROS pose covariance does too.
    for (int i=0; i<6; ++i) for (int j=0; j<6; ++j) out.pose.covariance[i*6+j] = covariance(i,j);
    const M3D velocity_cov = s.rot.toRotationMatrix().transpose() * covariance.block<3,3>(12,12) * s.rot.toRotationMatrix();
    for (int i=0; i<3; ++i) for (int j=0; j<3; ++j) out.twist.covariance[i*6+j] = velocity_cov(i,j);
    stage3_forward_pub->publish(out);
}

void stage3_reset_forward(const MeasureGroup &meas)
{
    if (meas.imu.empty()) return;
    stage3_forward_kf = kf;
    stage3_forward_time = stage3_forward_correction = meas.lidar_end_time;
    stage3_forward_last = meas.imu.back();
    stage3_forward_ready = true;
    for (const auto &msg: imu_buffer) stage3_advance_forward(msg, false);
}
''')
    start=code.index('void imu_cbk(')
    end=code.index('double lidar_mean_scantime',start)
    callback=code[start:end]
    callback=callback.replace('        imu_buffer.clear();','        imu_buffer.clear();\n        stage3_forward_ready = false;')
    callback=callback.replace('    sig_buffer.notify_all();','    sig_buffer.notify_all();\n    stage3_advance_forward(msg, true);')
    code=code[:start]+callback+code[end:]
    anchor='        pubOdomAftMapped_ = this->create_publisher<nav_msgs::msg::Odometry>("/Odometry", 20);'
    if code.count(anchor)!=1:raise RuntimeError('FAST-LIO propagation publisher anchor changed')
    code=code.replace(anchor,anchor+'\n        stage3_forward_pub = this->create_publisher<nav_msgs::msg::Odometry>("/Odometry_propagated", 20);')
    anchor='            kf.update_iterated_dyn_share_modified(LASER_POINT_COV, solve_H_time);'
    if code.count(anchor)!=1:raise RuntimeError('FAST-LIO propagation correction anchor changed')
    code=code.replace(anchor,anchor+'\n            if (effct_feat_num > 0) stage3_reset_forward(Measures);')
    mapping.write_text(code)
