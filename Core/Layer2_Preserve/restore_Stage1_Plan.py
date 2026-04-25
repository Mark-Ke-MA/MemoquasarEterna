#!/usr/bin/env python3
from __future__ import annotations

import json
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from Core.Layer1_Write.shared import build_store_paths
from Core.Layer2_Preserve.core import (
    L0_EMBEDDINGS_SUBSET_FILENAME,
    L0_INDEX_SUBSET_FILENAME,
    MANIFEST_FILENAME,
    archive_tarball_path,
    load_preserve_config,
    preserve_result,
    restored_run_root,
    sanitize_run_name,
)
from Core.Layer2_Preserve.shared import iso_week_id, normalize_for_json, parse_iso_date, previous_iso_week_anchor, iso_week_window_from_anchor, utc_now_iso


@dataclass(frozen=True, slots=True)
class RestoreAgentPlan:
    agent_id: str
    selector_type: str
    selector_value: str
    week_id: str
    window_start: str
    window_end: str
    restore_mode: str
    which_level: list[str]
    run_name: str | None
    archive_path: str
    target_surface_root: str
    l0_target_path: str
    l0_embeddings_target_path: str
    files_to_restore: list[str]
    l0_index_entries: list[dict[str, Any]]
    l0_embedding_entries: dict[str, Any]
    status: str
    skip_reason: str | None


ALLOWED_LEVELS = {'l0', 'l1', 'l2'}


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


def _resolve_selector(week: str | None, date: str | None) -> tuple[str, str, str, str, str]:
    if bool(week) == bool(date):
        raise ValueError('--week 与 --date 必须二选一')
    if date:
        day = parse_iso_date(date)
        week_id = iso_week_id(day)
        window_start, window_end = iso_week_window_from_anchor(day)
        return 'date', date, week_id, window_start.strftime('%Y-%m-%d'), window_end.strftime('%Y-%m-%d')
    anchor = datetime.strptime(str(week) + '-1', '%G-W%V-%u').date() if week else previous_iso_week_anchor(datetime.now().date())
    window_start, window_end = iso_week_window_from_anchor(anchor)
    return 'week', str(week), iso_week_id(anchor), window_start.strftime('%Y-%m-%d'), window_end.strftime('%Y-%m-%d')


def _parse_which_level(which_level: str | None) -> list[str]:
    raw = str(which_level or 'all').strip().lower()
    if not raw or raw == 'all':
        return ['l0', 'l1', 'l2']
    levels: list[str] = []
    seen: set[str] = set()
    for item in raw.split(','):
        item = item.strip().lower()
        if not item or item in seen:
            continue
        if item not in ALLOWED_LEVELS:
            raise ValueError(f'不支持的 --which-level: {item}')
        seen.add(item)
        levels.append(item)
    if not levels:
        raise ValueError('--which-level 解析后为空')
    return levels


def _load_tar_json(tf: tarfile.TarFile, member_name: str, *, default: Any) -> Any:
    try:
        member = tf.getmember(member_name)
    except KeyError:
        return default
    extracted = tf.extractfile(member)
    if extracted is None:
        return default
    try:
        return json.loads(extracted.read().decode('utf-8'))
    except Exception:
        return default


def _date_from_member_name(name: str) -> str | None:
    day_text = name[:10]
    try:
        parse_iso_date(day_text)
    except Exception:
        return None
    return day_text


def _include_member(name: str, levels: set[str]) -> bool:
    if name.endswith('_l2.json'):
        return 'l2' in levels
    if name.endswith('_l1.json'):
        return 'l1' in levels
    if name.endswith('.nocontent'):
        return 'l0' in levels or 'l1' in levels
    if name.endswith('.noconversation'):
        return True
    return False


def _filter_members(names: list[str], *, selector_type: str, selector_value: str, levels: list[str]) -> list[str]:
    level_set = set(levels)
    kept: list[str] = []
    for name in names:
        if name in {MANIFEST_FILENAME, L0_INDEX_SUBSET_FILENAME, L0_EMBEDDINGS_SUBSET_FILENAME}:
            continue
        day_text = _date_from_member_name(name)
        if day_text is None:
            continue
        if selector_type == 'date' and day_text != selector_value:
            continue
        if not _include_member(name, level_set):
            continue
        kept.append(name)
    return kept


def _filter_l0_index_entries(entries: list[dict[str, Any]], *, selector_type: str, selector_value: str, levels: list[str]) -> list[dict[str, Any]]:
    if 'l0' not in levels:
        return []
    if selector_type == 'week':
        return [entry for entry in entries if isinstance(entry, dict)]
    return [entry for entry in entries if isinstance(entry, dict) and str(entry.get('date', '')) == selector_value]


def _filter_l0_embedding_entries(entries: dict[str, Any], *, selector_type: str, selector_value: str, levels: list[str]) -> dict[str, Any]:
    if 'l0' not in levels:
        return {}
    if selector_type == 'week':
        return {str(k): v for k, v in entries.items()}
    kept: dict[str, Any] = {}
    for key, value in entries.items():
        if not isinstance(key, str) or '::' not in key:
            continue
        date_part, _ = key.split('::', 1)
        if date_part == selector_value:
            kept[key] = value
    return kept


