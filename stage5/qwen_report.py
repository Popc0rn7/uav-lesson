"""Qwen 的阶段结果报告；底层执行历史保留在本地证据中。"""
import math


def pick(value, keys):
    return {key: value[key] for key in keys.split() if key in value}


def rounded(value):
    if isinstance(value, float):
        return round(value, 3) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rounded(item) for item in value]
    return value


def report(value):
    result = pick(value, 'stage_id attempt plan_revision status reason error_type elapsed_s jev_calls jev_successes jev_errors progress metrics execution_health stage_allocation rejected_stage_status')
    result['jev_final'] = pick(value.get('judgment') or {},
        'stage_status stage_reason maneuver effective_maneuver risk source stale guard_reason error_type terminal_error')
    # 这是结束时的结果反馈，非实时感知输入；明确区分历史结果和当前 RGB。
    observation = value.get('observation') or {}
    result['tracking_at_end'] = dict(confirmed=bool(observation.get('tracking')),
        lost_for_s=observation.get('lost_for_s'), perception_error=observation.get('perception_error'))
    return result


def compact(payload, purpose):
    if purpose == 'summary':
        return rounded({'outcome': payload.get('outcome'), 'reason': payload.get('reason'),
                        'context': compact(payload.get('context', {}), 'review')})
    result = pick(payload, 'task default_duration_s current_index plan_revision usage previous_error qwen_completed_request_costs')
    stages = (payload.get('plan') or {}).get('stages', [])
    index = payload.get('current_index', 0)
    if purpose == 'plan':
        result['execution_guidance'] = payload.get('execution_guidance', {})
    else:
        result['current_stage'] = stages[index] if index < len(stages) else None
        result['plan_outline'] = [pick(stage, 'id goal skill') for stage in stages]
        reports = payload.get('stage_reports', [])
        result['stage_report'] = report(reports[-1]) if reports else None
        result['accepted_stage_ids'] = [entry['stage']['id'] for entry in payload.get('accepted', [])]
        result['execution_guidance'] = pick(payload.get('execution_guidance', {}),
            'remaining_qualified_follow_s estimated_approach_s estimate_source suggested_follow_timeout_s suggested_follow_budget')
    return rounded(result)
