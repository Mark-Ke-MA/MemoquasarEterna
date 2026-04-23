#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from Core.Layer2_Preserve.core import load_preserve_config, preserve_result, archive_log_path
from Core.Layer2_Preserve.shared import load_json_file, write_json_atomic, utc_now_iso
from Core.Layer2_Preserve.archive_Stage1_ListFiles import run_archive_stage1
from Core.Layer2_Preserve.archive_Stage2_Archive import run_archive_stage2


def _agent_plan_lookup(stage1_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for item in stage1_result.get('agent_plans', []):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get('agent_id', '') or '')
        if agent_id:
            lookup[agent_id] = item
    return lookup


def _mark_archived_in_file(path: str | Path) -> str | None:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None
    if not (file_path.name.endswith('_l1.json') or file_path.name.endswith('_l2.json')):
        return None
    payload = load_json_file(file_path)
    if not isinstance(payload, dict):
        return None
    status = payload.get('status', {})
    if not isinstance(status, dict):
        status = {}
    status['archived'] = True
    status['archived_at'] = utc_now_iso()
    payload['status'] = status
    write_json_atomic(file_path, payload)
    return str(file_path)


def run_archive_stage3(*, repo_root: str | None = None, week: str | None = None, agent: str | None = None, overwrite: bool = False, run_mode: str = 'manual', harness_only: bool = False, dry_run: bool = False, run_name: str | None = None, stage1_result: dict[str, Any] | None = None, stage2_result: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_preserve_config(repo_root)
    stage1_result = stage1_result or run_archive_stage1(repo_root=repo_root, week=week, agent=agent, overwrite=overwrite, run_mode=run_mode, harness_only=harness_only, dry_run=dry_run)
    stage2_result = stage2_result or run_archive_stage2(repo_root=repo_root, week=week, agent=agent, overwrite=overwrite, run_mode=run_mode, harness_only=harness_only, dry_run=dry_run, stage1_result=stage1_result)
    if not stage2_result.get('success', False):
        return preserve_result(success=False, stage='Layer2_Archive_Stage3_Finalize', note='Stage2 未成功，Stage3 不执行。')

    week_id = str(stage2_result.get('week_id') or stage1_result.get('week_id') or '')
    plan_lookup = _agent_plan_lookup(stage1_result)
    finalized: list[dict[str, Any]] = []
    log_payload = {
        'schema_version': str(cfg.overall_config.get('archive_schema_version', '') or '').strip(),
        'created_at': utc_now_iso(),
        'window_start': stage1_result.get('window_start'),
        'window_end': stage1_result.get('window_end'),
        'success': True,
        'agents': [],
    }
    if run_mode == 'manual':
        log_payload['run_name'] = run_name

    for item in stage2_result.get('results', []):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get('agent_id', '') or '')
        status = str(item.get('status', '') or '')
        updated_files: list[str] = []
        if status == 'archived':
            plan_item = plan_lookup.get(agent_id, {})
            for candidate_path in plan_item.get('candidate_files', []) if isinstance(plan_item, dict) else []:
                updated_path = _mark_archived_in_file(candidate_path)
                if updated_path:
                    updated_files.append(updated_path)
        agent_log: dict[str, Any] = {
            'agent_id': agent_id,
            'status': status,
        }
        if status == 'archived':
            agent_log['archive_path'] = item.get('archive_path')
            agent_log['updated_files'] = updated_files
        elif item.get('skip_reason'):
            agent_log['reason'] = item.get('skip_reason')
        elif item.get('reason'):
            agent_log['reason'] = item.get('reason')
        finalized.append(agent_log)
        log_payload['agents'].append(agent_log)

    log_payload['success'] = all(item.get('status') in {'archived', 'skipped'} for item in finalized)
    log_path = archive_log_path(cfg, week_id=week_id, run_mode=run_mode, run_name=run_name)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(log_path, log_payload)

    return preserve_result(
        success=True,
        stage='Layer2_Archive_Stage3_Finalize',
        note='Stage3 已完成：回写 l1/l2 的 archived 状态并记录 preserve log。',
        week_id=week_id,
        preserve_log_path=str(log_path),
        results=finalized,
    )
