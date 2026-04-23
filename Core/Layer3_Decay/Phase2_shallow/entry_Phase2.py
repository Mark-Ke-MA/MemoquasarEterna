#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer3_Decay.Phase2_shallow.Stage1_Plan import run_stage1
from Core.Layer3_Decay.Phase2_shallow.Stage2_ReduceDispatch import run_stage2
from Core.Layer3_Decay.Phase2_shallow.Stage3_Finalize import run_stage3
from Core.Layer3_Decay.Phase2_shallow.Stage4_IndexUpdate import run_stage4
from Core.Layer3_Decay.Phase2_shallow.Stage5_EmbedUpdate import run_stage5
from Core.Layer3_Decay.Phase2_shallow.Stage6_Cleanup import run_stage6
from Core.Layer3_Decay.shared import LoadConfig, previous_iso_week_id
from Core.shared_funcs import output_success


PHASE2_ALLOWED_STAGES = ('Stage1', 'Stage2', 'Stage3', 'Stage4', 'Stage5', 'Stage6')


def resolve_target_week(repo_root: str | Path | None, week: str | None) -> str:
    if week and str(week).strip():
        return str(week).strip()
    cfg = LoadConfig(repo_root)
    timezone_name = str(cfg.overall_config.get('timezone', 'Europe/London'))
    return previous_iso_week_id(timezone_name=timezone_name)


