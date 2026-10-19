"""Diagnose query-order changes by matching confident boxes; no accuracy gate."""
import argparse
import json
from pathlib import Path
import numpy as np


def detections(outputs, threshold):
    logits = outputs['pred_logits'][0].astype(np.float64)
    scores = 1/(1+np.exp(-np.clip(logits, -80, 80)))
    ids = np.flatnonzero(scores.max(1) > threshold)
    boxes = outputs['pred_boxes'][0, ids].astype(np.float64)
    boxes = np.concatenate((boxes[:, :2]-boxes[:, 2:]/2, boxes[:, :2]+boxes[:, 2:]/2), axis=1)
    return ids, boxes, scores[ids].max(1), scores[ids].argmax(1)


def compare(reference, actual, threshold):
    ri, rb, rs, rt = detections(reference, threshold)
    ai, ab, ass, at = detections(actual, threshold)
    pairs = []
    if len(ri) and len(ai):
        lo = np.maximum(rb[:, None, :2], ab[None, :, :2])
        hi = np.minimum(rb[:, None, 2:], ab[None, :, 2:])
        intersection = np.maximum(hi-lo, 0).prod(-1)
        union = np.maximum(rb[:, 2:]-rb[:, :2], 0).prod(-1)[:, None]+np.maximum(ab[:, 2:]-ab[:, :2], 0).prod(-1)[None]-intersection
        iou = intersection/np.maximum(union, 1e-12)
        # Only match boxes whose highest-scoring text token agrees.
        iou[rt[:, None] != at[None]] = -1
        for _ in range(min(len(ri), len(ai))):
            r,a = np.unravel_index(iou.argmax(), iou.shape)
            overlap = float(iou[r,a])
            if overlap < 0:
                break
            pairs.append({'reference_query': int(ri[r]), 'actual_query': int(ai[a]),
                          'iou': overlap, 'score_abs_delta': float(abs(rs[r]-ass[a]))})
            iou[r,:] = -1
            iou[:,a] = -1
    return {'reference_count': len(ri), 'actual_count': len(ai), 'matched_count': len(pairs),
            'iou_min': min((p['iou'] for p in pairs), default=None),
            'iou_mean': float(np.mean([p['iou'] for p in pairs])) if pairs else None,
            'score_max_abs_delta': max((p['score_abs_delta'] for p in pairs), default=None),
            'changed_query_ids': sum(p['reference_query'] != p['actual_query'] for p in pairs),
            'matches': pairs}


def main():
    here = Path(__file__).resolve().parent
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--bundle', type=Path, default=here/'bundle')
    cli.add_argument('--outputs-dir', type=Path, required=True)
    cli.add_argument('--report', type=Path, required=True)
    cli.add_argument('--threshold', type=float, default=.35)
    args = cli.parse_args()
    manifest = json.loads((args.bundle/'bundle.json').read_text())
    rows = []
    for case in manifest['cases']:
        with np.load(args.outputs_dir/case['inputs'],allow_pickle=False) as actual, np.load(args.bundle/case['golden'],allow_pickle=False) as golden, np.load(args.bundle/case['inputs'],allow_pickle=False) as inputs:
            floating = {n:inputs['ref__'+n] for n in manifest['output_names']}
            rows.append({'case':case['inputs'], 'golden':compare(golden,actual,args.threshold),
                         'float':compare(floating,actual,args.threshold)})
    report = {'threshold':args.threshold,'cases':rows,
              'note':'Greedy one-to-one IoU matching of confident boxes with matching top text token. Diagnostic only; does not replace strict golden validation or dataset accuracy evaluation.'}
    args.report.write_text(json.dumps(report,indent=2))
    for row in rows:
        print(row['case'], {ref:{k:v for k,v in row[ref].items() if k!='matches'} for ref in ('golden','float')})


if __name__ == '__main__':
    main()
