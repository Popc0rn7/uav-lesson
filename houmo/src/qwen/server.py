#!/usr/bin/env python3
# Copyright (c) 2026 HOUMO AI
#
# File: server.py
# Description:
#   Serve HTTP with Uvicorn and one resident native Qwen inference worker.
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

"""Uvicorn HTTP service backed by one resident native Qwen inference worker."""

import argparse
import base64
import binascii
import tempfile
import time
import uuid
import asyncio
import fcntl
import json
import logging
from pathlib import Path
import socket
import sys

LOG = logging.getLogger("qwen.server")
MAX_BODY = 1024 * 1024


class WorkerUnavailable(RuntimeError):
    pass


class WorkerTimeout(RuntimeError):
    pass


class WorkerBusy(RuntimeError):
    pass


class Worker:
    def __init__(self, command, startup_timeout=300, request_timeout=300):
        self.command = command
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self.process = None
        self.metadata = None
        self.lock = asyncio.Lock()
        self.pending = set()

    @property
    def ready(self):
        return (self.metadata is not None and self.process is not None
                and self.process.returncode is None)

    async def start(self):
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, limit=16 * 1024 * 1024)
            await asyncio.wait_for(self._read_ready(), self.startup_timeout)
        except BaseException:
            await self.stop()
            raise
        LOG.info("Model ready: worker_pid=%s max_context=%s",
                 self.metadata["pid"], self.metadata["max_context"])

    async def _read_ready(self):
        while True:
            line = await self.process.stdout.readline()
            if not line:
                raise WorkerUnavailable("inference worker exited during model loading")
            # Static library registration may log before native main redirects stdout.
            try:
                value = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                LOG.info("worker startup: %s", line.decode(errors="replace").rstrip())
                continue
            if (isinstance(value, dict) and value.get("type") == "ready"
                    and value.get("pid") == self.process.pid
                    and type(value.get("max_context")) is int
                    and value["max_context"] > 0):
                self.metadata = value
                return
            raise WorkerUnavailable("invalid inference worker startup response")

    async def stop(self):
        self.metadata = None
        process = self.process
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 10)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

    async def _exchange(self, body):
        self.process.stdin.write(json.dumps(body, ensure_ascii=False).encode() + b"\n")
        await self.process.stdin.drain()
        line = await self.process.stdout.readline()
        if not line:
            raise WorkerUnavailable("inference worker exited")
        value = json.loads(line)
        if (not isinstance(value, dict) or value.get("status") not in (200, 400, 500)
                or not isinstance(value.get("body"), dict)):
            raise WorkerUnavailable("invalid inference worker response")
        return value["status"], value["body"]

    async def infer(self, body):
        if not self.ready:
            raise WorkerUnavailable("inference worker is unavailable; restart service")
        if self.lock.locked():
            raise WorkerBusy("another inference is running; retry later")
        async with self.lock:
            try:
                return await asyncio.wait_for(self._exchange(body), self.request_timeout)
            except asyncio.TimeoutError as error:
                # Never reuse a pipe with an outstanding response after timeout.
                await self.stop()
                raise WorkerTimeout("inference timed out; restart service") from error
            except (WorkerUnavailable, OSError, ValueError) as error:
                await self.stop()
                raise WorkerUnavailable("inference worker failed; restart service") from error

    async def protected_infer(self, body, image_files=()):
        # A disconnected/cancelled HTTP task must not leave a reply in the pipe
        # for the next request. Let the current exchange finish under its lock.
        async def exchange():
            try:
                return await self.infer(body)
            finally:
                for path in image_files:
                    Path(path).unlink(missing_ok=True)
        task = asyncio.create_task(exchange())
        self.pending.add(task)

        def done(completed):
            self.pending.discard(completed)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(done)
        return await asyncio.shield(task)


async def respond(send, status, value):
    payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
    headers = [(b"content-type", b"application/json; charset=utf-8"),
               (b"content-length", str(len(payload)).encode("ascii"))]
    if status == 429:
        headers.append((b"retry-after", b"1"))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})



