#!/usr/bin/env python3
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any
import json
import shutil
import subprocess
import sys

from Core.Layer1_Write.shared import build_store_paths, load_json_file
from Core.Layer3_Decay.shared import LoadConfig, monday_of_iso_week, selected_agents, utc_now_iso, write_json_atomic


def _layer3_decay_config(repo_root: str | Path | None) -> dict[str, Any]:
    cfg = LoadConfig(repo_root).overall_config
    raw = cfg.get('layer3_decay')
    if not isinstance(raw, dict):
        raise KeyError('OverallConfig.json 缺少 layer3_decay')
    if str(raw.get('_interval_in_units', '')) != 'week':
        raise ValueError("当前仅支持 layer3_decay._interval_in_units = 'week'")
    if 'shallow_interval' not in raw:
        raise KeyError('OverallConfig.json.layer3_decay 缺少 shallow_interval')
    return {
        '_interval_in_units': 'week',
        'shallow_interval': int(raw.get('shallow_interval') or 0),
    }


def _iso_week_range(week_id: str) -> tuple[date, date]:
    monday = monday_of_iso_week(week_id)
    return monday, monday + timedelta(days=6)


def _shift_week(week_id: str, delta_weeks: int) -> str:
    monday = monday_of_iso_week(week_id)
    shifted = monday + timedelta(days=7 * int(delta_weeks))
    iso_year, iso_week, _ = shifted.isocalendar()
    return f'{iso_year}-W{iso_week:02d}'


def _date_texts_in_week(week_id: str) -> list[str]:
    monday, sunday = _iso_week_range(week_id)
    out: list[str] = []
    current = monday
    while current <= sunday:
        out.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    return out


def _staging_shallow_root(repo_root: str | Path | None) -> Path:
    cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(cfg['store_dir'])).expanduser()
    staging_cfg = cfg['store_dir_structure']['staging']
    return store_root / staging_cfg['root'] / staging_cfg['staging_shallow']


def _stage1_plan_path(repo_root: str | Path | None) -> Path:
    return _staging_shallow_root(repo_root) / 'plan.json'


def _clean_stage1_staging(*, repo_root: str | Path | None, selected_agents: list[str]) -> list[str]:
    plan_path = _stage1_plan_path(repo_root)
    if plan_path.exists():
        plan_path.unlink()

    staging_root = _staging_shallow_root(repo_root)
    cleaned: list[str] = []
    for agent_id in selected_agents:
        agent_root = staging_root / agent_id
        if agent_root.exists():
            shutil.rmtree(agent_root)
        agent_root.mkdir(parents=True, exist_ok=True)
        cleaned.append(str(agent_root))
    return cleaned


def _surface_day_paths(*, agent_id: str, target_date: str, overall_config: dict[str, Any]) -> dict[str, str]:
    store_paths = build_store_paths(agent_id, overall_config)
    month_dir = Path(store_paths['memory_surface_root']) / target_date[:7]
    return {
        'prefix_root': str(month_dir / target_date),
        'l1_path': str(month_dir / f'{target_date}_l1.json'),
        'l2_path': str(month_dir / f'{target_date}_l2.json'),
        'noconversation_path': str(month_dir / f'{target_date}.noconversation'),
        'nocontent_path': str(month_dir / f'{target_date}.nocontent'),
    }


def _landmark_rows(*, repo_root: str | Path | None, agent_id: str, date_start: str, date_end: str) -> dict[str, dict[str, Any]]:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    entry = root / 'Core' / 'LayerX_LandmarkJudge' / 'ENTRY_LAYERX.py'
    cmd = [
        sys.executable,
        str(entry),
        '--agent',
        agent_id,
        '--date_start',
        date_start,
        '--date_end',
        date_end,
        '--repo-root',
        str(root),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or '').strip()
        stdout = (proc.stdout or '').strip()
        detail = stderr or stdout or f'returncode={proc.returncode}'
        raise RuntimeError(f'LayerX ENTRY 调用失败: {detail}')
    payload = json.loads(proc.stdout or '[]')
    if not isinstance(payload, list):
        raise ValueError('LayerX ENTRY 输出不是合法 judge 列表')
    out: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        target_date = str(item.get('target_date', '') or '')
        if target_date:
            out[target_date] = item
    return out


