/*
 * Copyright (c) 2026 HOUMO AI
 *
 * File: main.cc
 * Description:
 *   Run DINO HMM inference on OpenHarmony with a resident TCIM worker.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <tcim/tcim_runtime.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <stdexcept>
#include <vector>
namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
double elapsed(Clock::time_point start) {
  return std::chrono::duration<double, std::milli>(Clock::now()-start).count();
}
void check(tcim::Status s) {
  if (s != tcim::Status::OK) {
    throw std::runtime_error("TCIM status " + std::to_string(int(s)));
  }
}
void schema(std::ostream& out, const std::string& name,
            const tcim::TensorInfo& info) {
  if (name.find_first_of("\t\r\n/") != std::string::npos) {
    throw std::runtime_error("Unsafe tensor name");
  }
  out << name << '\t' << int(info.DataType());
  for (auto d : info.Shape()) {
    out << '\t' << d;
  }
  out << '\n';
}
int main(int argc, char** argv) {
  try {
    if (argc < 4 || argc > 6) {
      std::cerr << "Usage: grounding_dino_infer inspect MODEL DIR [DEVICE]\n"
                   "       grounding_dino_infer run MODEL REQUEST_DIR [DEVICE] [REPEAT]\n"
                   "       grounding_dino_infer worker MODEL METADATA_DIR [DEVICE]\n";
      return 2;
    }
    std::string mode = argv[1];
    if (mode != "inspect" && mode != "run" && mode != "worker") {
      throw std::runtime_error("Unknown mode");
    }
    int device = argc > 4 ? std::stoi(argv[4]) : 0;
    int repeat = argc > 5 ? std::stoi(argv[5]) : 1;
    if (repeat < 1 || device < 0) {
      throw std::runtime_error("Invalid repeat/device");
    }
    std::cerr << "TCIM " << tcim::GetVersion() << '\n';
    auto startup_start = Clock::now();
    auto dm = tcim::DevManager::Create(device, "Xh2HalBackend");
    check(dm.GetInitStatus());
    double device_init_ms = elapsed(startup_start);
    auto load_start = Clock::now();
    auto model = tcim::Module::LoadFromFile(argv[2], tcim::Module::Option(dm));
    check(model.GetInitStatus());
    double model_load_ms = elapsed(load_start);
    fs::path dir(argv[3]);
    fs::create_directories(dir);
    std::ofstream inputs(dir / "inputs.tsv"), outputs(dir / "outputs.tsv");
    for (size_t i = 0; i < model.GetInputNum(); ++i) {
      auto name = model.GetInputName(i);
      schema(inputs, name, model.GetInputInfo(name));
    }
    for (size_t i = 0; i < model.GetOutputNum(); ++i) {
      auto name = model.GetOutputName(i);
      schema(outputs, name, model.GetOutputInfo(name));
    }
    if (!inputs || !outputs) {
      throw std::runtime_error("Cannot write tensor metadata");
    }
    std::ofstream startup(dir / "startup.json");
    startup << std::setprecision(10) << "{\"device_init_ms\":" << device_init_ms
            << ",\"model_load_ms\":" << model_load_ms << "}\n";
    startup.close();
    inputs.close();
    outputs.close();
    if (mode == "inspect") {
      return 0;
    }
    auto infer_request = [&](const fs::path& dir) {
      auto request_start = Clock::now();
      double input_set_ms = 0, output_get_ms = 0, output_write_ms = 0;
      std::vector<tcim::Tensor> tensors;
      for (size_t i = 0; i < model.GetInputNum(); ++i) {
        auto name = model.GetInputName(i);
        auto tensor = tcim::Tensor::CreateHostTensor(
            model.GetInputInfo(name).AsContiguous());
        check(tensor.GetInitStatus());
        auto file = dir / ("input_" + std::to_string(i) + ".bin");
        if (fs::file_size(file) != tensor.MemSize()) {
          throw std::runtime_error("Input size mismatch: " + file.string());
        }
        std::ifstream stream(file, std::ios::binary);
        if (!stream.read(static_cast<char*>(tensor.Data()), tensor.MemSize())) {
          throw std::runtime_error("Input read failed");
        }
        auto set_start = Clock::now();
        check(model.SetInput(name, tensor));
        input_set_ms += elapsed(set_start);
        tensors.push_back(tensor);
      }
      double input_total_ms = elapsed(request_start);
      auto start = std::chrono::steady_clock::now();
      for (int i = 0; i < repeat; ++i) {
        check(model.Run(true));
      }
      double run_ms = elapsed(start);
      std::cerr << "run_ms=" << run_ms / repeat << '\n';
      auto output_start = Clock::now();
      for (size_t i = 0; i < model.GetOutputNum(); ++i) {
        auto name = model.GetOutputName(i);
        auto tensor = tcim::Tensor::CreateHostTensor(
            model.GetOutputInfo(name).AsContiguous());
        check(tensor.GetInitStatus());
        auto get_start = Clock::now();
        check(model.GetOutput(name, tensor));
        output_get_ms += elapsed(get_start);
        auto write_start = Clock::now();
        std::ofstream stream(dir / ("output_" + std::to_string(i) + ".bin"),
                             std::ios::binary);
        if (!stream.write(static_cast<const char*>(tensor.Data()),
                          tensor.MemSize())) {
          throw std::runtime_error("Output write failed");
        }
        stream.close();
        if (!stream) throw std::runtime_error("Output close failed");
        output_write_ms += elapsed(write_start);
      }
      double output_total_ms = elapsed(output_start);
      double total_ms = elapsed(request_start);
      std::ofstream profile(dir / "native_timings.json");
      profile << std::setprecision(10)
              << "{\"native_input_allocate_read_ms\":" << input_total_ms-input_set_ms
              << ",\"native_set_input_ms\":" << input_set_ms
              << ",\"native_run_sync_ms\":" << run_ms
              << ",\"native_get_output_ms\":" << output_get_ms
              << ",\"native_output_allocate_ms\":" << output_total_ms-output_get_ms-output_write_ms
              << ",\"native_output_write_ms\":" << output_write_ms
              << ",\"native_total_ms\":" << total_ms << "}\n";
      if (!profile) throw std::runtime_error("Timing write failed");
    };
    if (mode == "worker") {
      std::cout << "DINO_READY" << std::endl;
      std::string request;
      while (std::getline(std::cin, request)) {
        infer_request(fs::path(request));
        std::cout << "DINO_DONE" << std::endl;
      }
    } else {
      infer_request(dir);
    }
  } catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
