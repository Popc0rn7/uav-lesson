"""Small HTTP adapter; no dependency on the original AeroVLA checkout."""
import base64
import json
import math
import os
import re
import time
import urllib.request
import urllib.error

from stage4.contracts import validate_action


class AeroVLAClient:
    def __init__(self, url=None, timeout=None, key=None):
        self.url = url or os.environ.get('AEROVLA_API_URL', '')
        self.timeout = float(timeout if timeout is not None else os.environ.get('AEROVLA_API_TIMEOUT_S', '30'))
        self.key = key if key is not None else os.environ.get('AEROVLA_API_KEY', '')
        if not self.url.startswith(('http://', 'https://')):
            raise ValueError('Set AEROVLA_API_URL to a full http(s) inference endpoint')
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError('AEROVLA_API_TIMEOUT_S must be finite and positive')

    def read_json(self, request, limit):
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read(limit+1))
        except urllib.error.HTTPError as exc:
            body=exc.read(4096).decode('utf-8',errors='replace')
            try: message=json.loads(body).get('error',body)
            except (ValueError,AttributeError): message=body
            raise RuntimeError(f'AeroVLA HTTP {exc.code}: {message}') from exc

    def health(self):
        url = self.url.rsplit('/', 1)[0] + '/health'
        headers = {'Authorization': 'Bearer '+self.key} if self.key else {}
        data = self.read_json(urllib.request.Request(url, headers=headers),4096)
        if not isinstance(data, dict) or data.get('status') != 'ready':
            raise RuntimeError('AeroVLA service is not ready')
        return data

    def infer(self, request_id, observation_time_s, position, orientation, target_position, instruction, front, down):
        from stage4.contracts import vector
        if 'degrees from you.' not in instruction or ' Please control' not in instruction.split('degrees from you.',1)[1]:
            raise ValueError('instruction must use the original dataset description delimiters')
        payload = dict(position=vector(position,3), orientation=vector(orientation,4),
                       target_position=vector(target_position,3), instruction=instruction,
                       front_image=base64.b64encode(front).decode('ascii'),
                       down_image=base64.b64encode(down).decode('ascii'))
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        request = urllib.request.Request(self.url, json.dumps(payload, allow_nan=False).encode(), headers)
        started = time.monotonic()
        data = self.read_json(request,1024*1024)
        if not isinstance(data, dict):
            raise ValueError('Inference response must be a JSON object')
        if type(data.get('stop')) is not bool:
            raise ValueError('Inference stop must be boolean')
        data['action'] = validate_action(data.get('action'))
        if not isinstance(data.get('raw_output'), str):
            raise ValueError('Inference raw_output must be a string')
        if 'LAND' not in data['raw_output']:
            bins=re.findall(r'\d+',data['raw_output'])
            if len(bins)<3 or any(not 0<=int(v)<=98 for v in bins[-3:]):
                raise ValueError('Invalid model action tokens; refusing the old zero-action fallback')
        if not isinstance(data.get('prompt'), str):
            raise ValueError('Inference prompt must be a string')
        elapsed = data.get('elapsed_seconds')
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError('Invalid elapsed_seconds')
        # Server is stateless and does not echo IDs. Bind the response to this
        # future locally; the control node still rejects cancelled work.
        data['request_id'] = request_id
        data['observation_time_s'] = observation_time_s
        data['http_seconds'] = time.monotonic()-started
        return data
