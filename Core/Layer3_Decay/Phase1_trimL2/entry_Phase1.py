#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer3_Decay.Phase1_trimL2.Stage1_Plan import run_stage1
from Core.Layer3_Decay.Phase1_trimL2.Stage2_Trim import run_stage2
from Core.Layer3_Decay.Phase1_trimL2.Stage3_Finalize import run_stage3
from Core.Layer3_Decay.shared import LoadConfig, previous_iso_week_id
from Core.shared_funcs import output_success


def resolve_target_week(repo_root: str | Path | None, week: str | None) -> str:
    if week and str(week).strip():
        return str(week).strip()
    cfg = LoadConfig(repo_root)
    timezone_name = str(cfg.overall_config.get('timezone', 'Europe/London'))
    return previous_iso_week_id(timezone_name=timezone_name)


def run_phase1(*, repo_root: str | Path | None = None, week: str | None = None, source_week: str | None = None, agent: str | None = None, stage: str | None = None, dry_run: bool = False) -> dict:
    if week and source_week:
        raise ValueError('--week 与 --source-week 不能同时使用')
    target_week = None if source_week else resolve_target_week(repo_root, week)

    if stage == 'Stage1':
        stage1_result = run_stage1(repo_root=repo_root, week=target_week, source_week=source_week, agent=agent)
        return {
            'success': True,
            'phase': 'Phase1_trimL2',
            'target_week': target_week,
            'boundary_date': stage1_result.get('boundary_date'),
            'planned_count': stage1_result.get('planned_count', 0),
            'skipped_count': stage1_result.get('skipped_count', 0),
            'note': 'Phase1 Stage1 完成。',
        }

    stage1_result = run_stage1(repo_root=repo_root, week=target_week, source_week=source_week, agent=agent)

    if stage == 'Stage2':
        stage2_result = run_stage2(stage1_result=stage1_result, dry_run=dry_run)
        return {
            'success': stage2_result.get('failed_count', 0) == 0,
            'phase': 'Phase1_trimL2',
            'target_week': target_week,
            'boundary_date': stage1_result.get('boundary_date'),
            'planned_count': stage1_result.get('planned_count', 0),
            'skipped_count': stage1_result.get('skipped_count', 0),
            'trimmed_count': stage2_result.get('trimmed_count', 0),
            'cleared_count': stage2_result.get('cleared_count', 0),
            'failed_count': stage2_result.get('failed_count', 0),
            'dry_run': dry_run,
            'note': 'Phase1 Stage2 完成。',
        }

    stage2_result = run_stage2(stage1_result=stage1_result, dry_run=dry_run)
    return run_stage3(stage1_result=stage1_result, stage2_result=stage2_result, dry_run=dry_run)


def parse_args():
    parser = argparse.ArgumentParser(description='Layer3_Decay Phase1_trimL2 入口')
    parser.add_argument('--week', default=None, help='目标 ISO week，例如 2026-W16；默认处理上一 ISO week')
    parser.add_argument('--source-week', dest='source_week', default=None, help='直接指定 source week；与 --week 二选一')
    parser.add_argument('--agent', default=None, help='只处理指定 agent；支持逗号分隔多个 agent')
    parser.add_argument('--Stage', '--stage', dest='stage', default=None, choices=('Stage1', 'Stage2', 'Stage3'))
    parser.add_argument('--dry-run', action='store_true', help='只计算，不写入')
    parser.add_argument('--repo-root', default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    result = run_phase1(repo_root=args.repo_root, week=args.week, source_week=args.source_week, agent=args.agent, stage=args.stage, dry_run=args.dry_run)
    output_success(result)


if __name__ == '__main__':
    main()
