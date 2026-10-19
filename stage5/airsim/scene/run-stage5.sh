#!/bin/sh
set -eu
package_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for route in PickupConvoy3Route01 ArmoredConvoy3Route01 VanConvoy3Route01; do
    if [ ! -s "$package_root/demo/Saved/SaveGames/$route.sav" ]; then
        echo "Missing convoy route: demo/Saved/SaveGames/$route.sav" >&2
        exit 1
    fi
done
binary="$package_root/demo/Binaries/Linux/demo-Linux-Shipping"
if [ ! -x "$binary" ]; then
    binary="$package_root/demo/Binaries/Linux/demo"
fi
exec "$binary" demo -UserDir="$package_root/demo/" -settings="$package_root/demo/Config/AirSim/settings.json" "$@"
