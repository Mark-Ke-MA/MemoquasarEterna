#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Core.Layer3_Decay.shared import LoadConfig, previous_iso_week_id
from Core.shared_funcs import write_json_atomic


def _layer3_logs_cfg(repo_root: str | Path | None = None) -> tuple[Path, str, str, str]:
    overall_cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(overall_cfg['store_dir'])).expanduser()
    store_structure = overall_cfg.get('store_dir_structure', {}) if isinstance(overall_cfg, dict) else {}
    logs_cfg = store_structure.get('logs', {}) if isinstance(store_structure, dict) else {}
    root = str(logs_cfg.get('root', 'logs') or 'logs')
    layer3_cfg = logs_cfg.get('layer3_decay', {}) if isinstance(logs_cfg.get('layer3_decay'), dict) else {}
    layer3_root = str(layer3_cfg.get('root', 'Layer3_Decay_logs') or 'Layer3_Decay_logs')
    auto_nested = str(layer3_cfg.get('auto', 'auto') or 'auto')
    manual_nested = str(layer3_cfg.get('manual', 'manual') or 'manual')
    return store_root / root, layer3_root, auto_nested, manual_nested


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


def _resolved_week(week: str | None, repo_root: str | Path | None = None) -> str:
    if week and str(week).strip():
        return str(week).strip()
    overall_cfg = LoadConfig(repo_root).overall_config
    timezone_name = str(overall_cfg.get('timezone', 'Europe/London'))
    return previous_iso_week_id(timezone_name=timezone_name)


def _build_failed_log_path(*, week: str, run_mode: str, run_name: str | None, repo_root: str | Path | None = None) -> Path:
    base_root, layer3_root, auto_nested, manual_nested = _layer3_logs_cfg(repo_root)
    filename = f'{week}.json' if week else 'unknown_week.json'
    if run_mode == 'auto':
        return base_root / layer3_root / auto_nested / filename
    safe_run_name = _sanitize_run_name(run_name)
    return base_root / layer3_root / manual_nested / safe_run_name / filename


def _extract_failed_agents(result: dict[str, Any] | None) -> list[str]:
    if not isinstance(result, dict):
        return []
    value = result.get('failed_agents', [])
    if isinstance(value, list):
        out = [str(item) for item in value if str(item).strip()]
        if out:
            return out
    nested = result.get('result')
    if isinstance(nested, dict):
        value = nested.get('failed_agents', [])
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
    return []


def build_failed_log_payload(*, failed_phase: str, result: dict[str, Any], week: str | None, source_week: str | None, run_mode: str, run_name: str | None, apply_cleanup: bool, repo_root: str | Path | None = None) -> dict[str, Any]:
    resolved_week = _resolved_week(week, repo_root=repo_root)
    payload: dict[str, Any] = {
        'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'week': resolved_week,
        'run_mode': run_mode,
        'apply_cleanup': bool(apply_cleanup),
        'failed_phase': failed_phase,
        'note': str(result.get('note', '') or ''),
    }
    if source_week is not None and str(source_week).strip():
        payload['source_week'] = str(source_week).strip()
    if run_mode == 'manual' and str(run_name or '').strip():
        payload['run_name'] = str(run_name).strip()
    failed_agents = _extract_failed_agents(result)
    if failed_agents:
        payload['failed_agents'] = failed_agents
    return payload


def write_failed_log(*, failed_phase: str, result: dict[str, Any], week: str | None, source_week: str | None, run_mode: str, run_name: str | None, apply_cleanup: bool, repo_root: str | Path | None = None) -> str:
    payload = build_failed_log_payload(
        failed_phase=failed_phase,
        result=result,
        week=week,
        source_week=source_week,
        run_mode=run_mode,
        run_name=run_name,
        apply_cleanup=apply_cleanup,
        repo_root=repo_root,
    )
    path = _build_failed_log_path(week=str(payload.get('week', '') or ''), run_mode=run_mode, run_name=run_name, repo_root=repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)
    return str(path)


__all__ = [
    'build_failed_log_payload',
    'write_failed_log',
]
