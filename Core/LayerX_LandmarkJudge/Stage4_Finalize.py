#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from Core.LayerX_LandmarkJudge.Stage2_Analyze import ALLOWED_KEY_ITEM_TYPES
from Core.LayerX_LandmarkJudge.shared import resolve_graphs_dir


def _quantile_threshold(values: list[float], landmark_ratio: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(float(v) for v in values)
    n = len(sorted_values)
    p = max(0.0, min(1.0, 1.0 - float(landmark_ratio)))
    if n == 1:
        return sorted_values[0]
    index = int(math.ceil(p * n) - 1)
    index = max(0, min(n - 1, index))
    return sorted_values[index]


def _save_histogram(values: list[float], *, title: str, xlabel: str, out_path: Path, bins=10, threshold_line: float | None = None) -> str | None:
    if not values:
        return None
    plt.figure(figsize=(7, 4.5))
    plt.hist(values, bins=bins, edgecolor='black')
    if threshold_line is not None:
        plt.axvline(threshold_line, color='red', linestyle='--', linewidth=1.5)
        ymax = plt.gca().get_ylim()[1]
        plt.text(threshold_line, ymax * 0.95, f'th={threshold_line:.1f}', color='red', rotation=90, va='top', ha='left')
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel('Count')
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path)
    plt.close()
    return str(out_path)


def _save_bar(mapping: dict[Any, int], *, title: str, xlabel: str, out_path: Path) -> str | None:
    if not mapping:
        return None
    labels = [str(k) for k in mapping.keys()]
    values = [int(v) for v in mapping.values()]
    plt.figure(figsize=(7, 4.5))
    plt.bar(labels, values)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel('Count')
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path)
    plt.close()
    return str(out_path)


def _analysis_output(*, repo_root: str | Path | None, stage2_result: dict[str, Any], stage3_result: dict[str, Any], graphs_path: str | None, landmark_ratio: float | None = None, window_start: str | None = None, window_end: str | None = None) -> dict[str, Any]:
    items = stage2_result.get('items', [])
    score_items = stage3_result.get('items', [])
    graphs_dir = resolve_graphs_dir(repo_root=repo_root, graphs_path=graphs_path) if graphs_path else None
    if graphs_dir is not None:
        graphs_dir.mkdir(parents=True, exist_ok=True)

    generated_graphs: list[str] = []

    all_intensities: list[int] = []
    mean_intensities: list[float] = []
    weighted_mean_intensities: list[float] = []
    key_item_global_counts = {item_type: 0 for item_type in ALLOWED_KEY_ITEM_TYPES}
    per_file_type_histograms = {item_type: {} for item_type in ALLOWED_KEY_ITEM_TYPES}
    score_values: list[float] = []

    for item in items:
        intensities = item.get('intensities', []) if isinstance(item.get('intensities'), list) else []
        all_intensities.extend([int(x) for x in intensities if isinstance(x, int) and not isinstance(x, bool) and x >= 0])
        mean_intensities.append(float(item.get('simple_mean_intensity', 0.0) or 0.0))
        weighted_mean_intensities.append(float(item.get('weighted_mean_intensity', 0.0) or 0.0))
        key_item_counts = item.get('key_item_counts', {}) if isinstance(item.get('key_item_counts'), dict) else {}
        for item_type in ALLOWED_KEY_ITEM_TYPES:
            count = int(key_item_counts.get(item_type, 0) or 0)
            key_item_global_counts[item_type] += count
            per_file_hist = per_file_type_histograms[item_type]
            per_file_hist[count] = int(per_file_hist.get(count, 0) or 0) + 1

    for score_item in score_items:
        score_values.append(float(score_item.get('score', 0.0) or 0.0))

    analysis_threshold = _quantile_threshold(score_values, landmark_ratio) if landmark_ratio is not None else None

    intensity_bins = None
    if all_intensities:
        min_intensity = min(all_intensities)
        max_intensity = max(all_intensities)
        intensity_bins = [value - 0.5 for value in range(min_intensity, max_intensity + 2)]

    if graphs_dir is not None:
        candidates = [
            _save_histogram(all_intensities, title='Emotional Peaks Intensity Histogram', xlabel='Intensity', out_path=graphs_dir / 'emotional_peaks_intensity_hist.svg', bins=intensity_bins or 10),
            _save_histogram(mean_intensities, title='Emotional Peaks Mean Intensity per L1', xlabel='Mean intensity', out_path=graphs_dir / 'emotional_peaks_mean_hist.svg', bins=10),
            _save_histogram(weighted_mean_intensities, title='Emotional Peaks Weighted Mean Intensity per L1', xlabel='Weighted mean intensity', out_path=graphs_dir / 'emotional_peaks_weighted_mean_hist.svg', bins=10),
            _save_bar(key_item_global_counts, title='Key Item Type Histogram', xlabel='Key item type', out_path=graphs_dir / 'key_item_type_hist.svg'),
            _save_histogram(score_values, title='Landmark Score Histogram', xlabel='Score', out_path=graphs_dir / 'landmark_score_hist.svg', bins=10, threshold_line=analysis_threshold),
        ]

        for item_type in ALLOWED_KEY_ITEM_TYPES:
            maybe_path = _save_bar(
                per_file_type_histograms[item_type],
                title=f'{item_type} Per-L1 Count Histogram',
                xlabel=f'{item_type} count per L1',
                out_path=graphs_dir / f'{item_type}_per_file_hist.svg',
            )
            candidates.append(maybe_path)

        generated_graphs.extend([path for path in candidates if path])

    result = {
        'success': True,
        'mode': 'analysis',
        'files_analyzed': int(stage2_result.get('count', 0) or 0),
    }
    if window_start is not None:
        result['window_start'] = window_start
    if window_end is not None:
        result['window_end'] = window_end
    if graphs_dir is not None:
        result['graphs_dir'] = str(graphs_dir)
        result['generated_graphs'] = generated_graphs
    if landmark_ratio is not None:
        result['analysis_threshold'] = round(analysis_threshold, 3) if analysis_threshold is not None else None
    else:
        result['threshold_used'] = stage3_result.get('threshold')
    return result


def _judge_output(stage3_result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in stage3_result.get('items', []):
        rows.append({
            'agentId': item.get('agent_id', ''),
            'target_date': item.get('target_date', ''),
            'score': float(item.get('score', 0.0) or 0.0),
            'landmark': bool(item.get('landmark', False)),
        })
    rows.sort(key=lambda item: (str(item.get('agentId', '')), str(item.get('target_date', ''))))
    return rows


def run_stage4(*, repo_root: str | Path | None = None, analysis: bool = False, graphs_path: str | None = None, stage2_result: dict[str, Any], stage3_result: dict[str, Any], landmark_ratio: float | None = None, window_start: str | None = None, window_end: str | None = None):
    if analysis:
        return _analysis_output(repo_root=repo_root, stage2_result=stage2_result, stage3_result=stage3_result, graphs_path=graphs_path, landmark_ratio=landmark_ratio, window_start=window_start, window_end=window_end)
    return _judge_output(stage3_result)


__all__ = [
    'run_stage4',
]
