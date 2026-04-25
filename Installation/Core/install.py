#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.shared_funcs import LoadConfig, get_production_agent_ids, output_success


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def _cfg(repo_root: str | Path | None = None) -> LoadConfig:
    return LoadConfig(Path(repo_root) if repo_root is not None else _repo_root_from_here())


def _expand_path(value: str) -> Path:
    return Path(os.path.expanduser(str(value))).resolve()


def _require_str(data: dict[str, Any], key: str, *, where: str) -> str:
    value = str(data.get(key, '') or '').strip()
    if not value:
        raise KeyError(f'{where} 缺少 {key}')
    return value


def _require_dict(data: dict[str, Any], key: str, *, where: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise KeyError(f'{where} 缺少 {key}')
    return value


def _require_list_of_agent_ids(cfg: dict[str, Any]) -> list[str]:
    return get_production_agent_ids(cfg)


def _cron_time_to_fields(value: str, *, where: str) -> tuple[str, str]:
    text = str(value or '').strip()
    if not re.fullmatch(r'\d{2}:\d{2}', text):
        raise ValueError(f'{where} 必须是 HH:MM 格式，实际为: {text!r}')
    hour, minute = text.split(':', 1)
    if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
        raise ValueError(f'{where} 超出合法范围，实际为: {text!r}')
    return minute, hour


def _cron_day_to_dow(value: str, *, where: str) -> str:
    text = str(value or '').strip()
    mapping = {
        'sun': '0',
        'mon': '1',
        'tue': '2',
        'wed': '3',
        'thu': '4',
        'fri': '5',
        'sat': '6',
    }
    key = text[:3].lower()
    if key not in mapping:
        raise ValueError(f'{where} 必须是 Sun/Mon/.../Sat，实际为: {text!r}')
    return mapping[key]


def _store_paths(cfg: dict[str, Any]) -> dict[str, Path]:
    store_root = _expand_path(_require_str(cfg, 'store_dir', where='OverallConfig.json'))
    structure = _require_dict(cfg, 'store_dir_structure', where='OverallConfig.json')
    memory = _require_dict(structure, 'memory', where='OverallConfig.json.store_dir_structure')
    staging = _require_dict(structure, 'staging', where='OverallConfig.json.store_dir_structure')
    logs = _require_dict(structure, 'logs', where='OverallConfig.json.store_dir_structure')
    restored = _require_dict(structure, 'restored', where='OverallConfig.json.store_dir_structure')
    statistics = _require_dict(structure, 'statistics', where='OverallConfig.json.store_dir_structure')
    harness_logs = _require_dict(logs, 'harness', where='OverallConfig.json.store_dir_structure.logs')
    layer1_logs = _require_dict(logs, 'layer1_write', where='OverallConfig.json.store_dir_structure.logs')
    layer2_logs = _require_dict(logs, 'layer2_preserve', where='OverallConfig.json.store_dir_structure.logs')
    layer3_logs = _require_dict(logs, 'layer3_decay', where='OverallConfig.json.store_dir_structure.logs')

    return {
        'store_root': store_root,
        'memory_root': store_root / _require_str(memory, 'root', where='OverallConfig.json.store_dir_structure.memory'),
        'memory_surface': store_root / _require_str(memory, 'root', where='OverallConfig.json.store_dir_structure.memory') / _require_str(memory, 'surface', where='OverallConfig.json.store_dir_structure.memory'),
        'memory_shallow': store_root / _require_str(memory, 'root', where='OverallConfig.json.store_dir_structure.memory') / _require_str(memory, 'shallow', where='OverallConfig.json.store_dir_structure.memory'),
        'memory_deep': store_root / _require_str(memory, 'root', where='OverallConfig.json.store_dir_structure.memory') / _require_str(memory, 'deep', where='OverallConfig.json.store_dir_structure.memory'),
        'staging_root': store_root / _require_str(staging, 'root', where='OverallConfig.json.store_dir_structure.staging'),
        'staging_surface': store_root / _require_str(staging, 'root', where='OverallConfig.json.store_dir_structure.staging') / _require_str(staging, 'staging_surface', where='OverallConfig.json.store_dir_structure.staging'),
        'staging_shallow': store_root / _require_str(staging, 'root', where='OverallConfig.json.store_dir_structure.staging') / _require_str(staging, 'staging_shallow', where='OverallConfig.json.store_dir_structure.staging'),
        'staging_deep': store_root / _require_str(staging, 'root', where='OverallConfig.json.store_dir_structure.staging') / _require_str(staging, 'staging_deep', where='OverallConfig.json.store_dir_structure.staging'),
        'logs_root': store_root / _require_str(logs, 'root', where='OverallConfig.json.store_dir_structure.logs'),
        'logs_harness_root': store_root / _require_str(logs, 'root', where='OverallConfig.json.store_dir_structure.logs') / _require_str(harness_logs, 'root', where='OverallConfig.json.store_dir_structure.logs.harness'),
        'logs_layer1_root': store_root / _require_str(logs, 'root', where='OverallConfig.json.store_dir_structure.logs') / _require_str(layer1_logs, 'root', where='OverallConfig.json.store_dir_structure.logs.layer1_write'),
        'logs_layer2_root': store_root / _require_str(logs, 'root', where='OverallConfig.json.store_dir_structure.logs') / _require_str(layer2_logs, 'root', where='OverallConfig.json.store_dir_structure.logs.layer2_preserve'),
        'logs_layer3_root': store_root / _require_str(logs, 'root', where='OverallConfig.json.store_dir_structure.logs') / _require_str(layer3_logs, 'root', where='OverallConfig.json.store_dir_structure.logs.layer3_decay'),
        'restored_root': store_root / _require_str(restored, 'root', where='OverallConfig.json.store_dir_structure.restored'),
        'statistics_root': store_root / _require_str(statistics, 'root', where='OverallConfig.json.store_dir_structure.statistics'),
    }


def _archive_paths(cfg: dict[str, Any]) -> dict[str, Path]:
    archive_root = _expand_path(_require_str(cfg, 'archive_dir', where='OverallConfig.json'))
    structure = _require_dict(cfg, 'archive_dir_structure', where='OverallConfig.json')
    return {
        'archive_root': archive_root,
        'archive_core_root': archive_root / _require_str(structure, 'core', where='OverallConfig.json.archive_dir_structure'),
        'archive_harness_root': archive_root / _require_str(structure, 'harness', where='OverallConfig.json.archive_dir_structure'),
    }


def _mkdir(path: Path, *, dry_run: bool, created: list[str]) -> None:
    if dry_run:
        created.append(str(path))
        return
    path.mkdir(parents=True, exist_ok=True)
    created.append(str(path))


def _summarize_tree_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        'path': result['path'],
        'status': result['status'],
        'created': result['created'],
        'reason': result.get('reason'),
        'created_count': len(result.get('created_paths', [])),
    }


