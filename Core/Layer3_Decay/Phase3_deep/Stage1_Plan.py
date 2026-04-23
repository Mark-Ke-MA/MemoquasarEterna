#!/usr/bin/env python3
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any
import shutil

from Core.Layer1_Write.shared import build_store_paths
from Core.Layer3_Decay.shared import LoadConfig, monday_of_iso_week, selected_agents, utc_now_iso, write_json_atomic


def _layer3_decay_config(repo_root: str | Path | None) -> dict[str, Any]:
    cfg = LoadConfig(repo_root).overall_config
    raw = cfg.get('layer3_decay')
    if not isinstance(raw, dict):
        raise KeyError('OverallConfig.json 缺少 layer3_decay')
    if str(raw.get('_interval_in_units', '')) != 'week':
        raise ValueError("当前仅支持 layer3_decay._interval_in_units = 'week'")
    if 'deep_max_shallow' not in raw:
        raise KeyError('OverallConfig.json.layer3_decay 缺少 deep_max_shallow')
    return {
        '_interval_in_units': 'week',
        'deep_max_shallow': int(raw.get('deep_max_shallow') or 0),
    }


def _staging_deep_root(repo_root: str | Path | None) -> Path:
    cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(cfg['store_dir'])).expanduser()
    staging_cfg = cfg['store_dir_structure']['staging']
    return store_root / staging_cfg['root'] / staging_cfg['staging_deep']


def _stage1_plan_path(repo_root: str | Path | None) -> Path:
    return _staging_deep_root(repo_root) / 'plan.json'


def _clean_stage1_staging(*, repo_root: str | Path | None, selected_agent_ids: list[str]) -> list[str]:
    plan_path = _stage1_plan_path(repo_root)
    if plan_path.exists():
        plan_path.unlink()

    staging_root = _staging_deep_root(repo_root)
    cleaned: list[str] = []
    for agent_id in selected_agent_ids:
        agent_root = staging_root / agent_id
        if agent_root.exists():
            for child in agent_root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        else:
            agent_root.mkdir(parents=True, exist_ok=True)
        cleaned.append(str(agent_root))
    return cleaned


def _read_shallow_counts(path: Path) -> list[str]:
    if not path.exists():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding='utf-8').splitlines():
        week_id = raw.strip()
        if not week_id or week_id in seen:
            continue
        monday_of_iso_week(week_id)
        seen.add(week_id)
        out.append(week_id)
    out.sort(key=monday_of_iso_week)
    return out


def _window_for_weeks(weeks: list[str]) -> tuple[str, str, str]:
    if not weeks:
        raise ValueError('weeks 不能为空')
    start_day = monday_of_iso_week(weeks[0])
    end_day = monday_of_iso_week(weeks[-1]) + timedelta(days=6)
    span_days = (end_day - start_day).days + 1
    return start_day.strftime('%Y-%m-%d'), end_day.strftime('%Y-%m-%d'), f"{start_day.strftime('%Y-%m-%d')}+{span_days}d"


def _agent_deep_facts(*, overall_config: dict[str, Any], agent_id: str, deep_max_shallow: int) -> dict[str, Any]:
    store_paths = build_store_paths(agent_id, overall_config)
    shallow_counts_path = Path(store_paths['memory_deep_root']) / 'shallow_counts.txt'
    available_weeks = _read_shallow_counts(shallow_counts_path)

    if len(available_weeks) < deep_max_shallow:
        return {
            'agent_id': agent_id,
            'status': 'skipped',
            'reason': 'insufficient_shallow_weeks',
            'deep_max_shallow': deep_max_shallow,
            'available_weeks': available_weeks,
            'available_count': len(available_weeks),
            'selected_weeks': [],
            'input_paths': [],
            'shallow_counts_path': str(shallow_counts_path),
        }

    selected_weeks = available_weeks[:deep_max_shallow]
    input_paths: list[str] = []
    shallow_root = Path(store_paths['memory_shallow_root'])
    for week_id in selected_weeks:
        file_path = shallow_root / f'{week_id}.json'
        if not file_path.exists():
            raise FileNotFoundError(f'缺少 shallow 文件: {file_path}')
        input_paths.append(str(file_path))

    window_date_start, window_date_end, window = _window_for_weeks(selected_weeks)
    deep_output_path = Path(store_paths['memory_deep_root']) / f'{window}.json'
    reduce_output_path = Path(store_paths['staging_deep_root']) / agent_id / 'reduced_results.json'

    return {
        'agent_id': agent_id,
        'status': 'planned',
        'reason': None,
        'deep_max_shallow': deep_max_shallow,
        'available_weeks': available_weeks,
        'available_count': len(available_weeks),
        'selected_weeks': selected_weeks,
        'input_paths': input_paths,
        'window': window,
        'window_date_start': window_date_start,
        'window_date_end': window_date_end,
        'reduce_output_path': str(reduce_output_path),
        'deep_output_path': str(deep_output_path),
        'shallow_counts_path': str(shallow_counts_path),
    }


def _build_reduce_batches(tasks: list[dict[str, Any]], max_parallel_workers: int) -> list[list[dict[str, Any]]]:
    if max_parallel_workers <= 0:
        max_parallel_workers = 1
    return [tasks[i:i + max_parallel_workers] for i in range(0, len(tasks), max_parallel_workers)]


