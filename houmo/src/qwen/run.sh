#!/bin/sh
# Compatibility entrypoint; runtime and service control live in run.py.
set -eu
app_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "${PYTHON_BIN:-python3}" "$app_dir/run.py" "$@"
