#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from Adapters.openclaw.Installation.shared import (
    cfg,
    critical_failure_payload,
    plugin_id_from_product_name,
    plugin_install_root,
    repo_root_from_here,
    production_agent_ids,
    shell_step,
    summarize_step_result,
    python_step,
)
from Adapters.openclaw.Installation.templates.openclaw_json.render import DEFAULT_OUTPUT_PATH, update_example_openclaw_json
from Adapters.openclaw.openclaw_shared_funcs import output_success


def _summarize_shell_step_result(result: dict[str, Any], *, plugin_id: str) -> dict[str, Any]:
    summary = {'plugin_id': plugin_id}
    if result.get('note'):
        summary['note'] = result['note']
    if result.get('returncode', 0) != 0:
        if result.get('stderr'):
            summary['error'] = result['stderr']
        elif result.get('stdout'):
            summary['error'] = result['stdout']
    return summary


def run_install(*, repo_root: str | Path | None = None, dry_run: bool = False, agent_ids: list[str] | None = None) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else repo_root_from_here()
    config = cfg(repo_root_path)
    agent_ids = production_agent_ids(config, agent_ids=agent_ids)

    product_name = str(config.overall_config.get('product_name', '') or '').strip()
    plugin_id = plugin_id_from_product_name(product_name)
    plugin_dir = plugin_install_root() / plugin_id
    read_install = repo_root_path / 'Adapters' / 'openclaw' / 'Read' / 'installation.sh'
    sessions_watch_initialize = repo_root_path / 'Adapters' / 'openclaw' / 'Sessions_Watch' / 'Mechanisms' / 'sessions_watch_initialize.py'
    steps: list[dict[str, Any]] = []
    warnings: list[str] = []

    try:
        render_result = update_example_openclaw_json(repo_root=repo_root_path, scope='production_agent', action='upsert', dry_run=dry_run, agent_ids=agent_ids)
    except Exception as exc:
        render_result = {'success': False, 'status': 'failed', 'message': str(exc)}
    steps.append({
        'name': 'render_production_agent_openclaw_json_example',
        'critical': True,
        'success': bool(render_result.get('success', False)),
        'summary': {
            'output_path': render_result.get('output_path'),
            'read_plugin_id': render_result.get('read_plugin_id'),
            'agent_count': render_result.get('agent_count'),
        },
    })
    if not bool(render_result.get('success', False)):
        return critical_failure_payload(
            step_results=steps,
            failed_step='render_production_agent_openclaw_json_example',
            message='渲染 production agent OpenClaw merge 示例失败。',
        )

    if dry_run:
        result = {
            'cmd': ['bash', str(read_install)],
            'returncode': 0,
            'stdout': '',
            'stderr': '',
            'parsed': None,
            'note': 'dry-run: skipped shell execution',
        }
    else:
        result = shell_step(
            read_install,
            repo_root=repo_root_path,
            env={'MEMOQUASAR_PRODUCTION_AGENT_IDS_JSON': json.dumps(agent_ids, ensure_ascii=False)},
        )
    steps.append({
        'name': 'install_read_plugin',
        'critical': True,
        'success': result['returncode'] == 0,
        'summary': _summarize_shell_step_result(result, plugin_id=plugin_id),
    })
    if result['returncode'] != 0:
        return critical_failure_payload(
            step_results=steps,
            failed_step='install_read_plugin',
            message='OpenClaw Read plugin 安装失败。',
        )

    session_results = []
    session_success = True
    for agent_id in agent_ids:
        session_args = ['--agent', agent_id]
        if not dry_run:
            session_args.append('--write')
        result = python_step(sessions_watch_initialize, args=session_args, repo_root=repo_root_path, dry_run=False)
        session_results.append(result)
        if result['returncode'] != 0:
            session_success = False
    steps.append({
        'name': 'initialize_sessions_watch',
        'critical': False,
        'success': session_success,
        'summary': {
            'agent_count': len(agent_ids),
            'results': [summarize_step_result(item) for item in session_results],
        },
    })
    if not session_success:
        warnings.append(
            'Sessions Watch 初始化失败。安装主流程已继续，但产品当前仍不可正常使用；请在后续修复并重试该步骤。'
        )

    cron_args = ['--generate-daily-init-cron']
    if not dry_run:
        cron_args.append('--write')
    cron_result = python_step(sessions_watch_initialize, args=cron_args, repo_root=repo_root_path, dry_run=False)
    cron_success = cron_result['returncode'] == 0
    steps.append({
        'name': 'install_sessions_watch_daily_init_cron',
        'critical': False,
        'success': cron_success,
        'summary': summarize_step_result(cron_result),
    })
    if not cron_success:
        warnings.append(
            'Sessions Watch daily init cron 安装失败。安装主流程已继续；请后续修复并重试该步骤。'
        )

    session_labels = []
    for result in session_results:
        session_parsed = result.get('parsed') if isinstance(result, dict) else None
        if isinstance(session_parsed, dict) and isinstance(session_parsed.get('agents'), list):
            session_labels.extend(str(item.get('label', '') or '').strip() for item in session_parsed['agents'] if isinstance(item, dict) and str(item.get('label', '') or '').strip())
        if isinstance(session_parsed, dict) and str(session_parsed.get('label', '') or '').strip():
            session_labels.append(str(session_parsed.get('label', '') or '').strip())

    return {
        'success': True,
        'status': 'success_with_warnings' if warnings else 'success',
        'dry_run': dry_run,
        'warnings': warnings,
        'plugin_id': plugin_id,
        'resolved_artifacts': {
            'plugin_id': plugin_id,
            'plugin_dir': str(plugin_dir),
            'example_openclaw_json_path': str(Path(render_result.get('output_path') or DEFAULT_OUTPUT_PATH).expanduser()),
            'sessions_watch': {
                'daily_init_cron_marker': str(config.openclaw_config['maintenance']['daily_init_cron_marker']),
                'labels': session_labels,
                'agent_ids': agent_ids,
            },
        },
        'steps': steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='OpenClaw production agent install.')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--dry-run', action='store_true', help='只输出计划，不实际写入')
    args = parser.parse_args()
    result = run_install(repo_root=args.repo_root, dry_run=args.dry_run)
    if result.get('success', False):
        output_success(result)
        return
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(1)


if __name__ == '__main__':
    main()
