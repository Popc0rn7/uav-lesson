"""红色车辆 demo 的语义候选筛选；不把检测候选等同于跟踪身份。"""
import math


def filter_candidates(detections, threshold=.35, iou_threshold=.5):
    results = []
    for detection in detections:
        item = dict(detection)
        label = str(item.get('label', '')).lower().strip(' .')
        score = item.get('score')
        box = item.get('box_xyxy', [])
        reason = None
        if not isinstance(score, (float, int)) or not math.isfinite(score) or not 0 <= score <= 1:
            reason = 'invalid_score'
        elif len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box) or box[2] <= box[0] or box[3] <= box[1]:
            reason = 'invalid_box'
        elif not any(word in label.split() for word in ('car', 'vehicle', 'box')):
            reason = 'unsupported_semantics'
        elif score < threshold:
            reason = 'low_confidence'
        item.update(accepted=reason is None, rejection_reason=reason,
                    semantic_role='red_vehicle_candidate' if reason is None else 'rejected')
        results.append(item)
    kept = []
    for item in sorted((v for v in results if v['accepted']), key=lambda v: v['score'], reverse=True):
        a = item['box_xyxy']
        duplicate = False
        for prior in kept:
            b = prior['box_xyxy']
            intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
            union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
            if intersection/union >= iou_threshold:
                duplicate = True; break
        if duplicate:
            item.update(accepted=False, rejection_reason='duplicate_box', semantic_role='rejected')
        else:
            kept.append(item)
    return kept, results
