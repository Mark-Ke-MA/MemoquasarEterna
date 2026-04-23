#!/usr/bin/env python3
"""Layer0 总入口：计算窗口 -> 调 OpenClaw adapter -> postprocess -> 写 L1/L2/staging。"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer0_Extract.preprocess import load_overall_config, compute_window, build_store_paths
from Core.Layer0_Extract.postprocess import build_write_bundle
from Core.harness_connector import get_required_connector_callable, load_harness_connector


def load_fetch_layer0_input(harness: str):
    connector = load_harness_connector(repo_root=ROOT, harness=harness)
    return get_required_connector_callable(connector, 'extract')


def dbg(msg: str):
    print(f'[DBG] {msg}', file=sys.stderr)


def output_success(data: dict):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def output_failure(error: str):
    print(json.dumps({'success': False, 'error': error}, ensure_ascii=False), flush=True)
    sys.exit(1)


def write_json_atomic(path: str, data, *, indent: int = 2):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.tmp-', suffix='.json', dir=parent or None)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def read_json_if_exists(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def merge_unique_lists(existing, new):
    merged = []
    seen = set()
    for item in existing or []:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, (dict, list)) else item
        if key not in seen:
            seen.add(key)
            merged.append(item)
    for item in new or []:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, (dict, list)) else item
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def merge_l1(existing: dict | None, new: dict) -> dict:
    if not existing:
        return new
    merged = dict(new)
    merged['stats'] = dict(new.get('stats', {}))
    for key in ('total_turns', 'user_turns', 'assistant_turns', 'tools_called_count'):
        merged['stats'][key] = int(existing.get('stats', {}).get(key, 0)) + int(new.get('stats', {}).get(key, 0))
    merged['generated_at'] = new.get('generated_at')
    merged['status'] = dict(existing.get('status', {})) if isinstance(existing.get('status'), dict) else dict(new.get('status', {}))
    for key in ('memory_signal', 'summary', 'tags', 'day_mood', 'topics', 'decisions', 'todos', 'key_items', 'emotional_peaks', '_compress_hints'):
        if existing.get(key) is not None:
            merged[key] = existing.get(key)
    return merged


def merge_l2(existing: dict | None, new: dict) -> dict:
    if not existing:
        return new
    merged = dict(new)
    merged['conversation_excerpts'] = merge_unique_lists(existing.get('conversation_excerpts', []), new.get('conversation_excerpts', []))
    merged['status'] = dict(existing.get('status', {})) if isinstance(existing.get('status'), dict) else dict(new.get('status', {}))
    return merged


def merge_staging(existing: dict | None, new: dict) -> dict:
    if not existing:
        return new
    merged = dict(new)
    merged['conversation_excerpts'] = merge_unique_lists(existing.get('conversation_excerpts', []), new.get('conversation_excerpts', []))
    merged['generated_at'] = new.get('generated_at')
    return merged


def parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--agent', required=True)
    parser.add_argument('--date', required=True)
    parser.add_argument('--write-l2', action='store_true')
    parser.add_argument('--write-l1-init', action='store_true')
    parser.add_argument('--write-staging', action='store_true')
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--session-alert', action='store_true')
    parser.add_argument('--session-file', default=None)
    parser.set_defaults(write_l2=True, write_l1_init=False, write_staging=False, update=False)
    try:
        return parser.parse_args()
    except SystemExit:
        output_failure('参数错误：--agent <agent_id> --date YYYY-MM-DD [--write-l2] [--write-l1-init] [--write-staging] [--update] [--session-alert] [--session-file <path>]')


def main():
    args = parse_args()
    agent_id = args.agent
    overall_config = load_overall_config()
    harness = overall_config.get('harness')
    fetch_layer0_input = load_fetch_layer0_input(harness)
    store_paths = build_store_paths(agent_id, overall_config)

    memory_date_str = args.date
    dbg(f'agent={agent_id}, memory_date={memory_date_str}, harness={harness}')

    window_start, window_end = compute_window(memory_date_str, overall_config)
    raw = fetch_layer0_input(
        agent_id,
        memory_date_str,
        window_start,
        window_end,
        session_file=args.session_file,
        session_alert_enabled=args.session_alert,
    )

    merged = raw['merged']
    month_dir = os.path.join(store_paths['memory_surface_root'], memory_date_str[:7])
    l1_path = os.path.join(month_dir, f'{memory_date_str}_l1.json')
    l2_path = os.path.join(month_dir, f'{memory_date_str}_l2.json')

    total_turns = merged['stats'].get('total_turns', 0)
    if total_turns == 0:
        dbg('当天无对话（total_turns=0），写 .noconversation 标记后退出')
        os.makedirs(month_dir, exist_ok=True)
        marker_suffix = overall_config.get('empty_conversation_marker_suffix', '.noconversation')
        marker_path = os.path.join(month_dir, f'{memory_date_str}{marker_suffix}')
        try:
            with open(marker_path, 'w', encoding='utf-8') as f:
                f.write(f'no conversations on {memory_date_str}\n')
            dbg(f'标记文件已写入: {marker_path}')
        except Exception as e:
            dbg(f'写入标记文件失败（非致命）: {e}')
        output_failure('no conversations today')

    bundle = build_write_bundle(
        agent_id=agent_id,
        target_date_str=memory_date_str,
        merged=merged,
        sessions_to_process=raw['sessions_to_process'],
        l1_path=l1_path,
        l2_path=l2_path,
    )

    l1_result = bundle['l1_result']
    l2_result = bundle['l2_result']
    staging_ready = bundle['staging_ready']

    if args.session_alert and raw.get('needs_alert') and raw.get('alert_message'):
        staging_dir = store_paths['staging_surface_agent_root']
        os.makedirs(staging_dir, exist_ok=True)
        alert_path = os.path.join(staging_dir, 'extraction_alert.json')
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=staging_dir, delete=False, suffix='.tmp', encoding='utf-8') as f:
                json.dump({'alert': True, 'message': raw['alert_message']}, f, ensure_ascii=False)
                tmp_path = f.name
            os.replace(tmp_path, alert_path)
            dbg(f'staging alert 已写入: {alert_path}')
        except Exception as e:
            dbg(f'staging alert 写入失败: {e}')

    os.makedirs(month_dir, exist_ok=True)

    if args.write_l2:
        existing_l2 = read_json_if_exists(l2_path) if args.update else None
        final_l2 = merge_l2(existing_l2, l2_result) if args.update else l2_result
        write_json_atomic(l2_path, final_l2)

    if args.write_l1_init:
        existing_l1 = read_json_if_exists(l1_path) if args.update else None
        final_l1 = merge_l1(existing_l1, l1_result) if args.update else l1_result
        write_json_atomic(l1_path, final_l1)

    if args.write_staging:
        staging_ready_path = os.path.join(store_paths['staging_surface_agent_root'], 'extraction_ready.json')
        os.makedirs(os.path.dirname(staging_ready_path), exist_ok=True)
        existing_stage = read_json_if_exists(staging_ready_path) if args.update else None
        final_stage = merge_staging(existing_stage, staging_ready) if args.update else staging_ready
        write_json_atomic(staging_ready_path, final_stage)

    output_success(dict(l1_result))


if __name__ == '__main__':
    main()
