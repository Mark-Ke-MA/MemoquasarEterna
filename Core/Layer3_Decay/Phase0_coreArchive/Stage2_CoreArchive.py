#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_stage2(*, repo_root: str | Path | None = None, week: str | None = None, agent: str | None = None, dry_run: bool = False, run_mode: str = 'manual', run_name: str | None = None) -> dict[str, Any]:
    repo = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    entry_path = repo / 'Core' / 'Layer2_Preserve' / 'ENTRY_LAYER2_archive.py'

    command = [sys.executable, str(entry_path)]
    if week is not None:
        command += ['--week', str(week)]
    if agent is not None:
        command += ['--agent', str(agent)]
    command += ['--overwrite']
    command += ['--run-mode', str(run_mode)]
    if run_name is not None:
        command += ['--run-name', str(run_name)]
    if dry_run:
        command += ['--dry-run']
    if repo_root is not None:
        command += ['--repo-root', str(repo)]

    proc = subprocess.run(command, capture_output=True, text=True, cwd=str(repo))
    stdout = (proc.stdout or '').strip()
    if not stdout:
        return {
            'success': False,
            'failed_stage': 'Stage2',
            'note': 'Layer2 统一入口未返回结果。',
            'stdout': '',
            'stderr': (proc.stderr or '').strip(),
        }

    try:
        result = json.loads(stdout)
    except Exception as exc:
        return {
            'success': False,
            'failed_stage': 'Stage2',
            'note': f'Layer2 统一入口返回了不可解析输出: {exc}',
            'stdout': stdout,
            'stderr': (proc.stderr or '').strip(),
        }

    if not isinstance(result, dict):
        return {
            'success': False,
            'failed_stage': 'Stage2',
            'note': 'Layer2 统一入口返回的不是 JSON 对象。',
            'stdout': stdout,
            'stderr': (proc.stderr or '').strip(),
        }
    return result


__all__ = ['run_stage2']
