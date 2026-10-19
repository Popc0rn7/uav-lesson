cmake_minimum_required(VERSION 3.16)
project(qwen_ohos_infer LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_SYSTEM_NAME STREQUAL "OHOS")
  message(FATAL_ERROR "Use build_ohos.sh with the OpenHarmony Native SDK")
endif()
set(REPO_ROOT "$ENV{MODELZOO_ROOT}")
if(NOT EXISTS "${REPO_ROOT}/utils/cpp/houmo_engine/CMakeLists.txt")
  message(FATAL_ERROR "Set MODELZOO_ROOT to postmo-modelzoo for shared Qwen engine dependencies")
endif()
set(QWEN_DIR "${REPO_ROOT}/models/llm/qwen3.5/cpp")
if(NOT ENGINE_BUILD_DIR)
  message(FATAL_ERROR "ENGINE_BUILD_DIR must point to the built OHOS houmo_engine")
endif()
add_executable(qwen_ohos_infer
  main.cc
  "${QWEN_DIR}/src/qwen35_mllm_model.cc"
  "${QWEN_DIR}/src/qwen35_dynamic_image_processor.cc")
target_include_directories(qwen_ohos_infer PRIVATE
  "${QWEN_DIR}/include"
  "${REPO_ROOT}/utils/cpp/houmo_engine/include"
  "${REPO_ROOT}/3rdparty/tokenizer.cpp/include"
  "${REPO_ROOT}/3rdparty"
  "$ENV{TCIM_RUNTIME_PATH}/include")
target_compile_definitions(qwen_ohos_infer PRIVATE
  EIGEN_MPL2_ONLY EIGEN_NO_OPTIMIZATION_BARRIER)
target_link_directories(qwen_ohos_infer PRIVATE
  "${ENGINE_BUILD_DIR}" "$ENV{TCIM_RUNTIME_PATH}/lib")
target_link_libraries(qwen_ohos_infer PRIVATE
  houmo_infer tokenizer_lib tcim_runtime_lite c++ c++abi)
set_target_properties(qwen_ohos_infer PROPERTIES
  BUILD_WITH_INSTALL_RPATH TRUE INSTALL_RPATH "$ORIGIN/lib")
