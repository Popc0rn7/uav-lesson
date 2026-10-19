#!/usr/bin/env python3
# Copyright (c) 2026 HOUMO AI
#
# File: run.py
# Description:
#   Configure inference runtime and manage the foreground or detached Qwen service.
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
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / 'server.pid'
LOG_FILE = ROOT / 'server.log'


def identity(pid):
    try:
        # starttime distinguishes a reused PID; state excludes unreaped zombies.
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (OSError, IndexError):
        return None


def read_state():
    try:
        state = json.loads(PID_FILE.read_text())
        pid = state['pid']
        if (type(pid) is int and pid > 1 and isinstance(state['starttime'], str)
                and identity(pid) == state['starttime']):
            return state
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def foreground_pid():
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            arguments = (entry / 'cmdline').read_bytes().split(b'\0')
            if os.fsencode(ROOT / 'server.py') in arguments and identity(int(entry.name)):
                return int(entry.name)
        except OSError:
            continue
    return None


def start(command, environment):
    state = read_state()
    if state:
        print(f"Service already running: PID={state['pid']}; use --stop first", file=sys.stderr)
        return 1
    existing = foreground_pid()
    if existing:
        print(f'Service already running in foreground: PID={existing}; stop it in its terminal first', file=sys.stderr)
        return 1
    PID_FILE.unlink(missing_ok=True)
    with LOG_FILE.open('ab') as output:
        process = subprocess.Popen(command, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        # Save immediately so --stop can also stop a model that is still loading.
        stamp = identity(process.pid)
        if stamp is None:
            process.wait()
            print(f'Start failed; check {LOG_FILE}', file=sys.stderr)
            return 1
        temporary = PID_FILE.with_suffix('.pid.tmp')
        state = {'pid':process.pid, 'starttime':stamp}
        if "--model-dir" in command:
            state["model_dir"] = command[command.index("--model-dir") + 1]
        temporary.write_text(json.dumps(state))
        temporary.replace(PID_FILE)
        time.sleep(.5)
        if process.poll() is not None:
            PID_FILE.unlink(missing_ok=True)
            print(f'Start failed (exit={process.returncode}); check {LOG_FILE}', file=sys.stderr)
            return 1
    print(f'Background process started: PID={process.pid} (model may still be loading)')
    print(f'Log: {LOG_FILE}')
    print('Use /health to confirm model readiness.')
    return 0


def stop():
    state = read_state()
    if not state:
        PID_FILE.unlink(missing_ok=True)
        existing = foreground_pid()
        print(f'Foreground service PID={existing}; stop it in its terminal' if existing else 'Service is not running')
        return 0
    pid = state['pid']
    try:
        if os.getpgid(pid) != pid:
            print('Refusing to stop: service is not in its own process group', file=sys.stderr)
            return 1
        # Signal the detached group, including a worker still loading its model.
        # Uvicorn startup otherwise waits for loading before honoring SIGTERM.
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 30
    while identity(pid) == state['starttime']:
        if time.monotonic() >= deadline:
            print(f'Service PID={pid} is still stopping; check {LOG_FILE}', file=sys.stderr)
            return 1
        time.sleep(.1)
    PID_FILE.unlink(missing_ok=True)
    print(f'Service stopped: PID={pid}')
    return 0


def status():
    state = read_state()
    existing = foreground_pid() if not state else None
    print(f"RUNNING PID={state['pid']} (readiness: GET /health)" if state else
          f"FOREGROUND PID={existing} (not managed by --stop)" if existing else "STOPPED")
    if state and state.get("model_dir"):
        print(f"Model: {state['model_dir']}")
    print(f"Log: {LOG_FILE}")
    return 0


DEFAULT_MODEL = "/data/local/workspace/models/qwen3.5-9b_w4a8_256_256k_b1_1chip_2cores"


def positive(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run Qwen inference or manage its HTTP service")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list-models", action="store_true", help="List configured model names and paths")
    action.add_argument("--serve", action="store_true")
    action.add_argument("--prompt", type=Path, help="UTF-8 prompt file")
    action.add_argument("--status", action="store_true")
    action.add_argument("--stop", action="store_true")
    parser.add_argument("--background", action="store_true", help="Detach the HTTP service")
    parser.add_argument("--model", help="Model name from models.json")
    parser.add_argument("--models-config", type=Path, default=ROOT / "models.json")
    parser.add_argument("--model-dir", help="Override the selected model directory")
    parser.add_argument("--max-new-tokens", type=positive, default=os.environ.get("MAX_NEW_TOKENS", "128"))
    parser.add_argument("--embedding", type=Path)
    parser.add_argument("--system-prompt", default="You are a helpful assistant.")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=positive, default=8080)
    parser.add_argument("--startup-timeout", type=positive, default=300)
    parser.add_argument("--request-timeout", type=positive, default=300)
    args = parser.parse_args(argv)
    if args.background and not args.serve:
        parser.error("--background requires --serve")
    if args.device < 0 or args.port > 65535:
        parser.error("device must be >=0 and port must be <=65535")
    if not (args.status or args.stop or args.list_models):
        try:
            select_model(args)
        except (OSError, ValueError) as error:
            parser.error(str(error))
    return args


