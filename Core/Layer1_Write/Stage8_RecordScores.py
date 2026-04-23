#!/usr/bin/env python3
"""Layer1 写入层的第8阶段：记录 landmark 原始统计。

职责：
- 读取 plan.json
- 找到本轮可用于 landmark 统计的正式 L1 与预先规划好的 record_path
- 提取 key_items 计数与 emotional_peaks intensity 计数
- 覆盖写入 statistics/landmark_scores/{agentId}_landmark_scores.json
- 回写 plan.stage8 的最小字段：status / results / failed_agents / succeed_agents
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os

from Core.Layer1_Write.shared import LoadConfig, load_json_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]

ALLOWED_KEY_ITEM_TYPES = ('milestone', 'bug_fix', 'config_change', 'decision', 'incident', 'question')


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


def _normalize_record(payload: dict[str, Any] | None, *, agent_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {'agentId': agent_id, 'counts': []}
    counts = payload.get('counts', [])
    if not isinstance(counts, list):
        counts = []
    return {
        'agentId': str(payload.get('agentId', agent_id) or agent_id),
        'counts': [item for item in counts if isinstance(item, dict)],
    }


def _load_existing_record(record_path: str | Path, *, agent_id: str) -> dict[str, Any]:
    path = Path(record_path)
    if not path.exists():
        return {'agentId': agent_id, 'counts': []}
    try:
        payload = load_json_file(path)
    except Exception:
        payload = None
    return _normalize_record(payload, agent_id=agent_id)


def _extract_counts_from_l1(l1_payload: dict[str, Any]) -> dict[str, Any]:
    target_date = str(l1_payload.get('date', '') or '')

    key_item_counts = {key: 0 for key in ALLOWED_KEY_ITEM_TYPES}
    key_items = l1_payload.get('key_items')
    if isinstance(key_items, list):
        for item in key_items:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get('type', '') or '')
            if item_type in key_item_counts:
                key_item_counts[item_type] += 1

    emotional_intensities: dict[str, int] = {}
    emotional_peaks = l1_payload.get('emotional_peaks')
    if isinstance(emotional_peaks, list):
        for item in emotional_peaks:
            if not isinstance(item, dict):
                continue
            intensity = item.get('intensity')
            if isinstance(intensity, bool) or not isinstance(intensity, int):
                continue
            if intensity < 0:
                continue
            key = str(intensity)
            emotional_intensities[key] = int(emotional_intensities.get(key, 0) or 0) + 1

    return {
        'date': target_date,
        'key_items': key_item_counts,
        'emotional_intensities': dict(sorted(emotional_intensities.items(), key=lambda item: int(item[0]))),
    }


def _record_task_lookup(plan: dict[str, Any]) -> list[dict[str, Any]]:
    root = plan.get('plan', {}) if isinstance(plan.get('plan', {}), dict) else {}
    stage8 = root.get('stage8', {}) if isinstance(root.get('stage8', {}), dict) else {}
    tasks = stage8.get('tasks', [])
    if isinstance(tasks, list) and tasks:
        return [task for task in tasks if isinstance(task, dict)]

    stage5 = root.get('stage5', {}) if isinstance(root.get('stage5', {}), dict) else {}
    succeed_agents = stage5.get('succeed_agents', []) if isinstance(stage5.get('succeed_agents', []), list) else []
    outputs = stage5.get('outputs', {}) if isinstance(stage5.get('outputs', {}), dict) else {}
    fallback: list[dict[str, Any]] = []
    for agent_id in succeed_agents:
        agent_id = str(agent_id or '')
        if not agent_id:
            continue
        output_info = outputs.get(agent_id, {}) if isinstance(outputs.get(agent_id, {}), dict) else {}
        l1_path = str(output_info.get('l1_path', '') or '')
        if not l1_path:
            continue
        fallback.append({'agent_id': agent_id, 'l1_path': l1_path, 'status': 'pending'})
    return fallback


def _upsert_record_entry(record_payload: dict[str, Any], entry: dict[str, Any]) -> None:
    counts = record_payload.setdefault('counts', [])
    date_text = str(entry.get('date', '') or '')
    replaced = False
    for idx, item in enumerate(counts):
        if not isinstance(item, dict):
            continue
        if str(item.get('date', '') or '') == date_text:
            counts[idx] = entry
            replaced = True
            break
    if not replaced:
        counts.append(entry)
    counts.sort(key=lambda item: str(item.get('date', '') or ''))


def _dump_landmark_record_compact(record_payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append('{')
    lines.append(f'  "agentId": {json.dumps(str(record_payload.get("agentId", "") or ""), ensure_ascii=False)},')
    lines.append('  "counts": [')
    counts = record_payload.get('counts', []) if isinstance(record_payload.get('counts', []), list) else []
    for idx, item in enumerate(counts):
        if not isinstance(item, dict):
            continue
        comma = ',' if idx < len(counts) - 1 else ''
        date_json = json.dumps(str(item.get('date', '') or ''), ensure_ascii=False)
        key_items_json = json.dumps(item.get('key_items', {}), ensure_ascii=False, separators=(', ', ': '), sort_keys=False)
        emotional_json = json.dumps(item.get('emotional_intensities', {}), ensure_ascii=False, separators=(', ', ': '), sort_keys=False)
        lines.append('    {')
        lines.append(f'      "date": {date_json}, "key_items": {key_items_json},')
        lines.append(f'      "emotional_intensities": {emotional_json}')
        lines.append(f'    }}{comma}')
    lines.append('  ]')
    lines.append('}')
    return '\n'.join(lines)


def _write_landmark_record_compact(path: str | Path, record_payload: dict[str, Any]) -> None:
    path = str(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(_dump_landmark_record_compact(record_payload))
        f.write('\n')
    os.replace(tmp, path)


def _process_single_task(task: dict[str, Any], *, repo_root: str | Path | None = None) -> dict[str, Any]:
    _ = repo_root
    agent_id = str(task.get('agent_id', '') or '')
    l1_path = str(task.get('l1_path', '') or '')
    record_path = str(task.get('record_path', '') or '')
    if not agent_id or not l1_path or not record_path:
        raise ValueError('stage8 task 缺少 agent_id / l1_path / record_path')

    l1_payload = load_json_file(l1_path)
    if not isinstance(l1_payload, dict):
        raise ValueError(f'L1 不是合法 JSON 对象: {l1_path}')
    entry = _extract_counts_from_l1(l1_payload)
    if not str(entry.get('date', '') or ''):
        raise ValueError(f'L1 缺少 date: {l1_path}')

    record_payload = _load_existing_record(record_path, agent_id=agent_id)
    _upsert_record_entry(record_payload, entry)

    record_path_obj = Path(record_path)
    record_path_obj.parent.mkdir(parents=True, exist_ok=True)
    _write_landmark_record_compact(record_path_obj, record_payload)

    return {
        'agent_id': agent_id,
        'status': 'completed',
        'date': entry['date'],
        'record_path': str(record_path_obj),
        'l1_path': l1_path,
    }


def run_stage8(*, repo_root: str | Path | None = None) -> dict[str, Any]:
    plan = _load_plan(repo_root)
    root = plan.setdefault('plan', {})
    stage8 = root.setdefault('stage8', {})

    tasks = _record_task_lookup(plan)
    stage8['status'] = 'running'
    stage8['tasks'] = tasks
    stage8.pop('results', None)
    stage8.pop('failed_agents', None)
    stage8.pop('succeed_agents', None)
    root.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    write_json_atomic(_plan_write_path(repo_root), plan)

    results: list[dict[str, Any]] = []
    failed_agents: list[str] = []
    succeed_agents: list[str] = []

    for task in tasks:
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
            })
            task['status'] = 'failed'
            if agent_id:
                failed_agents.append(agent_id)

    stage8['status'] = 'completed' if not failed_agents else 'failed'
    stage8['results'] = results
    stage8['failed_agents'] = failed_agents
    stage8['succeed_agents'] = succeed_agents
    root.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    write_json_atomic(_plan_write_path(repo_root), plan)

    return {
        'success': not failed_agents,
        'stage': 'Stage8',
        'note': 'Stage8 执行完成。' if not failed_agents else 'Stage8 执行结束，但存在失败 agent。',
        'results': results,
        'failed_agents': failed_agents,
        'succeed_agents': succeed_agents,
    }


__all__ = ['run_stage8']
