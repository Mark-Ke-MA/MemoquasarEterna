#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

from Core.Layer1_Write.json_repair import load_json_with_repair
from Core.Layer1_Write.shared import LoadConfig, load_json_file, write_json_atomic


DEFAULT_DEPTH = 'deep'


def _active_schema_version(repo_root: str | Path | None = None) -> str:
    overall_cfg = LoadConfig(repo_root).overall_config
    return str(overall_cfg.get('active_schema_version', '') or '').strip()


def _plan_path(repo_root: str | Path | None = None) -> Path:
    overall_cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(overall_cfg['store_dir'])).expanduser()
    staging_cfg = overall_cfg['store_dir_structure']['staging']
    staging_root = store_root / staging_cfg['root'] / staging_cfg['staging_deep']
    return staging_root / 'plan.json'


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


def _load_or_init_l0_index(path: str | Path, *, agent_id: str, repo_root: str | Path | None = None) -> dict[str, Any]:
    schema_version = _active_schema_version(repo_root)
    index_path = Path(path)
    if index_path.exists():
        ok, payload, _repaired = load_json_with_repair(index_path)
        if ok and isinstance(payload, dict):
            payload.setdefault('schema_version', schema_version)
            payload.setdefault('agent_id', agent_id)
            payload.setdefault('updated_at', None)
            payload.setdefault('entries', [])
            if not isinstance(payload.get('entries'), list):
                payload['entries'] = []
            return payload
    return {
        'schema_version': schema_version,
        'agent_id': agent_id,
        'updated_at': None,
        'entries': [],
    }


def _build_l0_entry(deep_payload: dict[str, Any]) -> dict[str, Any]:
    window = str(deep_payload.get('window', '') or '')
    summary = str(deep_payload.get('summary', '') or '')
    tags = deep_payload.get('tags', []) or []
    mood = str(deep_payload.get('window_mood', '') or '')
    window_date_start = str(deep_payload.get('window_date_start', '') or '')
    window_date_end = str(deep_payload.get('window_date_end', '') or '')
    if not isinstance(tags, list):
        tags = []
    tags = [str(tag) for tag in tags if isinstance(tag, str)]
    if not window:
        raise ValueError('deep 文件缺少 window')
    if not window_date_start or not window_date_end:
        raise ValueError('deep 文件缺少 window_date_start / window_date_end')
    return {
        'window': window,
        'summary': summary,
        'tags': tags,
        'mood': mood,
        'depth': DEFAULT_DEPTH,
        'window_date_start': window_date_start,
        'window_date_end': window_date_end,
        'access_count': 0,
    }


def _entry_sort_key(entry: dict[str, Any]) -> tuple[str, int, str]:
    depth = str(entry.get('depth', '') or '')
    if depth == 'deep':
        anchor = str(entry.get('window_date_start', '') or str(entry.get('window', '') or ''))
        priority = 0
    elif depth == 'shallow':
        anchor = str(entry.get('window_date_start', '') or str(entry.get('week', '') or ''))
        priority = 1
    else:
        anchor = str(entry.get('date', '') or '')
        priority = 2
    return (anchor, priority, depth)


def _upsert_l0_entry(index_payload: dict[str, Any], new_entry: dict[str, Any]) -> None:
    entries = index_payload.setdefault('entries', [])
    if not isinstance(entries, list):
        entries = []
        index_payload['entries'] = entries

    existing_idx = None
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        entry_depth = str(entry.get('depth', '') or '')
        if entry_depth != new_entry['depth']:
            continue
        if entry_depth == 'deep':
            if str(entry.get('window', '') or '') == new_entry['window']:
                existing_idx = idx
                break
        elif entry_depth == 'shallow':
            if str(entry.get('week', '') or '') == str(new_entry.get('week', '') or ''):
                existing_idx = idx
                break
        else:
            if str(entry.get('date', '') or '') == str(new_entry.get('date', '') or ''):
                existing_idx = idx
                break

    if existing_idx is not None:
        old_entry = entries[existing_idx] if isinstance(entries[existing_idx], dict) else {}
        new_entry['access_count'] = int(old_entry.get('access_count', 0) or 0)
        entries[existing_idx] = new_entry
    else:
        entries.append(new_entry)

    entries.sort(key=_entry_sort_key)
    index_payload['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _process_single_task(task: dict[str, Any], *, repo_root: str | Path | None = None) -> dict[str, Any]:
    agent_id = str(task.get('agent_id', '') or '')
    deep_output_path = str(task.get('deep_output_path', '') or '')
    l0_index_path = str(task.get('l0_index_path', '') or '')
    if not agent_id or not deep_output_path or not l0_index_path:
        raise ValueError('stage4 task 缺少 agent_id / deep_output_path / l0_index_path')

    deep_payload = _load_json_dict(deep_output_path)
    entry = _build_l0_entry(deep_payload)
    index_payload = _load_or_init_l0_index(l0_index_path, agent_id=agent_id, repo_root=repo_root)
    _upsert_l0_entry(index_payload, entry)
    write_json_atomic(l0_index_path, index_payload)

    return {
        'agent_id': agent_id,
        'status': 'completed',
        'deep_output_path': deep_output_path,
        'l0_index_path': l0_index_path,
        'window': entry['window'],
        'depth': entry['depth'],
    }


def run_stage4(repo_root: str | Path | None = None) -> dict[str, Any]:
    plan = _load_plan(repo_root)
    root = plan.setdefault('plan', {})
    stage4 = root.setdefault('stage4', {})
    tasks = stage4.get('tasks', [])
    if not isinstance(tasks, list):
        tasks = []

    results: list[dict[str, Any]] = []
    failed_agents: list[str] = []
    succeed_agents: list[str] = []

    for task in tasks:
        if not isinstance(task, dict):
            continue
        agent_id = str(task.get('agent_id', '') or '')
        try:
            result = _process_single_task(task, repo_root=repo_root)
            results.append(result)
            task['status'] = 'completed'
            if agent_id:
                succeed_agents.append(agent_id)
        except Exception as exc:  # noqa: BLE001
            results.append({
                'agent_id': agent_id,
                'status': 'failed',
                'reason': str(exc),
                'deep_output_path': str(task.get('deep_output_path', '') or ''),
                'l0_index_path': str(task.get('l0_index_path', '') or ''),
            })
            task['status'] = 'failed'
            if agent_id:
                failed_agents.append(agent_id)

    stage4['status'] = 'completed' if not failed_agents else 'failed'
    stage4['results'] = results
    stage4['succeed_agents'] = succeed_agents
    stage4['failed_agents'] = failed_agents
    root.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    write_json_atomic(_plan_write_path(repo_root), plan)

    return {
        'success': not failed_agents,
        'note': 'Phase3 Stage4 执行完成。' if not failed_agents else 'Phase3 Stage4 执行结束，但存在失败 agent。',
        'results': results,
        'succeed_agents': succeed_agents,
        'failed_agents': failed_agents,
    }


__all__ = [
    'run_stage4',
]
