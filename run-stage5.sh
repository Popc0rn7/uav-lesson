#!/bin/sh
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$repo_root"
if [ "$#" -eq 0 ]; then set -- up; fi
exec "$repo_root/.venv/bin/python" -m stage5.airsim.runtime "$@"
