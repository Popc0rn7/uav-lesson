# syntax=docker/dockerfile:1
# PC Linux 算力开发环境；不包含 OpenHarmony 产物或具体算法工作区。
ARG HUMBLE_IMAGE=osrf/ros@sha256:1ee56d3ee5111f81e0a2a17b6ecd73447afb5c5b8a3c3574754f2646da9aee34
FROM ${HUMBLE_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG PX4_MSGS_COMMIT=57f88be3c01a8c593c23507e4ca136767115ca22
ARG XRCE_AGENT_COMMIT=57d086216d01ec43121845d385894a25987f8a2c
ARG BUILD_JOBS=2
ARG DEV_UID=1000
ARG DEV_GID=1000

RUN printf 'Acquire::Retries "3";\nAcquire::http::Timeout "30";\nAcquire::https::Timeout "30";\n' > /etc/apt/apt.conf.d/80uav-retry \
    && find /etc/apt -maxdepth 2 -type f \( -name '*.list' -o -name '*.sources' \) \
       -exec sed -i 's|http://|https://|g' {} + \
    && apt-get update && apt-get install -y --no-install-recommends \
       ca-certificates curl gnupg git cmake build-essential pkg-config \
       python3-colcon-common-extensions python3-pytest python3-yaml python3-numpy \
       libeigen3-dev libompl-dev libpcl-dev libyaml-cpp-dev libdw-dev libspdlog-dev \
       ros-humble-pcl-conversions ros-humble-pcl-ros ros-humble-tf2-ros \
       ros-humble-rclcpp-components ros-humble-rosidl-default-generators \
       ros-humble-rmw-fastrtps-cpp ros-humble-fastcdr ros-humble-fastrtps \
    && rm -rf /var/lib/apt/lists/*

# Humble 默认桥接 Fortress；当前 Docker 1 是 Harmonic，必须使用匹配桥接包。
# https://gazebosim.org/docs/harmonic/ros_installation/
RUN curl --retry 3 --retry-all-errors -fsSL https://packages.osrfoundation.org/gazebo.gpg \
       | gpg --dearmor -o /usr/share/keyrings/gazebo-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gazebo-archive-keyring.gpg] https://packages.osrfoundation.org/gazebo/ubuntu-stable jammy main" \
       > /etc/apt/sources.list.d/gazebo-stable.list \
    && apt-get update && apt-get install -y --no-install-recommends \
       ros-humble-ros-gzharmonic-bridge libgz-transport13-dev libgz-msgs10-dev \
    && rm -rf /var/lib/apt/lists/*

# v2.4.2 使用 Humble 自带 Fast DDS / Fast CDR，不另建一套通信运行库。
# 版本依据：GCOPTER/integration/transport.md；许可证 Apache-2.0。
RUN git init /tmp/xrce-agent \
    && git -C /tmp/xrce-agent remote add origin https://github.com/eProsima/Micro-XRCE-DDS-Agent.git \
    && git -C /tmp/xrce-agent fetch --depth 1 origin ${XRCE_AGENT_COMMIT} \
    && git -C /tmp/xrce-agent checkout --detach FETCH_HEAD \
    && source /opt/ros/humble/setup.bash \
    && cmake -S /tmp/xrce-agent -B /tmp/xrce-build -DCMAKE_BUILD_TYPE=Release \
       -DUAGENT_SUPERBUILD=OFF -DUAGENT_USE_SYSTEM_FASTDDS=ON \
       -DUAGENT_USE_SYSTEM_FASTCDR=ON -DUAGENT_USE_SYSTEM_LOGGER=ON \
       -DUAGENT_P2P_PROFILE=OFF -DUAGENT_CED_PROFILE=OFF \
    && cmake --build /tmp/xrce-build -j${BUILD_JOBS} \
    && cmake --install /tmp/xrce-build && ldconfig \
    && rm -rf /tmp/xrce-agent /tmp/xrce-build

RUN git init /opt/px4_ws/src/px4_msgs \
    && git -C /opt/px4_ws/src/px4_msgs remote add origin https://github.com/PX4/px4_msgs.git \
    && git -C /opt/px4_ws/src/px4_msgs fetch --depth 1 origin ${PX4_MSGS_COMMIT} \
    && git -C /opt/px4_ws/src/px4_msgs checkout --detach FETCH_HEAD \
    && source /opt/ros/humble/setup.bash \
    && cd /opt/px4_ws && CMAKE_BUILD_PARALLEL_LEVEL=${BUILD_JOBS} colcon build \
       --executor sequential --cmake-args -DBUILD_TESTING=OFF \
    && rm -rf build log

ARG HUMBLE_IMAGE
LABEL org.opencontainers.image.title="uav-computer-ros-humble" \
      org.opencontainers.image.description="Humble 算力开发环境：PX4 DDS、Harmonic 接入、SUPER/FAST-LIO2 依赖"
RUN apt-get update && apt-get install -y --no-install-recommends python3-scipy \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/uav \
    && printf 'humble_image=%s\npx4_msgs=%s\nxrce_agent=%s\n' \
       "${HUMBLE_IMAGE}" "${PX4_MSGS_COMMIT}" "${XRCE_AGENT_COMMIT}" > /opt/uav/sources.txt \
    && dpkg-query -W > /opt/uav/packages.tsv \
    && groupadd -g ${DEV_GID} developer \
    && useradd -m -u ${DEV_UID} -g ${DEV_GID} developer
COPY entrypoint.sh /usr/local/bin/uav-computer-entrypoint
COPY check_runtime.py /opt/uav/check_runtime.py
ENV ROS_DOMAIN_ID=10 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
    GZ_PARTITION=uav-stage3 ROS_LOG_DIR=/tmp/uav-ros-logs PYTHONDONTWRITEBYTECODE=1
USER developer
WORKDIR /home/developer
ENTRYPOINT ["/bin/bash", "/usr/local/bin/uav-computer-entrypoint"]
CMD ["sleep", "infinity"]
