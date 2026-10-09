"""ROS 桥调用同板常驻 HTTP 服务；不创建推理子进程或临时问题文件。"""
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler, Request

INFER_URL = 'http://127.0.0.1:8080'
TIMEOUT_SECONDS = 310
STARTUP_SECONDS = 330
MAX_RESPONSE_BYTES = 1024 * 1024
# localhost 请求不经过主机环境里的 HTTP proxy。
HTTP = build_opener(ProxyHandler({}))


class InferenceError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def read_json(response):
    data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError('HTTP 回复超过 1 MiB')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('HTTP 回复必须为 JSON 对象')
    return value


def infer(prompt):
    request = Request(INFER_URL + '/infer',
                      data=json.dumps({'prompt': prompt}, ensure_ascii=False).encode('utf-8'),
                      headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with HTTP.open(request, timeout=TIMEOUT_SECONDS) as response:
            result = read_json(response)
    except HTTPError as error:
        try:
            message = read_json(error).get('error', str(error))
        except (ValueError, OSError):
            message = str(error)
        finally:
            error.close()
        status = {400: 'invalid', 429: 'busy', 504: 'timeout'}.get(error.code, 'error')
        raise InferenceError(status, message) from error
    except TimeoutError as error:
        raise InferenceError('timeout', '等待常驻服务超时；不自动重发，请检查服务健康状态') from error
    except URLError as error:
        status = 'timeout' if isinstance(error.reason, TimeoutError) else 'error'
        raise InferenceError(status, f'常驻模型服务不可达：{error.reason}') from error
    if not isinstance(result.get('text'), str):
        raise ValueError('常驻服务回复缺少 text')
    metadata = {key: result[key] for key in ('input_tokens', 'output_tokens', 'stop_reason')}
    return {'output': result['text'], 'diagnostics': json.dumps(metadata, ensure_ascii=False), **metadata}


def wait_ready():
    deadline = time.monotonic() + STARTUP_SECONDS
    last_error = None
    while time.monotonic() < deadline:
        try:
            with HTTP.open(INFER_URL + '/health', timeout=2) as response:
                health = read_json(response)
            if health.get('status') == 'ready':
                pid = health.get('worker_pid')
                if type(pid) is not int or pid <= 1:
                    raise RuntimeError('常驻服务 worker_pid 无效')
                expected = Path('/data/local/workspace/stage1/qwen_infer/qwen_ohos_infer').resolve()
                if Path(f'/proc/{pid}/exe').resolve() != expected:
                    raise RuntimeError('8080 端口属于其他推理部署，不复用该服务')
                print(f'模型已就绪，worker_pid={pid}', flush=True)
                return
        except (URLError, OSError, ValueError) as error:
            last_error = error
        time.sleep(1)
    raise RuntimeError(f'模型在 {STARTUP_SECONDS} 秒内未就绪：{last_error}')


if __name__ == '__main__':
    wait_ready()
