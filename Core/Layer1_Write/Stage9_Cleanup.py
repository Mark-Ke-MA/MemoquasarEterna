#!/usr/bin/env python3
"""Layer1 写入层的第9阶段：清理收尾。

职责：
- 读取 plan.json
- 判断是否需要写 failed log，并在需要时先写 log
- 清理 staging_surface/{agent_id}/*，但保留 agent 目录本身
- 不清理 plan.json
- 回写 plan.stage9 的最小字段：status / fail_log_needed / fail_log_path / staging_cleaned
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import shutil

from Core.Layer1_Write.shared import LoadConfig, load_json_file, write_json_atomic



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


def _write_plan(plan: dict[str, Any], repo_root: str | Path | None = None) -> None:
    write_json_atomic(_plan_path(repo_root), plan)


def _layer1_logs_cfg(repo_root: str | Path | None = None) -> tuple[Path, str, str, str]:
    overall_cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(overall_cfg['store_dir'])).expanduser()
    store_structure = overall_cfg.get('store_dir_structure', {}) if isinstance(overall_cfg, dict) else {}
    logs_cfg = store_structure.get('logs', {}) if isinstance(store_structure, dict) else {}
    root = str(logs_cfg.get('root', 'logs') or 'logs')
    layer1_cfg = logs_cfg.get('layer1_write', {}) if isinstance(logs_cfg.get('layer1_write'), dict) else {}
    layer1_root = str(layer1_cfg.get('root', 'Layer1_Write_logs') or 'Layer1_Write_logs')
    auto_nested = str(layer1_cfg.get('auto', 'auto') or 'auto')
    manual_nested = str(layer1_cfg.get('manual', 'manual') or 'manual')
    return store_root / root, layer1_root, auto_nested, manual_nested


def _sanitize_run_name(name: str | None) -> str:
    raw = str(name or '').strip()
    if not raw:
        return datetime.now(timezone.utc).strftime('manual_%Y-%m-%dT%H-%M-%SZ')
    keep: list[str] = []
    for ch in raw:
        if ch.isalnum() or ch in {'-', '_', '.'}:
            keep.append(ch)
        else:
            keep.append('_')
    cleaned = ''.join(keep).strip('._-')
    return cleaned or datetime.now(timezone.utc).strftime('manual_%Y-%m-%dT%H-%M-%SZ')


def _build_failed_log_path(*, target_date: str, run_mode: str, run_name: str | None, repo_root: str | Path | None = None) -> Path:
    base_root, layer1_write, auto_nested, manual_nested = _layer1_logs_cfg(repo_root)
    safe_target_date = target_date.strip() if target_date else ''
    filename = f'{safe_target_date}.json' if safe_target_date else 'unknown_date.json'
    if run_mode == 'auto':
        return base_root / layer1_write / auto_nested / filename

    safe_run_name = _sanitize_run_name(run_name)
    return base_root / layer1_write / manual_nested / safe_run_name / filename


def _stage(plan: dict[str, Any], stage_name: str) -> dict[str, Any]:
    value = plan.get('plan', {}).get(stage_name, {})
    return value if isinstance(value, dict) else {}


def _failed_status(stage_block: dict[str, Any]) -> bool:
    return str(stage_block.get('status', '') or '') == 'failed'


def _nonempty_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _stage3_failed_agents(plan: dict[str, Any]) -> list[dict[str, Any]]:
    stage2 = _stage(plan, 'stage2')
    stage3 = _stage(plan, 'stage3')
    failed_agents = set(_nonempty_str_list(stage3.get('failed_agents', [])))
    if not failed_agents:
        return []

    total_chunks_by_agent: dict[str, int] = {}
    for agent_plan in stage2.get('agents', []) if isinstance(stage2.get('agents', []), list) else []:
        if not isinstance(agent_plan, dict):
            continue
        agent_id = str(agent_plan.get('agent_id', '') or '')
        if not agent_id:
            continue
        try:
            total_chunks_by_agent[agent_id] = int(agent_plan.get('actual_chunk_count', 0) or 0)
        except Exception:
            total_chunks_by_agent[agent_id] = 0

    failed_chunks_by_agent: dict[str, list[dict[str, int]]] = {agent_id: [] for agent_id in failed_agents}
    raw_batches = stage3.get('map_batches') or []
    if isinstance(raw_batches, list):
        for batch in raw_batches:
            if not isinstance(batch, list):
                continue
            for job in batch:
                if not isinstance(job, dict):
                    continue
                agent_id = str(job.get('agent_id', '') or '')
                if agent_id not in failed_agents:
                    continue
                job_status = str(job.get('status', '') or '')
                if job_status != 'failed':
                    continue
                try:
                    chunk_id = int(job.get('chunk_id', 0) or 0)
                except Exception:
                    chunk_id = 0
                failed_chunks_by_agent.setdefault(agent_id, []).append({
                    'chunk_id': chunk_id,
                    'total_chunks': int(total_chunks_by_agent.get(agent_id, 0) or 0),
                })

    out: list[dict[str, Any]] = []
    for agent_id in sorted(failed_agents):
        payload = {'agent_id': agent_id}
        chunks = failed_chunks_by_agent.get(agent_id, [])
        if chunks:
            payload['failed_chunks'] = chunks
        out.append(payload)
    return out


def _build_fail_log_payload(plan: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    run_meta = plan.get('plan', {}).get('run_meta', {}) if isinstance(plan.get('plan', {}), dict) else {}
    target_date = str(run_meta.get('date', '') or '')

    stage1 = _stage(plan, 'stage1')
    stage2 = _stage(plan, 'stage2')
    stage3 = _stage(plan, 'stage3')
    stage4 = _stage(plan, 'stage4')
    stage5 = _stage(plan, 'stage5')
    stage6 = _stage(plan, 'stage6')
    stage7 = _stage(plan, 'stage7')
    stage8 = _stage(plan, 'stage8')

    need_log = any([
        _failed_status(stage1),
        _failed_status(stage2),
        _failed_status(stage3),
        _failed_status(stage4),
        _failed_status(stage5),
        _failed_status(stage6),
        _failed_status(stage7),
        _failed_status(stage8),
        bool(stage7.get('skipped', False)),
    ])

    payload: dict[str, Any] = {
        'target_date': target_date,
        'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'stage1': {
            'agents_with_conversation': _nonempty_str_list(stage1.get('agents_with_conversation', [])),
        },
    }

    stage3_failed = _stage3_failed_agents(plan)
    if stage3_failed:
        payload['stage3'] = {'failed_agents': stage3_failed}
    elif _failed_status(stage3):
        payload['stage3'] = {'status': 'failed'}

    stage4_failed = _nonempty_str_list(stage4.get('failed_agents', []))
    if stage4_failed:
        payload['stage4'] = {'failed_agents': stage4_failed}
    elif _failed_status(stage4):
        payload['stage4'] = {'status': 'failed'}

    stage5_failed = _nonempty_str_list(stage5.get('failed_agents', []))
    if stage5_failed:
        payload['stage5'] = {'failed_agents': stage5_failed}
    elif _failed_status(stage5):
        payload['stage5'] = {'status': 'failed'}

    stage6_failed = _nonempty_str_list(stage6.get('failed_agents', []))
    if stage6_failed:
        payload['stage6'] = {'failed_agents': stage6_failed}
    elif _failed_status(stage6):
        payload['stage6'] = {'status': 'failed'}

    stage7_failed = _nonempty_str_list(stage7.get('failed_agents', []))
    stage7_skipped = bool(stage7.get('skipped', False))
    stage7_block: dict[str, Any] = {}
    if stage7_failed:
        stage7_block['failed_agents'] = stage7_failed
    elif _failed_status(stage7):
        stage7_block['status'] = 'failed'
    if stage7_skipped:
        stage7_block['skipped'] = True
        skip_reason = str(stage7.get('skip_reason', '') or '')
        if skip_reason:
            stage7_block['skip_reason'] = skip_reason
    if stage7_block:
        payload['stage7'] = stage7_block

    stage8_failed = _nonempty_str_list(stage8.get('failed_agents', []))
    if stage8_failed:
        payload['stage8'] = {'failed_agents': stage8_failed}
    elif _failed_status(stage8):
        payload['stage8'] = {'status': 'failed'}

    if _failed_status(stage1):
        payload['stage1']['status'] = 'failed'
    if _failed_status(stage2):
        payload['stage2'] = {'status': 'failed'}

    return need_log, payload


def _write_failed_log(*, plan: dict[str, Any], run_mode: str, run_name: str | None, repo_root: str | Path | None = None) -> str | None:
    need_log, payload = _build_fail_log_payload(plan)
    if not need_log:
        return None
    target_date = str(payload.get('target_date', '') or '')
    log_path = _build_failed_log_path(target_date=target_date, run_mode=run_mode, run_name=run_name, repo_root=repo_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(log_path, payload)
    return str(log_path)


def _cleanup_agent_staging_dirs(plan: dict[str, Any], repo_root: str | Path | None = None) -> list[str]:
    _ = plan
    overall_cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(overall_cfg['store_dir'])).expanduser()
    staging_cfg = overall_cfg['store_dir_structure']['staging']
    staging_surface_root = store_root / staging_cfg['root'] / staging_cfg['staging_surface']
    agent_ids = _nonempty_str_list(overall_cfg.get('agentId_list', []))

    cleaned_roots: list[str] = []
    for agent_id in agent_ids:
        agent_root = staging_surface_root / agent_id
        if not agent_root.exists() or not agent_root.is_dir():
            raise FileNotFoundError(f'Stage9 清理目标目录不存在: {agent_root}')
        for child in list(agent_root.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        cleaned_roots.append(str(agent_root))
    return cleaned_roots


def run_stage9(*, repo_root: str | Path | None = None, run_mode: str = 'manual', run_name: str | None = None) -> dict[str, Any]:
    plan = _load_plan(repo_root)
    root = plan.setdefault('plan', {})
    stage9 = root.setdefault('stage9', {})
    stage9['status'] = 'running'
    stage9.pop('fail_log_needed', None)
    stage9.pop('fail_log_path', None)
    stage9['staging_cleaned'] = False
    _write_plan(plan, repo_root)

    log_path: str | None = None
    try:
        log_path = _write_failed_log(plan=plan, run_mode=run_mode, run_name=run_name, repo_root=repo_root)
        cleaned_roots = _cleanup_agent_staging_dirs(plan, repo_root=repo_root)
        stage9['status'] = 'done'
        stage9['fail_log_needed'] = log_path is not None
        stage9['fail_log_path'] = log_path
        stage9['staging_cleaned'] = True
        root.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        _write_plan(plan, repo_root)
        return {
            'success': True,
            'stage': 'Stage9',
            'note': 'Stage9 执行完成。',
            'fail_log_needed': log_path is not None,
            'fail_log_path': log_path,
            'cleaned_agent_roots': cleaned_roots,
        }
    except Exception:
        stage9['status'] = 'failed'
        stage9['fail_log_needed'] = log_path is not None
        stage9['fail_log_path'] = log_path
        stage9['staging_cleaned'] = False
        root.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        _write_plan(plan, repo_root)
        raise


__all__ = ['run_stage9']
