#!/usr/bin/env python3
# Copyright (c) 2026 HOUMO AI
#
# File: test_server_startup.py
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

"""Real Uvicorn startup tests with a fake native worker and no NPU access."""
import fcntl
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request


@unittest.skipUnless(importlib.util.find_spec("uvicorn") and importlib.util.find_spec("fastapi"),
                     "FastAPI/Uvicorn required for startup integration")
class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        source = Path(__file__).resolve().parents[1] / "server.py"
        shutil.copy2(source, self.root / "server.py")
        self.marker = self.root / "worker-started"
        self.worker = self.root / "fake-worker"
        self.worker.write_text("#!" + sys.executable + "\n" +
            "import json,os,sys\nfrom pathlib import Path\n" +
            "Path(__file__).with_name('worker-started').write_text(str(os.getpid()))\n" +
            "print(json.dumps({'type':'ready','pid':os.getpid(),'max_context':4096}),flush=True)\n" +
            "for line in sys.stdin:\n print(json.dumps({'status':200,'body':{'text':'ok'}}),flush=True)\n")
        self.worker.chmod(0o755)
        self.process = None

    def tearDown(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        if self.process:
            self.process.communicate(timeout=5)
        self.temporary.cleanup()

    def command(self, port):
        return [sys.executable, str(self.root / "server.py"), "--model-dir", str(self.root),
                "--executable", str(self.worker), "--port", str(port), "--startup-timeout", "3"]

    def test_occupied_port_never_starts_worker(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            result = subprocess.run(self.command(listener.getsockname()[1]), capture_output=True,
                                    text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot listen", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_service_lock_never_starts_second_worker(self):
        with (self.root / "server-instance.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = subprocess.run(self.command(18089), capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Service already running", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_reserved_socket_serves_health_and_blocks_another_port(self):
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        self.process = subprocess.Popen(self.command(port), stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.fail(self.process.communicate())
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=.5) as response:
                    health = json.loads(response.read())
                if health["status"] == "ready":
                    break
            except OSError:
                time.sleep(.05)
        else:
            self.fail("Service did not become ready")
        result = subprocess.run(self.command(port + 1 if port < 65535 else port - 1),
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Service already running", result.stderr)
        self.assertEqual(int(self.marker.read_text()), health["worker_pid"])
        self.process.terminate()
        self.process.wait(timeout=10)
        self.assertFalse(Path(f"/proc/{health['worker_pid']}").exists())
