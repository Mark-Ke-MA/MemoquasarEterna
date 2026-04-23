#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from Core.Layer3_Decay.shared import load_json_file, utc_now_iso, write_json_atomic


def run_stage3(*, stage1_result: dict, stage2_result: dict, dry_run: bool = False) -> dict:
    trimmed_at = utc_now_iso()
    finalized_count = 0
    failed_finalize_count = 0
    failed_dates: list[str] = []

    for item in stage2_result.get('results', []):
        if item.get('success') is not True:
            continue
        l2_path = Path(str(item.get('l2_path', '')))
        try:
            if not dry_run:
                l2_payload = load_json_file(l2_path)
                status = l2_payload.get('status')
                if not isinstance(status, dict):
                    raise ValueError('status 非 dict')
                updated_payload = dict(l2_payload)
                updated_status = dict(status)
                updated_status['trimmed'] = True
                updated_status['trimmed_at'] = trimmed_at
                updated_payload['status'] = updated_status
                write_json_atomic(l2_path, updated_payload)
            finalized_count += 1
        except Exception:
            failed_finalize_count += 1
            failed_dates.append(str(item.get('date', '')))

    failed_run_dates = [str(item.get('date', '')) for item in stage2_result.get('results', []) if item.get('success') is not True]
    all_failed_dates = sorted(set(failed_dates + failed_run_dates))

    return {
        'success': failed_finalize_count == 0 and stage2_result.get('failed_count', 0) == 0,
        'phase': 'Phase1_trimL2',
        'target_week': stage1_result.get('target_week'),
        'boundary_date': stage1_result.get('boundary_date'),
        'planned_count': stage1_result.get('planned_count', 0),
        'skipped_count': stage1_result.get('skipped_count', 0),
        'trimmed_count': stage2_result.get('trimmed_count', 0),
        'cleared_count': stage2_result.get('cleared_count', 0),
        'success_count': stage2_result.get('success_count', 0),
        'failed_count': stage2_result.get('failed_count', 0) + failed_finalize_count,
        'finalized_count': finalized_count,
        'failed_dates': all_failed_dates,
        'dry_run': dry_run,
        'note': 'Phase1_trimL2 执行完成。',
    }


__all__ = [
    'run_stage3',
]
