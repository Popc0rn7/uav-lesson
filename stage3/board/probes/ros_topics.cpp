// RoboPi: bounded, motion-free C++ topic/type registration probe.
#include <iostream>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <std_msgs/msg/string.hpp>
#include <rosgraph_msgs/msg/clock.hpp>
int main(int argc,char** argv) {
  rclcpp::init(argc,argv);
  auto node=std::make_shared<rclcpp::Node>("stage3_topic_probe");
  std::cout << "node ready" << std::endl;
  auto text=node->create_publisher<std_msgs::msg::String>("/stage3/probe/text",10);
  std::cout << "String ready" << std::endl;
  auto points=node->create_publisher<sensor_msgs::msg::PointCloud2>("/stage3/probe/points",10);
  std::cout << "PointCloud2 ready" << std::endl;
  auto markers=node->create_publisher<visualization_msgs::msg::MarkerArray>("/stage3/probe/markers",10);
  std::cout << "MarkerArray ready" << std::endl;
  auto odom=node->create_subscription<nav_msgs::msg::Odometry>("/stage3/probe/odom",10,[](nav_msgs::msg::Odometry::ConstSharedPtr){});
  std::cout << "Odometry ready" << std::endl;
  auto clock=node->create_publisher<rosgraph_msgs::msg::Clock>("/clock",1);
  std::cout << "Clock publisher ready" << std::endl;
  rclcpp::shutdown();
}
