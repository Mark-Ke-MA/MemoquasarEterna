#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer4_Read.ENTRY_LAYER4_vague import assemble_vague
from Core.Layer4_Read.recall_L2 import exact_recall_l2


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def _print_text(text: str) -> None:
    print(str(text or '').strip(), flush=True)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--agent', required=True, help='目标 agent_id / Hermes profile')
    parser.add_argument('--repo-root', default=str(ROOT), help='MemoquasarEterna repo root')
    parser.add_argument('--json', action='store_true', help='输出 JSON，而不是 agent 可直接阅读的文本')


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Hermes terminal bridge for MemoquasarEterna Layer4 recall.')
    subparsers = parser.add_subparsers(dest='mode', required=True)

    vague = subparsers.add_parser('vague', help='模糊回忆 / 最近概览')
    _add_common_args(vague)
    vague.add_argument('--query', default=None, help='可选查询文本；不传则读取最近几天概览')
    vague.add_argument('--recent-days', type=int, default=3, help='query 为空时读取最近 N 天，默认 3')
    vague.add_argument('--date-window', default=None, help='可选：YYYY-MM-DD 或 YYYY-MM-DD,YYYY-MM-DD')
    vague.add_argument('--prefer-l2-ratio', type=float, default=None, help='可选：0~1，query 非空时增加 L2 对话证据占比')
    vague.add_argument('--max-chars', type=int, default=12000, help='最大输出字符数')

    exact = subparsers.add_parser('exact', help='精确读取某天某时间窗口的 L2 transcript')
    _add_common_args(exact)
    exact.add_argument('--date', required=True, help='YYYY-MM-DD')
    exact.add_argument('--window-start', required=True, help='HH:MM')
    exact.add_argument('--window-end', required=True, help='HH:MM')
    exact.add_argument('--max-chars', type=int, default=None, help='最大输出字符数')
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        if args.mode == 'vague':
            result = assemble_vague(
                repo_root=args.repo_root,
                agent_id=args.agent,
                query=args.query,
                recent_days=args.recent_days,
                date_window=args.date_window,
                prefer_l2_ratio=args.prefer_l2_ratio,
                max_chars=args.max_chars,
            )
            if args.json:
                _print_json({'success': True, 'mode': 'vague', **result})
            else:
                _print_text(str(result.get('assembled_text', '') or ''))
            return

        transcript_text = exact_recall_l2(
            repo_root=args.repo_root,
            agent_id=args.agent,
            date=args.date,
            window_start=args.window_start,
            window_end=args.window_end,
            max_chars=args.max_chars,
        )
        if args.json:
            _print_json({'success': True, 'mode': 'exact', 'transcript_text': transcript_text})
        else:
            _print_text(transcript_text)
    except Exception as exc:  # noqa: BLE001
        if args.json:
            _print_json({'success': False, 'error': str(exc)})
        else:
            print(f'MemoquasarEterna recall failed: {exc}', file=sys.stderr, flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
