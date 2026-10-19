"""给出空帧比例，再附有候选的原始观测；不替模型分类或判断。"""
import copy


def summarize_observations(observations, generation, now, window_s=4.):
    frames = sorted((v for v in observations if v.get('generation') == generation
                     and 0 <= now-v['received'] <= window_s), key=lambda v: v['received'])
    candidates = [v for v in frames if any(d.get('accepted') for d in v.get('detections', []))]
    empty = len(frames)-len(candidates)
    records = [dict(copy.deepcopy(v), age_s=now-v['received']) for v in candidates]
    return dict(summary=f'Recent {window_s:g}s: {empty} out of {len(frames)} frames had no accepted detection.',
                window_s=window_s, observed_frames=len(frames), no_detection_frames=empty,
                candidate_observations=records)
