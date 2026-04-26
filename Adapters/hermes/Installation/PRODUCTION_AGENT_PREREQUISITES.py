#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from Adapters.hermes.Installation.shared import (
    load_config,
    output_success,
    production_agent_ids,
    profile_dir,
    recall_entry_path,
    repo_root_from_here,
    skill_template_path,
)


def run_prerequisites(*, repo_root: str | Path | None = None, dry_run: bool = False, agent_ids: list[str] | None = None) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else repo_root_from_here()
    try:
        config = load_config(repo_root_path)
        resolved_agent_ids = production_agent_ids(config, agent_ids=agent_ids)
    except Exception as exc:
        return {'success': False, 'status': 'failed', 'message': str(exc)}

    checks: dict[str, Any] = {
        'recall_entry': {
            'path': str(recall_entry_path(repo_root_path)),
            'exists': recall_entry_path(repo_root_path).exists(),
        },
        'skill_template': {
            'path': str(skill_template_path(repo_root_path)),
            'exists': skill_template_path(repo_root_path).exists(),
        },
        'profiles': [],
    }
    errors: list[str] = []
    if not checks['recall_entry']['exists']:
        errors.append(f'Hermes Layer4 recall entry 不存在: {checks["recall_entry"]["path"]}')
    if not checks['skill_template']['exists']:
        errors.append(f'Hermes recall skill template 不存在: {checks["skill_template"]["path"]}')

    for agent_id in resolved_agent_ids:
        path = profile_dir(config, agent_id)
        item = {
            'agent_id': agent_id,
            'profile_dir': str(path),
            'profile_exists': path.exists(),
            'skills_dir': str(path / 'skills'),
            'skills_dir_exists': (path / 'skills').exists(),
        }
        checks['profiles'].append(item)
        if not item['profile_exists']:
            errors.append(f'Hermes profile 不存在: {path}')

    return {
        'success': not errors,
        'status': 'success' if not errors else 'failed',
        'dry_run': dry_run,
        'agent_ids': resolved_agent_ids,
        'checks': checks,
        'errors': errors,
        'message': '; '.join(errors) if errors else '',
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Hermes production agent prerequisites.')
    parser.add_argument('--repo-root', default=None)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    result = run_prerequisites(repo_root=args.repo_root, dry_run=args.dry_run)
    if result.get('success'):
        output_success(result)
        return
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(1)


if __name__ == '__main__':
    main()
