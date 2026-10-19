#!/usr/bin/env python3
# Copyright (c) 2026 HOUMO AI
#
# File: test_http.py
# Description:
#   Verify FastAPI vision inference concurrency and request validation.
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
"""FastAPI concurrency and validation regression tests, with no NPU access.

Also run against SAM3 with VISION_APP_DIR=/path/to/sam3_ohos_infer.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.environ.get('VISION_APP_DIR', str(Path(__file__).resolve().parents[1])))
import server
import cv2
import numpy as np


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.calls = 0
        self.worker = SimpleNamespace(process=SimpleNamespace(pid=123, poll=lambda: None))
        def infer(directory):
            self.calls += 1
            self.entered.set()
            if self.block:
                assert self.release.wait(5), 'test thread timed out'
            return {'native_run_ms': 1}
        self.worker.infer = infer
        pipeline = SimpleNamespace(prepare=lambda *a: None,
                                   finish=lambda *a: {'detections': [], 'width': 2, 'height': 2})
        self.lock = threading.Lock()
        self.app = server.create_app(self.worker, pipeline, self.lock, self.temp.name)
        self.route = '/detect' if server.LOG.name == 'grounding_dino' else '/segment'
        _, encoded = cv2.imencode('.png', np.zeros((2, 2, 3), np.uint8))
        self.body = json.dumps({'prompt': 'shoe', 'image_base64': base64.b64encode(encoded).decode()}).encode()

    async def asyncTearDown(self):
        self.release.set()
        async with self.app.router.lifespan_context(self.app):
            pass
        self.temp.cleanup()

    async def http(self, method, path, body=b'', headers=()):
        events = []
        sent = False
        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            await asyncio.sleep(10)
            return {'type': 'http.disconnect'}
        async def send(event):
            events.append(event)
        scope = {'type': 'http', 'method': method, 'path': path, 'headers': list(headers),
                 'query_string': b'', 'scheme': 'http', 'server': ('test', 80), 'http_version': '1.1'}
        await self.app(scope, receive, send)
        return events[0]['status'], json.loads(b''.join(e.get('body', b'') for e in events[1:]))

    async def test_success_validation_limits_and_worker_reuse(self):
        for _ in range(2):
            status, result = await self.http('POST', self.route, self.body)
            self.assertEqual(status, 200)
            self.assertEqual(result['prompt'], 'shoe')
            self.assertNotIn('overlay_png_base64', result)
        self.assertEqual(self.calls, 2)
        if self.route == '/detect':
            self.assertEqual((await self.http('POST', self.route, self.body[:-1]+b',"overlay":true}'))[0], 400)
        for value in [b'{', b'[]', b'{}', b'{"prompt":true}',
                      self.body.replace(b'"shoe"', b'""'),
                      self.body[:-1]+b',"threshold":true}',
                      self.body[:-1]+b',"overlay":"yes"}']:
            self.assertEqual((await self.http('POST', self.route, value))[0], 400)
        self.assertEqual((await self.http('POST', self.route, self.body,
                         [(b'content-length', b'16777217')]))[0], 413)
        previous = server.MAX_BODY
        try:
            server.MAX_BODY = 2
            self.assertEqual((await self.http('POST', self.route, self.body))[0], 413)
        finally:
            server.MAX_BODY = previous
        self.assertEqual((await self.http('GET', '/missing'))[0], 404)
        self.assertFalse(self.lock.locked())

    async def test_health_and_busy_response_during_inference(self):
        self.block = True
        task = asyncio.create_task(self.http('POST', self.route, self.body))
        while not self.entered.is_set():
            await asyncio.sleep(.001)
        started = time.monotonic()
        status, health = await self.http('GET', '/health')
        self.assertEqual(status, 200)
        self.assertTrue(health['busy'])
        self.assertLess(time.monotonic()-started, .1)
        self.assertEqual((await self.http('POST', self.route, self.body))[0], 503)
        self.release.set()
        self.assertEqual((await task)[0], 200)

    async def test_cancelled_request_keeps_lock_until_worker_reply(self):
        self.block = True
        task = asyncio.create_task(self.http('POST', self.route, self.body))
        while not self.entered.is_set():
            await asyncio.sleep(.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.lock.locked())
        self.assertEqual((await self.http('POST', self.route, self.body))[0], 503)
        self.release.set()
        async with self.app.router.lifespan_context(self.app):
            pass
        self.assertFalse(self.lock.locked())
        self.assertEqual((await self.http('POST', self.route, self.body))[0], 200)

    async def test_dino_profile_still_returns_timings(self):
        if self.route != '/detect':
            self.skipTest('DINO profiling only')
        payload = self.body[:-1]+b',"profile":true}'
        status, value = await self.http('POST', self.route, payload)
        self.assertEqual(status, 200)
        self.assertIn('profile_id', value)
        self.assertEqual(value['timings_ms']['native_run_ms'], 1)


if __name__ == '__main__':
    unittest.main()
