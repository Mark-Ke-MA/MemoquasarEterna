#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer3_Decay.Phase0_coreArchive.Stage1_Maintenance import run_stage1
from Core.Layer3_Decay.Phase0_coreArchive.Stage2_CoreArchive import run_stage2
from Core.shared_funcs import output_success


PHASE0_ALLOWED_STAGES = ('Stage1', 'Stage2')


def run_phase0(*, repo_root: str | Path | None = None, week: str | None = None, source_week: str | None = None, agent: str | None = None, stage: str | None = None, dry_run: bool = False, run_mode: str = 'manual', run_name: str | None = None) -> dict:
    _ = source_week
    if stage is not None and stage not in PHASE0_ALLOWED_STAGES:
        raise ValueError(f'未知 Stage: {stage}')

    if stage == 'Stage1':
        result = run_stage1(repo_root=repo_root)
        return {
            'success': bool(result.get('success', False)),
            'phase': 'Phase0_coreArchive',
            'failed_stage': result.get('failed_stage'),
            'note': result.get('note', 'Phase0 Stage1 执行完成。'),
            'result': result,
        }

    if stage == 'Stage2':
        result = run_stage2(repo_root=repo_root, week=week, agent=agent, dry_run=dry_run, run_mode=run_mode, run_name=run_name)
        return {
            'success': bool(result.get('success', False)),
            'phase': 'Phase0_coreArchive',
            'failed_stage': result.get('failed_stage'),
            'note': result.get('note', 'Phase0 Stage2 执行完成。'),
            'result': result,
        }

    stage1_result = run_stage1(repo_root=repo_root)
    if not bool(stage1_result.get('success', False)):
        return {
            'success': False,
            'phase': 'Phase0_coreArchive',
            'failed_stage': 'Stage1',
            'note': stage1_result.get('note', 'Phase0 Stage1 执行失败。'),
            'result': stage1_result,
        }

    stage2_result = run_stage2(repo_root=repo_root, week=week, agent=agent, dry_run=dry_run, run_mode=run_mode, run_name=run_name)
    return {
        'success': bool(stage2_result.get('success', False)),
        'phase': 'Phase0_coreArchive',
        'failed_stage': None if bool(stage2_result.get('success', False)) else 'Stage2',
        'note': stage2_result.get('note', 'Phase0 执行完成。'),
        'result': stage2_result,
    }


def parse_args():
    parser = argparse.ArgumentParser(description='Layer3_Decay Phase0_coreArchive 入口')
    parser.add_argument('--week', default=None)
    parser.add_argument('--source-week', dest='source_week', default=None)
    parser.add_argument('--agent', default=None)
    parser.add_argument('--Stage', '--stage', dest='stage', default=None)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--run-mode', dest='run_mode', default='manual', choices=('auto', 'manual'))
    parser.add_argument('--run-name', dest='run_name', default=None)
    parser.add_argument('--repo-root', default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    output_success(run_phase0(repo_root=args.repo_root, week=args.week, source_week=args.source_week, agent=args.agent, stage=args.stage, dry_run=args.dry_run, run_mode=args.run_mode, run_name=args.run_name))


if __name__ == '__main__':
    main()
