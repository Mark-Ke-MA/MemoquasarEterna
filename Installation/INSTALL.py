#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.harness_connector import (
    get_required_connector_callable,
    get_required_connector_entry,
    get_configured_memory_worker_harness,
    load_harness_connector,
    production_agents_by_harness,
)
from Installation.Config import ensure_install_configs
from Installation.Core.install import run_install as run_core_install
from Installation.Core.prerequisites import run_prerequisites as run_core_prerequisites
from Installation.install_log_utils import build_install_snapshot, write_install_snapshot
from Adapters.openclaw.openclaw_shared_funcs import LoadConfig as OpenClawLoadConfig


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
    ):
        if key in result:
            summary[key] = result[key]
    if 'warnings' in result and isinstance(result.get('warnings'), list):
        summary['warning_count'] = len(result['warnings'])
    if 'errors' in result and isinstance(result.get('errors'), list):
        summary['error_count'] = len(result['errors'])
    if 'checks' in result and isinstance(result.get('checks'), dict):
        summary['check_keys'] = sorted(result['checks'].keys())
    if 'cron_install' in result and isinstance(result.get('cron_install'), dict):
        cron_install = result['cron_install']
        summary['cron_install'] = {
            'status': cron_install.get('status'),
            'layer1_status': (cron_install.get('layer1') or {}).get('status'),
            'layer3_status': (cron_install.get('layer3') or {}).get('status'),
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


def _combined_result(results: list[dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []
    for result in results:
        if isinstance(result.get('warnings'), list):
            warnings.extend(str(x) for x in result['warnings'] if str(x).strip())
        if not bool(result.get('success', False)):
            message = str(result.get('message', '') or '').strip()
            if message:
                errors.append(message)
            elif isinstance(result.get('errors'), list):
                errors.extend(str(x) for x in result['errors'] if str(x).strip())
    return {
        'success': not errors,
        'status': 'success_with_warnings' if warnings and not errors else ('success' if not errors else 'failed'),
        'dry_run': dry_run,
        'warnings': warnings,
        'errors': errors,
        'results': results,
    }


def _step_display_name(name: str) -> str:
    mapping = {
        'core_prerequisites': 'Core prerequisites',
        'config_bootstrap': 'Config bootstrap',
        'harness_config_bootstrap': 'Harness config bootstrap',
        'harness_memory_worker_prerequisites': 'Harness memory worker prerequisites',
        'harness_production_agent_prerequisites': 'Harness production agent prerequisites',
        'core_install': 'Core install',
        'harness_memory_worker_install': 'Harness memory worker install',
        'harness_production_agent_install': 'Harness production agent install',
    }
    return mapping.get(name, name)


def _step_status_text(step: dict[str, Any]) -> str:
    success = bool(step.get('success', False))
    summary = step.get('summary') if isinstance(step.get('summary'), dict) else {}
    warning_count = int(summary.get('warning_count', 0) or 0)
    if success and warning_count > 0:
        return f'通过（{warning_count} 条 warning）'
    if success:
        return '通过'
    return '失败'


def _collect_bullets(result: dict[str, Any]) -> list[str]:
    bullets: list[str] = []
    if not isinstance(result, dict):
        return bullets
    message = str(result.get('message', '') or '').strip()
    if message:
        bullets.append(message)
    errors = result.get('errors')
    if isinstance(errors, list):
        bullets.extend(str(x) for x in errors if str(x).strip())
    warnings = result.get('warnings')
    if isinstance(warnings, list):
        bullets.extend(str(x) for x in warnings if str(x).strip())
    return bullets


def _format_install_result(result: dict[str, Any]) -> str:
    lines: list[str] = []
    success = bool(result.get('success', False))
    dry_run = bool(result.get('dry_run', False))
    warnings = result.get('warnings') if isinstance(result.get('warnings'), list) else []
    steps = result.get('steps') if isinstance(result.get('steps'), list) else []

    title = 'MemoquasarEterna 安装完成。' if success else 'MemoquasarEterna 安装失败。'
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


def run_install(*, repo_root: str | Path | None = None, dry_run: bool = False, trigger: str = 'install') -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else _repo_root_from_here()
    steps: list[dict[str, Any]] = []

    config_result = ensure_install_configs(repo_root=repo_root_path, dry_run=dry_run)
    steps.append(_step_payload(name='config_bootstrap', critical=True, result=config_result))
    if not bool(config_result.get('success', False)):
        return _critical_failure_payload(
            step_results=steps,
            failed_step='config_bootstrap',
            message='Config bootstrap 未通过，安装已中止。',
        )

    memory_worker_harness = get_configured_memory_worker_harness(repo_root_path)
    production_groups = production_agents_by_harness(repo_root_path)
    participating_harnesses = [memory_worker_harness]
    participating_harnesses.extend(harness for harness in production_groups if harness not in participating_harnesses)

    connectors_by_harness = {
        harness: load_harness_connector(repo_root=repo_root_path, harness=harness)
        for harness in participating_harnesses
    }

    harness_config_results: list[dict[str, Any]] = []
    for harness, connector in connectors_by_harness.items():
        connector_where = f'connector({repo_root_path}, harness={harness})'
        harness_ensure_config = get_required_connector_entry(connector, 'ensure_config', where=connector_where)
        result = harness_ensure_config(repo_root=repo_root_path, dry_run=dry_run)
        result.setdefault('harness', harness)
        harness_config_results.append(result)
    harness_config_result = _combined_result(harness_config_results, dry_run=dry_run)
    steps.append(_step_payload(name='harness_config_bootstrap', critical=True, result=harness_config_result))
    if not bool(harness_config_result.get('success', False)):
        return _critical_failure_payload(
            step_results=steps,
            failed_step='harness_config_bootstrap',
            message='Harness config bootstrap 未通过，安装已中止。',
        )

    core_prereq_result = run_core_prerequisites(repo_root=repo_root_path, dry_run=dry_run)
    steps.append(_step_payload(name='core_prerequisites', critical=True, result=core_prereq_result))
    if not bool(core_prereq_result.get('success', False)):
        return _critical_failure_payload(
            step_results=steps,
            failed_step='core_prerequisites',
            message='Core prerequisites 未通过，安装已中止。',
        )

    mw_connector = connectors_by_harness[memory_worker_harness]
    mw_where = f'connector({repo_root_path}, harness={memory_worker_harness})'
    harness_mw_prerequisites = get_required_connector_callable(mw_connector, 'memory_worker', 'prerequisites', where=mw_where)
    harness_mw_install = get_required_connector_callable(mw_connector, 'memory_worker', 'install', where=mw_where)

    harness_mw_prereq_result = harness_mw_prerequisites(repo_root=repo_root_path, dry_run=dry_run)
    steps.append(_step_payload(name='harness_memory_worker_prerequisites', critical=True, result=harness_mw_prereq_result))
    if not bool(harness_mw_prereq_result.get('success', False)):
        return _critical_failure_payload(
            step_results=steps,
            failed_step='harness_memory_worker_prerequisites',
            message='Harness memory worker prerequisites 未通过，安装已中止。',
        )

    harness_pa_prereq_results: list[dict[str, Any]] = []
    for harness, agent_ids in production_groups.items():
        connector = connectors_by_harness[harness]
        connector_where = f'connector({repo_root_path}, harness={harness})'
        harness_pa_prerequisites = get_required_connector_callable(connector, 'production_agent', 'prerequisites', where=connector_where)
        result = harness_pa_prerequisites(repo_root=repo_root_path, dry_run=dry_run, agent_ids=agent_ids)
        result.setdefault('harness', harness)
        result.setdefault('agent_ids', agent_ids)
        harness_pa_prereq_results.append(result)
    harness_pa_prereq_result = _combined_result(harness_pa_prereq_results, dry_run=dry_run)
    steps.append(_step_payload(name='harness_production_agent_prerequisites', critical=True, result=harness_pa_prereq_result))
    if not bool(harness_pa_prereq_result.get('success', False)):
        return _critical_failure_payload(
            step_results=steps,
            failed_step='harness_production_agent_prerequisites',
            message='Harness production agent prerequisites 未通过，安装已中止。',
        )

    core_install_result = run_core_install(repo_root=repo_root_path, dry_run=dry_run)
    steps.append(_step_payload(name='core_install', critical=True, result=core_install_result))
    if not bool(core_install_result.get('success', False)):
        return _critical_failure_payload(
            step_results=steps,
            failed_step='core_install',
            message='Core install 失败，安装已中止。',
        )

    harness_mw_install_result = harness_mw_install(repo_root=repo_root_path, dry_run=dry_run)
    steps.append(_step_payload(name='harness_memory_worker_install', critical=True, result=harness_mw_install_result))
    if not bool(harness_mw_install_result.get('success', False)):
        return _critical_failure_payload(
            step_results=steps,
            failed_step='harness_memory_worker_install',
            message='Harness memory worker install 失败。',
        )

    harness_pa_install_results: list[dict[str, Any]] = []
    for harness, agent_ids in production_groups.items():
        connector = connectors_by_harness[harness]
        connector_where = f'connector({repo_root_path}, harness={harness})'
        harness_pa_install = get_required_connector_callable(connector, 'production_agent', 'install', where=connector_where)
        result = harness_pa_install(repo_root=repo_root_path, dry_run=dry_run, agent_ids=agent_ids)
        result.setdefault('harness', harness)
        result.setdefault('agent_ids', agent_ids)
        harness_pa_install_results.append(result)
    harness_pa_install_result = _combined_result(harness_pa_install_results, dry_run=dry_run)
    steps.append(_step_payload(name='harness_production_agent_install', critical=True, result=harness_pa_install_result))
    if not bool(harness_pa_install_result.get('success', False)):
        return _critical_failure_payload(
            step_results=steps,
            failed_step='harness_production_agent_install',
            message='Harness production agent install 失败。',
        )

    warnings: list[str] = []
    for result in (config_result, harness_config_result, core_prereq_result, harness_mw_prereq_result, harness_pa_prereq_result, core_install_result, harness_mw_install_result, harness_pa_install_result):
        if isinstance(result, dict) and isinstance(result.get('warnings'), list):
            warnings.extend(str(x) for x in result['warnings'])

    result = {
        'success': True,
        'status': 'success_with_warnings' if warnings else 'success',
        'dry_run': dry_run,
        'warnings': warnings,
        'steps': steps,
    }
    if not dry_run:
        try:
            harness_cfg = OpenClawLoadConfig(repo_root=repo_root_path).openclaw_config
        except Exception:
            harness_cfg = None
        snapshot = build_install_snapshot(
            repo_root=repo_root_path,
            trigger=trigger,
            install_result=result,
            overall_config=OpenClawLoadConfig(repo_root=repo_root_path).overall_config,
            harness_config=harness_cfg,
        )
        snapshot_path = write_install_snapshot(repo_root_path, trigger=trigger, snapshot=snapshot)
        result['snapshot_path'] = str(snapshot_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description='Top-level installation orchestrator')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--dry-run', action='store_true', help='只执行支持 dry-run 的步骤，不实际写入配置或 crontab')
    args = parser.parse_args()
    result = run_install(repo_root=args.repo_root, dry_run=args.dry_run, trigger='install')
    sys.stdout.write(_format_install_result(result))
    raise SystemExit(0 if bool(result.get('success', False)) else 1)


if __name__ == '__main__':
    main()
