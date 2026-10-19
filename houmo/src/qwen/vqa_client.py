#!/usr/bin/env python3
"""PC: submit one local PNG/JPEG to the resident Qwen VLM service."""
import argparse
import base64
import json
from pathlib import Path
import time
from urllib.error import HTTPError,URLError
from urllib.request import Request,build_opener,ProxyHandler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--prompt',default='请描述图片中的主要物体。')
    parser.add_argument('--base-url',default='http://127.0.0.1:18080/v1')
    parser.add_argument('--model',default='qwen3.6-35b-a3b')
    parser.add_argument('--max-tokens',type=int,default=128)
    parser.add_argument('--timeout',type=float,default=120)
    args=parser.parse_args()
    if args.max_tokens<1 or args.timeout<=0:parser.error('max-tokens and timeout must be positive')
    try:
        raw=args.image.read_bytes()
        if raw.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
        elif raw.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
        else:raise ValueError('image must be PNG or JPEG')
        body={'model':args.model,'temperature':0,'max_tokens':args.max_tokens,'messages':[{'role':'user','content':[
            {'type':'text','text':args.prompt},
            {'type':'image_url','image_url':{'url':f'data:{mime};base64,'+base64.b64encode(raw).decode()}}]}]}
        request=Request(args.base_url.rstrip('/')+'/chat/completions',data=json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
        started=time.monotonic()
        with build_opener(ProxyHandler({})).open(request,timeout=args.timeout) as response:result=json.load(response)
        print(result['choices'][0]['message']['content'])
        print(json.dumps({'wall_s':round(time.monotonic()-started,3),'usage':result.get('usage')},ensure_ascii=False))
    except HTTPError as error:
        raise SystemExit(f'HTTP {error.code}: '+error.read(1000).decode(errors='replace')) from None
    except (OSError,ValueError,URLError,KeyError) as error:raise SystemExit(str(error)) from None


if __name__=='__main__':main()
