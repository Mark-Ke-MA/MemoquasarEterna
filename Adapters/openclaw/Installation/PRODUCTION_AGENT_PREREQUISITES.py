#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from Adapters.openclaw.Installation.shared import (
    cfg,
    check_and_maybe_fill_registry_maintenance,
    check_and_maybe_patch_openclaw_root,
    load_openclaw_config_dict,
    production_agent_ids,
    repo_root_from_here,
    require_openclaw_harness,
    write_openclaw_config_dict,
)
from Adapters.openclaw.openclaw_shared_funcs import output_success


def run_prerequisites(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else repo_root_from_here()
    config = cfg(repo_root_path)
    preflight = require_openclaw_harness(config, action='production agent prerequisites')
    if preflight is not None:
        return preflight

    config_data = load_openclaw_config_dict()
    warnings: list[str] = []
    try:
        agent_ids = production_agent_ids(config)
        config_data, root_check, root_warnings = check_and_maybe_patch_openclaw_root(config_data, dry_run=dry_run)
        warnings.extend(root_warnings)
        config_data, registry_check, registry_warnings = check_and_maybe_fill_registry_maintenance(
            config_data,
            repo_root=repo_root_path,
            agent_ids=agent_ids,
            dry_run=dry_run,
        )
        warnings.extend(registry_warnings)
    except Exception as exc:
        return {
            'success': False,
            'status': 'failed',
            'message': str(exc),
        }

    config_updated = bool(root_check.get('config_updated') or registry_check.get('config_updated'))
    if config_updated:
        write_openclaw_config_dict(config_data, dry_run=dry_run)

    return {
        'success': True,
        'status': 'success_with_warnings' if warnings else 'success',
        'dry_run': dry_run,
        'config_updated': config_updated,
        'checks': {
            'openclaw_root': root_check,
            'sessions_registry_maintenance': registry_check,
        },
        'warnings': warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='OpenClaw production agent prerequisites check.')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--dry-run', action='store_true', help='只执行检查与交互预览，不实际写回 OpenclawConfig.json')
    args = parser.parse_args()
    result = run_prerequisites(repo_root=args.repo_root, dry_run=args.dry_run)
    if result.get('success', False):
        output_success(result)
        return
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(1)


if __name__ == '__main__':
    main()
