#!/usr/bin/env python3
"""Layer1 写入层的第5阶段：最终写回。

职责：
- 读取 Stage4 成功 agent 的 reduced_results.json
- normal 分支：把 reduce 结果写回正式 L1
- low 分支：删除正式 L1，保留 L2，并创建 .nocontent 标记
- 回写 plan.json 中的 Stage5 状态
- 对 low agent 从 Stage6 / Stage7 中移除
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

from Core.Layer1_Write.json_repair import load_json_with_repair
from Core.Layer1_Write.shared import LoadConfig, load_json_file, write_json_atomic


LOW_SIGNAL_SUMMARY = '当天有对话，但缺乏可沉淀的实质内容，不生成正式记忆。'
L1_FILLABLE_FIELDS = (
    'memory_signal',
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


def _touch_text_file(path: str | Path, text: str) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(text, encoding='utf-8')


def _remove_file_if_exists(path: str | Path) -> None:
    file_path = Path(path)
    if file_path.exists():
        file_path.unlink()


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


def _filter_following_tasks(tasks: list[dict[str, Any]], agent_set_to_remove: set[str]) -> list[dict[str, Any]]:
    return [
        task for task in tasks
        if isinstance(task, dict) and str(task.get('agent_id', '') or '') not in agent_set_to_remove
    ]


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
    memory_signal = str(reduce_payload.get('memory_signal', '') or '')
    if memory_signal not in {'low', 'normal'}:
        raise ValueError(f'{agent_id} 的 memory_signal 非法: {memory_signal}')

    nocontent_path = _nocontent_path_from_l1_path(l1_path)

    if memory_signal == 'low':
        _remove_file_if_exists(l1_path)
        _touch_text_file(
            nocontent_path,
            f'nocontent on {Path(l1_path).stem.replace("_l1", "")}\nsummary: {LOW_SIGNAL_SUMMARY}\n',
        )
        return {
            'agent_id': agent_id,
            'status': 'nocontent',
            'memory_signal': 'low',
            'reduce_output_path': reduce_output_path,
            'l1_path': l1_path,
            'nocontent_path': str(nocontent_path),
        }

    l1_payload = _load_json_dict(l1_path)
    updated_l1 = _apply_reduce_to_l1(l1_payload, reduce_payload)
    write_json_atomic(l1_path, updated_l1)
    if nocontent_path.exists():
        nocontent_path.unlink()
    return {
        'agent_id': agent_id,
        'status': 'completed',
        'memory_signal': 'normal',
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
    low_agents: list[str] = []

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
            if result.get('memory_signal') == 'low':
                low_agents.append(agent_id)
        except Exception as exc:  # noqa: BLE001
            results.append({
                'agent_id': agent_id,
                'status': 'failed',
                'reason': str(exc),
                'reduce_output_path': reduce_output_path,
                'l1_path': l1_path,
            })
            failed_agents.append(agent_id)

    low_agent_set = set(low_agents)
    if low_agent_set:
        stage6 = root.setdefault('stage6', {})
        stage6_tasks = stage6.get('tasks') or []
        if isinstance(stage6_tasks, list):
            stage6['tasks'] = _filter_following_tasks(stage6_tasks, low_agent_set)

        stage7 = root.setdefault('stage7', {})
        stage7_tasks = stage7.get('tasks') or []
        if isinstance(stage7_tasks, list):
            stage7['tasks'] = _filter_following_tasks(stage7_tasks, low_agent_set)

        stage8 = root.setdefault('stage8', {})
        stage8_tasks = stage8.get('tasks') or []
        if isinstance(stage8_tasks, list):
            stage8['tasks'] = _filter_following_tasks(stage8_tasks, low_agent_set)

    stage5['status'] = 'completed' if not failed_agents else 'failed'
    stage5['results'] = results
    stage5['succeed_agents'] = [agent for agent in succeed_agents if agent not in failed_agents]
    stage5['failed_agents'] = failed_agents
    stage5['low_agents'] = low_agents
    root.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    write_json_atomic(_plan_write_path(repo_root), plan)

    return {
        'success': not failed_agents,
        'note': 'Stage5 执行完成。' if not failed_agents else 'Stage5 执行结束，但存在失败 agent。',
        'results': results,
        'succeed_agents': stage5.get('succeed_agents', []),
        'failed_agents': failed_agents,
        'low_agents': low_agents,
    }


__all__ = [
    'run_stage5',
]
