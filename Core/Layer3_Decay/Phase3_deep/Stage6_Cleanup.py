#!/usr/bin/env python3
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

from Core.Layer1_Write.json_repair import load_json_with_repair
from Core.Layer1_Write.shared import LoadConfig, load_json_file, write_json_atomic



def _plan_path(repo_root: str | Path | None = None) -> Path:
    overall_cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(overall_cfg['store_dir'])).expanduser()
    staging_cfg = overall_cfg['store_dir_structure']['staging']
    staging_root = store_root / staging_cfg['root'] / staging_cfg['staging_deep']
    return staging_root / 'plan.json'


def _staging_root(repo_root: str | Path | None = None) -> Path:
    return _plan_path(repo_root).parent


def _load_plan(repo_root: str | Path | None = None) -> dict[str, Any]:
    path = _plan_path(repo_root)
    if not path.exists():
        raise FileNotFoundError(f'plan.json 不存在: {path}')
    return load_json_file(path)


def _plan_write_path(repo_root: str | Path | None = None) -> Path:
    return _plan_path(repo_root)


def _load_json_dict(path: str | Path) -> dict[str, Any]:
    ok, payload, _repaired = load_json_with_repair(path)
    if not ok or not isinstance(payload, dict):
        raise ValueError(f'无法读取合法 JSON 对象: {path}')
    return payload


def _clean_staging_agents(repo_root: str | Path | None, selected_agents: list[str]) -> list[str]:
    staging_root = _staging_root(repo_root)
    cleaned: list[str] = []
    for agent_id in selected_agents:
        agent_root = staging_root / str(agent_id)
        if agent_root.exists():
            for child in agent_root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            cleaned.append(str(agent_root))
        else:
            agent_root.mkdir(parents=True, exist_ok=True)
            cleaned.append(str(agent_root))
    return cleaned


def _delete_files(filelist: list[str]) -> dict[str, Any]:
    deleted: list[str] = []
    missing: list[str] = []
    failed: list[dict[str, str]] = []
    for raw in filelist:
        path = Path(str(raw))
        try:
            if path.exists():
                path.unlink()
                deleted.append(str(path))
            else:
                missing.append(str(path))
        except Exception as exc:  # noqa: BLE001
            failed.append({'path': str(path), 'reason': str(exc)})
    return {'deleted': deleted, 'missing': missing, 'failed': failed}


def _read_counts(path: str | Path) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    lines = file_path.read_text(encoding='utf-8').splitlines()
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        week = str(line).strip()
        if not week or week in seen:
            continue
        seen.add(week)
        out.append(week)
    return out


