#!/usr/bin/env python3
# Copyright (c) 2026 HOUMO AI
#
# File: server.py
# Description:
#   Serve end-to-end DINO object detection on the OpenHarmony board.
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
"""Board-local HTTP DINO service with a resident native inference worker."""
import os
os.environ.setdefault('OPENCV_IO_MAX_IMAGE_PIXELS', '16777216')
import argparse
from contextlib import asynccontextmanager
import base64
import binascii
import json
import logging
import math
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import uuid
import asyncio

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, Response
import uvicorn

import cv2
import numpy as np
from pipeline import Pipeline

LOG = logging.getLogger('grounding_dino')
MAX_BODY = 16*1024*1024


class Worker:
    def __init__(self, binary, model, directory, device, timeout):
        self.timeout = timeout
        self.process = subprocess.Popen([str(binary.resolve()), 'worker', str(model.resolve()), str(directory), str(device)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
                                        env={**os.environ, 'LD_PRELOAD': ''})
        self.lines = queue.Queue()
        def read():
            for line in self.process.stdout:
                if line.strip() in ('DINO_READY', 'DINO_DONE'):
                    self.lines.put(line.strip())
                else:
                    LOG.info('worker: %s', line.rstrip())
            self.lines.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            self.wait('DINO_READY')
        except BaseException:
            self.close()
            raise

    def wait(self, expected):
        try:
            value = self.lines.get(timeout=self.timeout)
        except queue.Empty:
            self.close()
            raise RuntimeError('Native worker timed out; restart service') from None
        if value != expected:
            raise RuntimeError('Native worker exited or protocol failed; restart service')

    def infer(self, directory):
        if self.process.poll() is not None:
            raise RuntimeError('Native worker unavailable; restart service')
        self.process.stdin.write(str(directory)+'\n')
        self.process.stdin.flush()
        self.wait('DINO_DONE')
        timing_path = Path(directory)/'native_timings.json'
        return json.loads(timing_path.read_text()) if timing_path.exists() else {}

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.reader.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()


class ProfileResponse(Response):
    async def __call__(self, scope, receive, send):
        write_start = time.perf_counter()
        await super().__call__(scope, receive, send)
        self.timings['response_socket_write_ms'] = (time.perf_counter()-write_start)*1000
        self.timings['server_handler_ms'] = (time.perf_counter()-self.request_started)*1000
        LOG.info('DINO_PROFILE %s', json.dumps({'profile_id': self.profile_id,
                 'response_bytes': len(self.body), 'timings_ms': self.timings}, allow_nan=False))


def profile_response(result, timings, request_started):
    serialize_start = time.perf_counter()
    body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
    timings['response_json_serialize_ms'] = (time.perf_counter()-serialize_start)*1000
    timings['server_to_headers_ms'] = (time.perf_counter()-request_started)*1000
    response = ProfileResponse(body, media_type='application/json', headers={
        'Server-Timing': ', '.join(f'{name};dur={timings[name]:.6f}' for name in
                                  ('response_json_serialize_ms', 'server_to_headers_ms'))})
    response.timings = timings
    response.profile_id = result['profile_id']
    response.request_started = request_started
    return response


def create_app(worker=None, pipeline=None, lock=None, work_dir=None, *, args=None):
    pending = set()
    if lock is None:
        lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        nonlocal worker, pipeline, work_dir
        temporary = None
        try:
            if args is not None:
                args.work_dir.mkdir(parents=True, exist_ok=True)
                temporary = tempfile.TemporaryDirectory(prefix='service-', dir=args.work_dir.resolve())
                work_dir = temporary.name
                worker, pipeline = await run_in_threadpool(load_model, args, work_dir)
            yield
        finally:
            if pending:
                await asyncio.gather(*tuple(pending), return_exceptions=True)
            if args is not None and worker is not None:
                await run_in_threadpool(worker.close)
            if temporary is not None:
                temporary.cleanup()

    app = FastAPI(lifespan=lifespan, title="Grounding DINO", redirect_slashes=False)

    @app.get('/health')
    async def health():
        ready = worker.process.poll() is None
        return JSONResponse({'ready': ready, 'busy': lock.locked(),
                             'worker_pid': worker.process.pid}, status_code=200 if ready else 503)

    def infer(body, timings, request_started):
        stage_start = time.perf_counter()
        data = json.loads(body)
        timings['request_json_parse_ms'] = (time.perf_counter()-stage_start)*1000
        stage_start = time.perf_counter()
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object')
        prompt = data.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4096:
            raise ValueError('prompt must be a nonempty string up to 4096 characters')
        threshold = data.get('threshold', .35)
        if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError('threshold must be between 0 and 1')
        overlay = data.get('overlay', False)
        if type(overlay) is not bool:
            raise ValueError('overlay must be boolean')
        if overlay:
            raise ValueError('Only detection JSON is supported; omit overlay or set it to false')
        profile = data.get('profile', False)
        if type(profile) is not bool:
            raise ValueError('profile must be boolean')
        encoded = data.get('image_base64')
        if not isinstance(encoded, str):
            raise ValueError('image_base64 must contain a base64 PNG or JPEG')
        timings['request_validate_ms'] = (time.perf_counter()-stage_start)*1000
        stage_start = time.perf_counter()
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('Invalid image_base64') from None
        timings['image_base64_decode_ms'] = (time.perf_counter()-stage_start)*1000
        stage_start = time.perf_counter()
        try:
            image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        except cv2.error:
            raise ValueError('Cannot decode image or image exceeds pixel limit') from None
        if image is None or image.size == 0:
            raise ValueError('Cannot decode image')
        timings['image_decode_ms'] = (time.perf_counter()-stage_start)*1000
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix='request-', dir=work_dir) as temp:
            timings['temp_create_ms'] = (time.perf_counter()-started)*1000
            stage_start = time.perf_counter()
            pipeline.prepare(temp, image, prompt, timings)
            timings['prepare_total_ms'] = (time.perf_counter()-stage_start)*1000
            stage_start = time.perf_counter()
            timings.update(worker.infer(temp))
            timings['worker_roundtrip_ms'] = (time.perf_counter()-stage_start)*1000
            stage_start = time.perf_counter()
            result = pipeline.finish(temp, image, threshold, False, timings)
            timings['finish_total_ms'] = (time.perf_counter()-stage_start)*1000
            cleanup_start = time.perf_counter()
        timings['temp_cleanup_ms'] = (time.perf_counter()-cleanup_start)*1000
        result.update(prompt=prompt, elapsed_ms=(time.perf_counter()-started)*1000)
        timings['server_before_json_ms'] = (time.perf_counter()-request_started)*1000
        if profile:
            result['profile_id'] = uuid.uuid4().hex
            result['timings_ms'] = dict(timings)
        return profile_response(result, timings, request_started) if profile else JSONResponse(result)

    @app.post('/detect')
    async def inference(request: Request):
        request_started = time.perf_counter()
        timings = {}
        if not lock.acquire(blocking=False):
            return JSONResponse({'error': 'Model busy; retry after current request'}, status_code=503)
        handed_off = False
        try:
            # Limit streamed bytes as well as Content-Length; never buffer an unbounded body.
            length = request.headers.get('content-length')
            if length is not None and not 0 < int(length) <= MAX_BODY:
                return JSONResponse({'error': 'Body must be between 1 byte and 16 MiB'}, status_code=413)
            async def read_body():
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_BODY:
                        return None
                return body
            stage_start = time.perf_counter()
            body = await asyncio.wait_for(read_body(), timeout=30)
            timings['request_body_read_ms'] = (time.perf_counter()-stage_start)*1000
            if body is None or not body:
                return JSONResponse({'error': 'Body must be between 1 byte and 16 MiB'}, status_code=413)
            if length is not None and len(body) != int(length):
                raise ValueError('Incomplete request body')
            # Blocking native IPC and CPU preprocessing must not block the event loop.
            # Shield the thread task so HTTP cancellation cannot release the model
            # lock or remove files before the native response has been consumed.
            async def exchange():
                try:
                    return await run_in_threadpool(infer, body, timings, request_started)
                finally:
                    lock.release()
            task = asyncio.create_task(exchange())
            pending.add(task)
            def done(completed):
                pending.discard(completed)
                if not completed.cancelled():
                    completed.exception()
            task.add_done_callback(done)
            handed_off = True
            return await asyncio.shield(task)
        except (ValueError, UnicodeError, KeyError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=400)
        except asyncio.TimeoutError:
            return JSONResponse({'error': 'Request body receive timeout'}, status_code=408)
        except ClientDisconnect:
            return Response(status_code=499)
        except Exception:
            LOG.exception('Inference failed')
            return JSONResponse({'error': 'Inference failed; check board service log'}, status_code=500)
        finally:
            if not handed_off:
                lock.release()
    return app


