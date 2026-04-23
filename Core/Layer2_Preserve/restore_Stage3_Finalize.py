#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from Core.Layer2_Preserve.core import load_preserve_config, preserve_result, restore_log_path
from Core.Layer2_Preserve.shared import load_json_file, utc_now_iso, write_json_atomic
from Core.Layer2_Preserve.restore_Stage1_Plan import run_restore_stage1
from Core.Layer2_Preserve.restore_Stage2_Apply import run_restore_stage2


def _mark_restored_in_file(path: str | Path) -> str | None:
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
    status['restored'] = True
    status['restored_at'] = utc_now_iso()
    payload['status'] = status
    write_json_atomic(file_path, payload)
    return str(file_path)


def run_restore_stage3(*, repo_root: str | None = None, week: str | None = None, date: str | None = None, agent: str | None = None, which_level: str | None = None, restore_mode: str = 'mirrored', run_mode: str = 'manual', run_name: str | None = None, stage1_result: dict[str, Any] | None = None, stage2_result: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_preserve_config(repo_root)
    stage1_result = stage1_result or run_restore_stage1(repo_root=repo_root, week=week, date=date, agent=agent, which_level=which_level, restore_mode=restore_mode, run_name=run_name)
    stage2_result = stage2_result or run_restore_stage2(repo_root=repo_root, week=week, date=date, agent=agent, which_level=which_level, restore_mode=restore_mode, run_name=run_name, stage1_result=stage1_result)
    if not stage2_result.get('success', False):
        return preserve_result(success=False, stage='Layer2_Restore_Stage3_Finalize', note='Stage2 未成功，Stage3 不执行。')

    finalized: list[dict[str, Any]] = []
    log_payload: dict[str, Any] = {
        'schema_version': str(cfg.overall_config.get('archive_schema_version', '') or '').strip(),
        'created_at': utc_now_iso(),
        'window_start': stage2_result.get('window_start'),
        'window_end': stage2_result.get('window_end'),
        'success': True,
        'agents': [],
    }
    if run_mode == 'manual':
        log_payload['run_name'] = stage2_result.get('run_name')

    for item in stage2_result.get('results', []):
        if not isinstance(item, dict):
            continue
        updated_status_files: list[str] = []
        if item.get('restore_mode') in {'update', 'overwrite'} and item.get('status') in {'restored', 'partial'}:
            for path in item.get('active_files', []):
                updated = _mark_restored_in_file(path)
                if updated:
                    updated_status_files.append(updated)
        agent_log: dict[str, Any] = {
            'agent_id': item.get('agent_id'),
            'status': item.get('status'),
            'archive_path': item.get('archive_path'),
            'restored_files': item.get('restored_files', []),
        }
        if item.get('reason'):
            agent_log['reason'] = item.get('reason')
        if updated_status_files:
            agent_log['updated_status_files'] = updated_status_files
        finalized.append(agent_log)
        log_payload['agents'].append(agent_log)

    log_payload['success'] = all(item.get('status') in {'restored', 'skipped', 'partial'} for item in finalized)
    log_path = restore_log_path(cfg, week_id=str(stage2_result.get('week_id') or ''), run_mode=run_mode, run_name=stage2_result.get('run_name'))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(log_path, log_payload)

    return preserve_result(
        success=True,
        stage='Layer2_Restore_Stage3_Finalize',
        note='Stage3 已完成：记录 restore log，并在 active restore 时回写 restored 状态。',
        week_id=stage2_result.get('week_id'),
        restore_log_path=str(log_path),
        results=finalized,
    )