def run_stage1(*, repo_root: str | Path | None = None, agent: str | None = None) -> dict[str, Any]:
    cfg = LoadConfig(repo_root)
    overall_config = cfg.overall_config
    decay_cfg = _layer3_decay_config(repo_root)
    all_agent_ids = list(overall_config.get('agentId_list', []))
    agent_ids = selected_agents(agent, all_agent_ids)
    if 'nprl_llm_max' not in overall_config:
        raise KeyError('OverallConfig.json 缺少 nprl_llm_max')
    nprl_llm_max = int(overall_config['nprl_llm_max'])
    deep_max_shallow = int(decay_cfg['deep_max_shallow'])
    if deep_max_shallow <= 0:
        raise ValueError('OverallConfig.json.layer3_decay.deep_max_shallow 必须为正整数')

    cleaned_agent_roots = _clean_stage1_staging(repo_root=repo_root, selected_agent_ids=agent_ids)

    reduce_tasks: list[dict[str, Any]] = []
    stage3_outputs: dict[str, dict[str, Any]] = {}
    stage4_tasks: list[dict[str, Any]] = []
    stage5_tasks: list[dict[str, Any]] = []
    files_to_delete: list[dict[str, Any]] = []
    counts_entries_to_delete: list[dict[str, Any]] = []
    l0_entries_to_delete: list[dict[str, Any]] = []
    skipped_agents: list[dict[str, Any]] = []
    planned_windows: dict[str, dict[str, Any]] = {}

    for agent_id in agent_ids:
        facts = _agent_deep_facts(
            overall_config=overall_config,
            agent_id=agent_id,
            deep_max_shallow=deep_max_shallow,
        )
        if facts['status'] != 'planned':
            skipped_agents.append({
                'agent_id': agent_id,
                'reason': facts['reason'],
                'available_count': facts['available_count'],
                'deep_max_shallow': facts['deep_max_shallow'],
                'available_weeks': list(facts['available_weeks']),
            })
            stage3_outputs[agent_id] = {
                'no_shallow_batches': True,
                'deep_output_path': None,
                'window': None,
                'window_date_start': None,
                'window_date_end': None,
                'source_weeks': [],
            }
            continue

        reduce_tasks.append({
            'agent_id': agent_id,
            'input_paths': list(facts['input_paths']),
            'output_path': facts['reduce_output_path'],
            'window': facts['window'],
            'window_date_start': facts['window_date_start'],
            'window_date_end': facts['window_date_end'],
            'source_weeks': list(facts['selected_weeks']),
            'status': 'pending',
        })
        stage3_outputs[agent_id] = {
            'reduce_output_path': facts['reduce_output_path'],
            'deep_output_path': facts['deep_output_path'],
            'window': facts['window'],
            'window_date_start': facts['window_date_start'],
            'window_date_end': facts['window_date_end'],
            'source_weeks': list(facts['selected_weeks']),
            'no_shallow_batches': False,
        }
        stage4_tasks.append({
            'agent_id': agent_id,
            'deep_output_path': facts['deep_output_path'],
            'l0_index_path': str(Path(build_store_paths(agent_id, overall_config)['memory_surface_root']) / 'l0_index.json'),
            'status': 'pending',
        })
        stage5_tasks.append({
            'agent_id': agent_id,
            'l0_index_path': str(Path(build_store_paths(agent_id, overall_config)['memory_surface_root']) / 'l0_index.json'),
            'l0_embedding_path': str(Path(build_store_paths(agent_id, overall_config)['memory_surface_root']) / 'l0_embeddings.json'),
            'status': 'pending',
        })
        files_to_delete.append({
            'agent_id': agent_id,
            'filelist': list(facts['input_paths']),
        })
        counts_entries_to_delete.append({
            'agent_id': agent_id,
            'shallow_counts_path': facts['shallow_counts_path'],
            'weeks': list(facts['selected_weeks']),
        })
        l0_entries_to_delete.append({
            'agent_id': agent_id,
            'l0_index_path': str(Path(build_store_paths(agent_id, overall_config)['memory_surface_root']) / 'l0_index.json'),
            'l0_embedding_path': str(Path(build_store_paths(agent_id, overall_config)['memory_surface_root']) / 'l0_embeddings.json'),
            'shallow_weeks': list(facts['selected_weeks']),
        })
        planned_windows[agent_id] = {
            'window': facts['window'],
            'window_date_start': facts['window_date_start'],
            'window_date_end': facts['window_date_end'],
            'source_weeks': list(facts['selected_weeks']),
        }

    now_iso = utc_now_iso()
    plan_payload = {
        'plan': {
            'run_meta': {
                'created_at': now_iso,
                'updated_at': now_iso,
                'deep_max_shallow': deep_max_shallow,
                'selected_agents': agent_ids,
            },
            'stage1': {
                'status': 'completed',
                'selected_agents': agent_ids,
                'planned_agents': [task['agent_id'] for task in reduce_tasks],
                'skipped_agents': skipped_agents,
                'planned_windows': planned_windows,
            },
            'stage2': {
                'status': 'pending',
                'reduce_batches': _build_reduce_batches(reduce_tasks, nprl_llm_max),
            },
            'stage3': {
                'status': 'pending',
                'outputs': stage3_outputs,
            },
            'stage4': {
                'status': 'pending',
                'tasks': stage4_tasks,
            },
            'stage5': {
                'status': 'pending',
                'tasks': stage5_tasks,
            },
            'stage6': {
                'status': 'pending',
                'files_to_delete': files_to_delete,
                'counts_entries_to_delete': counts_entries_to_delete,
                'l0_entries_to_delete': l0_entries_to_delete,
            },
        }
    }

    plan_path = _stage1_plan_path(repo_root)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(plan_path, plan_payload)

    return {
        'plan_path': str(plan_path),
        'planned_count': len(reduce_tasks),
        'planned_agents': [task['agent_id'] for task in reduce_tasks],
        'skipped_agents': skipped_agents,
        'deep_max_shallow': deep_max_shallow,
        'cleaned_agent_roots': cleaned_agent_roots,
    }


__all__ = [
    'run_stage1',
]
