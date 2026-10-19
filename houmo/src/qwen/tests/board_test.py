#!/usr/bin/env python3
# Copyright (c) 2026 HOUMO AI
#
# File: board_test.py
# Description:
#   Validate Uvicorn and native Qwen inference on an OpenHarmony NPU board.
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

"""Run on OHOS: real Uvicorn/native/NPU integration test, with process cleanup."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--app-dir', default='/data/houmo/qwen_infer_uvicorn')
parser.add_argument('--port', type=int, default=18082)
args = parser.parse_args()
root = Path(args.app_dir)
log_path = root / 'integration-test.log'
log = log_path.open('w')
process = subprocess.Popen([sys.executable, str(root / 'run.py'), '--serve', '--host', '127.0.0.1',
                            '--port', str(args.port)], stdout=log, stderr=subprocess.STDOUT)
base = f'http://127.0.0.1:{args.port}'
worker_pid = None


def request(path, value=None, expected=200, raw=None, timeout=300):
    data = raw if raw is not None else (json.dumps(value, ensure_ascii=False).encode()
                                        if value is not None else None)
    req = urllib.request.Request(base + path, data=data, headers={'Content-Type':'application/json'})
    before = time.monotonic()
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        result = json.loads(response.read())
        elapsed = time.monotonic() - before
        assert response.status == expected, (response.status, result)
        print(path, response.status, f'{elapsed:.3f}s', json.dumps(result, ensure_ascii=False), flush=True)
        return result


try:
    before = time.monotonic()
    print('Waiting for model loading...', flush=True)
    while time.monotonic() - before < 310:
        if process.poll() is not None:
            raise RuntimeError('service exited during startup')
        try:
            health = request('/health', timeout=2)
            assert health['status'] == 'ready'
            worker_pid = health['worker_pid']
            print(f'Model startup {time.monotonic() - before:.3f}s, worker_pid={worker_pid}', flush=True)
            break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    else:
        raise RuntimeError('startup timeout')
    first = request('/infer', {'prompt':'请只回答数字：1+1等于几？','max_new_tokens':16})
    assert '2' in first['text'] and 0 < first['output_tokens'] <= 16, first
    second = request('/infer', {'prompt':'中国的首都是哪里？请用一句话回答。','max_new_tokens':32})
    assert '北京' in second['text'] and 0 < second['output_tokens'] <= 32, second
    assert request('/health')['worker_pid'] == worker_pid
    for value in [{}, {'prompt':'x','max_new_tokens':True}, {'prompt':'x','system_prompt':None}]:
        request('/infer', value, expected=400)
    request('/infer', expected=400, raw=b'{')
    request('/infer', expected=400, raw=b'{"prompt":"\\ud800"}')
    assert request('/health')['worker_pid'] == worker_pid
    request('/missing', expected=404)
    long_prompt = ('这是用于测试长输入分块的背景资料。\n' * 60) + '请只回答数字：2+3等于几？'
    with ThreadPoolExecutor(max_workers=1) as pool:
        long_request = pool.submit(request, '/infer', {'prompt':long_prompt,'max_new_tokens':16})
        for _ in range(100):
            health = request('/health', timeout=3)
            assert health['worker_pid'] == worker_pid
            if health['busy']:
                request('/infer', {'prompt':'another request'}, expected=429)
                break
            if long_request.done():
                raise AssertionError('long inference finished before concurrency check')
            time.sleep(.01)
        else:
            raise AssertionError('worker never became busy')
        result = long_request.result()
        assert result['input_tokens'] > 256 and '5' in result['text'], result
    assert request('/health')['worker_pid'] == worker_pid
    print('PASS: real NPU outputs, same worker, long prefill, health while busy, HTTP validation', flush=True)
finally:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if worker_pid is not None:
        for _ in range(50):
            if not Path(f'/proc/{worker_pid}').exists():
                break
            time.sleep(.1)
        else:
            # This PID belongs to the worker spawned by this test only.
            os.kill(worker_pid, 9)
            raise AssertionError('worker survived service shutdown')
    log.close()
    text = log_path.read_text(errors='replace')
    print('Service stopped; exit:', process.returncode, flush=True)
    print('Prefill load count:', text.count('Prefill model loaded:'), flush=True)
    print('Decode load count:', text.count('Decode model loaded:'), flush=True)
    print('Log:', log_path, flush=True)
    print('\n'.join(text.splitlines()[-25:]), flush=True)
