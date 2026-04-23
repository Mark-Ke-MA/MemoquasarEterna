#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer2_Preserve.core import load_preserve_config, preserve_result, restored_root
from Core.Layer2_Preserve.restore_Stage1_Plan import run_restore_stage1
from Core.Layer2_Preserve.restore_Stage2_Apply import run_restore_stage2
from Core.Layer2_Preserve.restore_Stage3_Finalize import run_restore_stage3
from Core.shared_funcs import output_success


def parse_args():
    parser = argparse.ArgumentParser(description='Layer2_Preserve restore 入口')
    parser.add_argument('--week', default=None, help='目标 ISO week，例如 2026-W15')
    parser.add_argument('--date', default=None, help='目标日期，例如 2026-04-14')
    parser.add_argument('--agent', default=None, help='只处理指定 agent；支持逗号分隔多个 agent')
    parser.add_argument('--which-level', default='all', help='恢复粒度：all / l0 / l1 / l2 / 逗号列表')
    parser.add_argument('--restore-mode', default='mirrored', choices=('mirrored', 'update', 'overwrite'))
    parser.add_argument('--run-mode', default='manual', choices=('auto', 'manual'))
    parser.add_argument('--run-name', default=None)
    parser.add_argument('--clear', default=None, help='清理 restored 目录：all 或某个 run_name')
    parser.add_argument('--Stage', '--stage', dest='stage', default=None, choices=('Stage1', 'Stage2', 'Stage3'))
    parser.add_argument('--repo-root', default=None)
    return parser.parse_args()


def _clear_restored(*, repo_root: str | None, clear: str) -> dict:
    cfg = load_preserve_config(repo_root)
    root = restored_root(cfg)
    target = str(clear or '').strip()
    if not target:
        return preserve_result(success=False, stage='Layer2_Restore_Clear', note='--clear 不能为空')
    if target == 'all':
        root.mkdir(parents=True, exist_ok=True)
        for child in root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        return preserve_result(success=True, stage='Layer2_Restore_Clear', note='已清空 restored 目录内容，并保留根目录。', cleared_path=str(root))
    safe_name = Path(target).name
    if safe_name != target or safe_name in {'', '.', '..'}:
        return preserve_result(success=False, stage='Layer2_Restore_Clear', note='--clear 只允许 all 或单层 run_name')
    run_path = root / safe_name
    if not run_path.exists():
        return preserve_result(success=False, stage='Layer2_Restore_Clear', note='指定的 restored run 不存在。', cleared_path=str(run_path))
    shutil.rmtree(run_path)
    return preserve_result(success=True, stage='Layer2_Restore_Clear', note='已清理指定 restored run。', cleared_path=str(run_path))


def main():
    args = parse_args()
    if args.clear is not None:
        output_success(_clear_restored(repo_root=args.repo_root, clear=args.clear))
        return
    if args.restore_mode == 'mirrored' and not args.run_name:
        args.run_name = None
    if args.stage == 'Stage1':
        result = run_restore_stage1(repo_root=args.repo_root, week=args.week, date=args.date, agent=args.agent, which_level=args.which_level, restore_mode=args.restore_mode, run_name=args.run_name)
    elif args.stage == 'Stage2':
        result = run_restore_stage2(repo_root=args.repo_root, week=args.week, date=args.date, agent=args.agent, which_level=args.which_level, restore_mode=args.restore_mode, run_name=args.run_name)
    elif args.stage == 'Stage3':
        result = run_restore_stage3(repo_root=args.repo_root, week=args.week, date=args.date, agent=args.agent, which_level=args.which_level, restore_mode=args.restore_mode, run_mode=args.run_mode, run_name=args.run_name)
    else:
        stage1_result = run_restore_stage1(repo_root=args.repo_root, week=args.week, date=args.date, agent=args.agent, which_level=args.which_level, restore_mode=args.restore_mode, run_name=args.run_name)
        if not stage1_result.get('success', False):
            output_success(stage1_result)
            return
        stage2_result = run_restore_stage2(repo_root=args.repo_root, week=args.week, date=args.date, agent=args.agent, which_level=args.which_level, restore_mode=args.restore_mode, run_name=args.run_name, stage1_result=stage1_result)
        if not stage2_result.get('success', False):
            output_success(stage2_result)
            return
        result = run_restore_stage3(repo_root=args.repo_root, week=args.week, date=args.date, agent=args.agent, which_level=args.which_level, restore_mode=args.restore_mode, run_mode=args.run_mode, run_name=args.run_name, stage1_result=stage1_result, stage2_result=stage2_result)
    output_success(result)


if __name__ == '__main__':
    main()
