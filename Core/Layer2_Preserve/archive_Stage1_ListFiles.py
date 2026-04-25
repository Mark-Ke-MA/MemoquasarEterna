#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from Core.Layer2_Preserve.core import load_preserve_config, archive_tarball_path, preserve_result
from Core.Layer2_Preserve.shared import parse_iso_date, iso_week_id, previous_iso_week_anchor, iso_week_window_from_anchor, utc_now_iso, store_surface_root, normalize_for_json
from Core.harness_connector import call_optional_connector, load_harness_connector


@dataclass(frozen=True, slots=True)
class ArchiveAgentPlan:
    agent_id: str
    week_id: str
    window_start: str
    window_end: str
    surface_root: str
    archive_path: str
    overwrite: bool
    candidate_files: list[str]
    l0_index_path: str
    l0_embeddings_path: str
    status: str
    skip_reason: str | None


def _parse_selected_agents(agent: str | None, all_agents: list[str]) -> list[str]:
    if agent is None or not str(agent).strip():
        return list(all_agents)
    parsed: list[str] = []
    seen: set[str] = set()
    for item in str(agent).split(','):
        item = item.strip()
        if not item or item in seen:
            continue
        if item not in all_agents:
            raise ValueError(f'未知 agent: {item}')
        seen.add(item)
        parsed.append(item)
    if not parsed:
        raise ValueError('--agent 解析后为空')
    return parsed


def _resolve_week_window(week: str | None) -> tuple[str, str, str]:
    if week:
        anchor = datetime.strptime(week + '-1', '%G-W%V-%u').date()
    else:
        anchor = previous_iso_week_anchor(datetime.now().date())
    window_start, window_end = iso_week_window_from_anchor(anchor)
    return iso_week_id(anchor), window_start.strftime('%Y-%m-%d'), window_end.strftime('%Y-%m-%d')


def _collect_candidate_files(surface_root: Path, window_start: str, window_end: str) -> list[str]:
    start = parse_iso_date(window_start)
    end = parse_iso_date(window_end)
    candidates: list[str] = []
    for day_dir in sorted(surface_root.glob('????-??')):
        if not day_dir.is_dir():
            continue
        for path in sorted(day_dir.iterdir()):
            name = path.name
            day_text = name[:10]
            try:
                day = parse_iso_date(day_text)
            except Exception:
                continue
            if not (start <= day <= end):
                continue
            if name.endswith('_l2.json') or name.endswith('_l1.json') or name.endswith('.nocontent') or name.endswith('.noconversation'):
                candidates.append(str(path))
    return candidates


def run_archive_stage1(*, repo_root: str | None = None, week: str | None = None, agent: str | None = None, overwrite: bool = False, run_mode: str = 'manual', harness_only: bool = False, core_only: bool = False, dry_run: bool = False) -> dict[str, Any]:
    cfg = load_preserve_config(repo_root)
    connector = load_harness_connector(repo_root=repo_root, harness=str(cfg.overall_config.get('harness', 'openclaw') or 'openclaw'))
    call_optional_connector(
        connector,
        'production_agent',
        'preserve',
        context={
            'repo_root': repo_root,
            'inputs': {
                'week': week,
                'agent': agent,
                'overwrite': overwrite,
                'run_mode': run_mode,
                'harness_only': harness_only,
                'core_only': core_only,
                'dry_run': dry_run,
            },
        },
    )
    selected_agents = _parse_selected_agents(agent, list(cfg.overall_config.get('agentId_list', [])))
    week_id, window_start, window_end = _resolve_week_window(week)

    agent_plans: list[ArchiveAgentPlan] = []
    for agent_id in selected_agents:
        surface_root = store_surface_root(agent_id, cfg.overall_config)
        archive_path = archive_tarball_path(cfg, agent_id, week_id)
        candidate_files = _collect_candidate_files(surface_root, window_start, window_end)
        skip_reason = None
        status = 'pending'
        if archive_path.exists() and not overwrite:
            status = 'skipped'
            skip_reason = 'archive_exists'
        agent_plans.append(ArchiveAgentPlan(
            agent_id=agent_id,
            week_id=week_id,
            window_start=window_start,
            window_end=window_end,
            surface_root=str(surface_root),
            archive_path=str(archive_path),
            overwrite=overwrite,
            candidate_files=candidate_files,
            l0_index_path=str(surface_root / 'l0_index.json'),
            l0_embeddings_path=str(surface_root / 'l0_embeddings.json'),
            status=status,
            skip_reason=skip_reason,
        ))

    return preserve_result(
        success=True,
        stage='Layer2_Archive_Stage1_ListFiles',
        note='Stage1 已完成：解析目标周并收集候选文件。',
        week_id=week_id,
        window_start=window_start,
        window_end=window_end,
        overwrite=overwrite,
        agent_plans=normalize_for_json(agent_plans),
        created_at=utc_now_iso(),
    )
