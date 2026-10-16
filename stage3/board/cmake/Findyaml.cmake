# The target image exports libyaml_vendor but omits libyaml's CMake config.
# Resolve only the verified target snapshot, never a host library.
find_path(yaml_INCLUDE_DIR yaml.h
  PATHS "$ENV{UAV_BOARD_DEPS}/install/include/libyaml_vendor" NO_DEFAULT_PATH)
find_library(yaml_LIBRARY yaml
  PATHS "$ENV{UAV_BOARD_DEPS}/install/lib" NO_DEFAULT_PATH)
include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(yaml REQUIRED_VARS yaml_INCLUDE_DIR yaml_LIBRARY)
if(yaml_FOUND AND NOT TARGET yaml)
  add_library(yaml SHARED IMPORTED)
  set_target_properties(yaml PROPERTIES IMPORTED_LOCATION "${yaml_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${yaml_INCLUDE_DIR}")
endif()
set(yaml_TARGETS yaml)
set(yaml_LIBRARIES "${yaml_LIBRARY}")
set(yaml_INCLUDE_DIRS "${yaml_INCLUDE_DIR}")
