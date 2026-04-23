#!/usr/bin/env python3
"""Layer1 Write rerun maintenance script.

职责：
- 统一处理 Layer1 的单日 / 日期范围 rerun
- 支持从 failed_log 推导 rerun 目标
- 调用 Layer1_Write/ENTRY_LAYER1.py，而不是重复实现 Layer1 逻辑
- 若使用 failed_log 且 rerun 成功，则回写 rerun_done 标记
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.shared_funcs import output_failure, output_success, write_json_atomic


def _entry_script() -> Path:
    return ROOT / 'Core' / 'Layer1_Write' / 'ENTRY_LAYER1.py'


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _default_run_name() -> str:
    return datetime.now(timezone.utc).strftime('Rerun_from_script_%Y-%m-%dT%H-%M-%SZ')


def _load_json_dict(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f'JSON 文件不存在: {file_path}')
    with open(file_path, encoding='utf-8') as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f'JSON 顶层必须是 object: {file_path}')
    return payload


def _parse_date(text: str) -> datetime:
    return datetime.strptime(text, '%Y-%m-%d')


def _expand_date_range(start_date: str, end_date: str) -> list[str]:
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if end < start:
        raise ValueError('end_date 不能早于 start_date')
    out: list[str] = []
    current = start
    while current <= end:
        out.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    return out


def _parse_agent_csv(agent: str | None) -> list[str] | None:
    if agent is None or not str(agent).strip():
        return None
    raw_items = [item.strip() for item in str(agent).split(',')]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    if not out:
        return None
    return out


def _collect_failed_agents_from_log(payload: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _push(agent_id: str) -> None:
        agent_id = str(agent_id or '').strip()
        if not agent_id or agent_id in seen:
            return
        seen.add(agent_id)
        out.append(agent_id)

    stage3 = payload.get('stage3', {}) if isinstance(payload.get('stage3', {}), dict) else {}
    for item in stage3.get('failed_agents', []) if isinstance(stage3.get('failed_agents', []), list) else []:
        if isinstance(item, dict):
            _push(str(item.get('agent_id', '') or ''))

    for stage_name in ('stage4', 'stage5', 'stage6', 'stage7'):
        stage_block = payload.get(stage_name, {}) if isinstance(payload.get(stage_name, {}), dict) else {}
        failed_agents = stage_block.get('failed_agents', [])
        if isinstance(failed_agents, list):
            for agent_id in failed_agents:
                _push(str(agent_id or ''))

    return out


def _build_targets_from_failed_log(failed_log_payload: dict[str, Any], manual_agents: list[str] | None) -> list[dict[str, Any]]:
    target_date = str(failed_log_payload.get('target_date', '') or '').strip()
    if not target_date:
        raise ValueError('failed_log 缺少 target_date')

    if manual_agents:
        return [{'date': target_date, 'agents': manual_agents}]

    failed_agents = _collect_failed_agents_from_log(failed_log_payload)
    if failed_agents:
        return [{'date': target_date, 'agents': failed_agents}]
    return [{'date': target_date, 'agents': None}]


def _build_manual_targets(*, date: str | None, start_date: str | None, end_date: str | None, agents: list[str] | None) -> list[dict[str, Any]]:
    if date:
        return [{'date': date, 'agents': agents}]
    if start_date and end_date:
        return [{'date': item, 'agents': agents} for item in _expand_date_range(start_date, end_date)]
    raise ValueError('手动模式下必须提供 --date 或同时提供 --start-date 与 --end-date')


def _run_single_target(*, target_date: str, agents: list[str] | None, run_name: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(_entry_script()),
        '--date',
        target_date,
        '--run-mode',
        'manual',
        '--run-name',
        run_name,
    ]
    if agents:
        cmd.extend(['--agent', ','.join(agents)])

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
        except Exception:  # noqa: BLE001
            parsed_stdout = None

    return {
        'date': target_date,
        'agents': agents,
        'success': proc.returncode == 0 and bool(parsed_stdout and parsed_stdout.get('success', False)),
        'returncode': proc.returncode,
        'entry_note': (parsed_stdout or {}).get('note') if isinstance(parsed_stdout, dict) else None,
        'fail_log_needed': bool((parsed_stdout or {}).get('fail_log_needed', False)) if isinstance(parsed_stdout, dict) else False,
        'fail_log_path': (parsed_stdout or {}).get('fail_log_path') if isinstance(parsed_stdout, dict) else None,
    }


def _mark_failed_log_rerun_done(failed_log_path: str | Path, *, run_name: str) -> None:
    payload = _load_json_dict(failed_log_path)
    payload['rerun_done'] = True
    payload['rerun_at'] = _utc_now_iso()
    payload['rerun_run_name'] = run_name
    write_json_atomic(failed_log_path, payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Layer1 Write maintenance rerun script')
    parser.add_argument('--date', default=None, help='指定单个 target_date 进行 rerun')
    parser.add_argument('--start-date', default=None, help='日期范围起点 YYYY-MM-DD')
    parser.add_argument('--end-date', default=None, help='日期范围终点 YYYY-MM-DD')
    parser.add_argument('--failed-log', default=None, help='从 failed_log 推导 rerun 目标')
    parser.add_argument('--agent', default=None, help='指定 agent；支持逗号分隔多个 agent')
    parser.add_argument('--run-name', default=None, help='透传给 ENTRY_LAYER1.py 的 manual run name')
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    has_failed_log = bool(args.failed_log)
    has_single_date = bool(args.date)
    has_date_range = bool(args.start_date or args.end_date)

    if has_failed_log and (has_single_date or has_date_range):
        raise ValueError('--failed-log 不能与 --date / --start-date / --end-date 同时使用')
    if has_single_date and has_date_range:
        raise ValueError('--date 不能与 --start-date / --end-date 同时使用')
    if not has_failed_log and not has_single_date and not (args.start_date and args.end_date):
        raise ValueError('必须提供 --failed-log，或提供 --date，或同时提供 --start-date 与 --end-date')
    if bool(args.start_date) != bool(args.end_date):
        raise ValueError('--start-date 与 --end-date 必须同时提供')


def main() -> None:
    args = parse_args()
    try:
        _validate_args(args)
        run_name = str(args.run_name or _default_run_name())
        manual_agents = _parse_agent_csv(args.agent)

        failed_log_path = args.failed_log
        failed_log_payload: dict[str, Any] | None = None
        if failed_log_path:
            failed_log_payload = _load_json_dict(failed_log_path)
            if bool(failed_log_payload.get('rerun_done', False)):
                output_success({
                    'success': True,
                    'skipped': True,
                    'reason': 'failed_log_already_rerun',
                    'failed_log': str(Path(failed_log_path)),
                    'target_date': failed_log_payload.get('target_date'),
                    'note': '该 failed_log 已成功 rerun；若要覆写请手动处理后再运行。',
                })
                return

        if failed_log_payload is not None:
            targets = _build_targets_from_failed_log(failed_log_payload, manual_agents)
        else:
            targets = _build_manual_targets(
                date=args.date,
                start_date=args.start_date,
                end_date=args.end_date,
                agents=manual_agents,
            )

        results: list[dict[str, Any]] = []
        overall_success = True
        for target in targets:
            result = _run_single_target(
                target_date=str(target['date']),
                agents=target.get('agents'),
                run_name=run_name,
            )
            results.append(result)
            if not result.get('success', False):
                overall_success = False

        if failed_log_path and overall_success:
            _mark_failed_log_rerun_done(failed_log_path, run_name=run_name)

        output_success({
            'success': overall_success,
            'mode': 'failed-log' if failed_log_path else 'manual',
            'run_name': run_name,
            'target_count': len(targets),
            'results': results,
            'failed_log': str(Path(failed_log_path)) if failed_log_path else None,
            'failed_log_marked_rerun': bool(failed_log_path and overall_success),
            'note': 'Layer1 rerun 执行完成。' if overall_success else 'Layer1 rerun 执行结束，但存在失败目标。',
        })
    except Exception as exc:  # noqa: BLE001
        output_failure(str(exc))


if __name__ == '__main__':
    main()
