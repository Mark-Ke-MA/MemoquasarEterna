#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from Adapters.hermes.Installation.shared import (
    hermes_config_path,
    hermes_config_template_path,
    output_success,
    repo_root_from_here,
    write_text,
)


def run_ensure_config(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else repo_root_from_here()
    config_path = hermes_config_path(repo_root_path)
    template_path = hermes_config_template_path(repo_root_path)
    if config_path.exists():
        return {
            'success': True,
            'status': 'exists',
            'dry_run': dry_run,
            'config_path': str(config_path),
            'changed': False,
        }
    if not template_path.exists():
        return {
            'success': False,
            'status': 'failed',
            'message': f'HermesConfig-template.json 不存在: {template_path}',
        }
    result = write_text(config_path, template_path.read_text(encoding='utf-8'), dry_run=dry_run)
    return {
        'success': True,
        'status': result['status'],
        'dry_run': dry_run,
        'config_path': str(config_path),
        'template_path': str(template_path),
        'changed': bool(result.get('changed')),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Hermes config bootstrap.')
    parser.add_argument('--repo-root', default=None)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    result = run_ensure_config(repo_root=args.repo_root, dry_run=args.dry_run)
    if result.get('success'):
        output_success(result)
        return
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(1)


if __name__ == '__main__':
    main()