def prepare_request(value, openai, model_name):
    """Normalize the supported single-turn APIs; image input is inline PNG/JPEG only."""
    if not isinstance(value, dict):
        raise ValueError("request must be a JSON object")
    if openai:
        if value.get('stream', False):
            raise ValueError('streaming is not supported')
        if value.get('model',model_name) != model_name:
            raise ValueError('unknown model; query GET /v1/models')
        if value.get('temperature') not in (None,0) or value.get('top_p') not in (None,1):
            raise ValueError('only greedy decoding is supported: temperature=0, top_p=1')
        if value.get('n',1)!=1:raise ValueError('only n=1 is supported')
        if 'max_tokens' in value and 'max_completion_tokens' in value:
            raise ValueError('use max_tokens or max_completion_tokens, not both')
        for option in ('tools','tool_choice','response_format','stop','logprobs','top_logprobs','logit_bias','presence_penalty','frequency_penalty','seed'):
            if value.get(option) is not None:raise ValueError('unsupported option: '+option)
        messages=value.get('messages')
        if not isinstance(messages,list) or not messages:
            raise ValueError('messages must be a nonempty list')
        systems=[];users=[];images=[]
        for message in messages:
            if not isinstance(message,dict):raise ValueError('invalid message')
            role,content=message.get('role'),message.get('content')
            if role=='system' and isinstance(content,str):systems.append(content)
            elif role=='user':users.append(content)
            else:raise ValueError('only system messages and one user turn are supported')
        if len(users)!=1:raise ValueError('exactly one user message is required')
        content=users[0];texts=[]
        if isinstance(content,str):texts.append(content)
        elif isinstance(content,list):
            for part in content:
                if not isinstance(part,dict):raise ValueError('invalid user content')
                if part.get('type')=='text' and isinstance(part.get('text'),str):texts.append(part['text'])
                elif part.get('type')=='image_url' and isinstance(part.get('image_url'),dict):
                    detail=part['image_url'].get('detail','auto')
                    if detail!='auto':raise ValueError('only image detail=auto is supported')
                    images.append(part['image_url'].get('url'))
                    texts.append('<|vision_start|><|image_pad|><|vision_end|>')
                else:raise ValueError('only text and inline image_url content are supported')
        else:raise ValueError('invalid user content')
        body={'prompt':'\n'.join(texts),'images':images}
        if images:body['images_in_prompt']=True
        if systems:body['system_prompt']='\n'.join(systems)
        if 'max_tokens' in value:body['max_new_tokens']=value['max_tokens']
        elif 'max_completion_tokens' in value:body['max_new_tokens']=value['max_completion_tokens']
    else:
        if set(value)-{'prompt','system_prompt','max_new_tokens','images','image'}:
            raise ValueError('unsupported request fields; use images with inline data URLs')
        body=dict(value)
        images=body.pop('images',[])
        if 'image' in body:
            if images:raise ValueError('use image or images, not both')
            images=[body.pop('image')]
        body['images']=images
    if not isinstance(body.get('prompt'),str) or not body['prompt'].strip():
        raise ValueError('prompt must be a nonempty string')
    if not isinstance(body['images'],list) or len(body['images'])>4:
        raise ValueError('images must be an array of at most 4 inline images')
    decoded=[]
    for image in body.pop('images'):
        if not isinstance(image,str) or ',' not in image:raise ValueError('image must be a base64 PNG/JPEG data URL')
        header,encoded=image.split(',',1)
        if header not in ('data:image/png;base64','data:image/jpeg;base64'):
            raise ValueError('only inline PNG/JPEG images are supported; remote URLs are not fetched')
        try:raw=base64.b64decode(encoded,validate=True)
        except (ValueError,binascii.Error):raise ValueError('invalid base64 image') from None
        if not (raw.startswith(b'\x89PNG\r\n\x1a\n') if 'png' in header else raw.startswith(b'\xff\xd8\xff')):
            raise ValueError('image bytes do not match PNG/JPEG type')
        decoded.append((raw,'.png' if 'png' in header else '.jpg'))
    return body,decoded


def openai_response(result,model_name):
    input_tokens=result.get('input_tokens',0);output_tokens=result.get('output_tokens',0)
    return {'id':'chatcmpl-'+uuid.uuid4().hex,'object':'chat.completion','created':int(time.time()),
        'model':model_name,'choices':[{'index':0,'message':{'role':'assistant','content':result['text']},
        'finish_reason':'length' if result.get('stop_reason')=='max_tokens' else 'stop'}],
        'usage':{'prompt_tokens':input_tokens,'completion_tokens':output_tokens,'total_tokens':input_tokens+output_tokens}}