def load_models(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    models = value.get("models") if isinstance(value, dict) else None
    if not isinstance(models, dict) or not models:
        raise ValueError("models config must contain a nonempty 'models' object")
    for name, entry in models.items():
        if not name or not isinstance(entry, dict) or not isinstance(entry.get("model_dir"), str) or not entry["model_dir"]:
            raise ValueError(f"Invalid model entry: {name!r}; model_dir must be a nonempty string")
        if "embedding" in entry and (not isinstance(entry["embedding"], str) or not entry["embedding"]):
            raise ValueError(f"Invalid embedding path for model: {name}")
    return models


def config_path(value, config):
    path = Path(value).expanduser()
    return path if path.is_absolute() else (config.resolve().parent / path).resolve()


def select_model(args):
    if args.model:
        models = load_models(args.models_config)
        if args.model not in models:
            raise ValueError(f"Unknown model {args.model!r}; available: {', '.join(models)}")
        entry = models[args.model]
        if args.model_dir is None:
            args.model_dir = str(config_path(entry["model_dir"], args.models_config))
        if args.embedding is None and "embedding" in entry:
            args.embedding = config_path(entry["embedding"], args.models_config)
    if args.model_dir is None:
        args.model_dir = os.environ.get("QWEN_MODEL_DIR", DEFAULT_MODEL)


def runtime_environment():
    environment = os.environ.copy()
    houmo = Path(environment.get("HOUMO_PATH", "/data/local/houmo"))
    sdk = Path(environment.get("HOUMO_SDK_PATH", "/data/local/houmo-sdk"))
    libraries = [str(ROOT / "lib"), str(houmo / "lib"),
                 str(sdk / "hal/lib"), str(sdk / "lib")]
    if environment.get("LD_LIBRARY_PATH"):
        libraries.append(environment["LD_LIBRARY_PATH"])
    environment.update(LD_LIBRARY_PATH=":".join(libraries),
                       HOUMO_TARGET="xh2", TCIM_BACKEND="xh2")
    return environment, sdk


def driver_loaded():
    return any(line.split()[0] == "xh2a_drv"
               for line in Path("/proc/modules").read_text().splitlines() if line.split())


def driver_bound(devices=Path("/sys/bus/pci/devices")):
    for device in devices.iterdir():
        module = device / "driver/module"
        if module.is_symlink() and module.resolve().name == "xh2a_drv":
            return True
    return False


def ensure_driver(sdk, environment):
    if not driver_loaded():
        driver = sdk / "xh2a_drv.ko"
        if not driver.is_file():
            raise RuntimeError(f"Driver module does not exist: {driver}")
        subprocess.run(["insmod", str(driver)], env=environment, check=True)
        if not driver_loaded():
            raise RuntimeError("xh2a_drv was not loaded successfully")
    if not driver_bound():
        raise RuntimeError(
            "xh2a_drv is loaded but no PCI device is bound to it; "
            "check dmesg for probe failures (including DMA/CMA allocation errors). "
            "Model loading has not started."
        )


def check_port(host, port):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((host, port))
            listener.listen(1)
        except OSError as error:
            raise RuntimeError(f"Cannot listen on {host}:{port}: {error}; service not started") from error


def prepare_command(args, environment):
    model = Path(args.model_dir).resolve()
    executable = ROOT / "qwen_ohos_infer"
    if not model.is_dir():
        raise RuntimeError(f"Model directory does not exist: {model}")
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(f"Inference executable is missing or not executable: {executable}")
    common = ["--model-dir", str(model), "--max-new-tokens", str(args.max_new_tokens),
              "--system-prompt", args.system_prompt, "--device", str(args.device)]
    if args.embedding:
        embedding = args.embedding.resolve()
        if not embedding.is_file():
            raise RuntimeError(f"Embedding file does not exist: {embedding}")
        common.extend(["--embedding", str(embedding)])
    if args.serve:
        python = os.environ.get("PYTHON_BIN", sys.executable)
        subprocess.run([python, "-c", "import uvicorn, h11, asyncio"],
                       env=environment, check=True)
        return [python, str(ROOT / "server.py"), *common,
                "--host", args.host, "--port", str(args.port),
                "--startup-timeout", str(args.startup_timeout),
                "--request-timeout", str(args.request_timeout)]
    prompt = args.prompt.resolve()
    if not prompt.is_file() or not os.access(prompt, os.R_OK) or prompt.stat().st_size == 0:
        raise RuntimeError(f"Prompt file is missing, unreadable or empty: {prompt}")
    return [str(executable), *common, "--prompt-file", str(prompt)]


def main(argv=None):
    args = parse_args(argv)
    if args.list_models:
        for name, entry in load_models(args.models_config).items():
            print(f"{name}: {config_path(entry['model_dir'], args.models_config)}")
            if "embedding" in entry:
                print(f"  embedding: {config_path(entry['embedding'], args.models_config)}")
        return 0
    # Serialize service control and reject model changes until the old worker stops.
    with (ROOT / "service-control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.status:
            return status()
        if args.stop:
            return stop()
        if read_state() or foreground_pid():
            print("Service already running; use --stop before switching models", file=sys.stderr)
            return 1
        if args.serve:
            check_port(args.host, args.port)
        environment, sdk = runtime_environment()
        command = prepare_command(args, environment)
        ensure_driver(sdk, environment)
        if args.background:
            return start(command, environment)
        os.execvpe(command[0], command, environment)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