def _surface_root_for_mode(*, cfg, agent_id: str, restore_mode: str, run_name: str | None) -> Path:
    store_paths = build_store_paths(agent_id, cfg.overall_config)
    if restore_mode == 'mirrored':
        return restored_run_root(cfg, run_name) / agent_id / 'surface'
    return Path(store_paths['memory_surface_root'])


def run_restore_stage1(*, repo_root: str | None = None, week: str | None = None, date: str | None = None, agent: str | None = None, which_level: str | None = None, restore_mode: str = 'mirrored', run_name: str | None = None) -> dict[str, Any]:
    cfg = load_preserve_config(repo_root)
    from Core.shared_funcs import get_production_agent_ids
    selected_agents = _parse_selected_agents(agent, get_production_agent_ids(cfg.overall_config))
    selector_type, selector_value, week_id, window_start, window_end = _resolve_selector(week, date)
    levels = _parse_which_level(which_level)
    normalized_run_name = sanitize_run_name(run_name) if restore_mode == 'mirrored' else (sanitize_run_name(run_name) if run_name else None)

    agent_plans: list[RestoreAgentPlan] = []
    for agent_id in selected_agents:
        archive_path = archive_tarball_path(cfg, agent_id, week_id)
        if not archive_path.exists():
            agent_plans.append(RestoreAgentPlan(
                agent_id=agent_id,
                selector_type=selector_type,
                selector_value=selector_value,
                week_id=week_id,
                window_start=window_start,
                window_end=window_end,
                restore_mode=restore_mode,
                which_level=levels,
                run_name=normalized_run_name,
                archive_path=str(archive_path),
                target_surface_root=str(_surface_root_for_mode(cfg=cfg, agent_id=agent_id, restore_mode=restore_mode, run_name=normalized_run_name)),
                l0_target_path=str(_surface_root_for_mode(cfg=cfg, agent_id=agent_id, restore_mode=restore_mode, run_name=normalized_run_name) / 'l0_index.json'),
                l0_embeddings_target_path=str(_surface_root_for_mode(cfg=cfg, agent_id=agent_id, restore_mode=restore_mode, run_name=normalized_run_name) / 'l0_embeddings.json'),
                files_to_restore=[],
                l0_index_entries=[],
                l0_embedding_entries={},
                status='skipped',
                skip_reason='archive_missing',
            ))
            continue

        with tarfile.open(archive_path, 'r:gz') as tf:
            member_names = [member.name for member in tf.getmembers() if member.isfile()]
            manifest = _load_tar_json(tf, MANIFEST_FILENAME, default={})
            if not isinstance(manifest, dict):
                manifest = {}
            l0_index_entries = _load_tar_json(tf, L0_INDEX_SUBSET_FILENAME, default=[])
            l0_embedding_entries = _load_tar_json(tf, L0_EMBEDDINGS_SUBSET_FILENAME, default={})
            filtered_files = _filter_members(member_names, selector_type=selector_type, selector_value=selector_value, levels=levels)
            filtered_l0_index_entries = _filter_l0_index_entries(l0_index_entries if isinstance(l0_index_entries, list) else [], selector_type=selector_type, selector_value=selector_value, levels=levels)
            filtered_l0_embedding_entries = _filter_l0_embedding_entries(l0_embedding_entries if isinstance(l0_embedding_entries, dict) else {}, selector_type=selector_type, selector_value=selector_value, levels=levels)

        target_surface_root = _surface_root_for_mode(cfg=cfg, agent_id=agent_id, restore_mode=restore_mode, run_name=normalized_run_name)
        status = 'pending'
        skip_reason = None
        if restore_mode == 'mirrored' and target_surface_root.exists():
            status = 'skipped'
            skip_reason = 'run_name_exists'
        if not filtered_files and not filtered_l0_index_entries and not filtered_l0_embedding_entries:
            status = 'skipped'
            skip_reason = 'no_matching_artifacts'

        agent_plans.append(RestoreAgentPlan(
            agent_id=agent_id,
            selector_type=selector_type,
            selector_value=selector_value,
            week_id=week_id,
            window_start=window_start,
            window_end=window_end,
            restore_mode=restore_mode,
            which_level=levels,
            run_name=normalized_run_name,
            archive_path=str(archive_path),
            target_surface_root=str(target_surface_root),
            l0_target_path=str(target_surface_root / 'l0_index.json'),
            l0_embeddings_target_path=str(target_surface_root / 'l0_embeddings.json'),
            files_to_restore=filtered_files,
            l0_index_entries=filtered_l0_index_entries,
            l0_embedding_entries=filtered_l0_embedding_entries,
            status=status,
            skip_reason=skip_reason,
        ))

    return preserve_result(
        success=True,
        stage='Layer2_Restore_Stage1_Plan',
        note='Stage1 已完成：解析 restore 目标并生成计划。',
        selector_type=selector_type,
        selector_value=selector_value,
        week_id=week_id,
        window_start=window_start,
        window_end=window_end,
        restore_mode=restore_mode,
        run_name=normalized_run_name,
        which_level=levels,
        created_at=utc_now_iso(),
        agent_plans=normalize_for_json(agent_plans),
    )
