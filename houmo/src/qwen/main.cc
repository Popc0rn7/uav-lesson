/*
 * Copyright (c) 2026 HOUMO AI
 *
 * File: main.cc
 * Description: Native Qwen3.5/3.6 text inference for RoboPi OpenHarmony.
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

#include <cstdio>
#include <algorithm>
#include <memory>
#include <unistd.h>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include "modules/streaming_decoder.h"
#include "stb/stb_image.h"
#include "nlohmann/json.hpp"
#include "qwen35_mllm_model.h"

namespace fs = std::filesystem;

struct Options {
  fs::path model_dir;
  fs::path embedding_path;
  std::vector<std::string> prompts;
  std::string system_prompt = "You are a helpful assistant.";
  int max_tokens = 128;
  int device = 0;
  bool worker = false;
};

static void usage() {
  std::cout
      << "Usage: qwen_ohos_infer --model-dir DIR (--worker | --prompt TEXT) [options]\n"
      << "  --worker                   Keep model loaded; JSON Lines over stdin/stdout\n"
      << "  --prompt TEXT              Repeat for independent requests\n"
      << "  --prompt-file FILE         Read one complete UTF-8 prompt\n"
      << "  --system-prompt TEXT       Override system message\n"
      << "  --max-new-tokens N         Default: 128\n"
      << "  --device N                 Default: 0\n"
      << "  --embedding FILE           Override FP16 embedding path\n"
      << "  --help                     Show usage\n";
}

static int integer(const std::string& text, int minimum) {
  size_t consumed = 0;
  const int value = std::stoi(text, &consumed);
  if (consumed != text.size() || value < minimum) {
    throw std::runtime_error("invalid integer: " + text);
  }
  return value;
}

static std::string read_file(const fs::path& path) {
  std::ifstream input(path, std::ios::binary);
  if (!input) {
    throw std::runtime_error("cannot read: " + path.string());
  }
  return {std::istreambuf_iterator<char>(input),
          std::istreambuf_iterator<char>()};
}

static Options parse(int argc, char** argv) {
  Options options;
  for (int i = 1; i < argc; ++i) {
    const std::string flag = argv[i];
    if (flag == "--worker") {
      options.worker = true;
      continue;
    }
    if (i + 1 >= argc) {
      throw std::runtime_error("missing value for " + flag);
    }
    const std::string value = argv[++i];
    if (flag == "--model-dir") {
      options.model_dir = value;
    } else if (flag == "--embedding") {
      options.embedding_path = value;
    } else if (flag == "--prompt") {
      options.prompts.push_back(value);
    } else if (flag == "--prompt-file") {
      options.prompts.push_back(read_file(value));
    } else if (flag == "--system-prompt") {
      options.system_prompt = value;
    } else if (flag == "--max-new-tokens") {
      options.max_tokens = integer(value, 1);
    } else if (flag == "--device") {
      options.device = integer(value, 0);
    } else {
      throw std::runtime_error("unknown option: " + flag);
    }
  }
  if (options.model_dir.empty() || (!options.worker && options.prompts.empty())) {
    throw std::runtime_error(
        "--model-dir and either --worker or at least one prompt are required");
  }
  for (const auto& prompt : options.prompts) {
    if (prompt.empty()) {
      throw std::runtime_error("prompt must not be empty");
    }
  }
  return options;
}

static fs::path require_file(const fs::path& path) {
  if (!fs::is_regular_file(path) || fs::file_size(path) == 0) {
    throw std::runtime_error("missing or empty file: " + path.string());
  }
  return path;
}

static fs::path find_graph(const fs::path& root, const std::string& suffix) {
  fs::path result;
  for (const auto& entry : fs::directory_iterator(root)) {
    const std::string name = entry.path().filename().string();
    if (entry.is_regular_file() && name.size() >= suffix.size() &&
        name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0) {
      if (!result.empty()) {
        throw std::runtime_error("multiple " + suffix + " files in " +
                                 root.string());
      }
      result = entry.path();
    }
  }
  if (result.empty()) {
    throw std::runtime_error("no " + suffix + " file in " + root.string());
  }
  return require_file(result);
}

// Match the repository demo's Qwen chat format with thinking disabled.
static std::string render(const Options& options, const std::string& prompt) {
  return "<|im_start|>system\n" + options.system_prompt +
         "<|im_end|>\n<|im_start|>user\n" + prompt +
         "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n";
}

int main(int argc, char** argv) {
  if (argc == 2 && std::string(argv[1]) == "--help") {
    usage();
    return 0;
  }
  try {
    const auto options = parse(argc, argv);
    if (options.worker && !options.prompts.empty()) {
      throw std::runtime_error("--worker cannot be combined with prompts");
    }
    // Reserve the original stdout pipe for protocol replies, then route all
    // model/runtime stdout (including C printf) to stderr.
    std::unique_ptr<FILE, decltype(&std::fclose)> protocol(nullptr, &std::fclose);
    if (options.worker) {
      std::cout.flush();
      std::fflush(stdout);
      const int response_fd = dup(STDOUT_FILENO);
      if (response_fd < 0) throw std::runtime_error("cannot duplicate worker output");
      FILE* response_stream = fdopen(response_fd, "w");
      if (!response_stream) {
        close(response_fd);
        throw std::runtime_error("cannot open worker output");
      }
      protocol.reset(response_stream);
      if (dup2(STDERR_FILENO, STDOUT_FILENO) < 0)
        throw std::runtime_error("cannot redirect worker logs");
    }
    auto reply = [&](const nlohmann::json& value) {
      const auto line = value.dump(-1, ' ', false,
                                  nlohmann::json::error_handler_t::replace) + "\n";
      if (std::fwrite(line.data(), 1, line.size(), protocol.get()) != line.size() ||
          std::fflush(protocol.get()) != 0)
        throw std::runtime_error("worker response pipe closed");
    };
    const auto root = fs::absolute(options.model_dir);
    const auto hf = root / "hmquant/hf_config";
    require_file(hf / "tokenizer.json");
    require_file(hf / "tokenizer_config.json");
    const auto metadata =
        nlohmann::json::parse(read_file(require_file(hf / "config.json")));
    const auto& text = metadata.contains("text_config")
                           ? metadata.at("text_config")
                           : metadata;
    const auto vocab = text.at("vocab_size").get<uint64_t>();
    const auto hidden = text.at("hidden_size").get<uint64_t>();
    const auto embedding = require_file(
        options.embedding_path.empty() ? root / "hmquant/quant_embedding.bin"
                                       : options.embedding_path);
    if (vocab == 0 || hidden == 0 ||
        vocab > std::numeric_limits<uint64_t>::max() / 2 / hidden ||
        fs::file_size(embedding) != vocab * hidden * 2) {
      throw std::runtime_error(
          "embedding must be raw FP16 [vocab_size, hidden_size]");
    }

    houmo::ModelConfig config;
    config.devices = {options.device};
    config.prefill_path = find_graph(root, "_prefill.hmm").string();
    config.decode_path = find_graph(root, "_decode.hmm").string();
    config.embedding_path = embedding.string();
    config.tokenizer_path = hf.string();
    // Match the modelzoo demo: load the available dynamic visual gears.
    for (const auto& entry : fs::directory_iterator(root)) {
      if (entry.path().filename().string().find("_visual_m") != std::string::npos &&
          entry.path().extension() == ".hmm") {
        config.vision_path = root.string();
        break;
      }
    }
    houmo::Qwen35MLLMModel model(config);
    if (!model.tokenizer()) {
      throw std::runtime_error("failed to initialize tokenizer from hf_config");
    }
    if (model.embedding_dim() != static_cast<int>(hidden) ||
        model.vocab_size() != static_cast<int>(vocab)) {
      throw std::runtime_error(
          "loaded graph dimensions do not match hf_config");
    }
    auto infer = [&](const std::string& prompt, const std::string& system,
                     int max_tokens, bool stream, const std::vector<std::string>& images, bool images_in_prompt=false) {
      if (prompt.empty()) throw std::invalid_argument("prompt must not be empty");
      Options request_options = options;
      request_options.system_prompt = system;
      if (!images.empty() && config.vision_path.empty())
        throw std::invalid_argument("visual model is unavailable");
      std::string image_prefix;
      for (const auto& image : images) {
        int width=0, height=0, channels=0;
        if (!stbi_info(image.c_str(), &width, &height, &channels) || width<=0 || height<=0 ||
            static_cast<int64_t>(width)*height > 16000000)
          throw std::invalid_argument("image is invalid or exceeds 16 megapixels");
        image_prefix += "<|vision_start|><|image_pad|><|vision_end|>";
      }
      const auto tokens = model.tokenize(render(request_options, (images_in_prompt ? std::string{} : image_prefix)+prompt), false, false);
      if (tokens.empty() || tokens.size() >= static_cast<size_t>(model.max_ctx_available())) {
        throw std::invalid_argument("prompt is empty or exceeds model context capacity");
      }
      if (static_cast<size_t>(std::count(tokens.begin(),tokens.end(),houmo::IMAGE_TOKEN_ID)) != images.size())
        throw std::invalid_argument("image placeholder count does not match image inputs");
      model.ClearKVCache();
      auto context = model.create_context();
      if (!images.empty()) {
        auto* visual_context = dynamic_cast<houmo::Qwen35MLLMContext*>(context.get());
        if (!visual_context) throw std::runtime_error("visual context unavailable");
        visual_context->set_images(images);
      }
      houmo::SamplingParams sampling;
      sampling.max_tokens = max_tokens;
      sampling.temperature = 0.0f;
      sampling.top_k = 1;
      houmo::StreamingDecoder decoder(model.tokenizer());
      size_t emitted = 0;
      std::string output;
      context->generate(tokens, sampling, [&](houmo::Token token) {
        const auto piece = decoder.decode(token);
        output += piece;
        if (stream) std::cout << piece << std::flush;
        ++emitted;
        return emitted < static_cast<size_t>(max_tokens);
      });
      if (stream) std::cout << "\n";
      const char* reason = emitted >= static_cast<size_t>(max_tokens)
          ? "max_tokens" : (context->context_length() >= model.max_ctx_available()
              ? "context_limit" : "eos_or_bos");
      std::cerr << "input_tokens=" << tokens.size() << " output_tokens=" << emitted
                << " stop_reason=" << reason << "\n";
      context->profiler().print_summary();
      return nlohmann::json{{"text", output}, {"input_tokens", context->perf_stats().n_input_tokens},
                            {"output_tokens", emitted}, {"stop_reason", reason}};
    };
    if (options.worker) {
      reply({{"type", "ready"}, {"pid", getpid()},
             {"max_context", model.max_ctx_available()}, {"vision_enabled", !config.vision_path.empty()}});
      std::string line;
      while (std::getline(std::cin, line)) {
        nlohmann::json result;
        try {
          const auto body = nlohmann::json::parse(line);
          if (!body.is_object() || !body.contains("prompt") || !body.at("prompt").is_string())
            throw std::invalid_argument("prompt must be a string");
          const auto system = body.value("system_prompt", options.system_prompt);
          int limit = options.max_tokens;
          if (body.contains("max_new_tokens")) {
            const auto& value = body.at("max_new_tokens");
            if (!value.is_number_integer() || value < 1 || value > model.max_ctx_available())
              throw std::invalid_argument("max_new_tokens must be a positive integer within context capacity");
            limit = value.get<int>();
          }
          result = {{"status", 200},
                    {"body", infer(body.at("prompt").get<std::string>(), system, limit, false, body.value("image_paths", std::vector<std::string>{}), body.value("images_in_prompt",false))}};
        } catch (const nlohmann::json::exception& error) {
          result = {{"status", 400}, {"body", {{"error", error.what()}}}};
        } catch (const std::invalid_argument& error) {
          result = {{"status", 400}, {"body", {{"error", error.what()}}}};
        } catch (const std::exception& error) {
          result = {{"status", 500}, {"body", {{"error", error.what()}}}};
        }
        reply(result);
      }
    } else {
      for (const auto& prompt : options.prompts)
        infer(prompt, options.system_prompt, options.max_tokens, true, {});
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Error: " << error.what() << "\n";
    return 1;
  }
}
