#!/usr/bin/env python3
# Copyright (c) 2026 HOUMO AI
#
# File: test_server.py
# Description:
#   Verify inference worker lifecycle, IPC isolation and HTTP validation.
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

"""Lifecycle and IPC tests without NPU hardware."""
import asyncio
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Application, Worker, WorkerUnavailable

FAKE_WORKER = r'''
import json, os, sys, time
print('static registration log', flush=True)
print(json.dumps({'type':'ready', 'pid':os.getpid(), 'max_context':4096}), flush=True)
for line in sys.stdin:
    body=json.loads(line)
    prompt=body['prompt']
    if prompt == 'crash': sys.exit(9)
    if prompt in ('slow', 'timeout'): time.sleep(.2)
    print(json.dumps({'status':200, 'body':{'text':prompt, 'pid':os.getpid()}}), flush=True)
'''


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.worker = Worker([sys.executable, '-u', '-c', FAKE_WORKER], request_timeout=2)
        await self.worker.start()
        self.app = Application(self.worker)

    async def asyncTearDown(self):
        await self.worker.stop()
        if self.worker.pending:
            await asyncio.gather(*tuple(self.worker.pending), return_exceptions=True)
        self.assertIsNotNone(self.worker.process.returncode)

    async def http(self, method, path, body=b''):
        events = []
        async def receive():
            return {'type':'http.request', 'body':body, 'more_body':False}
        async def send(event):
            events.append(event)
        await self.app({'type':'http', 'method':method, 'path':path, 'headers':[], 'query_string':b'', 'scheme':'http', 'server':('test',80), 'http_version':'1.1'}, receive, send)
        return events[0]['status'], json.loads(events[1]['body'])

    async def test_reuses_worker_and_rejects_invalid_requests(self):
        pid = self.worker.process.pid
        for prompt in ['你好', 'second']:
            status, body = await self.http('POST', '/infer', json.dumps({'prompt':prompt}).encode())
            self.assertEqual(status, 200)
            self.assertEqual(body, {'text':prompt, 'pid':pid})
        for value in [{}, [], {'prompt':''}, {'prompt':'x','max_new_tokens':True},
                      {'prompt':'x','max_new_tokens':4097}, {'prompt':'x','system_prompt':None},
                      {'prompt':'\ud800'}]:
            status, _ = await self.http('POST','/infer',json.dumps(value).encode())
            self.assertEqual(status, 400)
        self.assertEqual((await self.http('POST','/infer',b'{'))[0],400)
        self.assertEqual((await self.http('POST','/infer',b'x'*(1024*1024+1)))[0],413)
        self.assertEqual((await self.http('GET','/missing'))[0],404)

    async def test_health_during_inference_and_busy_response(self):
        task = asyncio.create_task(self.worker.protected_infer({'prompt':'slow'}))
        while not self.worker.lock.locked(): await asyncio.sleep(0)
        status, health = await self.http('GET','/health')
        self.assertEqual(status,200)
        self.assertTrue(health['busy'])
        status, _ = await self.http('POST','/infer',b'{"prompt":"second"}')
        self.assertEqual(status,429)
        await task

    async def test_cancelled_http_does_not_mix_up_replies(self):
        task = asyncio.create_task(self.worker.protected_infer({'prompt':'slow'}))
        while not self.worker.lock.locked(): await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        await asyncio.gather(*tuple(self.worker.pending))
        _, result = await self.worker.protected_infer({'prompt':'next'})
        self.assertEqual(result['text'],'next')

    async def test_timeout_stops_worker_and_disables_health(self):
        self.worker.request_timeout = .02
        status, _ = await self.http('POST','/infer',b'{"prompt":"timeout"}')
        self.assertEqual(status,504)
        self.assertFalse(self.worker.ready)
        self.assertEqual((await self.http('GET','/health'))[0],503)
        self.assertEqual((await self.http('POST','/infer',b'{"prompt":"next"}'))[0],503)

    async def test_crash_disables_worker(self):
        status, _ = await self.http('POST','/infer',b'{"prompt":"crash"}')
        self.assertEqual(status,503)
        self.assertFalse(self.worker.ready)

    async def test_startup_failure_cleans_up(self):
        other = Worker([sys.executable,'-c','import time; time.sleep(5)'],startup_timeout=.02)
        with self.assertRaises(asyncio.TimeoutError): await other.start()
        self.assertIsNotNone(other.process.returncode)
        other = Worker([sys.executable,'-c','raise SystemExit(2)'])
        with self.assertRaises(WorkerUnavailable): await other.start()
        self.assertIsNotNone(other.process.returncode)


if __name__ == '__main__':
    unittest.main()