def run_phase2(*, repo_root: str | Path | None = None, week: str | None = None, source_week: str | None = None, agent: str | None = None, stage: str | None = None, dry_run: bool = False, apply_cleanup: bool = False) -> dict:
    _ = dry_run
    if week and source_week:
        raise ValueError('--week 与 --source-week 不能同时使用')
    target_week = None if source_week else resolve_target_week(repo_root, week)

    if stage is not None and stage not in PHASE2_ALLOWED_STAGES:
        raise ValueError(f'未知 Stage: {stage}')

    if stage is None:
        stage1_result = run_stage1(repo_root=repo_root, week=target_week, source_week=source_week, agent=agent)
        stage2_result = run_stage2(repo_root=repo_root)
        if not bool(stage2_result.get('success', False)):
            return {
                'success': False,
                'phase': 'Phase2_shallow',
                'target_week': target_week,
                'source_week': stage1_result.get('source_week'),
                'window_date_start': stage1_result.get('window_date_start'),
                'window_date_end': stage1_result.get('window_date_end'),
                'failed_stage': 'Stage2',
                'failed_agents': stage2_result.get('failed_agents', []),
                'succeed_agents': stage2_result.get('succeed_agents', []),
                'planned_agents': stage2_result.get('planned_agents', []),
                'note': stage2_result.get('note', 'Phase2 Stage2 执行结束，但存在失败 agent。'),
            }

        stage3_result = run_stage3(repo_root=repo_root)
        if not bool(stage3_result.get('success', False)):
            return {
                'success': False,
                'phase': 'Phase2_shallow',
                'target_week': target_week,
                'source_week': stage1_result.get('source_week'),
                'window_date_start': stage1_result.get('window_date_start'),
                'window_date_end': stage1_result.get('window_date_end'),
                'failed_stage': 'Stage3',
                'failed_agents': stage3_result.get('failed_agents', []),
                'succeed_agents': stage3_result.get('succeed_agents', []),
                'no_l1_agents': stage3_result.get('no_l1_agents', []),
                'note': stage3_result.get('note', 'Phase2 Stage3 执行结束，但存在失败 agent。'),
            }

        stage4_result = run_stage4(repo_root=repo_root)
        if not bool(stage4_result.get('success', False)):
            return {
                'success': False,
                'phase': 'Phase2_shallow',
                'target_week': target_week,
                'source_week': stage1_result.get('source_week'),
                'window_date_start': stage1_result.get('window_date_start'),
                'window_date_end': stage1_result.get('window_date_end'),
                'failed_stage': 'Stage4',
                'failed_agents': stage4_result.get('failed_agents', []),
                'succeed_agents': stage4_result.get('succeed_agents', []),
                'note': stage4_result.get('note', 'Phase2 Stage4 执行结束，但存在失败 agent。'),
            }

        stage5_result = run_stage5(repo_root=repo_root)
        if not bool(stage5_result.get('success', False)):
            return {
                'success': False,
                'phase': 'Phase2_shallow',
                'target_week': target_week,
                'source_week': stage1_result.get('source_week'),
                'window_date_start': stage1_result.get('window_date_start'),
                'window_date_end': stage1_result.get('window_date_end'),
                'failed_stage': 'Stage5',
                'failed_agents': stage5_result.get('failed_agents', []),
                'succeed_agents': stage5_result.get('succeed_agents', []),
                'skipped_agents': stage5_result.get('skipped_agents', []),
                'note': stage5_result.get('note', 'Phase2 Stage5 执行结束，但存在失败 agent。'),
            }

        stage6_result = run_stage6(repo_root=repo_root, apply_cleanup=apply_cleanup)
        return {
            'success': bool(stage6_result.get('success', False)),
            'phase': 'Phase2_shallow',
            'target_week': target_week,
            'source_week': stage1_result.get('source_week'),
            'window_date_start': stage1_result.get('window_date_start'),
            'window_date_end': stage1_result.get('window_date_end'),
            'failed_stage': None if bool(stage6_result.get('success', False)) else 'Stage6',
            'failed_agents': stage6_result.get('failed_agents', []),
            'succeed_agents': stage6_result.get('succeed_agents', []),
            'apply_cleanup': bool(stage6_result.get('apply_cleanup', False)),
            'note': stage6_result.get('note', 'Phase2 Stage6 执行完成。'),
        }

    if stage == 'Stage1':
        stage1_result = run_stage1(repo_root=repo_root, week=target_week, source_week=source_week, agent=agent)
        return {
            'success': True,
            'phase': 'Phase2_shallow',
            'target_week': target_week,
            'source_week': stage1_result.get('source_week'),
            'window_date_start': stage1_result.get('window_date_start'),
            'window_date_end': stage1_result.get('window_date_end'),
            'plan_path': stage1_result.get('plan_path'),
            'planned_count': stage1_result.get('planned_count', 0),
            'note': 'Phase2 Stage1 完成。',
        }

    if stage == 'Stage2':
        stage2_result = run_stage2(repo_root=repo_root)
        return {
            'success': bool(stage2_result.get('success', False)),
            'phase': 'Phase2_shallow',
            'target_week': target_week,
            'failed_agents': stage2_result.get('failed_agents', []),
            'succeed_agents': stage2_result.get('succeed_agents', []),
            'planned_agents': stage2_result.get('planned_agents', []),
            'note': stage2_result.get('note', 'Phase2 Stage2 执行完成。'),
        }

    if stage == 'Stage3':
        stage3_result = run_stage3(repo_root=repo_root)
        return {
            'success': bool(stage3_result.get('success', False)),
            'phase': 'Phase2_shallow',
            'target_week': target_week,
            'failed_agents': stage3_result.get('failed_agents', []),
            'succeed_agents': stage3_result.get('succeed_agents', []),
            'no_l1_agents': stage3_result.get('no_l1_agents', []),
            'note': stage3_result.get('note', 'Phase2 Stage3 执行完成。'),
        }

    if stage == 'Stage4':
        stage4_result = run_stage4(repo_root=repo_root)
        return {
            'success': bool(stage4_result.get('success', False)),
            'phase': 'Phase2_shallow',
            'target_week': target_week,
            'failed_agents': stage4_result.get('failed_agents', []),
            'succeed_agents': stage4_result.get('succeed_agents', []),
            'note': stage4_result.get('note', 'Phase2 Stage4 执行完成。'),
        }

    if stage == 'Stage5':
        stage5_result = run_stage5(repo_root=repo_root)
        return {
            'success': bool(stage5_result.get('success', False)),
            'phase': 'Phase2_shallow',
            'target_week': target_week,
            'failed_agents': stage5_result.get('failed_agents', []),
            'succeed_agents': stage5_result.get('succeed_agents', []),
            'skipped_agents': stage5_result.get('skipped_agents', []),
            'note': stage5_result.get('note', 'Phase2 Stage5 执行完成。'),
        }

    if stage == 'Stage6':
        stage6_result = run_stage6(repo_root=repo_root, apply_cleanup=apply_cleanup)
        return {
            'success': bool(stage6_result.get('success', False)),
            'phase': 'Phase2_shallow',
            'target_week': target_week,
            'failed_agents': stage6_result.get('failed_agents', []),
            'succeed_agents': stage6_result.get('succeed_agents', []),
            'apply_cleanup': bool(stage6_result.get('apply_cleanup', False)),
            'note': stage6_result.get('note', 'Phase2 Stage6 执行完成。'),
        }

    return {
        'success': False,
        'phase': 'Phase2_shallow',
        'target_week': target_week,
        'note': f'{stage} 尚未实现；当前已接通 Stage1-Stage6。',
    }


def parse_args():
    parser = argparse.ArgumentParser(description='Layer3_Decay Phase2_shallow 入口')
    parser.add_argument('--week', default=None, help='目标 ISO week，例如 2026-W16；默认处理上一 ISO week')
    parser.add_argument('--source-week', dest='source_week', default=None, help='直接指定 source week；与 --week 二选一')
    parser.add_argument('--agent', default=None, help='只处理指定 agent；支持逗号分隔多个 agent')
    parser.add_argument('--Stage', '--stage', dest='stage', default=None)
    parser.add_argument('--dry-run', action='store_true', help='当前仅占位；Stage1 仍会写出 plan.json')
    parser.add_argument('--apply_cleanup', action='store_true', help='显式执行真正的 cleanup 删除；默认仅清 staging，不删业务文件')
    parser.add_argument('--repo-root', default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    result = run_phase2(repo_root=args.repo_root, week=args.week, source_week=args.source_week, agent=args.agent, stage=args.stage, dry_run=args.dry_run, apply_cleanup=args.apply_cleanup)
    output_success(result)


if __name__ == '__main__':
    main()