def _is_archived_json(path: str | Path) -> bool:
    file_path = Path(path)
    if not file_path.exists():
        return False
    try:
        payload = load_json_file(file_path)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    status = payload.get('status')
    return isinstance(status, dict) and status.get('archived') is True


def _agent_week_facts(*, repo_root: str | Path | None, overall_config: dict[str, Any], agent_id: str, source_week: str, date_start: str, date_end: str) -> dict[str, Any]:
    landmark_map = _landmark_rows(repo_root=repo_root, agent_id=agent_id, date_start=date_start, date_end=date_end)
    input_paths: list[str] = []
    landmark_dates: list[str] = []
    window_dates = _date_texts_in_week(source_week)

    for date_text in window_dates:
        day_paths = _surface_day_paths(agent_id=agent_id, target_date=date_text, overall_config=overall_config)
        l1_path = Path(day_paths['l1_path'])
        if l1_path.exists():
            input_paths.append(str(l1_path))
        row = landmark_map.get(date_text)
        if isinstance(row, dict) and bool(row.get('landmark', False)) is True:
            landmark_dates.append(date_text)

    non_landmark_candidate_dates = [date_text for date_text in window_dates if date_text not in set(landmark_dates)]
    store_paths = build_store_paths(agent_id, overall_config)
    reduce_task = None
    if input_paths:
        reduce_task = {
            'agent_id': agent_id,
            'input_paths': input_paths,
            'output_path': str(Path(store_paths['staging_shallow_root']) / agent_id / 'reduced_results.json'),
            'status': 'pending',
        }

    return {
        'agent_id': agent_id,
        'reduce_task': reduce_task,
        'landmark_dates': landmark_dates,
        'non_landmark_candidate_dates': non_landmark_candidate_dates,
        'shallow_l1_path': str(Path(store_paths['memory_shallow_root']) / f'{source_week}.json'),
        'deep_shallow_counts_path': str(Path(store_paths['memory_deep_root']) / 'shallow_counts.txt'),
        'l0_index_path': str(Path(store_paths['memory_surface_root']) / 'l0_index.json'),
        'l0_embedding_path': str(Path(store_paths['memory_surface_root']) / 'l0_embeddings.json'),
    }


def _build_reduce_batches(tasks: list[dict[str, Any]], max_parallel_workers: int) -> list[list[dict[str, Any]]]:
    if max_parallel_workers <= 0:
        max_parallel_workers = 1
    return [tasks[i:i + max_parallel_workers] for i in range(0, len(tasks), max_parallel_workers)]


def _delete_candidates_for_agent(*, overall_config: dict[str, Any], agent_id: str, candidate_dates: list[str]) -> tuple[list[str], list[str]]:
    filelist: list[str] = []
    l0_dates: list[str] = []
    for date_text in candidate_dates:
        day_paths = _surface_day_paths(agent_id=agent_id, target_date=date_text, overall_config=overall_config)

        if _is_archived_json(day_paths['l1_path']):
            filelist.append(day_paths['l1_path'])
            l0_dates.append(date_text)

        if _is_archived_json(day_paths['l2_path']):
            filelist.append(day_paths['l2_path'])

        noconversation_path = Path(day_paths['noconversation_path'])
        if noconversation_path.exists():
            filelist.append(str(noconversation_path))

        nocontent_path = Path(day_paths['nocontent_path'])
        if nocontent_path.exists():
            filelist.append(str(nocontent_path))

    dedup_filelist: list[str] = []
    seen_files: set[str] = set()
    for path in filelist:
        if path in seen_files:
            continue
        seen_files.add(path)
        dedup_filelist.append(path)

    dedup_dates: list[str] = []
    seen_dates: set[str] = set()
    for date_text in l0_dates:
        if date_text in seen_dates:
            continue
        seen_dates.add(date_text)
        dedup_dates.append(date_text)

    return dedup_filelist, dedup_dates


