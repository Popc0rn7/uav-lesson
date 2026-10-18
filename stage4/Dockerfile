ARG BASE_IMAGE=uav-computer-ros-humble:local
FROM ${BASE_IMAGE}
# Model inference remains in the separately managed AeroVLA service.
RUN apt-get update && apt-get install -y --no-install-recommends python3-pil \
    && rm -rf /var/lib/apt/lists/*
