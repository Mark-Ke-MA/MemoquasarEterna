#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Core.Layer3_Decay.core import trim_l2_boundary_date
from Core.Layer3_Decay.shared import LoadConfig, load_json_file, month_dirs_under, monday_of_iso_week, parse_iso_date, selected_agents, surface_root


@dataclass(slots=True)
class TrimL2PlanItem:
    agent_id: str
    date: str
    l2_path: str
    l1_path: str | None
    nocontent_path: str | None
    mode: str
    keep_turn_indexes: list[int]
    original_excerpt_count: int


def _extract_keep_turn_indexes(l1_payload: dict[str, Any]) -> list[int] | None:
    emotional_peaks = l1_payload.get('emotional_peaks')
    compress_hints = l1_payload.get('_compress_hints')

    keep: set[int] = set()

    if emotional_peaks is not None:
        if not isinstance(emotional_peaks, list):
            return None
        for item in emotional_peaks:
            if not isinstance(item, dict):
                return None
            turn = item.get('turn')
            if isinstance(turn, bool) or not isinstance(turn, int):
                return None
            keep.add(turn)

    if compress_hints is not None:
        if not isinstance(compress_hints, list):
            return None
        for item in compress_hints:
            if isinstance(item, bool) or not isinstance(item, int):
                return None
            keep.add(item)

    return sorted(keep)


def _find_day_partner_paths(l2_path: Path) -> tuple[Path, Path]:
    day_text = l2_path.name[:10]
    return (
        l2_path.with_name(f'{day_text}_l1.json'),
        l2_path.with_name(f'{day_text}.nocontent'),
    )


def _build_candidate_item(agent_id: str, l2_path: Path) -> tuple[str, TrimL2PlanItem | None, dict[str, Any] | None]:
    try:
        l2_payload = load_json_file(l2_path)
    except Exception:
        return 'invalid_l2_schema', None, None
    if not isinstance(l2_payload, dict):
        return 'invalid_l2_schema', None, None

    status = l2_payload.get('status')
    if not isinstance(status, dict):
        return 'invalid_l2_schema', None, None
    if status.get('archived') is not True:
        return 'status_not_archived', None, None
    if status.get('trimmed') is True:
        return 'already_trimmed', None, None

    excerpts = l2_payload.get('conversation_excerpts')
    if not isinstance(excerpts, list):
        return 'invalid_l2_schema', None, None

    l1_path, nocontent_path = _find_day_partner_paths(l2_path)
    date_text = l2_path.name[:10]

    if l1_path.exists():
        try:
            l1_payload = load_json_file(l1_path)
        except Exception:
            return 'invalid_l1_schema', None, None
        if not isinstance(l1_payload, dict):
            return 'invalid_l1_schema', None, None
        keep_turn_indexes = _extract_keep_turn_indexes(l1_payload)
        if keep_turn_indexes is None:
            return 'invalid_l1_schema', None, None
        return 'planned', TrimL2PlanItem(
            agent_id=agent_id,
            date=date_text,
            l2_path=str(l2_path),
            l1_path=str(l1_path),
            nocontent_path=None,
            mode='trim_from_l1',
            keep_turn_indexes=keep_turn_indexes,
            original_excerpt_count=len(excerpts),
        ), None

    if nocontent_path.exists():
        return 'planned', TrimL2PlanItem(
            agent_id=agent_id,
            date=date_text,
            l2_path=str(l2_path),
            l1_path=None,
            nocontent_path=str(nocontent_path),
            mode='clear_for_nocontent',
            keep_turn_indexes=[],
            original_excerpt_count=len(excerpts),
        ), None

    return 'missing_l1_and_nocontent', None, None


def run_stage1(*, repo_root: str | Path | None = None, week: str | None = None, source_week: str | None = None, agent: str | None = None) -> dict[str, Any]:
    cfg = LoadConfig(repo_root)
    overall_config = cfg.overall_config
    agent_ids = selected_agents(agent, list(overall_config.get('agentId_list', [])))
    if week and source_week:
        raise ValueError('--week 与 --source-week 不能同时使用')
    if source_week:
        monday = monday_of_iso_week(str(source_week))
        boundary = monday.replace() + __import__('datetime').timedelta(days=6)
    elif week:
        boundary = trim_l2_boundary_date(str(week), repo_root=repo_root)
    else:
        raise ValueError('Phase1 Stage1 缺少 week/source_week')

    planned_items: list[TrimL2PlanItem] = []
    skipped: list[dict[str, str]] = []

    for agent_id in agent_ids:
        root = surface_root(agent_id, overall_config)
        for month_dir in month_dirs_under(root):
            for l2_path in sorted(month_dir.glob('*_l2.json')):
                date_text = l2_path.name[:10]
                try:
                    day = parse_iso_date(date_text)
                except Exception:
                    continue
                if day > boundary:
                    continue
                reason, item, _payload = _build_candidate_item(agent_id, l2_path)
                if item is not None:
                    planned_items.append(item)
                else:
                    skipped.append({
                        'agent_id': agent_id,
                        'date': date_text,
                        'l2_path': str(l2_path),
                        'reason': reason,
                    })

    return {
        'target_week': week,
        'source_week': source_week,
        'boundary_date': boundary.strftime('%Y-%m-%d'),
        'planned_items': planned_items,
        'skipped': skipped,
        'planned_count': len(planned_items),
        'skipped_count': len(skipped),
    }


__all__ = [
    'TrimL2PlanItem',
    'run_stage1',
]
