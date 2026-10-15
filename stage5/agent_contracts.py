"""任务协议：模型选择任务策略，运行器校验可执行性与保留不可修改历史。"""
import copy
import hashlib
import json
import math
import re

SKILLS = {'follow_red_vehicle', 'observe_target'}
ACTIONS = {'accept', 'redo', 'modify_stage', 'modify_plan', 'abort'}


def positive(value, name, integer=False):
    try:
        finite = isinstance(value,(int,float)) and math.isfinite(value)
    except OverflowError:
        finite = False
    if isinstance(value, bool) or not finite or value <= 0:
        raise ValueError(f'{name} 必须为正数')
    if integer and not isinstance(value, int):
        raise ValueError(f'{name} 必须为整数')
    return value


def allocation(value):
    if not isinstance(value, dict):
        raise ValueError('allocation 必须包含 budget 与 timeout')
    return {'budget': positive(value.get('budget'), 'Jev budget', True),
            'timeout': positive(value.get('timeout'), 'stage timeout')}


def stage(value):
    if not isinstance(value, dict):
        raise ValueError('stage 必须为对象')
    result = copy.deepcopy(value)
    for key in ('id', 'goal', 'dino_text', 'completion_criteria', 'failure_criteria'):
        if not isinstance(result.get(key), str) or not 1 <= len(result[key].strip()) <= 2000:
            raise ValueError(f'stage 缺少有效 {key}')
    if result.get('skill') not in SKILLS:
        raise ValueError('只支持 follow_red_vehicle / observe_target；没有搜索或绕障技能')
    result['allocation'] = allocation(result.get('allocation'))
    allowed = result.get('allowed_skills')
    supported = {'hold_course', 'brake', 'reacquire'} if result['skill'] == 'follow_red_vehicle' else {'brake', 'reacquire'}
    if not isinstance(allowed, list) or not allowed or any(not isinstance(v, str) or v not in supported for v in allowed):
        raise ValueError('allowed_skills 超出该技能能力')
    if result['skill'] == 'follow_red_vehicle':
        for key, lo, hi in (('horizontal_distance_m', 3, 12), ('above_m', 1, 4)):
            value = positive(result.get(key), key)
            if not lo <= value <= hi:
                raise ValueError(f'{key} 必须为 {lo}～{hi}')
        duration = positive(result.get('duration_s'), 'duration_s')
        # 仅核对明确数字秒数，不猜测自然语言中的隐含时长。
        for field in ('goal', 'completion_criteria'):
            text = result[field]
            seconds = re.findall(r'(?:跟随|达到|达标|持续)[^。；;\n]{0,35}?(\d+(?:\.\d+)?)\s*(?:秒|seconds?\b)', text)
            if any(not math.isclose(float(value), duration) for value in seconds):
                raise ValueError(f'{field} 中的跟随秒数与 duration_s={duration} 矛盾，请统一，不得使用缺省时长覆盖明确要求')
    return result


def plan(value, task=None):
    if not isinstance(value, dict):
        raise ValueError('计划必须为对象')
    if value.get('unsupported_reason'):
        raise ValueError('unsupported_task: ' + str(value['unsupported_reason']))
    if value.get('version') != 2 or not isinstance(value.get('mission'), str) or not value['mission'].strip():
        raise ValueError('计划需要 version=2 与 mission')
    stages = value.get('stages')
    if not isinstance(stages, list) or not stages:
        raise ValueError('计划必须含至少一个 stage')
    result = dict(version=2, mission=value['mission'], stages=[stage(item) for item in stages])
    if task:
        requested = re.findall(r'跟随[^。；;\n]{0,35}?(\d+(?:\.\d+)?)\s*(?:秒|seconds?\b)', task)
        follows = [item for item in result['stages'] if item['skill'] == 'follow_red_vehicle']
        if len(requested) == 1 and len(follows) == 1 and not math.isclose(float(requested[0]), follows[0]['duration_s']):
            raise ValueError('duration_s 与用户明确指定的跟随秒数矛盾；不得以缺省值替换')
    ids = [item['id'] for item in result['stages']]
    if len(ids) != len(set(ids)):
        raise ValueError('同一计划的 stage id 必须唯一')
    return result


def review(value, current_plan, index, task=None):
    if not isinstance(value, dict) or value.get('action') not in ACTIONS:
        raise ValueError('验收 action 必须为 accept/redo/modify_stage/modify_plan/abort')
    result = copy.deepcopy(value)
    if value['action'] == 'abort':
        if not isinstance(value.get('assessment'), str) or not value['assessment'].strip():
            raise ValueError('abort 必须说明无法继续的 assessment')
    elif value['action'] == 'redo':
        result['allocation'] = allocation(value.get('allocation'))
    elif value['action'] == 'modify_stage':
        result['stage'] = stage(value.get('stage'))
        if result['stage']['id'] != current_plan['stages'][index]['id']:
            raise ValueError('modify_stage 保留当前 stage id')
    elif value['action'] == 'modify_plan':
        suffix = value.get('stages')
        if not isinstance(suffix, list) or not suffix:
            raise ValueError('modify_plan 必须提供当前及后续的非空 stages；完成请用 accept')
        result['stages'] = [stage(item) for item in suffix]
    candidate = copy.deepcopy(current_plan)
    if value['action'] == 'modify_stage':
        candidate['stages'][index] = result['stage']
    elif value['action'] == 'modify_plan':
        candidate['stages'][index:] = result['stages']
    plan(candidate, task)  # 已接受前缀不可覆盖，且不允许 id 冲突。
    return result


def progress_key(value):
    semantics = {k: v for k, v in value.items() if k != 'allocation'}
    return hashlib.sha256(json.dumps(semantics, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def upgrade_legacy(value, budget=40, seconds=60):
    """仅供显式 --plan 复用；不把本地适配称为在线 Qwen 规划。"""
    if value.get('version') == 2:
        return plan(value)
    result = copy.deepcopy(value)
    result['version'] = 2
    for item in result.get('stages', []):
        item['allocation'] = {'budget': budget, 'timeout': max(seconds + 15, 30)}
    return plan(result)
