"""PC：不依赖 AirSim Python SDK 的三车车队 RPC 客户端。"""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from stage3.super.airsim.rpc_client import rpc
from stage5.airsim.config import load

DEFAULT_CONFIG = Path(__file__).with_name('runtime.demo.json')


class ConvoyClient:
    """仅控制场景车队；无人机控制由 PX4 接口承担。"""

    def __init__(self, ip='127.0.0.1', port=41451, timeout_value=10):
        self.ip = ip
        self.port = port
        self.timeout = timeout_value

    def _convoy_call(self, method):
        result = json.loads(rpc(method, host=self.ip, port=self.port, timeout=self.timeout))
        if not isinstance(result, dict) or type(result.get('ok')) is not bool:
            raise ValueError('车队 RPC 返回格式无效：需要带布尔 ok 的 JSON 对象')
        return result

    def simGetConvoyStatus(self):
        return self._convoy_call('simGetConvoyStatus')

    def simStartConvoy(self):
        """启动三车循环；重复启动不重置正在运行的车队。"""
        return self._convoy_call('simStartConvoy')

    def simStopConvoy(self):
        """停止循环并在当前位置刹停三车。"""
        return self._convoy_call('simStopConvoy')

    def simResetConvoy(self):
        """停止循环，将三车瞬移回初始位置；不复位无人机。"""
        return self._convoy_call('simResetConvoy')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'start', 'stop', 'reset'], nargs='?', default='status')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--ip', help='覆盖 runtime 配置中的 RPC 地址')
    parser.add_argument('--port', type=int, help='覆盖 runtime 配置中的 RPC 端口')
    parser.add_argument('--timeout', type=float, default=10)
    args = parser.parse_args()
    if args.timeout <= 0 or (args.port is not None and not 1 <= args.port <= 65535):
        parser.error('timeout 必须大于0，port 必须在1到65535之间')
    try:
        config = load(args.config)
        client = ConvoyClient(args.ip or config['rpc_host'],
                              args.port if args.port is not None else config['rpc_port'], args.timeout)
        method = {'status': client.simGetConvoyStatus, 'start': client.simStartConvoy,
                  'stop': client.simStopConvoy, 'reset': client.simResetConvoy}[args.action]
        result = method()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'车队 RPC 失败：{exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
