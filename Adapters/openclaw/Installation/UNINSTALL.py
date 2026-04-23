#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Adapters.openclaw.openclaw_shared_funcs import LoadConfig, output_success


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[3]


def _cfg(repo_root: str | Path | None = None) -> LoadConfig:
    return LoadConfig(Path(repo_root) if repo_root is not None else _repo_root_from_here())


def _python_step(script_path: Path, *, args: list[str], repo_root: Path | None, dry_run: bool) -> dict[str, Any]:
    cmd = [sys.executable, str(script_path)]
    if repo_root is not None:
        cmd.extend(['--repo-root', str(repo_root)])
    cmd.extend(args)
    if dry_run:
        cmd.append('--dry-run')
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stdout = (proc.stdout or '').strip()
    stderr = (proc.stderr or '').strip()
    parsed = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except Exception:
            parsed = None
    return {
        'cmd': cmd,
        'returncode': proc.returncode,
        'stdout': stdout,
        'stderr': stderr,
        'parsed': parsed,
    }


def _plugin_id_from_product_name(product_name: str) -> str:
    plugin_id = ''.join(ch.lower() if ch.isalnum() else '_' for ch in product_name).strip('_')
    return plugin_id or 'memoquasar_read'


def _summarize_python_step_result(result: dict[str, Any]) -> dict[str, Any]:
    parsed = result.get('parsed') if isinstance(result, dict) else None
    summary: dict[str, Any] = {}
    if isinstance(parsed, dict):
        for key in ('mode', 'labels', 'cron_cleanup', 'status'):
            if key in parsed:
                summary[key] = parsed[key]
    if result.get('returncode', 0) != 0:
        if result.get('stderr'):
            summary['error'] = result['stderr']
        elif result.get('stdout'):
            summary['error'] = result['stdout']
    return summary


def _memory_worker_workspace_path(cfg: LoadConfig) -> Path:
    worker_agent_id = str(cfg.overall_config.get('memory_worker_agentId', '') or '').strip()
    if not worker_agent_id:
        raise KeyError('OverallConfig.json 缺少 memory_worker_agentId')
    template = str(cfg.openclaw_config.get('memory_worker_agent_workspace_path', '') or '').strip()
    if not template:
        raise KeyError('OpenclawConfig.json 缺少 memory_worker_agent_workspace_path')
    rendered = template.format(memory_worker_agentId=worker_agent_id)
    return Path(rendered).expanduser()


def _plugin_install_root() -> Path:
    base = os.environ.get('OPENCLAW_EXTENSIONS_PATH', '').strip()
    if base:
        return Path(base).expanduser()
    return Path('~/.openclaw/extensions').expanduser()


def _remove_tree(path: Path, *, dry_run: bool) -> dict[str, Any]:
    exists = path.exists()
    if dry_run:
        return {
            'path': str(path),
            'exists': exists,
            'deleted': False,
            'status': 'would-delete' if exists else 'skipped',
        }
    if not exists:
        return {
            'path': str(path),
            'exists': False,
            'deleted': False,
            'status': 'skipped',
        }
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return {
        'path': str(path),
        'exists': True,
        'deleted': True,
        'status': 'deleted',
    }


def _crontab_list() -> str:
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if result.returncode != 0:
        return ''
    return result.stdout or ''


