#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer2_Preserve.archive_Stage1_ListFiles import run_archive_stage1
from Core.Layer2_Preserve.archive_Stage2_Archive import run_archive_stage2
from Core.Layer2_Preserve.archive_Stage3_Finalize import run_archive_stage3
from Core.shared_funcs import output_success, output_failure
from Core.harness_connector import call_optional_connector, load_harness_connector


def parse_args():
    parser = argparse.ArgumentParser(description='Layer2_Preserve archive 入口')
    parser.add_argument('--week', default=None, help='目标 ISO week，例如 2026-W15；默认处理上一 ISO week')
    parser.add_argument('--agent', default=None, help='只处理指定 agent；支持逗号分隔多个 agent')
    parser.add_argument('--overwrite', action='store_true', help='允许覆盖已存在周包')
    parser.add_argument('--run-mode', dest='run_mode', default='manual', choices=('auto', 'manual'))
    parser.add_argument('--harness-only', action='store_true', help='仅执行 harness hook（不跑 core）')
    parser.add_argument('--core-only', action='store_true', help='仅执行 core archive（不跑 harness）')
    parser.add_argument('--dry-run', action='store_true', help='只计算，不写入（主要用于 harness 测试）')
    parser.add_argument('--run-name', default=None)
    parser.add_argument('--Stage', '--stage', dest='stage', default=None, choices=('Stage1', 'Stage2', 'Stage3'))
    parser.add_argument('--repo-root', default=None)
    return parser.parse_args()


def _run_harness_only(args):
    connector = load_harness_connector(repo_root=args.repo_root)
    result = call_optional_connector(
        connector,
        'harness_preserve',
        context={
            'repo_root': args.repo_root,
            'inputs': {
                'week': args.week,
                'agent': args.agent,
                'overwrite': args.overwrite,
                'run_mode': args.run_mode,
                'harness_only': True,
                'core_only': False,
                'dry_run': args.dry_run,
            },
        },
    )
    return {
        'success': True,
        'stage': 'Layer2_Archive_HarnessOnly',
        'run_mode': args.run_mode,
        'harness_only': True,
        'results': [] if result is None else [result],
    }


def main():
    args = parse_args()
    if args.harness_only and args.core_only:
        output_failure('--harness-only 与 --core-only 不能同时使用')
    if args.harness_only and args.stage not in (None, 'Stage1'):
        output_failure('--harness-only 当前只支持整链路入口或 --stage Stage1')

    if args.harness_only:
        result = _run_harness_only(args)
    elif args.stage == 'Stage1':
        result = run_archive_stage1(repo_root=args.repo_root, week=args.week, agent=args.agent, overwrite=args.overwrite, run_mode=args.run_mode, harness_only=False, core_only=args.core_only, dry_run=args.dry_run)
    elif args.stage == 'Stage2':
        result = run_archive_stage2(repo_root=args.repo_root, week=args.week, agent=args.agent, overwrite=args.overwrite, run_mode=args.run_mode, harness_only=False, dry_run=args.dry_run)
    elif args.stage == 'Stage3':
        result = run_archive_stage3(repo_root=args.repo_root, week=args.week, agent=args.agent, overwrite=args.overwrite, run_mode=args.run_mode, harness_only=False, dry_run=args.dry_run, run_name=args.run_name)
    else:
        stage1_result = run_archive_stage1(repo_root=args.repo_root, week=args.week, agent=args.agent, overwrite=args.overwrite, run_mode=args.run_mode, harness_only=False, core_only=args.core_only, dry_run=args.dry_run)
        if not stage1_result.get('success', False):
            output_success(stage1_result)
            return
        stage2_result = run_archive_stage2(repo_root=args.repo_root, week=args.week, agent=args.agent, overwrite=args.overwrite, run_mode=args.run_mode, harness_only=False, dry_run=args.dry_run, stage1_result=stage1_result)
        if not stage2_result.get('success', False):
            output_success(stage2_result)
            return
        result = run_archive_stage3(repo_root=args.repo_root, week=args.week, agent=args.agent, overwrite=args.overwrite, run_mode=args.run_mode, harness_only=False, dry_run=args.dry_run, run_name=args.run_name, stage1_result=stage1_result, stage2_result=stage2_result)
    output_success(result)


if __name__ == '__main__':
    main()