def _write_counts(path: str | Path, weeks: list[str]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    ordered: list[str] = []
    seen: set[str] = set()
    for week in weeks:
        text = str(week).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    file_path.write_text(''.join(f'{week}\n' for week in ordered), encoding='utf-8')


def _prune_counts(path: str | Path, weeks_to_remove: set[str]) -> dict[str, Any]:
    current = _read_counts(path)
    new_weeks = [week for week in current if week not in weeks_to_remove]
    removed = [week for week in current if week in weeks_to_remove]
    _write_counts(path, new_weeks)
    return {'removed': removed, 'remaining': new_weeks}


def _prune_l0_index(path: str | Path, target_weeks: set[str]) -> dict[str, Any]:
    if not target_weeks:
        return {'updated': False, 'removed_count': 0}
    payload = _load_json_dict(path)
    entries = payload.get('entries', [])
    if not isinstance(entries, list):
        entries = []
    new_entries: list[dict[str, Any]] = []
    removed_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get('depth', '') or '') == 'shallow' and str(entry.get('week', '') or '') in target_weeks:
            removed_count += 1
            continue
        new_entries.append(entry)
    payload['entries'] = new_entries
    payload['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    write_json_atomic(path, payload)
    return {'updated': True, 'removed_count': removed_count}


def _prune_l0_embeddings(path: str | Path, target_weeks: set[str]) -> dict[str, Any]:
    if not target_weeks:
        return {'updated': False, 'removed_count': 0}
    payload = _load_json_dict(path)
    entries = payload.get('entries', {})
    if not isinstance(entries, dict):
        entries = {}
    new_entries: dict[str, Any] = {}
    removed_count = 0
    for key, value in entries.items():
        if isinstance(value, dict) and str(value.get('depth', '') or '') == 'shallow' and str(value.get('week', '') or '') in target_weeks:
            removed_count += 1
            continue
        if str(key).endswith('::shallow') and str(key).split('::', 1)[0] in target_weeks:
            removed_count += 1
            continue
        new_entries[key] = value
    payload['entries'] = new_entries
    payload['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    write_json_atomic(path, payload)
    return {'updated': True, 'removed_count': removed_count}


def run_stage6(repo_root: str | Path | None = None, *, apply_cleanup: bool = False) -> dict[str, Any]:
    plan = _load_plan(repo_root)
    root = plan.setdefault('plan', {})
    run_meta = root.setdefault('run_meta', {})
    stage1 = root.setdefault('stage1', {})
    stage6 = root.setdefault('stage6', {})

    selected_agents = stage1.get('selected_agents', [])
    if not isinstance(selected_agents, list):
        selected_agents = []

    files_to_delete = stage6.get('files_to_delete', [])
    if not isinstance(files_to_delete, list):
        files_to_delete = []
    counts_entries_to_delete = stage6.get('counts_entries_to_delete', [])
    if not isinstance(counts_entries_to_delete, list):
        counts_entries_to_delete = []
    l0_entries_to_delete = stage6.get('l0_entries_to_delete', [])
    if not isinstance(l0_entries_to_delete, list):
        l0_entries_to_delete = []

    staging_cleaned = _clean_staging_agents(repo_root, [str(agent) for agent in selected_agents if str(agent).strip()])

    file_results: list[dict[str, Any]] = []
    counts_results: list[dict[str, Any]] = []
    l0_results: list[dict[str, Any]] = []
    failed_agents: list[str] = []
    succeed_agents: list[str] = []

    if apply_cleanup:
        for item in files_to_delete:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get('agent_id', '') or '')
            filelist = item.get('filelist', [])
            if not isinstance(filelist, list):
                filelist = []
            result = _delete_files([str(path) for path in filelist])
            file_results.append({'agent_id': agent_id, **result})
            if result['failed']:
                if agent_id and agent_id not in failed_agents:
                    failed_agents.append(agent_id)
            else:
                if agent_id and agent_id not in succeed_agents:
                    succeed_agents.append(agent_id)

        for item in counts_entries_to_delete:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get('agent_id', '') or '')
            counts_path = str(item.get('shallow_counts_path', '') or '')
            weeks_raw = item.get('weeks', [])
            weeks = {str(x).strip() for x in weeks_raw if str(x).strip()} if isinstance(weeks_raw, list) else set()
            try:
                prune_result = _prune_counts(counts_path, weeks)
                counts_results.append({
                    'agent_id': agent_id,
                    'shallow_counts_path': counts_path,
                    'removed_weeks': prune_result['removed'],
                    'remaining_weeks': prune_result['remaining'],
                    'status': 'completed',
                })
                if agent_id and agent_id not in failed_agents and agent_id not in succeed_agents:
                    succeed_agents.append(agent_id)
            except Exception as exc:  # noqa: BLE001
                counts_results.append({
                    'agent_id': agent_id,
                    'shallow_counts_path': counts_path,
                    'status': 'failed',
                    'reason': str(exc),
                })
                if agent_id and agent_id not in failed_agents:
                    failed_agents.append(agent_id)

        for item in l0_entries_to_delete:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get('agent_id', '') or '')
            l0_index_path = str(item.get('l0_index_path', '') or '')
            l0_embedding_path = str(item.get('l0_embedding_path', '') or '')
            weeks_raw = item.get('shallow_weeks', [])
            weeks = {str(x).strip() for x in weeks_raw if str(x).strip()} if isinstance(weeks_raw, list) else set()
            try:
                index_result = _prune_l0_index(l0_index_path, weeks)
                embedding_result = _prune_l0_embeddings(l0_embedding_path, weeks)
                l0_results.append({
                    'agent_id': agent_id,
                    'l0_index_path': l0_index_path,
                    'l0_embedding_path': l0_embedding_path,
                    'shallow_weeks': sorted(weeks),
                    'index_removed_count': index_result['removed_count'],
                    'embedding_removed_count': embedding_result['removed_count'],
                    'status': 'completed',
                })
                if agent_id and agent_id not in failed_agents and agent_id not in succeed_agents:
                    succeed_agents.append(agent_id)
            except Exception as exc:  # noqa: BLE001
                l0_results.append({
                    'agent_id': agent_id,
                    'l0_index_path': l0_index_path,
                    'l0_embedding_path': l0_embedding_path,
                    'shallow_weeks': sorted(weeks),
                    'status': 'failed',
                    'reason': str(exc),
                })
                if agent_id and agent_id not in failed_agents:
                    failed_agents.append(agent_id)
    else:
        for item in files_to_delete:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get('agent_id', '') or '')
            filelist = item.get('filelist', [])
            if not isinstance(filelist, list):
                filelist = []
            file_results.append({'agent_id': agent_id, 'skipped': True, 'file_count': len(filelist)})
        for item in counts_entries_to_delete:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get('agent_id', '') or '')
            weeks_raw = item.get('weeks', [])
            weeks = [str(x).strip() for x in weeks_raw if str(x).strip()] if isinstance(weeks_raw, list) else []
            counts_results.append({'agent_id': agent_id, 'skipped': True, 'weeks': weeks})
        for item in l0_entries_to_delete:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get('agent_id', '') or '')
            weeks_raw = item.get('shallow_weeks', [])
            weeks = [str(x).strip() for x in weeks_raw if str(x).strip()] if isinstance(weeks_raw, list) else []
            l0_results.append({'agent_id': agent_id, 'skipped': True, 'shallow_weeks': weeks})

    stage6['status'] = 'completed' if not failed_agents else 'failed'
    stage6['staging_cleaned'] = staging_cleaned
    stage6['destructive_cleanup_applied'] = bool(apply_cleanup)
    stage6['file_results'] = file_results
    stage6['counts_results'] = counts_results
    stage6['l0_results'] = l0_results
    stage6['succeed_agents'] = succeed_agents
    stage6['failed_agents'] = failed_agents
    run_meta['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    write_json_atomic(_plan_write_path(repo_root), plan)

    return {
        'success': not failed_agents,
        'stage': 'Phase3_Stage6',
        'note': 'Phase3 Stage6 执行完成。' if not failed_agents else 'Phase3 Stage6 执行结束，但存在失败 agent。',
        'apply_cleanup': bool(apply_cleanup),
        'staging_cleaned': staging_cleaned,
        'failed_agents': failed_agents,
        'succeed_agents': succeed_agents,
    }


__all__ = [
    'run_stage6',
]
