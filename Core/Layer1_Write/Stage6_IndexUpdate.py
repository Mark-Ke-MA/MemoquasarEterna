#!/usr/bin/env python3
"""Layer1 写入层的第6阶段：L0 索引更新。

职责：
- 读取 stage6.tasks
- 从正式 L1 提取 date / summary / tags / mood
- 更新 memory/{agent}/surface/l0_index.json
- 同日同 depth 仅保留一个 entry；新结果直接覆写旧 entry
- 保留已有 access_count
- 回写 plan.json 中的 Stage6 状态
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

from Core.Layer1_Write.json_repair import load_json_with_repair
from Core.Layer1_Write.shared import LoadConfig, load_json_file, write_json_atomic


DEFAULT_DEPTH = 'surface'


def _active_schema_version(repo_root: str | Path | None = None) -> str:
    overall_cfg = LoadConfig(repo_root).overall_config
    return str(overall_cfg.get('active_schema_version', '') or '').strip()


def _plan_path(repo_root: str | Path | None = None) -> Path:
    overall_cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(overall_cfg['store_dir'])).expanduser()
    staging_cfg = overall_cfg['store_dir_structure']['staging']
    staging_root = store_root / staging_cfg['root'] / staging_cfg['staging_surface']
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


def _build_l0_entry(l1_payload: dict[str, Any]) -> dict[str, Any]:
    date = str(l1_payload.get('date', '') or '')
    summary = str(l1_payload.get('summary', '') or '')
    tags = l1_payload.get('tags', []) or []
    mood = str(l1_payload.get('day_mood', '') or '')
    if not isinstance(tags, list):
        tags = []
    tags = [str(tag) for tag in tags if isinstance(tag, str)]
    if not date:
        raise ValueError('L1 缺少 date')
    if not summary:
        raise ValueError('L1 缺少 summary')
    return {
        'date': date,
        'summary': summary,
        'tags': tags,
        'mood': mood,
        'depth': DEFAULT_DEPTH,
        'access_count': 0,
    }


def _upsert_l0_entry(index_payload: dict[str, Any], new_entry: dict[str, Any]) -> None:
    entries = index_payload.setdefault('entries', [])
    if not isinstance(entries, list):
        entries = []
        index_payload['entries'] = entries

    existing_idx = None
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if str(entry.get('date', '') or '') == new_entry['date'] and str(entry.get('depth', '') or '') == new_entry['depth']:
            existing_idx = idx
            break

    if existing_idx is not None:
        old_entry = entries[existing_idx] if isinstance(entries[existing_idx], dict) else {}
        new_entry['access_count'] = int(old_entry.get('access_count', 0) or 0)
        entries[existing_idx] = new_entry
    else:
        entries.append(new_entry)

    entries.sort(key=lambda item: (str(item.get('date', '') or ''), str(item.get('depth', '') or '')))
    index_payload['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _process_single_task(task: dict[str, Any], *, repo_root: str | Path | None = None) -> dict[str, Any]:
    agent_id = str(task.get('agent_id', '') or '')
    l1_path = str(task.get('l1_path', '') or '')
    l0_index_path = str(task.get('l0_index_path', '') or '')
    if not agent_id or not l1_path or not l0_index_path:
        raise ValueError('stage6 task 缺少 agent_id / l1_path / l0_index_path')

    l1_payload = _load_json_dict(l1_path)
    entry = _build_l0_entry(l1_payload)
    index_payload = _load_or_init_l0_index(l0_index_path, agent_id=agent_id, repo_root=repo_root)
    _upsert_l0_entry(index_payload, entry)
    write_json_atomic(l0_index_path, index_payload)

    return {
        'agent_id': agent_id,
        'status': 'completed',
        'l1_path': l1_path,
        'l0_index_path': l0_index_path,
        'date': entry['date'],
        'depth': entry['depth'],
    }


def run_stage6(repo_root: str | Path | None = None) -> dict[str, Any]:
    plan = _load_plan(repo_root)
    root = plan.setdefault('plan', {})
    stage6 = root.setdefault('stage6', {})
    tasks = stage6.get('tasks', [])
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
                'l1_path': str(task.get('l1_path', '') or ''),
                'l0_index_path': str(task.get('l0_index_path', '') or ''),
            })
            task['status'] = 'failed'
            if agent_id:
                failed_agents.append(agent_id)

    stage6['status'] = 'completed' if not failed_agents else 'failed'
    stage6['results'] = results
    stage6['succeed_agents'] = succeed_agents
    stage6['failed_agents'] = failed_agents
    root.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    write_json_atomic(_plan_write_path(repo_root), plan)

    return {
        'success': not failed_agents,
        'note': 'Stage6 执行完成。' if not failed_agents else 'Stage6 执行结束，但存在失败 agent。',
        'results': results,
        'succeed_agents': succeed_agents,
        'failed_agents': failed_agents,
    }


__all__ = [
    'run_stage6',
]
