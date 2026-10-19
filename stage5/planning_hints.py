"""给规划者的执行成本依据；估算不是执行限制或成功保证。"""
import math


JEV_INTERVAL_S = 2.
HORIZONTAL_SPEED_MPS = 1.2
VERTICAL_SPEED_MPS = .5


def guidance(observation, stage=None, default_duration_s=60, progress=None):
    stage, progress = stage or {}, progress or {}
    horizontal_limit = observation.get('horizontal_speed_limit_mps', HORIZONTAL_SPEED_MPS)
    vertical_limit = observation.get('vertical_speed_limit_mps', VERTICAL_SPEED_MPS)
    duration = stage.get('duration_s', default_duration_s)
    remaining = 0. if stage.get('continuous') else max(0., duration - progress.get('valid_follow_s', 0.))
    tracking = observation.get('tracking') or {}
    own = observation.get('own_position_ned_m')
    point, velocity = tracking.get('target_ned'), tracking.get('velocity_ned')
    speed = math.hypot(*velocity[:2]) if velocity is not None else None
    horizontal_error = vertical_error = None
    # 与执行器一样使用目标速度方向；静止/缺测时不臆测车头方向。
    if own is not None and point is not None and speed is not None and speed > .25:
        distance, above = stage.get('horizontal_distance_m', 8), stage.get('above_m', 2)
        goal = [point[i] - distance * velocity[i] / speed for i in range(2)]
        horizontal_error = math.hypot(goal[0]-own[0], goal[1]-own[1])
        vertical_error = abs(point[2]-above-own[2])
    closing = horizontal_limit-speed if speed is not None else None
    approach = 30.  # 缺测时的保守规划起点，非实测接近时间。
    source = 'conservative_default_without_geometry'
    if horizontal_error is not None and closing > .1:
        approach = max(10., 1.5*max(0., horizontal_error-1.)/closing,
                       max(0., vertical_error-.5)/vertical_limit)
        source = 'observed_geometry_with_closing_speed_and_1.5_margin'
    if closing is not None and closing <= .1:
        source = 'insufficient_closing_speed_do_not_assume_catchup'
        approach = None
    window = None if approach is None else math.ceil(5.+approach+remaining+10.)
    return {
        'jev_request_interval_s': JEV_INTERVAL_S,
        'horizontal_speed_limit_mps': horizontal_limit,
        'vertical_speed_limit_mps': vertical_limit,
        'startup_allowance_s': 5., 'execution_margin_s': 10.,
        'estimated_target_speed_mps': speed,
        'horizontal_goal_error_m': horizontal_error, 'vertical_goal_error_m': vertical_error,
        'estimated_approach_s': approach, 'estimate_source': source,
        'remaining_qualified_follow_s': None if stage.get('continuous') else remaining,
        'continuous_follow': bool(stage.get('continuous')),
        'review_execution': observation.get('review_execution', 'hold'),
        'suggested_follow_timeout_s': window,
        'suggested_follow_budget': None if window is None else math.ceil(window/JEV_INTERVAL_S)+3,
        'budget_formula': 'ceil(stage_timeout_s / jev_request_interval_s) + 3 retry/startup calls',
        'review_policy': observation.get('review_execution', 'aircraft holds; simulation and target motion continue throughout Qwen requests; task timeout is wall clock'),
        'available_recovery': (observation.get('search_description', 'stationary scan_yaw') if observation.get('active_search_available')
                               else 'no active search; reacquire only waits for target to return into current view'),
        'advisory_only': True,
    }
