#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

ALLOWED_KEY_ITEM_TYPES = ('milestone', 'bug_fix', 'config_change', 'decision', 'incident', 'question')


def _normalize_key_item_counts(raw: Any) -> dict[str, int]:
    out = {item_type: 0 for item_type in ALLOWED_KEY_ITEM_TYPES}
    if not isinstance(raw, dict):
        return out
    for item_type in ALLOWED_KEY_ITEM_TYPES:
        value = raw.get(item_type, 0)
        try:
            out[item_type] = int(value or 0)
        except Exception:
            out[item_type] = 0
    return out


def _normalize_emotional_intensity_counts(raw: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        try:
            key_int = int(str(key))
            count = int(value or 0)
        except Exception:
            continue
        if key_int < 0 or count <= 0:
            continue
        out[str(key_int)] = count
    return dict(sorted(out.items(), key=lambda item: int(item[0])))


def _analyze_count_entry(*, agent_id: str, target_date: str, count_entry: dict[str, Any]) -> dict[str, Any]:
    key_item_counts = _normalize_key_item_counts(count_entry.get('key_items'))
    emotional_intensity_counts = _normalize_emotional_intensity_counts(count_entry.get('emotional_intensities'))

    intensities: list[int] = []
    for key, count in emotional_intensity_counts.items():
        intensities.extend([int(key)] * max(0, int(count)))

    simple_mean = (sum(intensities) / len(intensities)) if intensities else 0.0
    weighted_mean = (sum(x * x for x in intensities) / sum(intensities)) if intensities and sum(intensities) > 0 else 0.0
    max_intensity = max(intensities) if intensities else 0
    intensity5_count = int(emotional_intensity_counts.get('5', 0) or 0)

    return {
        'agent_id': agent_id,
        'target_date': target_date,
        'intensities': intensities,
        'emotional_intensity_counts': emotional_intensity_counts,
        'emotional_peaks_count': len(intensities),
        'simple_mean_intensity': simple_mean,
        'weighted_mean_intensity': weighted_mean,
        'max_intensity': max_intensity,
        'intensity5_count': intensity5_count,
        'key_item_counts': key_item_counts,
    }


def run_stage2(*, stage1_result: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in stage1_result.get('items', []):
        if not isinstance(item, dict):
            continue
        count_entry = item.get('count_entry')
        if not isinstance(count_entry, dict):
            raise ValueError('stage1 item 缺少合法 count_entry')
        analyzed = _analyze_count_entry(
            agent_id=str(item.get('agent_id', '') or ''),
            target_date=str(item.get('target_date', '') or ''),
            count_entry=count_entry,
        )
        results.append(analyzed)
    return {
        'items': results,
        'count': len(results),
    }


__all__ = [
    'ALLOWED_KEY_ITEM_TYPES',
    'run_stage2',
]
