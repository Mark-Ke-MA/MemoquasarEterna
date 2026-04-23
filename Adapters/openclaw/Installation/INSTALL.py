#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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


def _python_step(script_path: Path, *, args: list[str], repo_root: Path, dry_run: bool) -> dict[str, Any]:
    cmd = [sys.executable, str(script_path), '--repo-root', str(repo_root)]
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


def _shell_step(script_path: Path, *, repo_root: Path) -> dict[str, Any]:
    cmd = ['bash', str(script_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_root))
    stdout = (proc.stdout or '').strip()
    stderr = (proc.stderr or '').strip()
    return {
        'cmd': cmd,
        'returncode': proc.returncode,
        'stdout': stdout,
        'stderr': stderr,
        'parsed': None,
    }


def _summarize_python_step_result(result: dict[str, Any]) -> dict[str, Any]:
    parsed = result.get('parsed') if isinstance(result, dict) else None
    summary: dict[str, Any] = {}
    if isinstance(parsed, dict):
        for key in (
            'mode',
            'output_path',
            'target_root',
            'worker_agent_id',
            'memory_worker_agentId',
            'memory_worker_workspace_path',
            'read_plugin_id',
            'agent_count',
            'status',
            'cron_install',
        ):
            if key in parsed:
                summary[key] = parsed[key]
    if result.get('returncode', 0) != 0:
        if result.get('stderr'):
            summary['error'] = result['stderr']
        elif result.get('stdout'):
            summary['error'] = result['stdout']
    return summary


def _plugin_install_root() -> Path:
    base = os.environ.get('OPENCLAW_EXTENSIONS_PATH', '').strip()
    if base:
        return Path(base).expanduser()
    return Path('~/.openclaw/extensions').expanduser()


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


def _critical_failure_payload(*, step_results: list[dict[str, Any]], failed_step: str, message: str) -> dict[str, Any]:
    return {
        'success': False,
        'status': 'failed',
        'failed_step': failed_step,
        'message': message,
        'steps': step_results,
    }


def run_install(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else _repo_root_from_here()
    cfg = _cfg(repo_root_path)

    if str(cfg.overall_config.get('harness', '') or '').strip() != 'openclaw':
        return _critical_failure_payload(
            step_results=[],
            failed_step='preflight',
            message='OverallConfig.json.harness 不是 openclaw，无法执行 OpenClaw installation。',
        )

    install_root = Path(__file__).resolve().parent
    memory_worker_install = install_root / 'templates' / 'memory_worker' / 'install.py'
    openclaw_json_render = install_root / 'templates' / 'openclaw_json' / 'render.py'
    read_install = repo_root_path / 'Adapters' / 'openclaw' / 'Read' / 'installation.sh'
    sessions_watch_initialize = repo_root_path / 'Adapters' / 'openclaw' / 'Sessions_Watch' / 'Mechanisms' / 'sessions_watch_initialize.py'
    product_name = str(cfg.overall_config.get('product_name', '') or '').strip()
    plugin_id = ''.join(ch.lower() if ch.isalnum() else '_' for ch in product_name).strip('_') or 'memoquasar_read'

    steps: list[dict[str, Any]] = []
    warnings: list[str] = []
    plugin_dir = _plugin_install_root() / plugin_id
    memory_worker_workspace = Path(str(cfg.openclaw_config.get('memory_worker_agent_workspace_path', '') or '').format(memory_worker_agentId=str(cfg.overall_config.get('memory_worker_agentId', '') or '').strip())).expanduser()
    example_openclaw_json = repo_root_path / 'Installation' / 'example-openclaw.json'

    # 1. Render openclaw.json merge example
    result = _python_step(openclaw_json_render, args=[], repo_root=repo_root_path, dry_run=dry_run)
    steps.append({
        'name': 'render_openclaw_json_example',
        'critical': True,
        'success': result['returncode'] == 0,
        'summary': _summarize_python_step_result(result),
    })
    if result['returncode'] != 0:
        return _critical_failure_payload(
            step_results=steps,
            failed_step='render_openclaw_json_example',
            message='渲染 Installation/example-openclaw.json 失败。',
        )

    # 2. Install memory worker workspace
    result = _python_step(memory_worker_install, args=[], repo_root=repo_root_path, dry_run=dry_run)
    steps.append({
        'name': 'install_memory_worker_workspace',
        'critical': True,
        'success': result['returncode'] == 0,
        'summary': _summarize_python_step_result(result),
    })
    if result['returncode'] != 0:
        return _critical_failure_payload(
            step_results=steps,
            failed_step='install_memory_worker_workspace',
            message='memory worker workspace 初始化失败。',
        )

    # 3. Install read plugin
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
        result = _shell_step(read_install, repo_root=repo_root_path)
    steps.append({
        'name': 'install_read_plugin',
        'critical': True,
        'success': result['returncode'] == 0,
        'summary': _summarize_shell_step_result(result, plugin_id=plugin_id),
    })
    if result['returncode'] != 0:
        return _critical_failure_payload(
            step_results=steps,
            failed_step='install_read_plugin',
            message='OpenClaw Read plugin 安装失败。',
        )

    # 4. Initialize sessions watch (non-critical at product-install level)
    session_args = ['--all']
    if not dry_run:
        session_args.append('--write')
    result = _python_step(sessions_watch_initialize, args=session_args, repo_root=repo_root_path, dry_run=False)
    session_success = result['returncode'] == 0
    steps.append({
        'name': 'initialize_sessions_watch',
        'critical': False,
        'success': session_success,
        'summary': _summarize_python_step_result(result),
    })
    if not session_success:
        warnings.append(
            'Sessions Watch 初始化失败。安装主流程已继续，但产品当前仍不可正常使用；请在后续修复并重试该步骤。'
        )

    session_parsed = result.get('parsed') if isinstance(result, dict) else None
    session_labels = []
    if isinstance(session_parsed, dict) and isinstance(session_parsed.get('agents'), list):
        session_labels = [str(item.get('label', '') or '').strip() for item in session_parsed['agents'] if isinstance(item, dict) and str(item.get('label', '') or '').strip()]
    status = 'success_with_warnings' if warnings else 'success'
    return {
        'success': True,
        'status': status,
        'dry_run': dry_run,
        'warnings': warnings,
        'plugin_id': plugin_id,
        'resolved_artifacts': {
            'plugin_id': plugin_id,
            'plugin_dir': str(plugin_dir),
            'memory_worker_workspace_path': str(memory_worker_workspace),
            'example_openclaw_json_path': str(example_openclaw_json),
            'sessions_watch': {
                'daily_init_cron_marker': str(cfg.openclaw_config['maintenance']['daily_init_cron_marker']),
                'labels': session_labels,
            },
        },
        'steps': steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='OpenClaw installation orchestrator')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--dry-run', action='store_true', help='只执行可支持 dry-run 的子步骤；shell 安装步骤仅做计划展示')
    args = parser.parse_args()

    result = run_install(repo_root=args.repo_root, dry_run=args.dry_run)
    if result.get('success', False):
        output_success(result)
        return

    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(1)


if __name__ == '__main__':
    main()
