#!/usr/bin/env bash
# PC：显式 OHOS 依赖；编译输出全部写入 houmo/build。
set -euo pipefail
compile_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
houmo_dir="$(cd "$compile_dir/../.." && pwd)"
service="${1:?Usage: bash houmo/src/compile/build.sh qwen|dino|aerovla}"
case "$service" in
    aerovla) echo 'AeroVLA 使用现有 tcim_lite Python runtime，无独立 C++ 编译；请准备三个 HMM 后装配。'; exit 0 ;;
    qwen|dino) ;;
    *) echo 'Expected qwen, dino or aerovla' >&2; exit 1 ;;
esac
OHOS_SDK="$(python3 "$compile_dir/config.py" OHOS_SDK)"
TCIM_RUNTIME_PATH="$(python3 "$compile_dir/config.py" TCIM_RUNTIME_PATH)"
export OHOS_SDK TCIM_RUNTIME_PATH
for required in "$OHOS_SDK/build/cmake/ohos.toolchain.cmake" "$OHOS_SDK/llvm/bin/clang" \
    "$TCIM_RUNTIME_PATH/include/tcim/tcim_runtime.h" "$TCIM_RUNTIME_PATH/lib/libtcim_runtime_lite.so"; do
    test -f "$required" || { echo "Missing: $required" >&2; exit 1; }
done
build_dir="$houmo_dir/build/$service"
common=(-DCMAKE_TOOLCHAIN_FILE="$OHOS_SDK/build/cmake/ohos.toolchain.cmake" -DOHOS_ARCH=arm64-v8a
    -DCMAKE_SYSTEM_PROCESSOR=aarch64 -DCMAKE_BUILD_TYPE=Release)
extra=()
if [[ "$service" == qwen ]]; then
    MODELZOO_ROOT="$(python3 "$compile_dir/config.py" HOUMO_MODELZOO_ROOT)"
    export MODELZOO_ROOT
    export HOUMO_EXAMPLES_PATH="$MODELZOO_ROOT" HOUMO_TARGET=xh2
    common+=(-DCMAKE_BUILD_WITH_INSTALL_RPATH=TRUE '-DCMAKE_INSTALL_RPATH=$ORIGIN' -DCMAKE_CXX_FLAGS=-DEIGEN_NO_OPTIMIZATION_BARRIER)
    cmake -S "$MODELZOO_ROOT/utils/cpp/houmo_engine" -B "$build_dir/engine" "${common[@]}"
    cmake --build "$build_dir/engine" --parallel "${BUILD_JOBS:-4}"
    extra+=(-DENGINE_BUILD_DIR="$build_dir/engine")
fi
cmake -S "$houmo_dir/src/$service" -B "$build_dir/cmake" "${common[@]}" "${extra[@]}"
cmake --build "$build_dir/cmake" --parallel "${BUILD_JOBS:-4}"
if [[ "$service" == qwen ]]; then
    cp "$build_dir/cmake/qwen_ohos_infer" "$build_dir/"
    mkdir -p "$build_dir/lib"
    cp "$build_dir/engine/libhoumo_infer.so" "$build_dir/engine/libtokenizer_lib.so" "$build_dir/lib/"
else
    cp "$build_dir/cmake/grounding_dino_infer" "$build_dir/"
fi
echo "Built: $build_dir; run python3 houmo/src/compile/package_runtime.py --service $service"
