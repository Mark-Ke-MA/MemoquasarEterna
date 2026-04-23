#!/usr/bin/env python3
"""Layer3 Decay rerun maintenance script.

职责：
- 统一处理 Layer3 的单周 rerun
- 支持从 failed_log 推导 rerun 目标
- 调用 Layer3_Decay/ENTRY_LAYER3.py，而不是重复实现 Layer3 逻辑
- 若使用 failed_log 且 rerun 成功，则回写 rerun_done 标记
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.shared_funcs import output_failure, output_success, write_json_atomic


LAYER3_ALLOWED_PHASES = ('Phase0', 'Phase1', 'Phase2', 'Phase3', 'Phase4')


def _entry_script() -> Path:
    return ROOT / 'Core' / 'Layer3_Decay' / 'ENTRY_LAYER3.py'


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


def _parse_phase(phase: str | None) -> str | None:
    if phase is None or not str(phase).strip():
        return None
    value = str(phase).strip()
    if value not in LAYER3_ALLOWED_PHASES:
        raise ValueError(f'未知 Phase: {value}')
    return value


def _date_to_iso_week(text: str) -> str:
    day = datetime.strptime(text, '%Y-%m-%d').date()
    iso_year, iso_week, _ = day.isocalendar()
    return f'{iso_year}-W{iso_week:02d}'


def _build_target_from_failed_log(failed_log_payload: dict[str, Any], *, manual_phase: str | None, manual_agents: list[str] | None) -> dict[str, Any]:
    week = str(failed_log_payload.get('week', '') or '').strip()
    if not week:
        raise ValueError('failed_log 缺少 week')

    if manual_phase is not None:
        phase = manual_phase
    else:
        raw_failed_phase = str(failed_log_payload.get('failed_phase', '') or '').strip()
        phase = raw_failed_phase or None
        if phase is not None and phase not in LAYER3_ALLOWED_PHASES:
            raise ValueError(f'failed_log 中的 failed_phase 非法: {phase}')

    if manual_agents is not None:
        agents = manual_agents
    else:
        raw_failed_agents = failed_log_payload.get('failed_agents', [])
        if isinstance(raw_failed_agents, list):
            parsed = [str(item).strip() for item in raw_failed_agents if str(item).strip()]
            agents = parsed or None
        else:
            agents = None

    return {
        'week': week,
        'phase': phase,
        'agents': agents,
    }


def _build_manual_target(*, date_text: str | None, week: str | None, phase: str | None, agents: list[str] | None) -> dict[str, Any]:
    if date_text and week:
        raise ValueError('--date 不能与 --week 同时使用')
    if not date_text and not week:
        raise ValueError('手动模式下必须提供 --date 或 --week')

    target_week = _date_to_iso_week(date_text) if date_text else str(week).strip()
    if not target_week:
        raise ValueError('week 解析后为空')
    return {
        'week': target_week,
        'phase': phase,
        'agents': agents,
    }


def _run_single_target(*, week: str, phase: str | None, agents: list[str] | None, run_name: str, apply_cleanup: bool) -> dict[str, Any]:
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
    if phase:
        cmd.extend(['--Phase', phase])
    if agents:
        cmd.extend(['--agent', ','.join(agents)])
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
        'phase': phase,
        'agents': agents,
        'success': success,
        'returncode': proc.returncode,
        'entry_note': (parsed_stdout or {}).get('note') if isinstance(parsed_stdout, dict) else None,
        'failed_phase': (parsed_stdout or {}).get('failed_phase') if isinstance(parsed_stdout, dict) else None,
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
    parser = argparse.ArgumentParser(description='Layer3 Decay maintenance rerun script')
    parser.add_argument('--date', default=None, help='指定某个日期；脚本会自动换算到所属 ISO week')
    parser.add_argument('--week', default=None, help='指定 target ISO week，例如 2026-W18')
    parser.add_argument('--agent', default=None, help='指定 agent；支持逗号分隔多个 agent')
    parser.add_argument('--failed-log', default=None, help='从某个 Layer3 failed_log 推导 rerun 目标')
    parser.add_argument('--run-name', default=None, help='透传给 ENTRY_LAYER3.py 的 manual run name')
    parser.add_argument('--Phase', '--phase', dest='phase', default=None, choices=LAYER3_ALLOWED_PHASES)
    parser.add_argument('--apply_cleanup', action='store_true', help='显式允许 rerun 执行 destructive cleanup；默认关闭')
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    has_failed_log = bool(args.failed_log)
    has_date = bool(args.date)
    has_week = bool(args.week)

    if has_failed_log and (has_date or has_week):
        raise ValueError('--failed-log 不能与 --date / --week 同时使用')
    if has_date and has_week:
        raise ValueError('--date 不能与 --week 同时使用')
    if not has_failed_log and not has_date and not has_week:
        raise ValueError('必须提供 --failed-log，或提供 --date，或提供 --week')


def main() -> None:
    args = parse_args()
    try:
        _validate_args(args)
        run_name = str(args.run_name or _default_run_name())
        manual_agents = _parse_agent_csv(args.agent)
        manual_phase = _parse_phase(args.phase)

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
                    'week': failed_log_payload.get('week'),
                    'note': '该 failed_log 已成功 rerun；若要覆写请手动处理后再运行。',
                })
                return

        if failed_log_payload is not None:
            target = _build_target_from_failed_log(failed_log_payload, manual_phase=manual_phase, manual_agents=manual_agents)
            mode = 'failed-log'
        else:
            target = _build_manual_target(date_text=args.date, week=args.week, phase=manual_phase, agents=manual_agents)
            mode = 'manual'

        result = _run_single_target(
            week=str(target['week']),
            phase=target.get('phase'),
            agents=target.get('agents'),
            run_name=run_name,
            apply_cleanup=bool(args.apply_cleanup),
        )

        overall_success = bool(result.get('success', False))
        if failed_log_path and overall_success:
            _mark_failed_log_rerun_done(failed_log_path, run_name=run_name)

        output_success({
            'success': overall_success,
            'mode': mode,
            'run_name': run_name,
            'apply_cleanup': bool(args.apply_cleanup),
            'result': result,
            'failed_log': str(Path(failed_log_path)) if failed_log_path else None,
            'failed_log_marked_rerun': bool(failed_log_path and overall_success),
            'note': 'Layer3 rerun 执行完成。' if overall_success else 'Layer3 rerun 执行结束，但存在失败目标。',
        })
    except Exception as exc:  # noqa: BLE001
        output_failure(str(exc))


if __name__ == '__main__':
    main()
