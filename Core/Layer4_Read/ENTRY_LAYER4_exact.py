#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

"""Layer4 exact recall entry.

输入：
- --agent
- --date YYYY-MM-DD
- --window-start HH:MM
- --window-end HH:MM

输出精简为：
- success
- transcript_text
"""

import argparse

from Core.shared_funcs import output_failure, output_success
from Core.Layer4_Read.recall_L2 import exact_recall_l2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Layer4 exact recall entry')
    parser.add_argument('--agent', required=True, help='目标 agent_id')
    parser.add_argument('--date', required=True, help='目标日期 YYYY-MM-DD')
    parser.add_argument('--window-start', required=True, help='时间窗口开始 HH:MM')
    parser.add_argument('--window-end', required=True, help='时间窗口结束 HH:MM')
    parser.add_argument('--repo-root', default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        transcript_text = exact_recall_l2(
            repo_root=args.repo_root,
            agent_id=args.agent,
            date=args.date,
            window_start=args.window_start,
            window_end=args.window_end,
        )
        output_success({
            'success': True,
            'transcript_text': str(transcript_text or ''),
        })
    except Exception as exc:  # noqa: BLE001
        output_failure(str(exc))


if __name__ == '__main__':
    main()
