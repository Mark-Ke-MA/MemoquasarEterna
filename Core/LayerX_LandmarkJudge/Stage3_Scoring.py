#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

LANDMARK_THRESHOLD = 5.5


def _score_single_analysis(analysis: dict[str, Any], *, threshold: float = LANDMARK_THRESHOLD) -> dict[str, Any]:
    key_item_counts = dict(analysis.get('key_item_counts', {})) if isinstance(analysis.get('key_item_counts'), dict) else {}
    milestone_count = int(key_item_counts.get('milestone', 0) or 0)
    bug_fix_count = int(key_item_counts.get('bug_fix', 0) or 0)
    incident_count = int(key_item_counts.get('incident', 0) or 0)

    key_item_score = 0.0
    if milestone_count == 1:
        key_item_score += 0.5
    elif milestone_count >= 2:
        key_item_score += 1.5
    if bug_fix_count >= 1:
        key_item_score += 2.0
    if incident_count == 1:
        key_item_score += 1.0
    elif incident_count >= 2:
        key_item_score += 1.5

    weighted_mean = float(analysis.get('weighted_mean_intensity', 0.0) or 0.0)
    intensity5_count = int(analysis.get('intensity5_count', 0) or 0)

    if weighted_mean < 3.6:
        emotion_score = 0.0
    else:
        emotion_score = weighted_mean - 3.6
    if intensity5_count >= 1:
        emotion_score += 0.5
    if intensity5_count >= 2:
        emotion_score += 0.5

    total_score = key_item_score + emotion_score
    return {
        'agent_id': analysis.get('agent_id', ''),
        'target_date': analysis.get('target_date', ''),
        'score': round(total_score, 3),
        'landmark': bool(total_score >= threshold),
        'score_breakdown': {
            'key_item_score': round(key_item_score, 3),
            'emotion_score': round(emotion_score, 3),
            'threshold': threshold,
        },
    }


def run_stage3(*, stage2_result: dict[str, Any], threshold: float = LANDMARK_THRESHOLD) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in stage2_result.get('items', []):
        scored = _score_single_analysis(item, threshold=threshold)
        results.append(scored)
    return {
        'items': results,
        'count': len(results),
        'threshold': threshold,
    }


__all__ = [
    'LANDMARK_THRESHOLD',
    'run_stage3',
]