def run_stage1(*, repo_root: str | Path | None = None, week: str | None = None, source_week: str | None = None, agent: str | None = None) -> dict[str, Any]:
    cfg = LoadConfig(repo_root)
    overall_config = cfg.overall_config
    decay_cfg = _layer3_decay_config(repo_root)
    from Core.shared_funcs import get_production_agent_ids
    all_agent_ids = get_production_agent_ids(overall_config)
    agent_ids = selected_agents(agent, all_agent_ids)
    if 'nprl_llm_max' not in overall_config:
        raise KeyError('OverallConfig.json 缺少 nprl_llm_max')
    nprl_llm_max = int(overall_config['nprl_llm_max'])

    cleaned_agent_roots = _clean_stage1_staging(repo_root=repo_root, selected_agents=agent_ids)

    if week and source_week:
        raise ValueError('--week 与 --source-week 不能同时使用')
    target_week = str(week) if week is not None else None
    source_week = str(source_week) if source_week is not None else _shift_week(str(target_week), -int(decay_cfg['shallow_interval']))
    window_start, window_end = _iso_week_range(source_week)
    window_date_start = window_start.strftime('%Y-%m-%d')
    window_date_end = window_end.strftime('%Y-%m-%d')

    reduce_tasks: list[dict[str, Any]] = []
    stage3_outputs: dict[str, dict[str, Any]] = {}
    stage4_tasks: list[dict[str, Any]] = []
    stage5_tasks: list[dict[str, Any]] = []
    files_to_delete: list[dict[str, Any]] = []
    l0_entries_to_delete: list[dict[str, Any]] = []
    stage1_landmark_dates: dict[str, list[str]] = {}

    for agent_id in agent_ids:
        facts = _agent_week_facts(
            repo_root=repo_root,
            overall_config=overall_config,
            agent_id=agent_id,
            source_week=source_week,
            date_start=window_date_start,
            date_end=window_date_end,
        )
        reduce_task = facts['reduce_task']
        stage1_landmark_dates[agent_id] = list(facts['landmark_dates'])

        if reduce_task is None:
            stage3_outputs[agent_id] = {
                'shallow_l1_path': facts['shallow_l1_path'],
                'deep_shallow_counts_path': facts['deep_shallow_counts_path'],
                'no_l1_files': True,
            }
        else:
            reduce_tasks.append(reduce_task)
            stage3_outputs[agent_id] = {
                'reduce_output_path': reduce_task['output_path'],
                'shallow_l1_path': facts['shallow_l1_path'],
                'deep_shallow_counts_path': facts['deep_shallow_counts_path'],
                'no_l1_files': False,
            }
            stage4_tasks.append({
                'agent_id': agent_id,
                'shallow_l1_path': facts['shallow_l1_path'],
                'l0_index_path': facts['l0_index_path'],
                'status': 'pending',
            })
            stage5_tasks.append({
                'agent_id': agent_id,
                'l0_index_path': facts['l0_index_path'],
                'l0_embedding_path': facts['l0_embedding_path'],
                'status': 'pending',
            })

        filelist, l0_dates = _delete_candidates_for_agent(
            overall_config=overall_config,
            agent_id=agent_id,
            candidate_dates=list(facts['non_landmark_candidate_dates']),
        )
        if filelist:
            files_to_delete.append({
                'agent_id': agent_id,
                'filelist': filelist,
            })
        if l0_dates:
            l0_entries_to_delete.append({
                'agent_id': agent_id,
                'l0_index_path': facts['l0_index_path'],
                'l0_embedding_path': facts['l0_embedding_path'],
                'surface_non_landmark_dates': l0_dates,
            })

    now_iso = utc_now_iso()
    plan_payload = {
        'plan': {
            'run_meta': {
                'target_week': target_week,
                'source_week': source_week,
                'window_date_start': window_date_start,
                'window_date_end': window_date_end,
                'created_at': now_iso,
                'updated_at': now_iso,
            },
            'stage1': {
                'status': 'completed',
                'selected_agents': agent_ids,
                'landmark_dates': stage1_landmark_dates,
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
                'l0_entries_to_delete': l0_entries_to_delete,
            },
        }
    }

    plan_path = _stage1_plan_path(repo_root)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(plan_path, plan_payload)

    return {
        'target_week': target_week,
        'source_week': source_week,
        'window_date_start': window_date_start,
        'window_date_end': window_date_end,
        'plan_path': str(plan_path),
        'planned_count': len(reduce_tasks),
        'cleaned_agent_roots': cleaned_agent_roots,
    }


__all__ = [
    'run_stage1',
]