def load_model(args, metadata):
    service_start = time.perf_counter()
    worker = Worker(args.binary, args.model, metadata, args.device, args.timeout)
    worker_startup_ms = (time.perf_counter()-service_start)*1000
    try:
        pipeline_start = time.perf_counter()
        pipeline = Pipeline(metadata, args.tokenizer)
        pipeline_startup_ms = (time.perf_counter()-pipeline_start)*1000
        LOG.info('Model loaded, worker PID=%s', worker.process.pid)
        startup_path = Path(metadata)/'startup.json'
        startup = json.loads(startup_path.read_text()) if startup_path.exists() else {}
        startup.update(worker_startup_ms=worker_startup_ms, pipeline_startup_ms=pipeline_startup_ms,
                       ready_after_worker_start_ms=(time.perf_counter()-service_start)*1000)
        LOG.info('DINO_STARTUP %s', json.dumps(startup))
        return worker, pipeline
    except BaseException:
        worker.close()
        raise


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--binary', type=Path, default=here/'grounding_dino_infer')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8083)
    parser.add_argument('--device', type=int, default=0)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--work-dir', type=Path, default=here/'work')
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('timeout must be positive')
    logging.basicConfig(level=logging.INFO)
    app = create_app(args=args)
    uvicorn.run(app, host=args.host, port=args.port, workers=1,
                loop='asyncio', http='h11', ws='none', lifespan='on',
                timeout_graceful_shutdown=int(args.timeout)+30)


if __name__ == '__main__':
    main()
