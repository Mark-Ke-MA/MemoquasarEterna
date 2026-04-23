#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

from Core.Layer1_Write.json_repair import load_json_with_repair
from Core.Layer1_Write.shared import LoadConfig, load_json_file, write_json_atomic


SHALLOW_FIELDS = (
    'week',
    'window_date_start',
    'window_date_end',
    'week_mood',
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
    staging_root = store_root / staging_cfg['root'] / staging_cfg['staging_shallow']
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


def _read_shallow_weeks(path: str | Path) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        lines = file_path.read_text(encoding='utf-8').splitlines()
    except Exception:
        return []
    weeks: list[str] = []
    seen: set[str] = set()
    for line in lines:
        week = str(line).strip()
        if not week or week in seen:
            continue
        seen.add(week)
        weeks.append(week)
    return weeks


def _write_shallow_weeks(path: str | Path, weeks: list[str]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = []
    seen: set[str] = set()
    for week in sorted(str(item).strip() for item in weeks if str(item).strip()):
        if week in seen:
            continue
        seen.add(week)
        ordered.append(week)
    text = ''.join(f'{week}\n' for week in ordered)
    file_path.write_text(text, encoding='utf-8')


def _normal_shallow_payload(reduce_payload: dict[str, Any]) -> dict[str, Any]:
    payload = {field: reduce_payload.get(field) for field in SHALLOW_FIELDS}
    payload['depth'] = 'shallow'
    payload['no_l1_files'] = False
    payload['status'] = {
        'filled': True,
        'filled_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    return payload


def _empty_shallow_payload(*, output_info: dict[str, Any], run_meta: dict[str, Any]) -> dict[str, Any]:
    return {
        'week': str(run_meta.get('source_week', '') or ''),
        'window_date_start': str(run_meta.get('window_date_start', '') or ''),
        'window_date_end': str(run_meta.get('window_date_end', '') or ''),
        'week_mood': '',
        'summary': '本周无可用 surface L1 文件，不生成周级语义摘要。',
        'tags': [],
        'topics': [],
        'decisions': [],
        'todos': [],
        'key_items': [],
        'emotional_peaks': [],
        'depth': 'shallow',
        'no_l1_files': True,
        'status': {
            'filled': True,
            'filled_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        },
    }


def _process_single_output(*, agent_id: str, output_info: dict[str, Any], run_meta: dict[str, Any]) -> dict[str, Any]:
    shallow_l1_path = str(output_info.get('shallow_l1_path', '') or '')
    deep_shallow_counts_path = str(output_info.get('deep_shallow_counts_path', '') or '')
    if not shallow_l1_path or not deep_shallow_counts_path:
        raise ValueError(f'{agent_id} 缺少 shallow_l1_path / deep_shallow_counts_path')

    no_l1_files = bool(output_info.get('no_l1_files', False))
    if no_l1_files:
        payload = _empty_shallow_payload(output_info=output_info, run_meta=run_meta)
    else:
        reduce_output_path = str(output_info.get('reduce_output_path', '') or '')
        if not reduce_output_path:
            raise ValueError(f'{agent_id} 缺少 reduce_output_path')
        reduce_payload = _load_json_dict(reduce_output_path)
        payload = _normal_shallow_payload(reduce_payload)

    write_json_atomic(shallow_l1_path, payload)
    current_weeks = _read_shallow_weeks(deep_shallow_counts_path)
    current_week = str(payload.get('week', '') or '')
    if current_week and current_week not in current_weeks:
        current_weeks.append(current_week)
    _write_shallow_weeks(deep_shallow_counts_path, current_weeks)

    return {
        'agent_id': agent_id,
        'status': 'completed',
        'no_l1_files': no_l1_files,
        'shallow_l1_path': shallow_l1_path,
        'deep_shallow_counts_path': deep_shallow_counts_path,
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
    no_l1_agents: list[str] = []

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
            result = _process_single_output(agent_id=str(agent_id), output_info=output_info, run_meta=run_meta)
            results.append(result)
            succeed_agents.append(str(agent_id))
            if bool(result.get('no_l1_files', False)):
                no_l1_agents.append(str(agent_id))
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
    stage3['no_l1_agents'] = no_l1_agents
    run_meta['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    write_json_atomic(_plan_write_path(repo_root), plan)

    return {
        'success': not failed_agents,
        'stage': 'Phase2_Stage3',
        'note': 'Phase2 Stage3 执行完成。' if not failed_agents else 'Phase2 Stage3 执行结束，但存在失败 agent。',
        'results': results,
        'succeed_agents': succeed_agents,
        'failed_agents': failed_agents,
        'no_l1_agents': no_l1_agents,
    }


__all__ = [
    'run_stage3',
]
