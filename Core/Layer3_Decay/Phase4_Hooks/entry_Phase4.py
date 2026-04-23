#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer3_Decay.Phase4_Hooks.Stage1_Hooks import run_stage1
from Core.shared_funcs import output_success


PHASE4_ALLOWED_STAGES = ('Stage1',)


def run_phase4(*, repo_root: str | Path | None = None, week: str | None = None, source_week: str | None = None, agent: str | None = None, stage: str | None = None, dry_run: bool = False, apply_cleanup: bool = False) -> dict:
    if stage is not None and stage not in PHASE4_ALLOWED_STAGES:
        raise ValueError(f'未知 Stage: {stage}')
    effective_dry_run = bool(dry_run or (not apply_cleanup))
    result = run_stage1(repo_root=repo_root, week=week, source_week=source_week, agent=agent, dry_run=effective_dry_run)
    return {
        'success': bool(result.get('success', False)),
        'phase': 'Phase4_Hooks',
        'failed_stage': result.get('failed_stage'),
        'note': result.get('note', 'Phase4 执行完成。'),
        'results': result.get('results', []),
        'dry_run': effective_dry_run,
    }


def parse_args():
    parser = argparse.ArgumentParser(description='Layer3_Decay Phase4_Hooks 入口')
    parser.add_argument('--week', default=None)
    parser.add_argument('--source-week', dest='source_week', default=None)
    parser.add_argument('--agent', default=None)
    parser.add_argument('--Stage', '--stage', dest='stage', default=None)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--apply_cleanup', action='store_true')
    parser.add_argument('--repo-root', default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    output_success(run_phase4(repo_root=args.repo_root, week=args.week, source_week=args.source_week, agent=args.agent, stage=args.stage, dry_run=args.dry_run, apply_cleanup=args.apply_cleanup))


if __name__ == '__main__':
    main()
