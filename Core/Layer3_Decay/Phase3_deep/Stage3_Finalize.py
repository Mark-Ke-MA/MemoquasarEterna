#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

from Core.Layer1_Write.json_repair import load_json_with_repair
from Core.Layer1_Write.shared import LoadConfig, load_json_file, write_json_atomic


DEEP_FIELDS = (
    'window',
    'window_date_start',
    'window_date_end',
    'source_weeks',
    'window_mood',
    'summary',
    'tags',
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


def _normal_deep_payload(reduce_payload: dict[str, Any]) -> dict[str, Any]:
    payload = {field: reduce_payload.get(field) for field in DEEP_FIELDS}
    payload['depth'] = 'deep'
    payload['status'] = {
        'filled': True,
        'filled_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    return payload


def _process_single_output(*, agent_id: str, output_info: dict[str, Any]) -> dict[str, Any]:
    no_shallow_batches = bool(output_info.get('no_shallow_batches', False))
    if no_shallow_batches:
        return {
            'agent_id': agent_id,
            'status': 'skipped',
            'reason': 'no_shallow_batches',
        }

    deep_output_path = str(output_info.get('deep_output_path', '') or '')
    reduce_output_path = str(output_info.get('reduce_output_path', '') or '')
    if not deep_output_path or not reduce_output_path:
        raise ValueError(f'{agent_id} 缺少 deep_output_path / reduce_output_path')

    reduce_payload = _load_json_dict(reduce_output_path)
    payload = _normal_deep_payload(reduce_payload)
    write_json_atomic(deep_output_path, payload)

    return {
        'agent_id': agent_id,
        'status': 'completed',
        'deep_output_path': deep_output_path,
        'window': str(payload.get('window', '') or ''),
        'source_weeks': payload.get('source_weeks', []),
    }


def run_stage3(repo_root: str | Path | None = None) -> dict[str, Any]:
    plan = _load_plan(repo_root)
    root = plan.setdefault('plan', {})
    run_meta = root.setdefault('run_meta', {})
    stage3 = root.setdefault('stage3', {})
    outputs = stage3.get('outputs', {})
    if not isinstance(outputs, dict):
        outputs = {}

    results: list[dict[str, Any]] = []
    failed_agents: list[str] = []
    succeed_agents: list[str] = []
    skipped_agents: list[str] = []

    for agent_id, output_info in outputs.items():
        if not isinstance(output_info, dict):
            failed_agents.append(str(agent_id))
            results.append({
                'agent_id': str(agent_id),
                'status': 'failed',
                'reason': 'invalid_stage3_output_contract',
            })
            continue
        try:
            result = _process_single_output(agent_id=str(agent_id), output_info=output_info)
            results.append(result)
            if result.get('status') == 'completed':
                succeed_agents.append(str(agent_id))
            elif result.get('status') == 'skipped':
                skipped_agents.append(str(agent_id))
        except Exception as exc:  # noqa: BLE001
            failed_agents.append(str(agent_id))
            results.append({
                'agent_id': str(agent_id),
                'status': 'failed',
                'reason': str(exc),
            })

    stage3['status'] = 'completed' if not failed_agents else 'failed'
    stage3['results'] = results
    stage3['succeed_agents'] = succeed_agents
    stage3['failed_agents'] = failed_agents
    stage3['skipped_agents'] = skipped_agents
    run_meta['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    write_json_atomic(_plan_write_path(repo_root), plan)

    return {
        'success': not failed_agents,
        'stage': 'Phase3_Stage3',
        'note': 'Phase3 Stage3 执行完成。' if not failed_agents else 'Phase3 Stage3 执行结束，但存在失败 agent。',
        'results': results,
        'succeed_agents': succeed_agents,
        'failed_agents': failed_agents,
        'skipped_agents': skipped_agents,
    }


__all__ = [
    'run_stage3',
]
