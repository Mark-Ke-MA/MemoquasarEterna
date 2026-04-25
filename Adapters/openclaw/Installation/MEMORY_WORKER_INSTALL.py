#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from Adapters.openclaw.Installation.shared import (
    cfg,
    critical_failure_payload,
    memory_worker_workspace_path,
    repo_root_from_here,
    require_openclaw_harness,
)
from Adapters.openclaw.Installation.templates.memory_worker.install import install_memory_worker_workspace
from Adapters.openclaw.Installation.templates.openclaw_json.render import DEFAULT_OUTPUT_PATH, update_example_openclaw_json
from Adapters.openclaw.openclaw_shared_funcs import output_success


def run_install(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else repo_root_from_here()
    config = cfg(repo_root_path)
    preflight = require_openclaw_harness(config, action='memory worker install')
    if preflight is not None:
        return {**preflight, 'steps': []}

    steps: list[dict[str, Any]] = []

    try:
        worker_result = install_memory_worker_workspace(repo_root=repo_root_path, dry_run=dry_run)
    except Exception as exc:
        worker_result = {'success': False, 'status': 'failed', 'message': str(exc)}
    steps.append({
        'name': 'install_memory_worker_workspace',
        'critical': True,
        'success': bool(worker_result.get('success', False)),
        'summary': {
            'mode': worker_result.get('mode'),
            'target_root': worker_result.get('target_root'),
            'worker_agent_id': worker_result.get('worker_agent_id'),
        },
    })
    if not bool(worker_result.get('success', False)):
        return critical_failure_payload(
            step_results=steps,
            failed_step='install_memory_worker_workspace',
            message='memory worker workspace 初始化失败。',
        )

    try:
        render_result = update_example_openclaw_json(repo_root=repo_root_path, scope='memory_worker', action='upsert', dry_run=dry_run)
    except Exception as exc:
        render_result = {'success': False, 'status': 'failed', 'message': str(exc)}
    steps.append({
        'name': 'render_memory_worker_openclaw_json_example',
        'critical': True,
        'success': bool(render_result.get('success', False)),
        'summary': {
            'output_path': render_result.get('output_path'),
            'memory_worker_agentId': render_result.get('memory_worker_agentId'),
        },
    })
    if not bool(render_result.get('success', False)):
        return critical_failure_payload(
            step_results=steps,
            failed_step='render_memory_worker_openclaw_json_example',
            message='渲染 memory worker OpenClaw merge 示例失败。',
        )

    return {
        'success': True,
        'status': 'success',
        'dry_run': dry_run,
        'warnings': [],
        'resolved_artifacts': {
            'memory_worker_workspace_path': str(memory_worker_workspace_path(config)),
            'example_openclaw_json_path': str(Path(render_result.get('output_path') or DEFAULT_OUTPUT_PATH).expanduser()),
        },
        'steps': steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='OpenClaw memory worker install.')
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
