#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.shared_funcs import LoadConfig, output_failure, output_success


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def _cfg(repo_root: str | Path | None = None) -> LoadConfig:
    return LoadConfig(Path(repo_root) if repo_root is not None else _repo_root_from_here())


def _require_str(data: dict[str, Any], key: str, *, where: str) -> str:
    value = str(data.get(key, '') or '').strip()
    if not value:
        raise KeyError(f'{where} 缺少 {key}')
    return value


def _layer1_marker(cfg: dict[str, Any], snapshot: dict[str, Any] | None = None) -> str:
    if isinstance(snapshot, dict):
        marker = str((((snapshot.get('core_install') or {}).get('cron_install') or {}).get('layer1') or {}).get('marker') or '').strip()
        if marker:
            return marker
        marker = str(((snapshot.get('resolved') or {}).get('layer1_auto_cron_marker') or '')).strip()
        if marker:
            return marker
    return _require_str(cfg, 'layer1_auto_cron_marker', where='OverallConfig.json')


def _layer3_marker(cfg: dict[str, Any], snapshot: dict[str, Any] | None = None) -> str:
    if isinstance(snapshot, dict):
        marker = str((((snapshot.get('core_install') or {}).get('cron_install') or {}).get('layer3') or {}).get('marker') or '').strip()
        if marker:
            return marker
        marker = str(((snapshot.get('resolved') or {}).get('layer3_auto_cron_marker') or '')).strip()
        if marker:
            return marker
    return _require_str(cfg, 'layer3_auto_cron_marker', where='OverallConfig.json')


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


def _summarize_crontab_write(result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        'status': result['status'],
        'returncode': result['returncode'],
    }
    if result.get('returncode', 0) != 0:
        summary['error'] = result.get('stderr') or result.get('stdout') or ''
    return summary


def _summarize_block_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        'changed': result['changed'],
        'status': result['status'],
        'removed_count': len(result.get('removed', [])),
    }


def _remove_marked_block(current: str, *, marker: str) -> tuple[str, dict[str, Any]]:
    begin_marker = f'# BEGIN {marker}'
    end_marker = f'# END {marker}'
    current_lines = [ln.rstrip() for ln in current.splitlines() if ln.strip()]
    removed: list[str] = []
    kept: list[str] = []
    inside_block = False
    pending_title_idx: int | None = None

    for ln in current_lines:
        if ln.startswith('# ====='):
            pending_title_idx = len(kept)
            kept.append(ln)
            continue
        if ln == begin_marker:
            inside_block = True
            if pending_title_idx is not None and pending_title_idx == len(kept) - 1:
                removed.append(kept.pop())
                if kept and kept[-1] == '#':
                    removed.append(kept.pop())
            pending_title_idx = None
            removed.append(ln)
            continue
        if ln == end_marker:
            inside_block = False
            removed.append(ln)
            pending_title_idx = None
            continue
        if inside_block:
            removed.append(ln)
            continue
        pending_title_idx = None
        kept.append(ln)

    new_content = '\n'.join(kept).strip()
    if new_content:
        new_content += '\n'

    if not removed:
        return current, {
            'changed': False,
            'status': 'absent',
            'removed': [],
        }
    return new_content, {
        'changed': True,
        'status': 'removed',
        'removed': removed,
    }


def run_uninstall(*, repo_root: str | Path | None = None, dry_run: bool = False, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _cfg(repo_root).overall_config
    current = _crontab_list()

    layer1_marker = _layer1_marker(cfg, snapshot=snapshot)
    layer3_marker = _layer3_marker(cfg, snapshot=snapshot)
    content, layer1_result = _remove_marked_block(current, marker=layer1_marker)
    content, layer3_result = _remove_marked_block(content, marker=layer3_marker)

    changed = bool(layer1_result['changed'] or layer3_result['changed'])
    if not changed:
        write_result = {
            'cmd': ['crontab', '-'],
            'returncode': 0,
            'stdout': '',
            'stderr': '',
            'status': 'skipped',
        }
    else:
        write_result = _crontab_write(content, dry_run=dry_run)
        if write_result['returncode'] != 0:
            output_failure(f"删除 core auto cron 失败: {write_result['stderr'] or write_result['stdout']}")
        if dry_run:
            if layer1_result['changed']:
                layer1_result['status'] = 'would-remove'
            if layer3_result['changed']:
                layer3_result['status'] = 'would-remove'

    return {
        'success': True,
        'status': 'ok',
        'cron_uninstall': {
            'changed': changed,
            'dry_run': dry_run,
            'layer1': {
                'marker': layer1_marker,
                **_summarize_block_result(layer1_result),
            },
            'layer3': {
                'marker': layer3_marker,
                **_summarize_block_result(layer3_result),
            },
            'crontab_write': _summarize_crontab_write(write_result),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Remove core auto cron blocks.')
    parser.add_argument('--repo-root', default=None, help='Repository root path (defaults to auto-detect).')
    parser.add_argument('--dry-run', action='store_true', help='Preview actions without writing crontab.')
    args = parser.parse_args()
    output_success(run_uninstall(repo_root=args.repo_root, dry_run=args.dry_run))


if __name__ == '__main__':
    main()
