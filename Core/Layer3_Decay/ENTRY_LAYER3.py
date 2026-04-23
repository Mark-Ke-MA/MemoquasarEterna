#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer3_Decay.Phase0_coreArchive.entry_Phase0 import run_phase0
from Core.Layer3_Decay.Phase1_trimL2.entry_Phase1 import run_phase1
from Core.Layer3_Decay.Phase2_shallow.entry_Phase2 import run_phase2
from Core.Layer3_Decay.Phase3_deep.entry_Phase3 import run_phase3
from Core.Layer3_Decay.Phase4_Hooks.entry_Phase4 import run_phase4
from Core.Layer3_Decay.FailedLog import write_failed_log
from Core.shared_funcs import output_success


LAYER3_ALLOWED_PHASES = ('Phase0', 'Phase1', 'Phase2', 'Phase3', 'Phase4')


def parse_args():
    parser = argparse.ArgumentParser(description='Layer3_Decay 总入口')
    parser.add_argument('--week', default=None, help='目标 ISO week，例如 2026-W16；默认处理上一 ISO week')
    parser.add_argument('--source-week', dest='source_week', default=None, help='直接指定 source week；与 --week 二选一')
    parser.add_argument('--agent', default=None, help='只处理指定 agent；支持逗号分隔多个 agent')
    parser.add_argument('--Phase', '--phase', dest='phase', default=None, choices=LAYER3_ALLOWED_PHASES)
    parser.add_argument('--Stage', '--stage', dest='stage', default=None)
    parser.add_argument('--dry-run', action='store_true', help='只计算，不写入')
    parser.add_argument('--run-mode', dest='run_mode', default='manual', choices=('auto', 'manual'))
    parser.add_argument('--run-name', dest='run_name', default=None)
    parser.add_argument('--apply_cleanup', action='store_true', help='显式执行真正的 cleanup 删除；默认仅清 staging，不删业务文件')
    parser.add_argument('--repo-root', default=None)
    return parser.parse_args()


def _run_single_phase(phase: str, *, repo_root: str | Path | None, week: str | None, source_week: str | None, agent: str | None, stage: str | None, dry_run: bool, run_mode: str, run_name: str | None, apply_cleanup: bool):
    if phase == 'Phase0':
        return run_phase0(repo_root=repo_root, week=week, source_week=source_week, agent=agent, stage=stage, dry_run=dry_run, run_mode=run_mode, run_name=run_name)
    if phase == 'Phase1':
        return run_phase1(repo_root=repo_root, week=week, source_week=source_week, agent=agent, stage=stage, dry_run=dry_run)
    if phase == 'Phase2':
        return run_phase2(repo_root=repo_root, week=week, source_week=source_week, agent=agent, stage=stage, dry_run=dry_run, apply_cleanup=apply_cleanup)
    if phase == 'Phase3':
        return run_phase3(repo_root=repo_root, week=week, source_week=source_week, agent=agent, stage=stage, dry_run=dry_run, apply_cleanup=apply_cleanup)
    if phase == 'Phase4':
        return run_phase4(repo_root=repo_root, week=week, source_week=source_week, agent=agent, stage=stage, dry_run=dry_run, apply_cleanup=apply_cleanup)
    return {'success': False, 'phase': phase, 'note': f'{phase} 尚未实现。'}


def main():
    args = parse_args()

    if args.phase is None and args.stage is not None:
        output_success({'success': False, 'phase': None, 'note': '顶层不消费 Stage。传 --Stage 时必须同时指定 --Phase。'})
        return

    if args.phase is not None:
        result = _run_single_phase(args.phase, repo_root=args.repo_root, week=args.week, source_week=args.source_week, agent=args.agent, stage=args.stage, dry_run=args.dry_run, run_mode=args.run_mode, run_name=args.run_name, apply_cleanup=args.apply_cleanup)
        fail_log_needed = False
        fail_log_path = None
        if not args.dry_run and not bool(result.get('success', False)):
            fail_log_path = write_failed_log(
                failed_phase=args.phase,
                result=result,
                week=args.week,
                source_week=args.source_week,
                run_mode=args.run_mode,
                run_name=args.run_name,
                apply_cleanup=args.apply_cleanup,
                repo_root=args.repo_root,
            )
            fail_log_needed = True
        output_success({
            'success': bool(result.get('success', False)),
            'phase': args.phase,
            'failed_phase': None if bool(result.get('success', False)) else args.phase,
            'note': result.get('note', f'{args.phase} 执行完成。' if bool(result.get('success', False)) else f'{args.phase} 执行失败。'),
            'fail_log_needed': fail_log_needed,
            'fail_log_path': fail_log_path,
        })
        return

    ordered_phases = ('Phase0', 'Phase1', 'Phase2', 'Phase3', 'Phase4')
    completed_phases: list[str] = []
    for phase in ordered_phases:
        result = _run_single_phase(phase, repo_root=args.repo_root, week=args.week, source_week=args.source_week, agent=args.agent, stage=None, dry_run=args.dry_run, run_mode=args.run_mode, run_name=args.run_name, apply_cleanup=args.apply_cleanup)
        if not bool(result.get('success', False)):
            fail_log_needed = False
            fail_log_path = None
            if not args.dry_run:
                fail_log_path = write_failed_log(
                    failed_phase=phase,
                    result=result,
                    week=args.week,
                    source_week=args.source_week,
                    run_mode=args.run_mode,
                    run_name=args.run_name,
                    apply_cleanup=args.apply_cleanup,
                    repo_root=args.repo_root,
                )
                fail_log_needed = True
            output_success({
                'success': False,
                'failed_phase': phase,
                'completed_phases': completed_phases,
                'note': result.get('note', f'{phase} 执行失败。'),
                'fail_log_needed': fail_log_needed,
                'fail_log_path': fail_log_path,
            })
            return
        completed_phases.append(phase)

    output_success({
        'success': True,
        'note': 'Layer3 默认完整链路执行完成。',
        'completed_phases': completed_phases,
    })


if __name__ == '__main__':
    main()
