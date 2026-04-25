#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from Adapters.openclaw.Installation.shared import (
    cfg,
    plugin_id_from_product_name,
    plugin_install_root,
    python_step,
    remove_tree,
    repo_root_from_here,
    summarize_step_result,
)
from Adapters.openclaw.Installation.templates.openclaw_json.render import DEFAULT_OUTPUT_PATH, update_example_openclaw_json
from Adapters.openclaw.openclaw_shared_funcs import output_success


def _snapshot_resolved(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    raw = snapshot.get('harness_production_agent_install') or {}
    if isinstance(raw.get('resolved_artifacts'), dict):
        return raw.get('resolved_artifacts') or {}
    if isinstance(raw.get('results'), list):
        merged: dict[str, Any] = {}
        labels: list[str] = []
        agent_ids: list[str] = []
        for item in raw['results']:
            if not isinstance(item, dict):
                continue
            artifacts = item.get('resolved_artifacts')
            if not isinstance(artifacts, dict):
                continue
            merged.update({key: value for key, value in artifacts.items() if key != 'sessions_watch'})
            sessions_watch = artifacts.get('sessions_watch')
            if isinstance(sessions_watch, dict):
                labels.extend(str(x).strip() for x in sessions_watch.get('labels', []) if str(x).strip())
                agent_ids.extend(str(x).strip() for x in sessions_watch.get('agent_ids', []) if str(x).strip())
                if sessions_watch.get('daily_init_cron_marker'):
                    merged.setdefault('sessions_watch', {})['daily_init_cron_marker'] = sessions_watch.get('daily_init_cron_marker')
        if labels or agent_ids:
            merged.setdefault('sessions_watch', {})
            merged['sessions_watch']['labels'] = labels
            merged['sessions_watch']['agent_ids'] = agent_ids
        return merged
    return {}


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
    pending_spacing_idx: int | None = None
    pending_title_idx: int | None = None
    for ln in current_lines:
        if ln == '#':
            pending_spacing_idx = len(kept)
            kept.append(ln)
            continue
        if ln.startswith('# ====='):
            pending_title_idx = len(kept)
            kept.append(ln)
            continue
        if ln == begin_marker:
            inside_block = True
            if pending_title_idx is not None and pending_title_idx == len(kept) - 1:
                removed.append(kept.pop())
                if pending_spacing_idx is not None and pending_spacing_idx == len(kept) - 1:
                    removed.append(kept.pop())
            pending_title_idx = None
            pending_spacing_idx = None
            removed.append(ln)
            continue
        if ln == end_marker:
            inside_block = False
            removed.append(ln)
            pending_title_idx = None
            pending_spacing_idx = None
            continue
        if inside_block:
            removed.append(ln)
            continue
        pending_spacing_idx = None
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


def run_uninstall(*, repo_root: str | Path | None = None, dry_run: bool = False, snapshot: dict[str, Any] | None = None, agent_ids: list[str] | None = None) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else repo_root_from_here()
    config = cfg(repo_root_path)

    product_name = str(config.overall_config.get('product_name', '') or '').strip()
    if not product_name:
        return {
            'success': False,
            'status': 'failed',
            'failed_step': 'preflight',
            'message': 'OverallConfig.json 缺少 product_name。',
            'steps': [],
        }

    snapshot_artifacts = _snapshot_resolved(snapshot)
    plugin_id = str(snapshot_artifacts.get('plugin_id') or plugin_id_from_product_name(product_name)).strip()
    plugin_dir = Path(str(snapshot_artifacts.get('plugin_dir') or (plugin_install_root() / plugin_id))).expanduser()
    sessions_watch_manage = repo_root_path / 'Adapters' / 'openclaw' / 'Sessions_Watch' / 'Mechanisms' / 'sessions_watch_manage.py'
    sessions_watch = snapshot_artifacts.get('sessions_watch') if isinstance(snapshot_artifacts.get('sessions_watch'), dict) else {}
    session_labels = [str(x).strip() for x in sessions_watch.get('labels', []) if str(x).strip()]
    daily_marker = str(sessions_watch.get('daily_init_cron_marker') or config.openclaw_config['maintenance']['daily_init_cron_marker']).strip()

    steps: list[dict[str, Any]] = []
    warnings: list[str] = []

    if session_labels:
        label_results = []
        session_watch_success = True
        for label in session_labels:
            result = python_step(
                sessions_watch_manage,
                args=['delete', '--label', label, '--repo-root', str(repo_root_path)],
                repo_root=None,
                dry_run=dry_run,
            )
            label_results.append({'label': label, 'result': summarize_step_result(result)})
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
                'label_results': label_results,
                'cron_cleanup': cron_cleanup,
            },
        })
        if not session_watch_success:
            warnings.append('Sessions Watch 卸载失败；请后续手动重试该步骤。')
    else:
        result = python_step(
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
            'summary': summarize_step_result(result),
        })
        if not session_watch_success:
            warnings.append('Sessions Watch 卸载失败；请后续手动重试该步骤。')

    result = remove_tree(plugin_dir, dry_run=dry_run)
    steps.append({
        'name': 'remove_read_plugin_directory',
        'critical': False,
        'success': True,
        'summary': result,
    })

    try:
        render_result = update_example_openclaw_json(repo_root=repo_root_path, scope='production_agent', action='remove', dry_run=dry_run, agent_ids=agent_ids)
    except Exception as exc:
        render_result = {'success': False, 'status': 'failed', 'message': str(exc)}
    steps.append({
        'name': 'remove_production_agent_openclaw_json_example',
        'critical': False,
        'success': bool(render_result.get('success', False)),
        'summary': {
            'output_path': render_result.get('output_path'),
            'read_plugin_id': render_result.get('read_plugin_id'),
            'agent_count': render_result.get('agent_count'),
        },
    })
    if not bool(render_result.get('success', False)):
        warnings.append('production agent OpenClaw merge 示例清理失败；请后续手动检查。')

    example_path = Path(str(render_result.get('output_path') or snapshot_artifacts.get('example_openclaw_json_path') or DEFAULT_OUTPUT_PATH)).expanduser()
    result = remove_tree(example_path, dry_run=dry_run)
    steps.append({
        'name': 'remove_openclaw_json_example',
        'critical': False,
        'success': True,
        'summary': result,
    })

    return {
        'success': True,
        'status': 'success_with_warnings' if warnings else 'success',
        'dry_run': dry_run,
        'warnings': warnings,
        'plugin_id': plugin_id,
        'steps': steps,
        'snapshot_used': bool(snapshot_artifacts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='OpenClaw production agent uninstall.')
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
