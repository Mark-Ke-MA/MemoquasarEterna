#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from Core.Layer3_Decay.shared import load_json_file, write_json_atomic


def _trim_excerpts(excerpts: list[dict[str, Any]], keep_turn_indexes: list[int]) -> list[dict[str, Any]]:
    keep_set = set(keep_turn_indexes)
    trimmed: list[dict[str, Any]] = []
    for item in excerpts:
        if not isinstance(item, dict):
            continue
        turn_index = item.get('turn_index')
        if isinstance(turn_index, bool) or not isinstance(turn_index, int):
            continue
        if turn_index in keep_set:
            trimmed.append(item)
    return trimmed


def run_stage2(*, stage1_result: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    failed_count = 0
    trimmed_count = 0
    cleared_count = 0

    for item in stage1_result.get('planned_items', []):
        l2_path = Path(item.l2_path)
        try:
            l2_payload = load_json_file(l2_path)
            excerpts = l2_payload.get('conversation_excerpts')
            if not isinstance(excerpts, list):
                raise ValueError('conversation_excerpts 非 list')

            if item.mode == 'clear_for_nocontent':
                new_excerpts = []
            elif item.mode == 'trim_from_l1':
                new_excerpts = _trim_excerpts(excerpts, item.keep_turn_indexes)
            else:
                raise ValueError(f'未知 mode: {item.mode}')

            if not dry_run:
                updated_payload = dict(l2_payload)
                updated_payload['conversation_excerpts'] = new_excerpts
                write_json_atomic(l2_path, updated_payload)

            if item.mode == 'clear_for_nocontent':
                cleared_count += 1
            elif item.mode == 'trim_from_l1':
                trimmed_count += 1

            results.append({
                'agent_id': item.agent_id,
                'date': item.date,
                'l2_path': str(l2_path),
                'mode': item.mode,
                'success': True,
                'before_excerpt_count': item.original_excerpt_count,
                'after_excerpt_count': len(new_excerpts),
            })
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            results.append({
                'agent_id': item.agent_id,
                'date': item.date,
                'l2_path': str(l2_path),
                'mode': item.mode,
                'success': False,
                'reason': str(exc),
            })

    return {
        'results': results,
        'trimmed_count': trimmed_count,
        'cleared_count': cleared_count,
        'failed_count': failed_count,
        'success_count': sum(1 for item in results if item.get('success') is True),
    }


__all__ = [
    'run_stage2',
]
