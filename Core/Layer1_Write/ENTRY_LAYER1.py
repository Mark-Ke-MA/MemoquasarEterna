#!/usr/bin/env python3
"""Layer1 写入层总入口。

职责：
- 解析 CLI 参数
- 按顺序调度 Stage1 / Stage2
- 支持 `--Stage StageX` 仅运行指定阶段，用于阶段性测试

说明：
当前已接入 Stage1~Stage9 的入口，其中 Stage3 需要 runtime 才能实际执行。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer1_Write.Stage1_CallLayer0 import run_stage1
from Core.Layer1_Write.Stage2_ChunkPlan import run_stage2
from Core.Layer1_Write.Stage3_MapDispatch import run_stage3
from Core.Layer1_Write.Stage4_ReduceDispatch import run_stage4
from Core.Layer1_Write.Stage5_Finalize import run_stage5
from Core.Layer1_Write.Stage6_IndexUpdate import run_stage6
from Core.Layer1_Write.Stage7_EmbedUpdate import run_stage7
from Core.Layer1_Write.Stage8_RecordScores import run_stage8
from Core.Layer1_Write.Stage9_Cleanup import run_stage9
from Core.Layer1_Write.shared import get_previous_window_date, output_success, LoadConfig, load_json_file, write_json_atomic

STAGE_ORDER = ('Stage1', 'Stage2', 'Stage3', 'Stage4', 'Stage5', 'Stage6', 'Stage7', 'Stage8', 'Stage9')
IMPLEMENTED_STAGES = {'Stage1', 'Stage2', 'Stage3', 'Stage4', 'Stage5', 'Stage6', 'Stage7', 'Stage8', 'Stage9'}


def parse_args():
    parser = argparse.ArgumentParser(description='Layer1 Stage 入口：按顺序调度各阶段')
    parser.add_argument('--date', default=None, help='目标日期，默认按 boundary 推导上一个窗口日期')
    parser.add_argument('--repo-root', default=None, help='仓库根目录')
    parser.add_argument('--agent', default=None, help='只对指定 agent 运行；支持逗号分隔多个 agent，例如 agent_a,agent_b')
    parser.add_argument('--all', action='store_true', help='保留兼容参数；默认按全量模式处理')
    parser.add_argument('--Stage', '--stage', dest='stage', default=None, help='只运行指定阶段；支持逗号分隔多个阶段，例如 Stage1,Stage2,Stage8')
    parser.add_argument('--dry-run', action='store_true', help='只预览，不实际执行')
    parser.add_argument('--show-plan', action='store_true', help='只展示 Stage1 的调用计划')
    parser.add_argument('--run-mode', choices=('auto', 'manual'), default='manual', help='Stage9 failed log 写入模式')
    parser.add_argument('--run-name', default=None, help='Stage9 manual 模式下的运行名')
    parser.add_argument('--output_mode', choices=('print', 'write'), default='print', help='最终结果输出模式')
    parser.add_argument('--output_write_path', default=None, help='output_mode=write 时的结果写入路径')
    parser.add_argument('--stage1-staging-only', action='store_true', help='Stage1 调 Layer0 时只写 staging，不写正式 l2 / l1-init')
    return parser.parse_args()


# ---------------------------------------------------------------------------
# plan 辅助
# ---------------------------------------------------------------------------


def _plan_path(repo_root: str | None = None) -> Path:
    overall_cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(overall_cfg['store_dir'])).expanduser()
    staging_cfg = overall_cfg['store_dir_structure']['staging']
    staging_root = store_root / staging_cfg['root'] / staging_cfg['staging_surface']
    return staging_root / 'plan.json'


def _load_plan(repo_root: str | None = None) -> dict[str, Any] | None:
    path = _plan_path(repo_root)
    if not path.exists():
        return None
    return load_json_file(path)


def _set_stage_status(repo_root: str | None, stage_name: str, status: str) -> None:
    plan = _load_plan(repo_root)
    if not isinstance(plan, dict):
        return
    root = plan.setdefault('plan', {})
    stage_key = stage_name.lower()
    stage_block = root.get(stage_key)
    if not isinstance(stage_block, dict):
        return
    stage_block['status'] = status
    write_json_atomic(_plan_path(repo_root), plan)


# ---------------------------------------------------------------------------
# 单阶段调度
# ---------------------------------------------------------------------------


def _run_single_stage(stage_name: str, *, target_date: str, repo_root: str | None, agent: str | None, dry_run: bool, stage1_staging_only: bool, show_plan: bool, run_mode: str, run_name: str | None) -> dict[str, Any]:
    if stage_name == 'Stage1':
        stage_result = run_stage1(
            target_date=target_date,
            repo_root=repo_root,
            agent=agent,
            dry_run=dry_run,
            stage1_staging_only=stage1_staging_only,
            show_plan=show_plan,
        )
        return {
            'success': bool(stage_result.get('success', False)),
            'stage': 'Stage1',
            'note': stage_result.get('note'),
            'target_date': target_date,
        }
    if stage_name == 'Stage2':
        stage_result = run_stage2(repo_root=repo_root, dry_run=dry_run)
        return {
            'success': bool(stage_result.get('success', False)),
            'stage': 'Stage2',
            'dry_run': bool(stage_result.get('dry_run', False)),
            'plan_path': stage_result.get('plan_path'),
            'target_date': stage_result.get('target_date'),
            'note': stage_result.get('note'),
        }
    if stage_name == 'Stage3':
        stage_result = run_stage3(repo_root=repo_root)
        return {
            'success': bool(stage_result.get('success', False)),
            'stage': 'Stage3',
            'dry_run': False,
            'note': stage_result.get('note'),
            'failed_jobs': stage_result.get('failed_jobs', []),
            'failed_agents': stage_result.get('failed_agents', []),
            'succeed_agents': stage_result.get('succeed_agents', []),
            'stage1_agents': stage_result.get('stage1_agents', []),
        }
    if stage_name == 'Stage4':
        stage_result = run_stage4(repo_root=repo_root)
        return {
            'success': bool(stage_result.get('success', False)),
            'stage': 'Stage4',
            'dry_run': False,
            'note': stage_result.get('note'),
            'failed_jobs': stage_result.get('failed_jobs', []),
            'failed_agents': stage_result.get('failed_agents', []),
            'succeed_agents': stage_result.get('succeed_agents', []),
            'planned_agents': stage_result.get('planned_agents', []),
        }
    if stage_name == 'Stage5':
        stage_result = run_stage5(repo_root=repo_root)
        return {
            'success': bool(stage_result.get('success', False)),
            'stage': 'Stage5',
            'dry_run': False,
            'note': stage_result.get('note'),
            'failed_agents': stage_result.get('failed_agents', []),
            'succeed_agents': stage_result.get('succeed_agents', []),
            'low_agents': stage_result.get('low_agents', []),
        }
    if stage_name == 'Stage6':
        stage_result = run_stage6(repo_root=repo_root)
        return {
            'success': bool(stage_result.get('success', False)),
            'stage': 'Stage6',
            'dry_run': False,
            'note': stage_result.get('note'),
            'failed_agents': stage_result.get('failed_agents', []),
            'succeed_agents': stage_result.get('succeed_agents', []),
        }
    if stage_name == 'Stage7':
        stage_result = run_stage7(repo_root=repo_root)
        return {
            'success': bool(stage_result.get('success', False)),
            'stage': 'Stage7',
            'dry_run': False,
            'note': stage_result.get('note'),
            'failed_agents': stage_result.get('failed_agents', []),
            'succeed_agents': stage_result.get('succeed_agents', []),
            'skipped_agents': stage_result.get('skipped_agents', []),
            'skipped': stage_result.get('skipped', False),
        }
    if stage_name == 'Stage8':
        stage_result = run_stage8(repo_root=repo_root)
        return {
            'success': bool(stage_result.get('success', False)),
            'stage': 'Stage8',
            'dry_run': False,
            'note': stage_result.get('note'),
            'failed_agents': stage_result.get('failed_agents', []),
            'succeed_agents': stage_result.get('succeed_agents', []),
        }
    if stage_name == 'Stage9':
        stage_result = run_stage9(repo_root=repo_root, run_mode=run_mode, run_name=run_name)
        return {
            'success': bool(stage_result.get('success', False)),
            'stage': 'Stage9',
            'dry_run': False,
            'note': stage_result.get('note'),
            'fail_log_needed': stage_result.get('fail_log_needed', False),
            'fail_log_path': stage_result.get('fail_log_path'),
        }

    return {
        'success': False,
        'stage': stage_name,
        'error': f'{stage_name} 目前尚未接入。',
        'target_date': target_date,
        'note': 'Stage4~Stage9 仍在逐步实现中。',
    }


def _parse_stage_sequence(stage_arg: str | None) -> list[str]:
    if stage_arg is None or not str(stage_arg).strip():
        return []
    parsed: list[str] = []
    seen: set[str] = set()
    for item in str(stage_arg).split(','):
        stage_name = item.strip()
        if not stage_name:
            continue
        if stage_name not in IMPLEMENTED_STAGES:
            raise ValueError(f'未知或未接入的 Stage: {stage_name}')
        if stage_name in seen:
            continue
        seen.add(stage_name)
        parsed.append(stage_name)
    if not parsed:
        raise ValueError('--Stage 解析后为空')
    return parsed


def _run_stage_sequence(stage_names: list[str], *, target_date: str, repo_root: str | None, agent: str | None, dry_run: bool, stage1_staging_only: bool, show_plan: bool, run_mode: str, run_name: str | None) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for stage_name in stage_names:
        stage_result = _run_single_stage(
            stage_name,
            target_date=target_date,
            repo_root=repo_root,
            agent=agent,
            dry_run=dry_run,
            stage1_staging_only=stage1_staging_only,
            show_plan=show_plan,
            run_mode=run_mode,
            run_name=run_name,
        )
        results.append(stage_result)
        if not bool(stage_result.get('success', False)):
            return {
                'success': False,
                'stage': 'ENTRY_LAYER1',
                'mode': 'multi_stage',
                'target_date': target_date,
                'stages': results,
                'note': f'{stage_name} 失败，后续阶段未继续执行。',
            }
    return {
        'success': True,
        'stage': 'ENTRY_LAYER1',
        'mode': 'multi_stage',
        'target_date': target_date,
        'stages': results,
        'note': '多阶段执行完成。',
    }


# ---------------------------------------------------------------------------
# 默认流水线
# ---------------------------------------------------------------------------


def _run_default_pipeline(*, target_date: str, repo_root: str | None, agent: str | None, dry_run: bool, stage1_staging_only: bool, show_plan: bool, run_mode: str, run_name: str | None) -> dict[str, Any]:
    pipeline_failed = False
    next_stage = 'Stage1'

    stage1_result = run_stage1(
        target_date=target_date,
        repo_root=repo_root,
        agent=agent,
        dry_run=dry_run,
        stage1_staging_only=stage1_staging_only,
        show_plan=show_plan,
    )
    if not stage1_result.get('success', False):
        pipeline_failed = True
        _set_stage_status(repo_root, 'Stage1', 'failed')

    # dry-run / show-plan 模式只预览 Stage1，不继续往下跑，避免依赖实际落盘。
    if dry_run or show_plan:
        return {
            'success': True,
            'stage': 'ENTRY_LAYER1',
            'mode': 'pipeline',
            'target_date': target_date,
            'next_stage': 'Stage2',
            'note': '当前为预览模式，未继续执行 Stage2。',
        }

    stage2_should_run = bool(stage1_result.get('success', False))
    stage2_result: dict[str, Any]
    if stage2_should_run:
        stage2_result = run_stage2(repo_root=repo_root, dry_run=False)
        if not stage2_result.get('success', False):
            pipeline_failed = True
            _set_stage_status(repo_root, 'Stage2', 'failed')
    else:
        _set_stage_status(repo_root, 'Stage2', 'failed')
        stage2_result = {
            'success': False,
            'stage': 'Stage2',
            'skipped': True,
            'note': 'Stage1 未成功，Stage2 跳过。',
        }
        pipeline_failed = True

    stage3_should_run = bool(stage2_result.get('success', False))
    stage3_result: dict[str, Any]
    if stage3_should_run:
        stage3_result = run_stage3(repo_root=repo_root)
        if not stage3_result.get('success', False):
            pipeline_failed = True
            _set_stage_status(repo_root, 'Stage3', 'failed')
    else:
        _set_stage_status(repo_root, 'Stage3', 'failed')
        stage3_result = {
            'success': False,
            'stage': 'Stage3',
            'skipped': True,
            'note': 'Stage2 未成功，Stage3 跳过。',
            'failed_jobs': [],
            'failed_agents': [],
            'succeed_agents': [],
            'stage1_agents': [],
        }
        pipeline_failed = True

    stage4_should_run = bool(stage3_result.get('succeed_agents', []))
    stage4_result: dict[str, Any]
    if stage4_should_run:
        stage4_result = run_stage4(repo_root=repo_root)
        if not stage4_result.get('success', False):
            pipeline_failed = True
            _set_stage_status(repo_root, 'Stage4', 'failed')
    else:
        _set_stage_status(repo_root, 'Stage4', 'failed')
        stage4_result = {
            'success': False,
            'stage': 'Stage4',
            'skipped': True,
            'note': 'Stage3 无成功 agent，Stage4 跳过。',
            'failed_jobs': [],
            'failed_agents': [],
            'succeed_agents': [],
            'planned_agents': [],
        }
        pipeline_failed = True

    stage5_should_run = bool(stage4_result.get('succeed_agents', []))
    stage5_result: dict[str, Any]
    if stage5_should_run:
        stage5_result = run_stage5(repo_root=repo_root)
        if not stage5_result.get('success', False):
            pipeline_failed = True
            _set_stage_status(repo_root, 'Stage5', 'failed')
    else:
        _set_stage_status(repo_root, 'Stage5', 'failed')
        stage5_result = {
            'success': False,
            'stage': 'Stage5',
            'skipped': True,
            'note': 'Stage4 无成功 agent，Stage5 跳过。',
            'results': [],
            'failed_agents': [],
            'succeed_agents': [],
            'low_agents': [],
        }
        pipeline_failed = True

    stage6_should_run = bool(stage5_result.get('succeed_agents', []))
    stage6_result: dict[str, Any]
    if stage6_should_run:
        stage6_result = run_stage6(repo_root=repo_root)
        if not stage6_result.get('success', False):
            pipeline_failed = True
            _set_stage_status(repo_root, 'Stage6', 'failed')
    else:
        _set_stage_status(repo_root, 'Stage6', 'failed')
        stage6_result = {
            'success': False,
            'stage': 'Stage6',
            'skipped': True,
            'note': 'Stage5 无成功 agent，Stage6 跳过。',
            'results': [],
            'failed_agents': [],
            'succeed_agents': [],
        }
        pipeline_failed = True

    stage7_should_run = bool(stage5_result.get('succeed_agents', []))
    stage7_result: dict[str, Any]
    if stage7_should_run:
        stage7_result = run_stage7(repo_root=repo_root)
        if not stage7_result.get('success', False):
            pipeline_failed = True
            _set_stage_status(repo_root, 'Stage7', 'failed')
    else:
        _set_stage_status(repo_root, 'Stage7', 'failed')
        stage7_result = {
            'success': False,
            'stage': 'Stage7',
            'skipped': True,
            'note': 'Stage5 无成功 agent，Stage7 跳过。',
            'results': [],
            'failed_agents': [],
            'succeed_agents': [],
            'skipped_agents': [],
            'skipped': True,
        }
        pipeline_failed = True

    stage8_result = run_stage8(repo_root=repo_root)
    if not stage8_result.get('success', False):
        pipeline_failed = True
        _set_stage_status(repo_root, 'Stage8', 'failed')

    stage9_result = run_stage9(repo_root=repo_root, run_mode=run_mode, run_name=run_name)
    if not stage9_result.get('success', False):
        pipeline_failed = True
        _set_stage_status(repo_root, 'Stage9', 'failed')

    next_stage = None
    return {
        'success': not pipeline_failed,
        'stage': 'ENTRY_LAYER1',
        'mode': 'pipeline',
        'target_date': target_date,
        'next_stage': next_stage,
        'available_stages': list(STAGE_ORDER),
        'implemented_stages': [stage for stage in STAGE_ORDER if stage in IMPLEMENTED_STAGES],
        'note': '默认流水线已执行到 Stage9。',
        'failed_agents': stage8_result.get('failed_agents', []),
        'succeed_agents': stage8_result.get('succeed_agents', []),
        'skipped_agents': stage7_result.get('skipped_agents', []),
        'skipped': stage7_result.get('skipped', False),
        'fail_log_needed': stage9_result.get('fail_log_needed', False),
        'fail_log_path': stage9_result.get('fail_log_path'),
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main():
    args = parse_args()
    if args.output_mode == 'write' and not args.output_write_path:
        raise ValueError('output_mode=write 时必须提供 --output_write_path')

    target_date = args.date or get_previous_window_date(args.repo_root)

    if args.stage:
        stage_names = _parse_stage_sequence(args.stage)
        if len(stage_names) == 1:
            result = _run_single_stage(
                stage_names[0],
                target_date=target_date,
                repo_root=args.repo_root,
                agent=args.agent,
                dry_run=args.dry_run,
                stage1_staging_only=args.stage1_staging_only,
                show_plan=args.show_plan,
                run_mode=args.run_mode,
                run_name=args.run_name,
            )
        else:
            result = _run_stage_sequence(
                stage_names,
                target_date=target_date,
                repo_root=args.repo_root,
                agent=args.agent,
                dry_run=args.dry_run,
                stage1_staging_only=args.stage1_staging_only,
                show_plan=args.show_plan,
                run_mode=args.run_mode,
                run_name=args.run_name,
            )
    else:
        result = _run_default_pipeline(
            target_date=target_date,
            repo_root=args.repo_root,
            agent=args.agent,
            dry_run=args.dry_run,
            stage1_staging_only=args.stage1_staging_only,
            show_plan=args.show_plan,
            run_mode=args.run_mode,
            run_name=args.run_name,
        )

    if args.output_mode == 'write':
        write_json_atomic(args.output_write_path, result)
        return
    elif args.output_mode == 'print':
        output_success(result)


if __name__ == '__main__':
    main()
