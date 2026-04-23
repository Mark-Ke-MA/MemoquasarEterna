#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.harness_connector import get_required_connector_callable, load_harness_connector
from Installation.Core.uninstall import run_uninstall as run_core_uninstall
from Installation.install_log_utils import load_latest_snapshot


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[1]


def _summarize_result(result: dict[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {'status': 'unknown', 'note': 'non-dict result'}
    summary: dict[str, Any] = {}
    for key in (
        'status',
        'message',
        'dry_run',
        'config_updated',
        'failed_step',
        'plugin_id',
    ):
        if key in result:
            summary[key] = result[key]
    if 'warnings' in result and isinstance(result.get('warnings'), list):
        summary['warning_count'] = len(result['warnings'])
    if 'cron_uninstall' in result and isinstance(result.get('cron_uninstall'), dict):
        cron_uninstall = result['cron_uninstall']
        summary['cron_uninstall'] = {
            'changed': cron_uninstall.get('changed'),
            'layer1_status': (cron_uninstall.get('layer1') or {}).get('status'),
            'layer3_status': (cron_uninstall.get('layer3') or {}).get('status'),
        }
    if 'steps' in result and isinstance(result.get('steps'), list):
        summary['step_count'] = len(result['steps'])
    return summary


def _step_payload(*, name: str, critical: bool, result: dict[str, Any]) -> dict[str, Any]:
    return {
        'name': name,
        'critical': critical,
        'success': bool(result.get('success', False)) if isinstance(result, dict) else False,
        'summary': _summarize_result(result),
        'raw': result,
    }


def _critical_failure_payload(*, step_results: list[dict[str, Any]], failed_step: str, message: str) -> dict[str, Any]:
    return {
        'success': False,
        'status': 'failed',
        'failed_step': failed_step,
        'message': message,
        'steps': step_results,
    }


def _step_display_name(name: str) -> str:
    mapping = {
        'core_uninstall': 'Core uninstall',
        'harness_uninstall': 'Harness uninstall',
    }
    return mapping.get(name, name)


def _step_status_text(step: dict[str, Any]) -> str:
    success = bool(step.get('success', False))
    summary = step.get('summary') if isinstance(step.get('summary'), dict) else {}
    warning_count = int(summary.get('warning_count', 0) or 0)
    if success and warning_count > 0:
        return f'完成（{warning_count} 条 warning）'
    if success:
        return '完成'
    return '失败'


def _collect_bullets(result: dict[str, Any]) -> list[str]:
    bullets: list[str] = []
    if not isinstance(result, dict):
        return bullets
    message = str(result.get('message', '') or '').strip()
    if message:
        bullets.append(message)
    warnings = result.get('warnings')
    if isinstance(warnings, list):
        bullets.extend(str(x) for x in warnings if str(x).strip())
    return bullets


def _format_uninstall_result(result: dict[str, Any]) -> str:
    lines: list[str] = []
    success = bool(result.get('success', False))
    dry_run = bool(result.get('dry_run', False))
    warnings = result.get('warnings') if isinstance(result.get('warnings'), list) else []
    steps = result.get('steps') if isinstance(result.get('steps'), list) else []

    title = 'MemoquasarEterna 卸载完成。' if success else 'MemoquasarEterna 卸载失败。'
    if dry_run:
        title += '（dry-run）'
    lines.append(title)
    lines.append('')

    for idx, step in enumerate(steps, start=1):
        lines.append(f'[{idx}/{len(steps)}] {_step_display_name(str(step.get("name", "")))}：{_step_status_text(step)}')

    if not success:
        failed_step = str(result.get('failed_step', '') or '').strip()
        message = str(result.get('message', '') or '').strip()
        if failed_step:
            lines.append('')
            lines.append(f'失败步骤：{_step_display_name(failed_step)}')
        if message:
            lines.append(f'原因：{message}')

    detail_bullets: list[str] = []
    if not success:
        for step in steps:
            if not bool(step.get('success', False)):
                raw = step.get('raw') if isinstance(step.get('raw'), dict) else {}
                detail_bullets.extend(_collect_bullets(raw))
                break
    else:
        detail_bullets.extend(str(x) for x in warnings if str(x).strip())

    if detail_bullets:
        unique_bullets: list[str] = []
        seen: set[str] = set()
        for item in detail_bullets:
            if item in seen:
                continue
            seen.add(item)
            unique_bullets.append(item)
        lines.append('')
        lines.append('提示：' if success else '详情：')
        for item in unique_bullets:
            lines.append(f'- {item}')

    return '\n'.join(lines).rstrip() + '\n'


def run_uninstall(*, repo_root: str | Path | None = None, dry_run: bool = False, snapshot: dict[str, Any] | None = None, use_latest_snapshot: bool = True) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else _repo_root_from_here()
    snapshot_path = None
    if snapshot is None and use_latest_snapshot:
        snapshot, snapshot_path = load_latest_snapshot(repo_root_path)
    snapshot_harness = ''
    if isinstance(snapshot, dict):
        snapshot_harness = str(((snapshot.get('context') or {}).get('harness') or '')).strip()
    connector = load_harness_connector(repo_root=repo_root_path, harness=snapshot_harness or None)
    connector_where = f'connector({repo_root_path}, harness={snapshot_harness or "current"})'
    harness_uninstall = get_required_connector_callable(connector, 'uninstall', where=connector_where)

    steps: list[dict[str, Any]] = []

    core_uninstall_result = run_core_uninstall(repo_root=repo_root_path, dry_run=dry_run, snapshot=snapshot)
    steps.append(_step_payload(name='core_uninstall', critical=True, result=core_uninstall_result))
    if not bool(core_uninstall_result.get('success', False)):
        return _critical_failure_payload(
            step_results=steps,
            failed_step='core_uninstall',
            message='Core uninstall 失败，卸载已中止。',
        )

    harness_uninstall_result = harness_uninstall(repo_root=repo_root_path, dry_run=dry_run, snapshot=snapshot)
    steps.append(_step_payload(name='harness_uninstall', critical=True, result=harness_uninstall_result))
    if not bool(harness_uninstall_result.get('success', False)):
        return _critical_failure_payload(
            step_results=steps,
            failed_step='harness_uninstall',
            message='Harness uninstall 失败。',
        )

    warnings: list[str] = []
    for result in (core_uninstall_result, harness_uninstall_result):
        if isinstance(result, dict) and isinstance(result.get('warnings'), list):
            warnings.extend(str(x) for x in result['warnings'])

    return {
        'success': True,
        'status': 'success_with_warnings' if warnings else 'success',
        'dry_run': dry_run,
        'warnings': warnings,
        'steps': steps,
        'snapshot_used': snapshot is not None,
        'snapshot_path': str(snapshot_path) if snapshot_path is not None else None,
        'snapshot_harness': snapshot_harness or None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Top-level uninstall orchestrator')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--dry-run', action='store_true', help='只执行支持 dry-run 的步骤，不实际删除')
    args = parser.parse_args()
    result = run_uninstall(repo_root=args.repo_root, dry_run=args.dry_run)
    sys.stdout.write(_format_uninstall_result(result))
    raise SystemExit(0 if bool(result.get('success', False)) else 1)


if __name__ == '__main__':
    main()