class Application:
    def __init__(self, worker, model_name="qwen"):
        self.worker = worker
        self.model_name = model_name

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.lifespan(receive, send)
        elif scope["type"] == "http":
            await self.http(scope, receive, send)

    async def lifespan(self, receive, send):
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                try:
                    await self.worker.start()
                except Exception as error:
                    LOG.exception("model startup failed")
                    await send({"type": "lifespan.startup.failed", "message": str(error)})
                    return
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                await self.worker.stop()
                if self.worker.pending:
                    await asyncio.gather(*tuple(self.worker.pending), return_exceptions=True)
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def http(self, scope, receive, send):
        method, path = scope["method"], scope["path"]
        openai=path=="/v1/chat/completions"
        async def reply(status,value):
            if openai and status>=400 and isinstance(value.get('error'),str):
                value={'error':{'message':value['error'],
                    'type':'invalid_request_error' if status<500 else 'server_error',
                    'param':None,'code':str(status)}}
            await respond(send,status,value)
        if method == "GET" and path == "/health":
            ready = self.worker.ready
            await reply( 200 if ready else 503,
                          {"status": "ready" if ready else "unavailable",
                           "worker_pid": self.worker.process.pid if self.worker.process else None,
                           "model": self.model_name,
                           "busy": self.worker.lock.locked(), "vision_enabled": self.worker.metadata.get("vision_enabled",False) if self.worker.metadata else False})
            return
        if method=="GET" and path=="/v1/models":
            await reply(200,{"object":"list","data":[{"id":self.model_name,"object":"model","owned_by":"local"}]})
            return
        openai = path=="/v1/chat/completions"
        if method != "POST" or path not in ("/infer","/v1/chat/completions"):
            await reply( 404, {"error": "use GET /health, GET /v1/models, POST /infer or POST /v1/chat/completions"})
            return
        if not self.worker.ready:
            await reply( 503, {"error": "inference worker unavailable"})
            return
        try:
            body = await asyncio.wait_for(self.read_body(receive), 30)
        except asyncio.TimeoutError:
            await reply( 408, {"error": "request body receive timeout"})
            return
        if body is None:  # Client disconnected.
            return
        if len(body) > MAX_BODY:
            await reply( 413, {"error": "body exceeds 1 MiB"})
            return
        if not self.worker.ready:
            await reply( 503, {"error": "inference worker unavailable"})
            return
        try:
            value,images = prepare_request(json.loads(body),openai,self.model_name)
            if images and not self.worker.metadata.get("vision_enabled",False):
                raise ValueError("this worker has no loaded visual graph")
            if not isinstance(value, dict):
                raise ValueError("request must be a JSON object")
            if not isinstance(value.get("prompt"), str) or not value["prompt"]:
                raise ValueError("prompt must be a nonempty string")
            if "system_prompt" in value and not isinstance(value["system_prompt"], str):
                raise ValueError("system_prompt must be a string")
            if "max_new_tokens" in value:
                limit = value["max_new_tokens"]
                if (type(limit) is not int or limit < 1
                        or limit > self.worker.metadata["max_context"]):
                    raise ValueError("max_new_tokens must be a positive integer within context capacity")
            # Reject escaped lone surrogates before writing to the native pipe.
            json.dumps(value, ensure_ascii=False).encode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            await reply( 400, {"error": str(error)})
            return
        image_files=[]
        try:
            for raw,suffix in images:
                with tempfile.NamedTemporaryFile(prefix='qwen-vqa-',suffix=suffix,delete=False) as image:
                    image_files.append(image.name)
                    image.write(raw)
        except OSError:
            for path in image_files:Path(path).unlink(missing_ok=True)
            await reply(500,{'error':'could not stage image input'})
            return
        if image_files:value['image_paths']=image_files
        try:
            status, result = await self.worker.protected_infer(value,image_files)
        except WorkerBusy as error:
            status, result = 429, {"error": str(error)}
        except WorkerTimeout as error:
            status, result = 504, {"error": str(error)}
        except WorkerUnavailable as error:
            status, result = 503, {"error": str(error)}
        if openai and status==200:result=openai_response(result,self.model_name)
        await reply( status, result)

    @staticmethod
    async def read_body(receive):
        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return None
            body.extend(event.get("body", b""))
            if len(body) > MAX_BODY or not event.get("more_body", False):
                return body


def positive(text):
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--executable", default=str(Path(__file__).resolve().with_name("qwen_ohos_infer")))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=positive, default=8080)
    parser.add_argument("--max-new-tokens", type=positive, default=128)
    parser.add_argument("--system-prompt", default="You are a helpful assistant.")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--embedding")
    parser.add_argument("--startup-timeout", type=positive, default=300)
    parser.add_argument("--request-timeout", type=positive, default=300)
    args = parser.parse_args()
    if args.port > 65535 or args.device < 0:
        parser.error("port must be <=65535 and device must be >=0")
    command = [args.executable, "--worker", "--model-dir", args.model_dir,
               "--max-new-tokens", str(args.max_new_tokens),
               "--system-prompt", args.system_prompt, "--device", str(args.device)]
    if args.embedding:
        command.extend(["--embedding", args.embedding])
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    # Keep this lock for the whole service lifetime, including model loading.
    # It also protects direct server.py launches and launches on another port.
    with Path(__file__).resolve().with_name("server-instance.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Service already running in this deployment directory") from error
        family = socket.AF_INET6 if ":" in args.host else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind((args.host, args.port))
                listener.listen(2048)
            except OSError as error:
                raise RuntimeError(f"Cannot listen on {args.host}:{args.port}: {error}; model not loaded") from error
            config = uvicorn.Config(
                Application(Worker(command, args.startup_timeout, args.request_timeout), Path(args.model_dir).name.split("_w")[0]),
                host=args.host, port=args.port, workers=1, loop="asyncio", http="h11",
                ws="none", lifespan="on", timeout_graceful_shutdown=10)
            uvicorn.Server(config).run(sockets=[listener])


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
