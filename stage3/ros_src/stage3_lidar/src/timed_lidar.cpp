#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <livox_ros_driver2/msg/custom_msg.hpp>
#include <gz/transport/Node.hh>
#include <gz/msgs/pointcloud_packed.pb.h>
#include "mid360_pattern.hpp"
#include <mutex>
#include <cstring>
#include <algorithm>

class TimedLidar : public rclcpp::Node {
  gz::transport::Node gz_;
  std::mutex mutex_;
  rclcpp::Publisher<livox_ros_driver2::msg::CustomMsg>::SharedPtr pub_;
  rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr preview_;
  livox_ros_driver2::msg::CustomMsg packet_;
  int64_t previous_=-1,base_=-1;
  double deadline_=0,sensor_z_;
  bool self_filter_;
public:
  TimedLidar():Node("stage3_timed_lidar") {
    sensor_z_=declare_parameter("sensor_z",.335);
    self_filter_=declare_parameter("self_filter",true);
    pub_=create_publisher<livox_ros_driver2::msg::CustomMsg>("/stage3/lio/lidar",20);
    preview_=create_publisher<sensor_msgs::msg::PointCloud2>("/stage3/lidar/filtered",rclcpp::SensorDataQoS());
    if(!gz_.Subscribe("/mid360s/scan/points",&TimedLidar::receive,this))throw std::runtime_error("Gazebo subscribe failed");
  }
  void receive(const gz::msgs::PointCloudPacked &m) {
    std::lock_guard<std::mutex> guard(mutex_);
    const int64_t now=static_cast<int64_t>(m.header().stamp().sec())*1000000000LL+m.header().stamp().nsec();
    if(previous_<0||now<=previous_||now-previous_>200000000LL) {
      packet_.points.clear();base_=-1;deadline_=now*1e-9+1./30.;previous_=now;
      return; // Need two observed snapshots to define the first real interval.
    }
    if(m.is_bigendian()||m.point_step()<12||m.data().size()<static_cast<size_t>(m.row_step())*m.height())return;
    uint32_t offsets[3]={};bool found[3]={};
    for(const auto &f:m.field())for(int i=0;i<3;i++)if(f.name()==std::string(1,"xyz"[i])&&f.datatype()==6&&f.offset()+4<=m.point_step()){offsets[i]=f.offset();found[i]=true;}
    if(!found[0]||!found[1]||!found[2])return;
    // Frame timebase is the beginning of the first observation interval.
    // The ray-cast group occurs at 'now', so its offset is strictly positive.
    // FAST-LIO's backward deskew excludes points with exactly zero offset.
    if(base_<0)base_=previous_;
    const auto cells=mid360_cells(previous_*1e-9,now*1e-9,m.width(),m.height(),false);
    previous_=now;
    for(auto cell:cells) {
      const auto ptr=m.data().data()+(cell/m.width())*m.row_step()+(cell%m.width())*m.point_step();
      float p[3];for(int i=0;i<3;i++)std::memcpy(&p[i],ptr+offsets[i],4);
      if(!std::isfinite(p[0])||!std::isfinite(p[1])||!std::isfinite(p[2]))continue;
      const double r2=p[0]*p[0]+p[1]*p[1]+p[2]*p[2];
      if(r2<.36||r2>=69.9*69.9)continue;
      const double bz=p[2]+sensor_z_;
      if(self_filter_&&std::abs(p[0])<=.34&&std::abs(p[1])<=.34&&bz>=-.235&&bz<=.12)continue;
      livox_ros_driver2::msg::CustomPoint point;
      // Each group was actually ray-cast at 'now'. No invented 5us firing times.
      point.offset_time=static_cast<uint32_t>(now-base_);
      point.x=p[0];point.y=p[1];point.z=p[2];point.reflectivity=100;point.tag=0x10;point.line=0;
      packet_.points.push_back(point);
    }
    if(now*1e-9<deadline_)return;
    while(deadline_<=now*1e-9)deadline_+=1./30.;
    if(!packet_.points.empty()) {
      packet_.header.stamp.sec=base_/1000000000LL;packet_.header.stamp.nanosec=base_%1000000000LL;
      packet_.header.frame_id="mid360s_sensor";packet_.timebase=base_;packet_.point_num=packet_.points.size();
      pub_->publish(packet_);
      sensor_msgs::msg::PointCloud2 cloud;cloud.header=packet_.header;cloud.height=1;cloud.width=packet_.point_num;cloud.point_step=20;cloud.row_step=cloud.width*20;cloud.is_dense=true;
      const char *names[]={"x","y","z","intensity","time"};
      for(int i=0;i<5;i++){sensor_msgs::msg::PointField f;f.name=names[i];f.offset=i*4;f.count=1;f.datatype=7;cloud.fields.push_back(f);}
      cloud.data.resize(cloud.row_step);
      for(size_t i=0;i<packet_.points.size();i++){const auto &p=packet_.points[i];float v[]={p.x,p.y,p.z,100.f,p.offset_time*1e-9f};std::memcpy(cloud.data.data()+i*20,v,20);}
      preview_->publish(std::move(cloud));
    }
    packet_.points.clear();base_=-1;
  }
};
int main(int argc,char **argv){rclcpp::init(argc,argv);rclcpp::spin(std::make_shared<TimedLidar>());rclcpp::shutdown();}
