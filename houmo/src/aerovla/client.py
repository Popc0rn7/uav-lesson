#!/usr/bin/env python3
"""PC/同板：发送预处理后的 AeroVLA JSON 请求，只保存模型输出。"""
import argparse
import json
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='例如 http://127.0.0.1:18084')
    parser.add_argument('--request', type=Path, required=True, help='含 input_ids、pixel_values_b64、pixel_values_shape 的 JSON')
    parser.add_argument('--output', type=Path, default=Path('artifacts/aerovla/result.json'))
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args()
    value = json.loads(args.request.read_text())
    request = Request(args.url.rstrip('/')+'/infer',
                      data=json.dumps(value,allow_nan=False).encode(),
                      headers={'Content-Type':'application/json'})
    with build_opener(ProxyHandler({})).open(request,timeout=args.timeout) as response:
        result = json.load(response)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('模型输出已保存：'+str(args.output))


if __name__ == '__main__':
    main()
