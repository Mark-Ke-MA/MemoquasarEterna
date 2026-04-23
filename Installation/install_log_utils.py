#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Core.shared_funcs import load_json_file, write_json_atomic

SNAPSHOT_SCHEMA_VERSION = '1.0'
SNAPSHOT_KEEP_LATEST = 3


def install_logs_dir(repo_root: str | Path) -> Path:
    return Path(repo_root) / 'Installation' / '.install_logs'


def _timestamp_local() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _filename_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds').replace(':', '-').replace('+', '+')


def _snapshot_path(repo_root: str | Path, *, trigger: str) -> Path:
    return install_logs_dir(repo_root) / f'{trigger}-{_filename_timestamp()}.json'


def write_install_snapshot(repo_root: str | Path, *, trigger: str, snapshot: dict[str, Any], keep_latest: int = SNAPSHOT_KEEP_LATEST) -> Path:
    logs_dir = install_logs_dir(repo_root)
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = _snapshot_path(repo_root, trigger=trigger)
    write_json_atomic(path, snapshot, indent=2)
    prune_old_snapshots(repo_root, keep_latest=keep_latest)
    return path


def prune_old_snapshots(repo_root: str | Path, *, keep_latest: int = SNAPSHOT_KEEP_LATEST) -> list[str]:
    logs_dir = install_logs_dir(repo_root)
    if not logs_dir.exists():
        return []
    files = sorted(
        [p for p in logs_dir.glob('*.json') if p.is_file()],
        key=lambda p: p.name,
        reverse=True,
    )
    removed: list[str] = []
    for path in files[keep_latest:]:
        path.unlink(missing_ok=True)
        removed.append(str(path))
    return removed


def latest_snapshot_path(repo_root: str | Path) -> Path | None:
    logs_dir = install_logs_dir(repo_root)
    if not logs_dir.exists():
        return None
    files = sorted(
        [p for p in logs_dir.glob('*.json') if p.is_file()],
        key=lambda p: p.name,
        reverse=True,
    )
    return files[0] if files else None


def load_latest_snapshot(repo_root: str | Path) -> tuple[dict[str, Any] | None, Path | None]:
    path = latest_snapshot_path(repo_root)
    if path is None:
        return None, None
    data = load_json_file(path)
    if not isinstance(data, dict):
        raise ValueError(f'install snapshot 格式错误: {path}')
    return data, path


def build_install_snapshot(*, repo_root: str | Path, trigger: str, install_result: dict[str, Any], overall_config: dict[str, Any], harness_config: dict[str, Any] | None = None) -> dict[str, Any]:
    repo_root_path = Path(repo_root).resolve()
    steps = install_result.get('steps') if isinstance(install_result.get('steps'), list) else []
    step_map = {str(step.get('name', '')): step for step in steps if isinstance(step, dict)}
    core_raw = step_map.get('core_install', {}).get('raw', {}) if isinstance(step_map.get('core_install'), dict) else {}
    harness_raw = step_map.get('harness_install', {}).get('raw', {}) if isinstance(step_map.get('harness_install'), dict) else {}

    snapshot = {
        'schema_version': SNAPSHOT_SCHEMA_VERSION,
        'kind': 'install_snapshot',
        'trigger': trigger,
        'created_at': _timestamp_local(),
        'created_at_utc': _timestamp_utc(),
        'status': install_result.get('status'),
        'dry_run': bool(install_result.get('dry_run', False)),
        'retention': {
            'keep_latest': SNAPSHOT_KEEP_LATEST,
        },
        'context': {
            'product_name': overall_config.get('product_name'),
            'harness': overall_config.get('harness'),
            'repo_root': str(repo_root_path),
            'code_dir': str(repo_root_path),
        },
        'config_snapshot': {
            'overall_config': overall_config,
            'harness_config': harness_config,
        },
        'resolved': {
            'code_dir': str(repo_root_path),
            'store_dir': str(Path(str(overall_config.get('store_dir', '') or '')).expanduser().resolve()) if overall_config.get('store_dir') else '',
            'archive_dir': str(Path(str(overall_config.get('archive_dir', '') or '')).expanduser().resolve()) if overall_config.get('archive_dir') else '',
            'memory_worker_agentId': overall_config.get('memory_worker_agentId'),
            'agentId_list': overall_config.get('agentId_list', []),
            'layer1_auto_cron_marker': overall_config.get('layer1_auto_cron_marker'),
            'layer3_auto_cron_marker': overall_config.get('layer3_auto_cron_marker'),
            'daily_write_cron_time': overall_config.get('daily_write_cron_time'),
            'weekly_decay_cron_day': overall_config.get('weekly_decay_cron_day'),
            'weekly_decay_cron_time': overall_config.get('weekly_decay_cron_time'),
        },
        'core_install': core_raw,
        'harness_install': harness_raw,
        'steps': [
            {
                'name': step.get('name'),
                'critical': step.get('critical'),
                'success': step.get('success'),
                'summary': step.get('summary'),
            }
            for step in steps
            if isinstance(step, dict)
        ],
        'warnings': install_result.get('warnings', []),
    }
    return snapshot
