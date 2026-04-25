#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.shared_funcs import output_success
from Installation.Config import ConfigSpec, ensure_config_file


OPENCLAW_CONFIG_SPEC = ConfigSpec(
    key='openclaw',
    label='Adapters/openclaw/OpenclawConfig.json',
    config_relpath=Path('Adapters/openclaw/OpenclawConfig.json'),
    template_relpath=Path('Adapters/openclaw/OpenclawConfig-template.json'),
)


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[3]


def run_ensure_config(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else _repo_root_from_here()
    result = ensure_config_file(repo_root_path, OPENCLAW_CONFIG_SPEC, dry_run=dry_run)
    return {
        'success': bool(result.get('success', False)),
        'status': result.get('status', 'unknown'),
        'dry_run': dry_run,
        'configs': {
            OPENCLAW_CONFIG_SPEC.key: result,
        },
        'created_count': 1 if result.get('status') == 'created' else 0,
        'warnings': result.get('warnings', []) if isinstance(result.get('warnings'), list) else [],
        'errors': result.get('errors', []) if isinstance(result.get('errors'), list) else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Ensure OpenClaw adapter config exists and matches the template schema.')
    parser.add_argument('--repo-root', default=None, help='Repository root path (defaults to auto-detect).')
    parser.add_argument('--dry-run', action='store_true', help='Preview actions without creating config files.')
    args = parser.parse_args()
    output_success(run_ensure_config(repo_root=args.repo_root, dry_run=args.dry_run))


if __name__ == '__main__':
    main()
