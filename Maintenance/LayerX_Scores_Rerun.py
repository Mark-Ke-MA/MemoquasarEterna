#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.shared_funcs import LoadConfig


def parse_iso_date(text: str):
    return datetime.strptime(text, '%Y-%m-%d').date()


def iter_dates(date_start: str, date_end: str):
    start = parse_iso_date(date_start)
    end = parse_iso_date(date_end)
    if end < start:
        raise ValueError('--date_end 不能早于 --date_start')
    current = start
    while current <= end:
        yield current.strftime('%Y-%m-%d')
        current += timedelta(days=1)


def parse_args():
    parser = argparse.ArgumentParser(description='批量重跑 LayerX landmark score records')
    parser.add_argument('--agent', default=None, help='原样透传给 Layer1 ENTRY 的 --agent；不传则读取 OverallConfig.agentId_list')
    parser.add_argument('--date', default=None, help='单日 YYYY-MM-DD')
    parser.add_argument('--date_start', default=None, help='起始日期 YYYY-MM-DD')
    parser.add_argument('--date_end', default=None, help='结束日期 YYYY-MM-DD')
    parser.add_argument('--repo-root', default=str(ROOT))
    return parser.parse_args()


def target_dates_from_args(args) -> list[str]:
    if args.date and (args.date_start or args.date_end):
        raise ValueError('--date 与 --date_start/--date_end 不能同时使用')
    if args.date:
        return [str(args.date)]
    if args.date_start and args.date_end:
        return list(iter_dates(str(args.date_start), str(args.date_end)))
    raise ValueError('必须提供 --date 或 --date_start --date_end')


def extract_stage8_success(stdout_text: str) -> bool:
    payload = json.loads(stdout_text)
    if not isinstance(payload, dict):
        return False

    if payload.get('mode') == 'multi_stage':
        stages = payload.get('stages', [])
        if isinstance(stages, list):
            for item in stages:
                if isinstance(item, dict) and str(item.get('stage', '') or '') == 'Stage8':
                    return bool(item.get('success', False))
        return False

    if str(payload.get('stage', '') or '') == 'Stage8':
        return bool(payload.get('success', False))

    return False


def resolve_agent_arg(*, repo_root: str, agent: str | None) -> str:
    if agent is not None and str(agent).strip():
        return str(agent).strip()
    cfg = LoadConfig(repo_root).overall_config
    agent_ids = cfg.get('agentId_list', []) if isinstance(cfg, dict) else []
    if not isinstance(agent_ids, list) or not agent_ids:
        raise ValueError('OverallConfig.agentId_list 为空，且未显式提供 --agent')
    parsed = [str(item).strip() for item in agent_ids if str(item).strip()]
    if not parsed:
        raise ValueError('OverallConfig.agentId_list 解析后为空，且未显式提供 --agent')
    return ','.join(parsed)


def run_single_date(*, repo_root: str, agent: str, target_date: str) -> bool:
    entry = Path(repo_root) / 'Core' / 'Layer1_Write' / 'ENTRY_LAYER1.py'
    cmd = [
        sys.executable,
        str(entry),
        '--agent',
        agent,
        '--date',
        target_date,
        '--Stage',
        'Stage1,Stage2,Stage8',
        '--stage1-staging-only',
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return False
    try:
        return extract_stage8_success(proc.stdout or '')
    except Exception:
        return False


def main():
    args = parse_args()
    dates = target_dates_from_args(args)
    agent_arg = resolve_agent_arg(repo_root=str(args.repo_root), agent=args.agent)
    for target_date in dates:
        success = run_single_date(repo_root=str(args.repo_root), agent=agent_arg, target_date=target_date)
        print(target_date, bool(success), flush=True)


if __name__ == '__main__':
    main()
