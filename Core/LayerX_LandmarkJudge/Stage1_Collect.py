#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from Core.LayerX_LandmarkJudge.shared import LoadConfig, landmark_scores_path, parse_iso_date, selected_agents, load_json_file


def _date_in_range(day_text: str, *, target_date: str | None, date_start: str | None, date_end: str | None) -> bool:
    day = parse_iso_date(day_text)
    if target_date is not None:
        return day == parse_iso_date(target_date)
    if date_start is not None and date_end is not None:
        return parse_iso_date(date_start) <= day <= parse_iso_date(date_end)
    if date_start is not None:
        return day >= parse_iso_date(date_start)
    if date_end is not None:
        return day <= parse_iso_date(date_end)
    return True


def _normalize_record_counts(payload: dict[str, Any], *, agent_id: str) -> list[dict[str, Any]]:
    counts = payload.get('counts', []) if isinstance(payload, dict) else []
    if not isinstance(counts, list):
        return []
    out: list[dict[str, Any]] = []
    for item in counts:
        if not isinstance(item, dict):
            continue
        date_text = str(item.get('date', '') or '')
        if not date_text:
            continue
        out.append({
            'agent_id': agent_id,
            'target_date': date_text,
            'count_entry': item,
        })
    return out


def run_stage1(*, repo_root: str | Path | None = None, agent: str | None = None, date: str | None = None, date_start: str | None = None, date_end: str | None = None) -> dict[str, Any]:
    if date and (date_start or date_end):
        raise ValueError('--date 与 --date_start/--date_end 不能同时使用')

    cfg = LoadConfig(repo_root)
    overall_config = cfg.overall_config
    agent_ids = selected_agents(agent, list(overall_config.get('agentId_list', [])))

    items: list[dict[str, Any]] = []
    for agent_id in agent_ids:
        record_path = landmark_scores_path(agent_id, overall_config)
        if not record_path.exists():
            continue
        payload = load_json_file(Path(record_path))
        if not isinstance(payload, dict):
            raise ValueError(f'landmark_scores 不是合法 JSON 对象: {record_path}')
        for item in _normalize_record_counts(payload, agent_id=agent_id):
            date_text = str(item['target_date'])
            try:
                if not _date_in_range(date_text, target_date=date, date_start=date_start, date_end=date_end):
                    continue
            except Exception:
                continue
            items.append(item)

    items.sort(key=lambda item: (str(item.get('agent_id', '')), str(item.get('target_date', ''))))
    return {
        'items': items,
        'count': len(items),
    }


__all__ = [
    'run_stage1',
]
