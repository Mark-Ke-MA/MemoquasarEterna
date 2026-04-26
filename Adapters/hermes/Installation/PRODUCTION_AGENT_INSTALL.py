#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from Adapters.hermes.Installation.shared import (
    installed_skill_dir,
    load_config,
    output_success,
    production_agent_ids,
    render_skill,
    repo_root_from_here,
    write_text,
)


def run_install(*, repo_root: str | Path | None = None, dry_run: bool = False, agent_ids: list[str] | None = None) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else repo_root_from_here()
    try:
        config = load_config(repo_root_path)
        resolved_agent_ids = production_agent_ids(config, agent_ids=agent_ids)
    except Exception as exc:
        return {'success': False, 'status': 'failed', 'message': str(exc)}

    steps: list[dict[str, Any]] = []
    errors: list[str] = []
    for agent_id in resolved_agent_ids:
        try:
            skill_dir = installed_skill_dir(config, agent_id)
            skill_path = skill_dir / 'SKILL.md'
            result = write_text(skill_path, render_skill(repo_root_path, agent_id), dry_run=dry_run)
            steps.append({
                'name': 'install_recall_skill',
                'agent_id': agent_id,
                'success': True,
                'summary': result,
            })
        except Exception as exc:  # noqa: BLE001
            errors.append(f'{agent_id}: {exc}')
            steps.append({
                'name': 'install_recall_skill',
                'agent_id': agent_id,
                'success': False,
                'summary': {'error': str(exc)},
            })

    return {
        'success': not errors,
        'status': 'success' if not errors else 'failed',
        'dry_run': dry_run,
        'agent_ids': resolved_agent_ids,
        'steps': steps,
        'errors': errors,
        'message': '; '.join(errors) if errors else '',
        'resolved_artifacts': {
            'skills': [
                {
                    'agent_id': agent_id,
                    'skill_dir': str(installed_skill_dir(config, agent_id)),
                }
                for agent_id in resolved_agent_ids
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Hermes production agent install.')
    parser.add_argument('--repo-root', default=None)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    result = run_install(repo_root=args.repo_root, dry_run=args.dry_run)
    if result.get('success'):
        output_success(result)
        return
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(1)


if __name__ == '__main__':
    main()
