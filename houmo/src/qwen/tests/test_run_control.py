# Copyright (c) 2026 HOUMO AI
#
# File: test_run_control.py
# Description:
#   Verify detached service control, duplicate prevention and stale PID handling.
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

import contextlib
import importlib.util
import io
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("qwen_run", Path(__file__).resolve().parents[1] / "run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ControlTests(unittest.TestCase):
    def test_detach_duplicate_stop_and_stale_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.py"
            server.write_text("import time; print('daemon running', flush=True); time.sleep(300)\n")
            with patch.multiple(runner, ROOT=root, PID_FILE=root / "server.pid", LOG_FILE=root / "server.log"):
                try:
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        with patch.object(runner, "prepare_command", return_value=[sys.executable, str(server)]), patch.object(runner, "ensure_driver") as driver, patch.object(runner, "check_port"):
                            self.assertEqual(runner.main(["--serve", "--background"]), 0)
                            self.assertEqual(runner.main(["--serve", "--background"]), 1)
                            driver.assert_called_once()
                        state = json.loads(runner.PID_FILE.read_text())
                        self.assertEqual(os.getsid(state["pid"]), state["pid"])
                        self.assertEqual(runner.read_state()["pid"], state["pid"])
                        self.assertEqual(runner.start([sys.executable, str(server)], os.environ.copy()), 1)
                        self.assertIn("daemon running", runner.LOG_FILE.read_text())
                        self.assertEqual(runner.main(["--stop"]), 0)
                        self.assertFalse(runner.PID_FILE.exists())
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output):
                            self.assertEqual(runner.main(["--status"]), 0)
                        self.assertIn("STOPPED", output.getvalue())
                        runner.PID_FILE.write_text(json.dumps({"pid": os.getpid(), "starttime": "invalid"}))
                        self.assertEqual(runner.main(["--stop"]), 0)
                        self.assertFalse(runner.PID_FILE.exists())
                finally:
                    runner.stop()

    def test_control_does_not_prepare_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(runner, ROOT=root, PID_FILE=root / "server.pid", LOG_FILE=root / "server.log"), \
                    patch.object(runner, "prepare_command", side_effect=AssertionError("runtime touched")), \
                    patch.object(runner, "ensure_driver", side_effect=AssertionError("driver touched")):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.main(["--status"]), 0)
                    self.assertEqual(runner.main(["--stop"]), 0)

    def test_failed_background_start_clears_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(runner, ROOT=root, PID_FILE=root / "server.pid", LOG_FILE=root / "server.log"):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(runner.start([sys.executable, "-c", "raise SystemExit(2)"], os.environ.copy()), 1)
                self.assertFalse(runner.PID_FILE.exists())

    def test_native_arguments_environment_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "qwen_ohos_infer"
            executable.touch()
            executable.chmod(0o700)
            prompt = root / "prompt with spaces.txt"
            prompt.write_text("你好")
            embedding = root / "embedding.bin"
            embedding.touch()
            with patch.multiple(runner, ROOT=root, PID_FILE=root / "server.pid", LOG_FILE=root / "server.log"), patch.dict(os.environ, {"QWEN_MODEL_DIR": str(root), "MAX_NEW_TOKENS": "16"}):
                args = runner.parse_args(["--prompt", str(prompt), "--embedding", str(embedding), "--max-new-tokens", "32"])
                env, sdk = runner.runtime_environment()
                command = runner.prepare_command(args, env)
                self.assertEqual(command[0], str(executable))
                self.assertEqual(command[-2:], ["--prompt-file", str(prompt)])
                self.assertEqual(command[command.index("--max-new-tokens") + 1], "32")
                self.assertEqual(command[command.index("--embedding") + 1], str(embedding))
                self.assertEqual(env["TCIM_BACKEND"], "xh2")
                self.assertTrue(env["LD_LIBRARY_PATH"].startswith(str(root / "lib") + ":"))
                prompt.write_text("")
                with self.assertRaisesRegex(RuntimeError, "Prompt file"):
                    runner.prepare_command(args, env)

    def test_serve_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "qwen_ohos_infer"
            executable.touch()
            executable.chmod(0o700)
            with patch.multiple(runner, ROOT=root, PID_FILE=root / "server.pid", LOG_FILE=root / "server.log"), patch.object(runner.subprocess, "run") as check:
                args = runner.parse_args(["--serve", "--model-dir", str(root), "--port", "18080"])
                command = runner.prepare_command(args, os.environ.copy())
                self.assertIn(str(root / "server.py"), command)
                self.assertEqual(command[command.index("--port") + 1], "18080")
                check.assert_called_once()

    def test_invalid_options_and_compatibility_help(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for arguments in [["--background", "--status"], ["--serve", "--port", "65536"], ["--serve", "--max-new-tokens", "0"]]:
                with self.assertRaises(SystemExit):
                    runner.parse_args(arguments)
        wrapper = Path(__file__).resolve().parents[1] / "run.sh"
        result = subprocess.run(["sh", str(wrapper), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--embedding", result.stdout)


class ModelSelectionTests(unittest.TestCase):
    def test_each_model_selects_its_own_paths_and_cli_can_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "models.json"
            config.write_text(json.dumps({"models": {
                "small": {"model_dir": "small", "embedding": "small.bin"},
                "large": {"model_dir": "large", "embedding": "large.bin"}
            }}))
            for name in ["small", "large"]:
                args = runner.parse_args(["--serve", "--model", name, "--models-config", str(config)])
                self.assertEqual(Path(args.model_dir), root / name)
                self.assertEqual(args.embedding, root / (name + ".bin"))
            args = runner.parse_args(["--serve", "--model", "small", "--models-config", str(config),
                                      "--model-dir", str(root / "override"), "--embedding", str(root / "override.bin")])
            self.assertEqual(Path(args.model_dir), root / "override")
            self.assertEqual(args.embedding, root / "override.bin")

    def test_unknown_and_invalid_models_fail_before_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "models.json"
            config.write_text(json.dumps({"models": {"small": {"model_dir": "small"}}}))
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    runner.parse_args(["--serve", "--model", "unknown", "--models-config", str(config)])
                config.write_text('{"models":{"bad":{"model_dir":42}}}')
                with self.assertRaises(SystemExit):
                    runner.parse_args(["--serve", "--model", "bad", "--models-config", str(config)])

    def test_list_and_control_do_not_need_runtime_or_valid_model_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "models.json"
            config.write_text('{"models":{"small":{"model_dir":"not-deployed"}}}')
            with patch.multiple(runner, ROOT=root, PID_FILE=root / "server.pid", LOG_FILE=root / "server.log"), \
                    patch.object(runner, "prepare_command", side_effect=AssertionError("runtime touched")), \
                    patch.object(runner, "ensure_driver", side_effect=AssertionError("driver touched")):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(runner.main(["--list-models", "--models-config", str(config)]), 0)
                    config.write_text("invalid json")
                    self.assertEqual(runner.main(["--status", "--models-config", str(config)]), 0)
                    self.assertEqual(runner.main(["--stop", "--models-config", str(config)]), 0)
                self.assertIn("small:", output.getvalue())

    def test_active_service_blocks_new_model_in_foreground_and_background(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "models.json"
            config.write_text('{"models":{"small":{"model_dir":"small"},"large":{"model_dir":"large"}}}')
            active = {"pid": os.getpid(), "starttime": runner.identity(os.getpid())}
            with patch.object(runner, "ROOT", root), patch.object(runner, "read_state", return_value=active), \
                    patch.object(runner, "prepare_command", side_effect=AssertionError("model reloaded")), \
                    patch.object(runner, "ensure_driver", side_effect=AssertionError("driver touched")):
                with contextlib.redirect_stderr(io.StringIO()):
                    for flags in [["--serve"], ["--serve", "--background"], ["--prompt", "prompt.txt"]]:
                        self.assertEqual(runner.main([*flags, "--model", "large", "--models-config", str(config)]), 1)


class DriverChecksTests(unittest.TestCase):
    def test_loaded_module_without_bound_device_stops_before_model_loading(self):
        with patch.object(runner, "driver_loaded", return_value=True), \
                patch.object(runner, "driver_bound", return_value=False), \
                patch.object(runner.subprocess, "run") as command:
            with self.assertRaisesRegex(RuntimeError, "no PCI device is bound"):
                runner.ensure_driver(Path("/unused"), {})
            command.assert_not_called()

    def test_bound_device_is_required_and_detected_through_module_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / "devices/0000:01:00.0"
            device.mkdir(parents=True)
            self.assertFalse(runner.driver_bound(root / "devices"))
            module = root / "modules/xh2a_drv"
            module.mkdir(parents=True)
            driver = root / "drivers/houmo,xh2a"
            driver.mkdir(parents=True)
            (driver / "module").symlink_to(module)
            (device / "driver").symlink_to(driver)
            self.assertTrue(runner.driver_bound(root / "devices"))
            with patch.object(runner, "driver_loaded", return_value=True), \
                    patch.object(runner, "driver_bound", return_value=True), \
                    patch.object(runner.subprocess, "run") as command:
                runner.ensure_driver(Path("/unused"), {})
                command.assert_not_called()


class PortChecksTests(unittest.TestCase):
    def test_occupied_port_fails_before_driver_or_model_setup(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as listener:
            root = Path(directory)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            with patch.object(runner, "ROOT", root), patch.object(runner, "read_state", return_value=None), \
                    patch.object(runner, "foreground_pid", return_value=None), \
                    patch.object(runner, "prepare_command", side_effect=AssertionError("model touched")), \
                    patch.object(runner, "ensure_driver", side_effect=AssertionError("driver touched")):
                for mode in [["--serve"], ["--serve", "--background"]]:
                    with self.assertRaisesRegex(RuntimeError, "Cannot listen"):
                        runner.main([*mode, "--port", str(port)])

    def test_available_port_and_wildcard_conflict(self):
        runner.check_port("127.0.0.1", 0)
        with socket.socket() as listener:
            listener.bind(("0.0.0.0", 0))
            listener.listen(1)
            with self.assertRaisesRegex(RuntimeError, "Cannot listen"):
                runner.check_port("127.0.0.1", listener.getsockname()[1])
