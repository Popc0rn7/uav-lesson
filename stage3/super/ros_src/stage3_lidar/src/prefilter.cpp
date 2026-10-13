#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <cmath>
#include <mutex>
#include "mid360_pattern.hpp"
#include <cstring>
#include <unordered_set>
#include <gz/transport/Node.hh>
#include <gz/msgs/pointcloud_packed.pb.h>

class Prefilter : public rclcpp::Node {
  using Cloud = sensor_msgs::msg::PointCloud2;
  rclcpp::Publisher<Cloud>::SharedPtr pub_;
  gz::transport::Node gz_;
  std::function<void(Cloud::ConstSharedPtr)> filter_;
  double max_,sensor_z_;
  bool self_filter_,pattern_;
  std::mutex scan_mutex_;
  double last_scan_=-1.;
  std::unordered_set<uint64_t> selected_;
public:
  Prefilter() : Node("stage3_dense_scan_prefilter") {
    max_=declare_parameter("range_max",69.9);
    sensor_z_=declare_parameter("sensor_z",.135);
    pattern_=declare_parameter("mid360_pattern",false);
    self_filter_=declare_parameter("self_filter",true);
    pub_=create_publisher<Cloud>("/stage3/lidar/filtered",rclcpp::SensorDataQoS());
    filter_=[this](Cloud::ConstSharedPtr m) {
        if(m->is_bigendian || m->point_step==0 || m->data.size()<m->height*m->row_step) return;
        uint32_t offsets[3]={0,0,0};bool found[3]={false,false,false};
        for(const auto &f:m->fields) for(int i=0;i<3;i++) if(f.name==std::string(1,"xyz"[i]) && f.datatype==7 && f.offset+4<=m->point_step) {offsets[i]=f.offset;found[i]=true;}
        if(!found[0]||!found[1]||!found[2])return;
        Cloud out;out.header=m->header;out.height=1;out.point_step=12;out.is_dense=true;
        for(int i=0;i<3;i++) {sensor_msgs::msg::PointField f;f.name=std::string(1,"xyz"[i]);f.offset=i*4;f.datatype=7;f.count=1;out.fields.push_back(f);}
        std::unordered_set<uint64_t> seen;seen.reserve(50000);out.data.reserve(600000);
        size_t self_points=0;
        for(uint32_t row=0;row<m->height;row++) for(uint32_t col=0;col<m->width;col++) {
          if(pattern_ && !selected_.count(static_cast<uint64_t>(row)*m->width+col))continue;
          auto ptr=m->data.data()+row*m->row_step+col*m->point_step;float p[3];
          for(int i=0;i<3;i++)std::memcpy(&p[i],ptr+offsets[i],4);
          if(!std::isfinite(p[0])||!std::isfinite(p[1])||!std::isfinite(p[2]))continue;
          // X500 conservative body/rotor envelope in FLU base_link. Sensor is
          // configured by sensor_z. This removes returns, never fills occlusions.
          const double base_z=p[2]+sensor_z_;
          if(self_filter_ && std::abs(p[0])<=.34 && std::abs(p[1])<=.34 &&
             base_z>=-.235 && base_z<=.12) {++self_points;continue;}
          double r2=p[0]*p[0]+p[1]*p[1]+p[2]*p[2];if(r2<.36||r2>=max_*max_)continue;
          uint64_t key=0;bool valid=true;
          for(int i=0;i<3;i++) {int64_t q=static_cast<int64_t>(std::floor(p[i]/.1))+(1<<20);if(q<0||q>=(1<<21)){valid=false;break;}key=(key<<21)|static_cast<uint64_t>(q);}
          if(valid&&seen.insert(key).second) {auto n=out.data.size();out.data.resize(n+12);std::memcpy(out.data.data()+n,p,12);}
        }
        out.width=out.data.size()/12;out.row_step=out.data.size();pub_->publish(std::move(out));
        RCLCPP_INFO_THROTTLE(get_logger(),*get_clock(),5000,
          "self_filter=%s body_returns=%zu (before existing 0.6m range filter)",
          self_filter_?"on":"off",self_points);
      };
    if(!gz_.Subscribe("/mid360s/scan/points",&Prefilter::receive,this))throw std::runtime_error("Gazebo cloud subscription failed");
  }
  void receive(const gz::msgs::PointCloudPacked &g) {
    std::lock_guard<std::mutex> guard(scan_mutex_);
    if(pattern_) {
      const double stamp=g.header().stamp().sec()+g.header().stamp().nsec()*1e-9;
      const double begin=(last_scan_<0||stamp<=last_scan_||stamp-last_scan_>.1)?std::max(0.,stamp-1./30.):last_scan_;
      selected_=mid360_cells(begin,stamp,g.width(),g.height());last_scan_=stamp;
    }
    auto m=std::make_shared<Cloud>();
    m->header.stamp.sec=g.header().stamp().sec();m->header.stamp.nanosec=g.header().stamp().nsec();
    m->header.frame_id="mid360s_sensor";
    m->height=g.height();m->width=g.width();m->point_step=g.point_step();m->row_step=g.row_step();m->is_bigendian=g.is_bigendian();
    for(const auto &field:g.field()) {sensor_msgs::msg::PointField f;f.name=field.name();f.offset=field.offset();f.datatype=field.datatype()+1;f.count=field.count();m->fields.push_back(f);}
    m->data.assign(g.data().begin(),g.data().end());filter_(m);
  }
};
int main(int argc,char**argv){rclcpp::init(argc,argv);rclcpp::spin(std::make_shared<Prefilter>());rclcpp::shutdown();}
