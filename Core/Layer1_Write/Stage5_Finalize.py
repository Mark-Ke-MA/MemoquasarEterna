#!/usr/bin/env python3
"""Layer1 写入层的第5阶段：最终写回。

职责：
- 读取 Stage4 成功 agent 的 reduced_results.json
- 把 reduce 结果写回正式 L1
- 回写 plan.json 中的 Stage5 状态
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

from Core.Layer1_Write.json_repair import load_json_with_repair
from Core.Layer1_Write.shared import LoadConfig, load_json_file, write_json_atomic


L1_FILLABLE_FIELDS = (
    'summary',
    'tags',
    'day_mood',
    'topics',
    'decisions',
    'todos',
    'key_items',
    'emotional_peaks',
)


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


def _nocontent_path_from_l1_path(l1_path: str | Path) -> Path:
    file_path = Path(l1_path)
    name = file_path.name
    if name.endswith('_l1.json'):
        return file_path.with_name(name[:-8] + '.nocontent')
    return file_path.with_suffix(file_path.suffix + '.nocontent')


def _load_json_dict(path: str | Path) -> dict[str, Any]:
    ok, payload, _repaired = load_json_with_repair(path)
    if not ok or not isinstance(payload, dict):
        raise ValueError(f'无法读取合法 JSON 对象: {path}')
    return payload


def _stage4_reduce_output_lookup(plan: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    stage4 = plan.get('plan', {}).get('stage4', {})
    raw_batches = stage4.get('reduce_batches') or []
    if not isinstance(raw_batches, list):
        return lookup
    for batch in raw_batches:
        if not isinstance(batch, list):
            continue
        for job in batch:
            if not isinstance(job, dict):
                continue
            agent_id = str(job.get('agent_id', '') or '')
            output_path = str(job.get('output_path', '') or '')
            if agent_id and output_path:
                lookup[agent_id] = output_path
    return lookup


def _stage5_output_lookup(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    outputs = plan.get('plan', {}).get('stage5', {}).get('outputs', {})
    if not isinstance(outputs, dict):
        return {}
    return {
        str(agent_id): payload
        for agent_id, payload in outputs.items()
        if str(agent_id).strip() and isinstance(payload, dict)
    }


def _apply_reduce_to_l1(l1_payload: dict[str, Any], reduce_payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(l1_payload)
    for field in L1_FILLABLE_FIELDS:
        updated[field] = reduce_payload.get(field)
    updated['_compress_hints'] = reduce_payload.get('source_turns')
    status = dict(updated.get('status', {})) if isinstance(updated.get('status'), dict) else {}
    status['filled'] = True
    status['filled_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    updated['status'] = status
    return updated


def _process_single_agent(*, agent_id: str, reduce_output_path: str, l1_path: str) -> dict[str, Any]:
    reduce_payload = _load_json_dict(reduce_output_path)
    nocontent_path = _nocontent_path_from_l1_path(l1_path)

    l1_payload = _load_json_dict(l1_path)
    updated_l1 = _apply_reduce_to_l1(l1_payload, reduce_payload)
    write_json_atomic(l1_path, updated_l1)
    if nocontent_path.exists():
        nocontent_path.unlink()
    return {
        'agent_id': agent_id,
        'status': 'completed',
        'reduce_output_path': reduce_output_path,
        'l1_path': l1_path,
        'nocontent_path': None,
    }


def run_stage5(repo_root: str | Path | None = None) -> dict[str, Any]:
    plan = _load_plan(repo_root)
    root = plan.setdefault('plan', {})
    stage4 = root.setdefault('stage4', {})
    stage5 = root.setdefault('stage5', {})

    succeed_agents = stage4.get('succeed_agents', [])
    if not isinstance(succeed_agents, list):
        succeed_agents = []
    succeed_agents = [str(agent) for agent in succeed_agents if str(agent).strip()]

    stage5_output_lookup = _stage5_output_lookup(plan)

    results: list[dict[str, Any]] = []
    failed_agents: list[str] = []

    for agent_id in succeed_agents:
        output_info = stage5_output_lookup.get(agent_id) or {}
        reduce_output_path = str(output_info.get('reduce_output_path', '') or '')
        l1_path = str(output_info.get('l1_path', '') or '')

        if not reduce_output_path or not l1_path:
            results.append({
                'agent_id': agent_id,
                'status': 'failed',
                'reason': 'missing_paths',
                'reduce_output_path': reduce_output_path,
                'l1_path': l1_path,
            })
            failed_agents.append(agent_id)
            continue

        try:
            result = _process_single_agent(
                agent_id=agent_id,
                reduce_output_path=reduce_output_path,
                l1_path=l1_path,
            )
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            results.append({
                'agent_id': agent_id,
                'status': 'failed',
                'reason': str(exc),
                'reduce_output_path': reduce_output_path,
                'l1_path': l1_path,
            })
            failed_agents.append(agent_id)

    stage5['status'] = 'completed' if not failed_agents else 'failed'
    stage5['results'] = results
    stage5['succeed_agents'] = [agent for agent in succeed_agents if agent not in failed_agents]
    stage5['failed_agents'] = failed_agents
    root.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    write_json_atomic(_plan_write_path(repo_root), plan)

    return {
        'success': not failed_agents,
        'note': 'Stage5 执行完成。' if not failed_agents else 'Stage5 执行结束，但存在失败 agent。',
        'results': results,
        'succeed_agents': stage5.get('succeed_agents', []),
        'failed_agents': failed_agents,
    }


__all__ = [
    'run_stage5',
]
