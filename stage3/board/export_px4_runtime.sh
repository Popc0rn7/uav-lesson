#!/bin/sh
# Runs only inside the pinned PX4 source image. Preserve its loader/library ABI.
set -eu
mkdir /px4-runtime
ldd /opt/px4-gazebo/bin/px4 > /px4-runtime/ldd-source.txt
awk '$3 ~ /^\// {print $3} $1 ~ /^\// {print $1}' /px4-runtime/ldd-source.txt |
while IFS= read -r library; do
    cp -L "$library" /px4-runtime/
done
sha256sum /opt/px4-gazebo/bin/px4 /px4-runtime/*.so* > /px4-runtime/SHA256SUMS