def _summarize_crontab_write(result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        'status': result['status'],
        'returncode': result['returncode'],
    }
    if result.get('returncode', 0) != 0:
        summary['error'] = result.get('stderr') or result.get('stdout') or ''
    return summary


def _ensure_store_tree(cfg: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    paths = _store_paths(cfg)
    root = paths['store_root']
    if root.exists():
        return {
            'path': str(root),
            'status': 'skipped',
            'created': False,
            'reason': 'store_dir already exists',
            'created_paths': [],
        }

    agent_ids = _require_list_of_agent_ids(cfg)
    created_paths: list[str] = []

    _mkdir(root, dry_run=dry_run, created=created_paths)
    for key in (
        'memory_root',
        'staging_root', 'staging_surface', 'staging_shallow', 'staging_deep',
        'logs_root', 'logs_harness_root', 'logs_layer1_root', 'logs_layer2_root', 'logs_layer3_root',
        'restored_root', 'statistics_root',
    ):
        _mkdir(paths[key], dry_run=dry_run, created=created_paths)

    memory_surface_name = paths['memory_surface'].name
    memory_shallow_name = paths['memory_shallow'].name
    memory_deep_name = paths['memory_deep'].name
    for agent_id in agent_ids:
        agent_memory_root = paths['memory_root'] / agent_id
        _mkdir(agent_memory_root, dry_run=dry_run, created=created_paths)
        _mkdir(agent_memory_root / memory_surface_name, dry_run=dry_run, created=created_paths)
        _mkdir(agent_memory_root / memory_shallow_name, dry_run=dry_run, created=created_paths)
        _mkdir(agent_memory_root / memory_deep_name, dry_run=dry_run, created=created_paths)
        for key in ('staging_surface', 'staging_shallow', 'staging_deep'):
            _mkdir(paths[key] / agent_id, dry_run=dry_run, created=created_paths)

    return {
        'path': str(root),
        'status': 'would-create' if dry_run else 'created',
        'created': True,
        'reason': None,
        'created_paths': created_paths,
    }


def _ensure_archive_tree(cfg: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    paths = _archive_paths(cfg)
    root = paths['archive_root']
    if root.exists():
        return {
            'path': str(root),
            'status': 'skipped',
            'created': False,
            'reason': 'archive_dir already exists',
            'created_paths': [],
        }

    agent_ids = _require_list_of_agent_ids(cfg)
    created_paths: list[str] = []

    _mkdir(root, dry_run=dry_run, created=created_paths)
    _mkdir(paths['archive_core_root'], dry_run=dry_run, created=created_paths)
    _mkdir(paths['archive_harness_root'], dry_run=dry_run, created=created_paths)
    for agent_id in agent_ids:
        _mkdir(paths['archive_core_root'] / agent_id, dry_run=dry_run, created=created_paths)

    return {
        'path': str(root),
        'status': 'would-create' if dry_run else 'created',
        'created': True,
        'reason': None,
        'created_paths': created_paths,
    }


def _crontab_list() -> str:
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if result.returncode != 0:
        return ''
    return result.stdout or ''


def _crontab_write(content: str, *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {
            'cmd': ['crontab', '-'],
            'returncode': 0,
            'stdout': '',
            'stderr': '',
            'status': 'would-write',
        }
    proc = subprocess.run(['crontab', '-'], input=content, capture_output=True, text=True)
    return {
        'cmd': ['crontab', '-'],
        'returncode': proc.returncode,
        'stdout': (proc.stdout or '').strip(),
        'stderr': (proc.stderr or '').strip(),
        'status': 'written' if proc.returncode == 0 else 'failed',
    }


def _upsert_cron_block(existing: str, *, marker: str, block: str) -> tuple[str, str]:
    begin = f'# BEGIN {marker}'
    end = f'# END {marker}'
    lines = existing.splitlines()

    start_idx = next((i for i, line in enumerate(lines) if line.strip() == begin), None)
    if start_idx is not None:
        end_idx = next((i for i in range(start_idx + 1, len(lines)) if lines[i].strip() == end), None)
        if end_idx is None:
            raise ValueError(f'检测到不完整的 cron block：缺少 {end}')
        new_lines = lines[:start_idx] + block.rstrip('\n').splitlines() + lines[end_idx + 1:]
        return '\n'.join(new_lines).rstrip() + '\n', 'updated'

    base = existing.rstrip('\n')
    if base:
        base += '\n'
    base += block.rstrip('\n') + '\n'
    return base, 'created'


def _layer1_marker(cfg: dict[str, Any]) -> str:
    return _require_str(cfg, 'layer1_auto_cron_marker', where='OverallConfig.json')


def _layer3_marker(cfg: dict[str, Any]) -> str:
    return _require_str(cfg, 'layer3_auto_cron_marker', where='OverallConfig.json')


def _layer1_block(cfg: dict[str, Any], *, repo_root: Path) -> str:
    minute, hour = _cron_time_to_fields(
        _require_str(cfg, 'daily_write_cron_time', where='OverallConfig.json'),
        where='OverallConfig.json.daily_write_cron_time',
    )
    marker = _layer1_marker(cfg)
    command = (
        f'{sys.executable} {repo_root / "Core" / "Layer1_Write" / "ENTRY_LAYER1.py"} '
        f'--repo-root {repo_root} --run-mode auto'
    )
    return (
        '#\n'
        f'# ===== MemoquasarEterna Layer1 Auto Write（每日 {hour}:{minute}）=====\n'
        f'# BEGIN {marker}\n'
        f'{minute} {hour} * * * {command}\n'
        f'# END {marker}'
    )


def _layer3_block(cfg: dict[str, Any], *, repo_root: Path) -> str:
    minute, hour = _cron_time_to_fields(
        _require_str(cfg, 'weekly_decay_cron_time', where='OverallConfig.json'),
        where='OverallConfig.json.weekly_decay_cron_time',
    )
    day_text = _require_str(cfg, 'weekly_decay_cron_day', where='OverallConfig.json')
    dow = _cron_day_to_dow(day_text, where='OverallConfig.json.weekly_decay_cron_day')
    marker = _layer3_marker(cfg)
    command = (
        f'{sys.executable} {repo_root / "Core" / "Layer3_Decay" / "ENTRY_LAYER3.py"} '
        f'--repo-root {repo_root} --run-mode auto --apply_cleanup'
    )
    return (
        '#\n'
        f'# ===== MemoquasarEterna Layer3 Auto Decay（每周 {day_text} {hour}:{minute}）=====\n'
        f'# BEGIN {marker}\n'
        f'{minute} {hour} * * {dow} {command}\n'
        f'# END {marker}'
    )


def _install_core_crons(cfg: dict[str, Any], *, repo_root: Path, dry_run: bool) -> dict[str, Any]:
    existing = _crontab_list()
    layer1_command = (
        f'{sys.executable} {repo_root / "Core" / "Layer1_Write" / "ENTRY_LAYER1.py"} '
        f'--repo-root {repo_root} --run-mode auto'
    )
    layer3_command = (
        f'{sys.executable} {repo_root / "Core" / "Layer3_Decay" / "ENTRY_LAYER3.py"} '
        f'--repo-root {repo_root} --run-mode auto --apply_cleanup'
    )
    content, layer1_status = _upsert_cron_block(existing, marker=_layer1_marker(cfg), block=_layer1_block(cfg, repo_root=repo_root))
    content, layer3_status = _upsert_cron_block(content, marker=_layer3_marker(cfg), block=_layer3_block(cfg, repo_root=repo_root))
    write_result = _crontab_write(content, dry_run=dry_run)
    success = write_result['returncode'] == 0
    return {
        'success': success,
        'status': write_result['status'],
        'layer1': {
            'marker': _layer1_marker(cfg),
            'status': layer1_status,
            'cron_time': _require_str(cfg, 'daily_write_cron_time', where='OverallConfig.json'),
            'command': layer1_command,
        },
        'layer3': {
            'marker': _layer3_marker(cfg),
            'status': layer3_status,
            'cron_day': _require_str(cfg, 'weekly_decay_cron_day', where='OverallConfig.json'),
            'cron_time': _require_str(cfg, 'weekly_decay_cron_time', where='OverallConfig.json'),
            'command': layer3_command,
        },
        'crontab_write': _summarize_crontab_write(write_result),
    }


def run_install(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else _repo_root_from_here()
    cfg = _cfg(repo_root_path).overall_config
    store_result = _ensure_store_tree(cfg, dry_run=dry_run)
    archive_result = _ensure_archive_tree(cfg, dry_run=dry_run)
    cron_result = _install_core_crons(cfg, repo_root=repo_root_path, dry_run=dry_run)

    success = bool(cron_result.get('success', False))
    return {
        'success': success,
        'status': 'ok' if success else 'failed',
        'store_dir_install': _summarize_tree_result(store_result),
        'archive_dir_install': _summarize_tree_result(archive_result),
        'cron_install': cron_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Install core storage skeleton and auto crons.')
    parser.add_argument('--repo-root', default=None, help='Repository root path (defaults to auto-detect).')
    parser.add_argument('--dry-run', action='store_true', help='Preview actions without writing files or crontab.')
    args = parser.parse_args()
    output_success(run_install(repo_root=args.repo_root, dry_run=args.dry_run))


if __name__ == '__main__':
    main()
