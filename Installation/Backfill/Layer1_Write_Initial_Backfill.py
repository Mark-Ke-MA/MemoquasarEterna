#!/usr/bin/env python3
"""Layer1 Write initial backfill script.

职责：
- 在给定日期范围内串行调用 Layer1_Write/ENTRY_LAYER1.py
- 默认面向全部 agents
- overwrite=false 时，跳过已存在产物的 agent/day 组合
- 把 skip existed 记录追加到 logs/Layer1_Write_logs/manual/<run_name>/skip_existed.txt
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer1_Write.shared import LoadConfig, build_layer0_artifact_paths, build_store_paths
from Core.shared_funcs import output_failure, output_success


def _entry_script() -> Path:
    return ROOT / 'Core' / 'Layer1_Write' / 'ENTRY_LAYER1.py'


def _default_run_name() -> str:
    return datetime.now(timezone.utc).strftime('Initial_backfill_%Y-%m-%dT%H-%M-%SZ')


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


def _load_json_dict(path: str | Path) -> dict[str, Any] | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    try:
        with open(file_path, encoding='utf-8') as f:
            payload = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def _layer1_logs_manual_root(cfg: dict[str, Any], run_name: str) -> Path:
    store_root = Path(str(cfg['store_dir'])).expanduser()
    logs_cfg = cfg.get('store_dir_structure', {}).get('logs', {}) if isinstance(cfg.get('store_dir_structure', {}), dict) else {}
    root = str(logs_cfg.get('root', 'logs') or 'logs')
    layer1_cfg = logs_cfg.get('layer1_write', {}) if isinstance(logs_cfg.get('layer1_write'), dict) else {}
    layer1_root = str(layer1_cfg.get('root', 'Layer1_Write_logs') or 'Layer1_Write_logs')
    manual_nested = str(layer1_cfg.get('manual', 'manual') or 'manual')
    return store_root / root / layer1_root / manual_nested / run_name


def _skip_existed_file(cfg: dict[str, Any], run_name: str) -> Path:
    return _layer1_logs_manual_root(cfg, run_name) / 'skip_existed.txt'


def _latest_result_file(cfg: dict[str, Any], run_name: str) -> Path:
    return _layer1_logs_manual_root(cfg, run_name) / 'latest_result.json'


def _progress_trace_file(cfg: dict[str, Any], run_name: str) -> Path:
    return _layer1_logs_manual_root(cfg, run_name) / 'progress_trace.txt'


def _append_skip_existed(cfg: dict[str, Any], run_name: str, *, target_date: str, agent_id: str) -> None:
    path = _skip_existed_file(cfg, run_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(f'{target_date}\t{agent_id}\n')


def _append_progress_trace(cfg: dict[str, Any], run_name: str, line: str) -> None:
    path = _progress_trace_file(cfg, run_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def _l0_index_path(agent_id: str, cfg: dict[str, Any]) -> Path:
    store_paths = build_store_paths(agent_id, cfg)
    return Path(store_paths['memory_surface_root']) / 'l0_index.json'


def _has_l0_index_entry(agent_id: str, target_date: str, cfg: dict[str, Any]) -> bool:
    payload = _load_json_dict(_l0_index_path(agent_id, cfg))
    if not payload:
        return False
    entries = payload.get('entries', []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get('date', '') or '') == target_date:
            return True
    return False


def _should_skip_existing(agent_id: str, target_date: str, cfg: dict[str, Any]) -> bool:
    paths = build_layer0_artifact_paths(agent_id, target_date, cfg)
    l2_exists = Path(paths['l2_path']).exists()
    l1_exists = Path(paths['l1_path']).exists()
    nocontent_exists = Path(paths['l1_path']).with_name(f'{target_date}.nocontent').exists()

    if not l2_exists:
        return False
    if nocontent_exists:
        return True
    if l1_exists and _has_l0_index_entry(agent_id, target_date, cfg):
        return True
    return False


def _run_single_date(*, target_date: str, selected_agents: list[str] | None, run_name: str, result_write_path: str | Path) -> dict[str, Any]:
    result_path = Path(result_write_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    if result_path.exists():
        result_path.unlink()

    cmd = [
        sys.executable,
        str(_entry_script()),
        '--date',
        target_date,
        '--run-mode',
        'manual',
        '--run-name',
        run_name,
        '--output_mode',
        'write',
        '--output_write_path',
        str(result_path),
    ]
    if selected_agents is not None:
        cmd.extend(['--agent', ','.join(selected_agents)])

    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )

    parsed_result = _load_json_dict(result_path)
    result_payload = parsed_result if isinstance(parsed_result, dict) else {}
    entry_note = result_payload.get('note') if isinstance(result_payload, dict) else None
    if not entry_note and not isinstance(parsed_result, dict):
        entry_note = 'result_json_missing_or_invalid'

    return {
        'date': target_date,
        'agents': selected_agents,
        'success': proc.returncode == 0 and bool(result_payload.get('success', False)),
        'returncode': proc.returncode,
        'entry_note': entry_note,
        'fail_log_needed': bool(result_payload.get('fail_log_needed', False)),
        'fail_log_path': result_payload.get('fail_log_path'),
        'failed_agents': result_payload.get('failed_agents', []),
        'skipped_agents': result_payload.get('skipped_agents', []),
        'result_file_ok': isinstance(parsed_result, dict),
    }


def _format_agents_for_log(agents: list[str] | None) -> str:
    if agents is None:
        return 'all'
    if not agents:
        return '0()'
    return f"{len(agents)}({','.join(agents)})"


def _format_str_list(value: Any) -> str:
    if not isinstance(value, list):
        return ''
    items = [str(item).strip() for item in value if str(item).strip()]
    return ','.join(items)


def _emit_line(cfg: dict[str, Any], run_name: str, line: str) -> None:
    print(line, flush=True)
    _append_progress_trace(cfg, run_name, line)


def _print_skip_line(cfg: dict[str, Any], run_name: str, target_date: str) -> None:
    _emit_line(cfg, run_name, f'[SKIP] {target_date} | agents=all | reason=all_agents_already_exist')


def _print_result_line(cfg: dict[str, Any], run_name: str, result: dict[str, Any]) -> None:
    status = '[DONE]' if result.get('success', False) else '[FAIL]'
    target_date = str(result.get('date', '') or '')
    agents_text = _format_agents_for_log(result.get('agents'))
    fail_log_needed = 'yes' if result.get('fail_log_needed', False) else 'no'
    note = str(result.get('entry_note', '') or '')
    _emit_line(cfg, run_name, f'{status} {target_date} | agents={agents_text} | failed_log={fail_log_needed} | note={note}')

    failed_agents = _format_str_list(result.get('failed_agents', []))
    skipped_agents = _format_str_list(result.get('skipped_agents', []))
    fail_log_path = str(result.get('fail_log_path', '') or '')
    if (not result.get('success', False)) or result.get('fail_log_needed', False):
        details: list[str] = []
        if failed_agents:
            details.append(f'failed_agents={failed_agents}')
        if skipped_agents:
            details.append(f'skipped_agents={skipped_agents}')
        if fail_log_path:
            details.append(f'fail_log={fail_log_path}')
        if details:
            _emit_line(cfg, run_name, f"       {' | '.join(details)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Layer1 Write initial backfill script')
    parser.add_argument('--start-date', required=True, help='初始化回填起始日期 YYYY-MM-DD')
    parser.add_argument('--end-date', required=True, help='初始化回填结束日期 YYYY-MM-DD')
    parser.add_argument('--overwrite', action='store_true', help='若提供，则不做存在性跳过，直接全量重跑')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        cfg = LoadConfig(ROOT).overall_config
        all_agents = [str(agent_id).strip() for agent_id in (cfg.get('agentId_list', []) or []) if str(agent_id).strip()]
        if not all_agents:
            raise ValueError('OverallConfig.json 中 agentId_list 为空')

        run_name = _default_run_name()
        result_write_path = _latest_result_file(cfg, run_name)
        target_dates = _expand_date_range(args.start_date, args.end_date)

        results: list[dict[str, Any]] = []
        overall_success = True
        skipped_existing_count = 0
        fully_skipped_dates: list[str] = []

        for target_date in target_dates:
            if args.overwrite:
                selected_agents = None
            else:
                remaining_agents: list[str] = []
                for agent_id in all_agents:
                    if _should_skip_existing(agent_id, target_date, cfg):
                        _append_skip_existed(cfg, run_name, target_date=target_date, agent_id=agent_id)
                        skipped_existing_count += 1
                    else:
                        remaining_agents.append(agent_id)

                if not remaining_agents:
                    fully_skipped_dates.append(target_date)
                    results.append({
                        'date': target_date,
                        'agents': [],
                        'success': True,
                        'returncode': 0,
                        'entry_note': '该日期所有 agents 均已存在，整天跳过。',
                        'fail_log_needed': False,
                        'fail_log_path': None,
                    })
                    _print_skip_line(cfg, run_name, target_date)
                    continue
                selected_agents = remaining_agents

            result = _run_single_date(
                target_date=target_date,
                selected_agents=selected_agents,
                run_name=run_name,
                result_write_path=result_write_path,
            )
            results.append(result)
            _print_result_line(cfg, run_name, result)
            if not result.get('success', False):
                overall_success = False

        output_success({
            'success': overall_success,
            'run_name': run_name,
            'start_date': args.start_date,
            'end_date': args.end_date,
            'overwrite': bool(args.overwrite),
            'target_count': len(target_dates),
            'skipped_existing_count': skipped_existing_count,
            'fully_skipped_dates': fully_skipped_dates,
            'skip_existed_path': str(_skip_existed_file(cfg, run_name)),
            'results': results,
            'note': 'Layer1 initial backfill 执行完成。' if overall_success else 'Layer1 initial backfill 执行结束，但存在失败日期。',
        })
    except Exception as exc:  # noqa: BLE001
        output_failure(str(exc))


if __name__ == '__main__':
    main()
