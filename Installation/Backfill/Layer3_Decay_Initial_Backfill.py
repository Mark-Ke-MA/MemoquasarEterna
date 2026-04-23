#!/usr/bin/env python3
"""Layer3 Decay initial backfill script.

职责：
- 在给定日期范围内，把 Layer3 以“仿佛自动 cron 正常一路运行到现在”的方式补灌到当前 store_dir
- 默认假设 Layer1 initial backfill 已经全量成功完成
- 按周串行调用 Layer3_Decay/ENTRY_LAYER3.py
- 支持显式开启 apply_cleanup；默认不做 destructive cleanup
- 运行过程中持续打印可追踪、可读的进度摘要
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer3_Decay.shared import monday_of_iso_week
from Core.shared_funcs import LoadConfig, output_failure, output_success


def _entry_script() -> Path:
    return ROOT / 'Core' / 'Layer3_Decay' / 'ENTRY_LAYER3.py'


def _default_run_name() -> str:
    return datetime.now(timezone.utc).strftime('Initial_backfill_%Y-%m-%dT%H-%M-%SZ')


def _parse_date(text: str) -> date:
    return datetime.strptime(text, '%Y-%m-%d').date()


def _iso_week_id(day: date) -> str:
    iso_year, iso_week, _ = day.isocalendar()
    return f'{iso_year}-W{iso_week:02d}'


def _shift_week(week_id: str, offset_weeks: int) -> str:
    monday = monday_of_iso_week(week_id)
    shifted = monday + timedelta(days=7 * int(offset_weeks))
    return _iso_week_id(shifted)


def _expand_week_range(start_week: str, end_week: str) -> list[str]:
    start_monday = monday_of_iso_week(start_week)
    end_monday = monday_of_iso_week(end_week)
    if end_monday < start_monday:
        raise ValueError('end_week 不能早于 start_week')
    out: list[str] = []
    current = start_monday
    while current <= end_monday:
        out.append(_iso_week_id(current))
        current += timedelta(days=7)
    return out


def _resolve_end_week(end_date_text: str) -> str:
    end_day = _parse_date(end_date_text)
    end_week = _iso_week_id(end_day)
    if end_day.isoweekday() == 7:
        return end_week
    return _shift_week(end_week, -1)


def _resolve_start_week(start_date_text: str) -> str:
    start_day = _parse_date(start_date_text)
    start_week = _iso_week_id(start_day)
    return start_week


def _run_single_week(*, week: str, run_name: str, apply_cleanup: bool) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(_entry_script()),
        '--week',
        week,
        '--run-mode',
        'manual',
        '--run-name',
        run_name,
    ]
    if apply_cleanup:
        cmd.append('--apply_cleanup')

    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )

    parsed_stdout: dict[str, Any] | None = None
    stdout_text = (proc.stdout or '').strip()
    if stdout_text:
        try:
            candidate = json.loads(stdout_text)
            if isinstance(candidate, dict):
                parsed_stdout = candidate
        except Exception:
            parsed_stdout = None

    success = proc.returncode == 0 and bool(parsed_stdout and parsed_stdout.get('success', False))
    return {
        'week': week,
        'success': success,
        'returncode': proc.returncode,
        'entry_note': (parsed_stdout or {}).get('note') if isinstance(parsed_stdout, dict) else None,
        'failed_phase': (parsed_stdout or {}).get('failed_phase') if isinstance(parsed_stdout, dict) else None,
        'completed_phases': (parsed_stdout or {}).get('completed_phases') if isinstance(parsed_stdout, dict) else None,
        'fail_log_needed': bool((parsed_stdout or {}).get('fail_log_needed', False)) if isinstance(parsed_stdout, dict) else False,
        'fail_log_path': (parsed_stdout or {}).get('fail_log_path') if isinstance(parsed_stdout, dict) else None,
    }


def _format_str_list(value: Any) -> str:
    if not isinstance(value, list):
        return ''
    items = [str(item).strip() for item in value if str(item).strip()]
    return ','.join(items)


def _print_result_line(result: dict[str, Any]) -> None:
    status = '[DONE]' if result.get('success', False) else '[FAIL]'
    week = str(result.get('week', '') or '')
    note = str(result.get('entry_note', '') or '')
    print(f'{status} {week} | note={note}', flush=True)

    failed_phase = str(result.get('failed_phase', '') or '')
    completed_phases = _format_str_list(result.get('completed_phases'))
    fail_log_needed = bool(result.get('fail_log_needed', False))
    fail_log_path = str(result.get('fail_log_path', '') or '')
    details: list[str] = []
    if failed_phase:
        details.append(f'failed_phase={failed_phase}')
    if completed_phases:
        details.append(f'completed_phases={completed_phases}')
    if fail_log_needed and fail_log_path:
        details.append(f'fail_log={fail_log_path}')
    if details:
        print(f"       {' | '.join(details)}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Layer3 Decay initial backfill script')
    parser.add_argument('--start-date', required=True, help='初始化回填起始日期 YYYY-MM-DD')
    parser.add_argument('--end-date', required=True, help='初始化回填结束日期 YYYY-MM-DD')
    parser.add_argument('--apply_cleanup', action='store_true', help='显式允许初始化回填执行 destructive cleanup；默认关闭')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        start_day = _parse_date(args.start_date)
        end_day = _parse_date(args.end_date)
        if end_day < start_day:
            raise ValueError('end-date 不能早于 start-date')

        run_name = _default_run_name()
        start_week = _resolve_start_week(args.start_date)
        end_week = _resolve_end_week(args.end_date)
        target_weeks = _expand_week_range(start_week, end_week)

        results: list[dict[str, Any]] = []
        overall_success = True
        for week in target_weeks:
            result = _run_single_week(
                week=week,
                run_name=run_name,
                apply_cleanup=bool(args.apply_cleanup),
            )
            results.append(result)
            _print_result_line(result)
            if not result.get('success', False):
                overall_success = False

        output_success({
            'success': overall_success,
            'run_name': run_name,
            'start_date': args.start_date,
            'end_date': args.end_date,
            'start_week': start_week,
            'end_week': end_week,
            'target_count': len(target_weeks),
            'apply_cleanup': bool(args.apply_cleanup),
            'results': results,
            'note': 'Layer3 initial backfill 执行完成。' if overall_success else 'Layer3 initial backfill 执行结束，但存在失败 week。',
        })
    except Exception as exc:  # noqa: BLE001
        output_failure(str(exc))


if __name__ == '__main__':
    main()
