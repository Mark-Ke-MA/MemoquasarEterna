#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.LayerX_LandmarkJudge.Stage1_Collect import run_stage1
from Core.LayerX_LandmarkJudge.Stage2_Analyze import run_stage2
from Core.LayerX_LandmarkJudge.Stage3_Scoring import run_stage3
from Core.LayerX_LandmarkJudge.Stage4_Finalize import run_stage4
from Core.LayerX_LandmarkJudge.shared import LoadConfig
from Core.shared_funcs import output_failure

LANDMARK_THRESHOLD = 5.5


def _today_local(repo_root: str | Path | None):
    cfg = LoadConfig(repo_root)
    timezone_name = str(cfg.overall_config.get('timezone', 'Europe/London'))
    return datetime.now(ZoneInfo(timezone_name)).date()


def _default_analysis_window(repo_root: str | Path | None, recent_days: int | None) -> tuple[str | None, str]:
    today_local = _today_local(repo_root)
    date_end = (today_local - timedelta(days=1)).strftime('%Y-%m-%d')
    if recent_days is None:
        return None, date_end
    if int(recent_days) <= 0:
        raise ValueError('--recent-days 必须是正整数')
    date_start = (today_local - timedelta(days=int(recent_days))).strftime('%Y-%m-%d')
    return date_start, date_end


def parse_args():
    parser = argparse.ArgumentParser(description='LayerX_LandmarkJudge 入口')
    parser.add_argument('--agent', default=None, help='只处理指定 agent；支持逗号分隔多个 agent')
    parser.add_argument('--date', default=None, help='目标单日 YYYY-MM-DD')
    parser.add_argument('--date_start', default=None, help='起始日期 YYYY-MM-DD')
    parser.add_argument('--date_end', default=None, help='结束日期 YYYY-MM-DD')
    parser.add_argument('--analysis', action='store_true', help='分析模式：输出 histogram 图与精简 summary')
    parser.add_argument('--graphs_path', default=None, help='analysis 模式下的图像输出目录；不传则不画图')
    parser.add_argument('--landmark_ratio', type=float, default=None, help='仅 analysis 模式使用；按目标 landmark 比例反推 threshold，例如 0.2 表示 20%%')
    parser.add_argument('--recent-days', type=int, default=None, help='仅 analysis 模式使用；若不传日期范围，则只分析最近 N 天（截至昨天）')
    parser.add_argument('--repo-root', default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.landmark_ratio is not None:
            if not args.analysis:
                raise ValueError('--landmark_ratio 只允许在 --analysis 模式下使用')
            if not (0 < float(args.landmark_ratio) < 1):
                raise ValueError('--landmark_ratio 必须在 0 和 1 之间')
        if args.recent_days is not None and not args.analysis:
            raise ValueError('--recent-days 只允许在 --analysis 模式下使用')

        date = args.date
        date_start = args.date_start
        date_end = args.date_end
        if args.analysis and not date and not date_start and not date_end:
            date_start, date_end = _default_analysis_window(args.repo_root, args.recent_days)

        stage1_result = run_stage1(repo_root=args.repo_root, agent=args.agent, date=date, date_start=date_start, date_end=date_end)
        stage2_result = run_stage2(stage1_result=stage1_result)
        stage3_result = run_stage3(stage2_result=stage2_result, threshold=LANDMARK_THRESHOLD)
        result = run_stage4(
            repo_root=args.repo_root,
            analysis=args.analysis,
            graphs_path=args.graphs_path,
            stage2_result=stage2_result,
            stage3_result=stage3_result,
            landmark_ratio=args.landmark_ratio,
            window_start=date_start,
            window_end=date_end,
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
    except Exception as exc:  # noqa: BLE001
        output_failure(str(exc))


if __name__ == '__main__':
    main()
