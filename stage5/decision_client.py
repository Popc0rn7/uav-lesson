"""TypeSafe System One / JEV-9B vLLM 的统一问题与概率结果。"""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from types import SimpleNamespace

import requests


@dataclass
class Question:
    type: str
    instructions: str
    criteria: object


def Choice(*, instructions, criteria):
    return Question('choice', instructions, criteria)


def Score(*, instructions, criteria):
    return Question('score', instructions, criteria)


def Noul(*, instructions, criteria):
    return Question('noul', instructions, criteria)


class DecisionHTTPError(RuntimeError):
    def __init__(self, response):
        super().__init__(f'Jev HTTP {response.status_code}')
        self.status = response.status_code
        # 不保存响应正文，避免服务端回显 state、提示词或凭据。


def distribution(values, count):
    if not isinstance(values, list) or len(values) != count:
        raise ValueError('Jev 概率维度不匹配')
    if any(type(p) not in (int, float) or not math.isfinite(p) or p < 0 or p > 1 for p in values):
        raise ValueError('Jev 概率非法')
    total = sum(values)
    if not math.isclose(total, 1, abs_tol=.02):
        raise ValueError('Jev 概率和不为 1')
    return [p / total for p in values]


class DecisionClient:
    def __init__(self, config, timeout):
        self.backend = config.get('JEV_BACKEND', 'typesafe')
        if self.backend not in ('typesafe', 'vllm'):
            raise ValueError('JEV_BACKEND 必须为 typesafe 或 vllm')
        self.base = (config.get('JEV_BASE_URL') or config.get('TYPESAFE_BASE_URL') or
                     ('https://api.typesafe.ai/v1' if self.backend == 'typesafe' else '')).rstrip('/')
        if not self.base.startswith(('http://', 'https://')):
            raise ValueError('请设置含 /v1 的 JEV_BASE_URL')
        key = config.get('JEV_API_KEY') or (config.get('TYPESAFE_API_KEY') if self.backend == 'typesafe' else None)
        if self.backend == 'typesafe' and not key:
            raise ValueError('TypeSafe 后端需要 JEV_API_KEY')
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False
        if key:
            self.session.headers['Authorization'] = 'Bearer ' + key
        if config.get('JEV_PROXY'):
            self.session.proxies.update(http=config['JEV_PROXY'], https=config['JEV_PROXY'])
        if self.backend == 'vllm':
            # 两个 JSON 必须来自部署该 adapter 的同一模型版本，不在线自动下载。
            root = Path(__file__).resolve().parents[1]
            def metadata(key):
                value = config.get(key)
                if not value:
                    raise ValueError(f'vLLM 后端需要 {key}，来自 JEV-9B 模型包')
                return json.loads((root / Path(value).expanduser()).read_text())
            self.head = metadata('JEV_DECISION_HEAD')
            self.temperatures = metadata('JEV_CALIBRATION')['per_kind']

    def post(self, route, body, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Jev 整轮请求超时')
        response = self.session.post(self.base + route, json=body, timeout=remaining)
        if not response.ok:
            raise DecisionHTTPError(response)
        return response.json()

    def system_one(self, *, state, model, questions):
        deadline = time.monotonic() + self.timeout
        if self.backend == 'typesafe':
            result = self.post('/systemone', dict(state=state, model=model,
                questions={key: vars(q) for key, q in questions.items()}), deadline)
            answers = {}
            for key, q in questions.items():
                answer = result['answers'][key]
                if answer['type'] != q.type:
                    raise ValueError('TypeSafe 答案类型不匹配')
                if q.type == 'choice':
                    probabilities = answer['probabilities']
                    if set(probabilities) != set(q.criteria):
                        raise ValueError('TypeSafe 选项不匹配')
                    distribution([probabilities[k] for k in q.criteria], len(q.criteria))
                answers[key] = SimpleNamespace(**answer)
            usage = result.get('usage', {})
        else:
            answers, usage = {}, dict(input_tokens=0, output_tokens=0)
            for key, q in questions.items():
                answer, consumed = self.vllm_question(state, model, q, deadline)
                answers[key] = answer
                for field in usage:
                    usage[field] += consumed.get(field, 0) or 0
        return SimpleNamespace(answers=answers, usage=SimpleNamespace(
            input_tokens=usage.get('input_tokens', 0), output_tokens=usage.get('output_tokens', 0)))

    def vllm_question(self, state, model, q, deadline):
        # Score 用任意长度的有序 Choice 表达，避免把课程三档风险强塞到原生六档 Score。
        kind = 'noul' if q.type == 'noul' else 'choice'
        keys = list(q.criteria) if q.type == 'choice' else list(range(len(q.criteria))) if q.type == 'score' else ['false', 'true']
        if not 2 <= len(keys) <= 16:
            raise ValueError('JEV-9B 支持 2～16 个选项')
        options = [f'{k}: {q.criteria[k]}' if q.type == 'choice' else str(q.criteria[k]) for k in keys]
        lines = options if kind == 'choice' else keys
        if kind == 'choice':
            lines = [f'{chr(65+i)}) {text}' for i, text in enumerate(options)]
        instructions = q.instructions
        if kind == 'noul':
            instructions += '\n' + json.dumps(q.criteria, ensure_ascii=False)
        prompt = f'[kind] {kind}\n[state] {json.dumps(state, ensure_ascii=False)}\n[question] {instructions}\n[options]\n' + '\n'.join(lines) + '\n[decision]:'
        start, end = self.head['slots']['ranges'][kind]
        ids = self.head['verbalizer_ids'][start:start+len(keys)]
        if len(ids) != len(keys) or start+len(keys) > end:
            raise ValueError('JEV-9B decision_head 选项槽不足')
        temperature = self.temperatures[kind]
        if not math.isfinite(temperature) or temperature <= 0:
            raise ValueError('JEV-9B calibration 温度非法')
        result = self.post('/completions', dict(model=model, prompt=prompt, max_tokens=1,
            temperature=1., top_p=1., top_k=0, min_p=0., repetition_penalty=1.,
            logprobs=len(keys), allowed_token_ids=ids, add_special_tokens=False,
            return_tokens_as_token_ids=True), deadline)
        lp = result['choices'][0]['logprobs']['top_logprobs'][0]
        logits = [(lp[f'token_id:{token}'] + self.head['bias'][start+i]) / temperature
                  for i, token in enumerate(ids)]
        if not all(math.isfinite(z) for z in logits):
            raise ValueError('JEV-9B logprobs 非法或不完整')
        exp = [math.exp(z-max(logits)) for z in logits]
        probabilities = distribution([v/sum(exp) for v in exp], len(keys))
        if q.type == 'choice':
            best = max(range(len(keys)), key=probabilities.__getitem__)
            answer = dict(choice=keys[best], probabilities=dict(zip(keys, probabilities)),
                confidence=(probabilities[best]-1/len(keys))/(1-1/len(keys)))
        elif q.type == 'score':
            answer = dict(score=sum(i*p for i, p in enumerate(probabilities)))
        else:
            answer = dict(noul=probabilities[1])
        tokens = result.get('usage', {})
        return SimpleNamespace(**answer), dict(input_tokens=tokens.get('prompt_tokens', 0),
                                               output_tokens=tokens.get('completion_tokens', 0))

    def close(self):
        self.session.close()
