#!/usr/bin/env python3
# Copyright (c) 2026 HOUMO AI
#
# File: prepare_embedding.py
# Description:
#   Export Hub Qwen embedding weights as validated raw FP16 for OHOS inference.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

import argparse
import json
import os
from pathlib import Path
import tempfile


def main():
    parser = argparse.ArgumentParser(description="Export Qwen embedding as raw FP16")
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite: {args.output}")
    import torch

    config = json.loads(
        (args.model_dir / "hmquant/hf_config/config.json").read_text(encoding="utf-8")
    )
    text = config.get("text_config", config)
    expected = (int(text["vocab_size"]), int(text["hidden_size"]))
    source = args.model_dir / "hmquant/quant_embedding.pt"
    # Hub artifacts must be trusted: some releases serialize an Embedding object.
    value = torch.load(source, map_location="cpu", weights_only=False, mmap=True)
    if isinstance(value, dict):
        value = value["weight"]
    elif hasattr(value, "weight"):
        value = value.weight
    if not torch.is_tensor(value) or tuple(value.shape) != expected:
        raise ValueError(f"Expected embedding tensor with shape {expected}")
    value = value.detach()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=args.output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            # Keep conversion and finite-value checks bounded for large vocabularies.
            for start in range(0, expected[0], 1024):
                chunk = value[start:start + 1024].to(
                    dtype=torch.float16, device="cpu"
                ).contiguous()
                if not torch.isfinite(chunk).all():
                    raise ValueError("Embedding contains non-finite FP16 values")
                chunk.numpy().astype("<f2", copy=False).tofile(stream)
        expected_bytes = expected[0] * expected[1] * 2
        if temporary.stat().st_size != expected_bytes:
            raise ValueError("Exported embedding size mismatch")
        # Exclusive publication: an existing file is never replaced.
        os.link(temporary, args.output)
        print(f"{args.output}: shape={expected}, dtype=FP16, bytes={expected_bytes}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
