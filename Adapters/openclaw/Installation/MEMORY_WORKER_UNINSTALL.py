#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from Adapters.openclaw.Installation.shared import (
    cfg,
    memory_worker_workspace_path,
    remove_tree,
    repo_root_from_here,
    require_openclaw_harness,
)
from Adapters.openclaw.Installation.templates.openclaw_json.render import DEFAULT_OUTPUT_PATH, update_example_openclaw_json
from Adapters.openclaw.openclaw_shared_funcs import output_success


def _snapshot_resolved(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    return (snapshot.get('harness_memory_worker_install') or {}).get('resolved_artifacts') or {}


def _snapshot_has_openclaw_production_agent(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    overall_cfg = ((snapshot.get('config_snapshot') or {}).get('overall_config') or {})
    production_agents = overall_cfg.get('production_agents')
    if isinstance(production_agents, list):
        return any(
            isinstance(item, dict)
            and str(item.get('agentId', '') or '').strip()
            and str(item.get('harness', '') or '').strip() == 'openclaw'
            for item in production_agents
        )
    legacy_agents = overall_cfg.get('agentId_list')
    legacy_harness = str(((snapshot.get('context') or {}).get('harness') or overall_cfg.get('harness') or '')).strip()
    return legacy_harness == 'openclaw' and isinstance(legacy_agents, list) and any(str(item).strip() for item in legacy_agents)


def run_uninstall(*, repo_root: str | Path | None = None, dry_run: bool = False, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else repo_root_from_here()
    config = cfg(repo_root_path)
    preflight = require_openclaw_harness(config, action='memory worker uninstall')
    if preflight is not None:
        return {**preflight, 'steps': []}

    snapshot_artifacts = _snapshot_resolved(snapshot)
    workspace = Path(str(snapshot_artifacts.get('memory_worker_workspace_path') or memory_worker_workspace_path(config))).expanduser()
    steps: list[dict[str, Any]] = []

    result = remove_tree(workspace, dry_run=dry_run)
    steps.append({
        'name': 'remove_memory_worker_workspace',
        'critical': False,
        'success': True,
        'summary': result,
    })

    try:
        render_result = update_example_openclaw_json(repo_root=repo_root_path, scope='memory_worker', action='remove', dry_run=dry_run)
    except Exception as exc:
        render_result = {'success': False, 'status': 'failed', 'message': str(exc)}
    steps.append({
        'name': 'remove_memory_worker_openclaw_json_example',
        'critical': False,
        'success': bool(render_result.get('success', False)),
        'summary': {
            'output_path': render_result.get('output_path'),
            'memory_worker_agentId': render_result.get('memory_worker_agentId'),
        },
    })

    warnings = []
    if not bool(render_result.get('success', False)):
        warnings.append('memory worker OpenClaw merge 示例清理失败；请后续手动检查。')

    if not _snapshot_has_openclaw_production_agent(snapshot):
        example_path = Path(str(render_result.get('output_path') or snapshot_artifacts.get('example_openclaw_json_path') or DEFAULT_OUTPUT_PATH)).expanduser()
        result = remove_tree(example_path, dry_run=dry_run)
        steps.append({
            'name': 'remove_openclaw_json_example_if_no_openclaw_production_agent',
            'critical': False,
            'success': True,
            'summary': result,
        })

    return {
        'success': True,
        'status': 'success_with_warnings' if warnings else 'success',
        'dry_run': dry_run,
        'warnings': warnings,
        'steps': steps,
        'snapshot_used': bool(snapshot_artifacts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='OpenClaw memory worker uninstall.')
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