def _crontab_write(content: str, *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {'returncode': 0, 'status': 'would-write', 'stdout': '', 'stderr': ''}
    proc = subprocess.run(['crontab', '-'], input=content, capture_output=True, text=True)
    return {
        'returncode': proc.returncode,
        'status': 'written' if proc.returncode == 0 else 'failed',
        'stdout': (proc.stdout or '').strip(),
        'stderr': (proc.stderr or '').strip(),
    }


def _remove_cron_block_by_marker(marker: str, *, dry_run: bool) -> dict[str, Any]:
    current = _crontab_list()
    current_lines = [ln.rstrip() for ln in current.splitlines() if ln.strip()]
    begin_marker = f'# BEGIN {marker}'
    end_marker = f'# END {marker}'
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
    if not removed:
        return {'changed': False, 'status': 'absent', 'removed_count': 0}
    new_content = '\n'.join(kept).strip()
    if new_content:
        new_content += '\n'
    write_result = _crontab_write(new_content, dry_run=dry_run)
    if write_result['returncode'] != 0:
        return {'changed': True, 'status': 'failed', 'removed_count': len(removed), 'error': write_result['stderr'] or write_result['stdout']}
    return {'changed': True, 'status': 'would-remove' if dry_run else 'removed', 'removed_count': len(removed)}


def _snapshot_resolved(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    return (snapshot.get('harness_install') or {}).get('resolved_artifacts') or {}


def run_uninstall(*, repo_root: str | Path | None = None, dry_run: bool = False, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else _repo_root_from_here()
    cfg = _cfg(repo_root_path)

    if str(cfg.overall_config.get('harness', '') or '').strip() != 'openclaw':
        return {
            'success': False,
            'status': 'failed',
            'failed_step': 'preflight',
            'message': 'OverallConfig.json.harness 不是 openclaw，无法执行 OpenClaw uninstall。',
            'steps': [],
        }

    product_name = str(cfg.overall_config.get('product_name', '') or '').strip()
    if not product_name:
        return {
            'success': False,
            'status': 'failed',
            'failed_step': 'preflight',
            'message': 'OverallConfig.json 缺少 product_name。',
            'steps': [],
        }

    snapshot_artifacts = _snapshot_resolved(snapshot)
    plugin_id = str(snapshot_artifacts.get('plugin_id') or _plugin_id_from_product_name(product_name)).strip()
    plugin_dir = Path(str(snapshot_artifacts.get('plugin_dir') or (_plugin_install_root() / plugin_id))).expanduser()
    memory_worker_workspace = Path(str(snapshot_artifacts.get('memory_worker_workspace_path') or _memory_worker_workspace_path(cfg))).expanduser()
    example_openclaw_json = Path(str(snapshot_artifacts.get('example_openclaw_json_path') or (repo_root_path / 'Installation' / 'example-openclaw.json'))).expanduser()
    sessions_watch_manage = repo_root_path / 'Adapters' / 'openclaw' / 'Sessions_Watch' / 'Mechanisms' / 'sessions_watch_manage.py'
    sessions_watch = snapshot_artifacts.get('sessions_watch') if isinstance(snapshot_artifacts.get('sessions_watch'), dict) else {}
    session_labels = [str(x).strip() for x in sessions_watch.get('labels', []) if str(x).strip()]
    daily_marker = str(sessions_watch.get('daily_init_cron_marker') or cfg.openclaw_config['maintenance']['daily_init_cron_marker']).strip()

    steps: list[dict[str, Any]] = []
    warnings: list[str] = []

    # 1. Remove sessions watch managed objects.
    if session_labels:
        label_results = []
        session_watch_success = True
        for label in session_labels:
            result = _python_step(
                sessions_watch_manage,
                args=['delete', '--label', label, '--repo-root', str(repo_root_path)],
                repo_root=None,
                dry_run=dry_run,
            )
            label_results.append({'label': label, 'result': _summarize_python_step_result(result)})
            if result['returncode'] != 0:
                session_watch_success = False
        cron_cleanup = _remove_cron_block_by_marker(daily_marker, dry_run=dry_run)
        if cron_cleanup.get('status') == 'failed':
            session_watch_success = False
        steps.append({
            'name': 'uninstall_sessions_watch',
            'critical': False,
            'success': session_watch_success,
            'summary': {
                'status': 'removed' if session_watch_success else 'partial-failed',
                'labels': session_labels,
                'cron_cleanup': cron_cleanup,
            },
        })
        if not session_watch_success:
            warnings.append('Sessions Watch 卸载失败；请后续手动重试该步骤。')
    else:
        result = _python_step(
            sessions_watch_manage,
            args=['delete', '--all', '--remove-daily-init-cron', '--repo-root', str(repo_root_path)],
            repo_root=None,
            dry_run=dry_run,
        )
        session_watch_success = result['returncode'] == 0
        steps.append({
            'name': 'uninstall_sessions_watch',
            'critical': False,
            'success': session_watch_success,
            'summary': _summarize_python_step_result(result),
        })
        if not session_watch_success:
            warnings.append('Sessions Watch 卸载失败；请后续手动重试该步骤。')

    # 2. Remove read plugin directory.
    result = _remove_tree(plugin_dir, dry_run=dry_run)
    steps.append({
        'name': 'remove_read_plugin_directory',
        'critical': False,
        'success': True,
        'summary': result,
    })

    # 3. Remove memory worker workspace.
    result = _remove_tree(memory_worker_workspace, dry_run=dry_run)
    steps.append({
        'name': 'remove_memory_worker_workspace',
        'critical': False,
        'success': True,
        'summary': result,
    })

    # 4. Remove generated merge-example artifact.
    result = _remove_tree(example_openclaw_json, dry_run=dry_run)
    steps.append({
        'name': 'remove_generated_example_openclaw_json',
        'critical': False,
        'success': True,
        'summary': result,
    })

    status = 'success_with_warnings' if warnings else 'success'
    return {
        'success': True,
        'status': status,
        'dry_run': dry_run,
        'warnings': warnings,
        'plugin_id': plugin_id,
        'steps': steps,
        'snapshot_used': bool(snapshot_artifacts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='OpenClaw uninstall orchestrator')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--dry-run', action='store_true', help='只输出计划，不实际删除')
    args = parser.parse_args()

    result = run_uninstall(repo_root=args.repo_root, dry_run=args.dry_run)
    if result.get('success', False):
        output_success(result)
        return

    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(1)


if __name__ == '__main__':
    main()
