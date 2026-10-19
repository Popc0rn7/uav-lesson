#!/usr/bin/env python3
# Copyright (c) 2026 HOUMO AI
#
# File: client.py
# Description:
#   Submit images to the DINO board service and save returned boxes.
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
"""Send an image to the board service; requires only Python's standard library."""
import argparse
import base64
import json
from pathlib import Path
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='For example http://192.168.1.20:8083')
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--threshold', type=float, default=.35)
    parser.add_argument('--output', type=Path, default=Path('grounding_dino_result'))
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args()
    request = urllib.request.Request(args.url.rstrip('/')+'/detect', data=json.dumps({
        'image_base64': base64.b64encode(args.image.read_bytes()).decode('ascii'),
        'prompt': args.prompt, 'threshold': args.threshold,
    }, allow_nan=False).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        parser.exit(1, f'HTTP {exc.code}: {exc.read().decode(errors="replace")}\n')
    except urllib.error.URLError as exc:
        parser.exit(1, f'Cannot reach board service: {exc.reason}\n')
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f'{len(result["detections"])} detections, {result["elapsed_ms"]:.1f} ms; saved to {args.output}')


if __name__ == '__main__':
    main()
