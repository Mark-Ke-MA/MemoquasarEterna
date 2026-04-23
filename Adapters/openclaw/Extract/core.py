#!/usr/bin/env python3
"""OpenClaw Layer0 adapter：只负责把原始 session 取出并清洗成统一 turns。"""
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os

from .session_parser import parse_session
from ..openclaw_shared_funcs import dbg, output_failure, LoadConfig, SessionFinder


REPO_ROOT = Path(__file__).resolve().parents[3]


def _render_openclaw_path(config: LoadConfig, template: str, agent_id: str) -> str:
    adapter_dirname = str(config.openclaw_config.get('adapter_dirname', config.adapter_root.name) or config.adapter_root.name)
    archive_structure = config.overall_config.get('archive_dir_structure', {}) if isinstance(config.overall_config, dict) else {}
    archive_harness_dirname = str(archive_structure.get('harness', 'harness') or 'harness')
    return os.path.expanduser(template.format(
        agentId=agent_id,
        agent_id=agent_id,
        code_dir=config.code_root,
        store_dir=config.store_root,
        archive_dir=os.path.expanduser(config.overall_config['archive_dir']),
        adapter_dirname=adapter_dirname,
        archive_harness_dirname=archive_harness_dirname,
    ))


def _session_paths(config: LoadConfig, agent_id: str) -> dict:
    sessions_path = _render_openclaw_path(config, config.openclaw_config['sessions_path'], agent_id)
    return {
        'sessions_path': sessions_path,
        'sessions_json_path': os.path.join(sessions_path, 'sessions.json'),
        'sessions_registry_path': _render_openclaw_path(config, config.openclaw_config['sessions_registry_path'], agent_id),
        'sessions_registry_archive_path': _render_openclaw_path(config, config.openclaw_config['sessions_registry_archive_path'], agent_id),
        'sessions_files_archive_dir': _render_openclaw_path(config, config.openclaw_config['sessions_files_archive_dir'], agent_id),
    }


def _read_known_sessions(path: str) -> list[tuple[str, str]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return []
    history = data.get('history_sessions', []) if isinstance(data, dict) else []
    out: list[tuple[str, str]] = []
    for entry in history:
        if not isinstance(entry, dict) or not entry.get('date'):
            continue
        for session in entry.get('sessions', []):
            sid = session.get('sessionId') if isinstance(session, dict) else None
            if sid:
                out.append((entry['date'], sid))
    return out


def _find_session_file_for_uuid(sessions_path: str, session_id: str) -> str | None:
    if not os.path.isdir(sessions_path):
        return None
    plain = os.path.join(sessions_path, f'{session_id}.jsonl')
    if os.path.exists(plain):
        return plain
    reset_files = sorted([f for f in os.listdir(sessions_path) if f.startswith(session_id) and '.reset.' in f], reverse=True)
    if reset_files:
        return os.path.join(sessions_path, reset_files[0])
    return None


def _archived_sessions_for_date(registry_archive_path: str, target_date_str: str) -> list[str]:
    if not os.path.exists(registry_archive_path):
        return []
    try:
        with open(registry_archive_path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return []
    sessions = data.get('sessions', {}) if isinstance(data, dict) else {}
    if not isinstance(sessions, dict):
        return []
    matched: list[tuple[str, str]] = []
    for sid, entry in sessions.items():
        if not isinstance(sid, str) or not isinstance(entry, dict):
            continue
        dates = entry.get('dates', [])
        if not isinstance(dates, list) or target_date_str not in dates:
            continue
        first_seen = str(entry.get('first_seen_min', '') or '')
        matched.append((first_seen, sid))
    matched.sort(key=lambda item: ((not item[0]), item[0], item[1]))
    return [sid for _, sid in matched]


def _sessions_for_window(registry_path: str, target_date_str: str, sessions_path: str, *, registry_archive_path: str | None = None, sessions_files_archive_dir: str | None = None) -> list[tuple[str, str]]:
    if os.path.exists(registry_path):
        try:
            with open(registry_path, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}
    history = data.get('history_sessions', []) if isinstance(data, dict) else []
    date_entry = next((e for e in history if isinstance(e, dict) and e.get('date') == target_date_str), None)

    results: list[tuple[str, str]] = []
    if date_entry:
        for session in date_entry.get('sessions', []):
            if not isinstance(session, dict):
                continue
            sid = session.get('sessionId')
            if not sid:
                continue
            found = _find_session_file_for_uuid(sessions_path, sid)
            if not found:
                found = _find_session_file_for_uuid(sessions_files_archive_dir or '', sid)
            if found:
                results.append((sid, found))
        return results

    archived_ids = _archived_sessions_for_date(registry_archive_path or '', target_date_str)
    if not archived_ids:
        return []
    for sid in archived_ids:
        found = _find_session_file_for_uuid(sessions_files_archive_dir or '', sid)
        if found:
            results.append((sid, found))
    return results


def fetch_openclaw_layer0_input(agent_id: str, target_date_str: str, window_start, window_end, *, session_file: str | None = None, session_alert_enabled: bool = False) -> dict:
    Config = LoadConfig(REPO_ROOT)
    SFinder = SessionFinder(REPO_ROOT, agent_id)
    dbg(f'overall config loaded: {list(Config.overall_config.keys())}')
    dbg(f'openclaw config loaded: {list(Config.openclaw_config.keys())}')

    local_tz = ZoneInfo(Config.overall_config.get('timezone', 'Europe/London'))
    paths = _session_paths(Config, agent_id)
    if session_file:
        session_file = os.path.expanduser(session_file)
        if not os.path.exists(session_file):
            output_failure(f'--session-file 指定的文件不存在: {session_file}')
        current_session_id = session_file.split('.jsonl')[0]
        sessions_to_process = [(current_session_id, session_file)]
        needs_alert = False
    else:
        current_session_id = SFinder.find_current_session_id()
        if not current_session_id:
            output_failure(f'未找到 {agent_id} 的当前 direct session')
        sessions_to_process = _sessions_for_window(
            paths['sessions_registry_path'],
            target_date_str,
            paths['sessions_path'],
            registry_archive_path=paths['sessions_registry_archive_path'],
            sessions_files_archive_dir=paths['sessions_files_archive_dir'],
        )
        needs_alert = current_session_id not in [s[0] for s in sessions_to_process]
        current_session_path = os.path.join(paths['sessions_path'], f'{current_session_id}.jsonl')
        if current_session_id not in [s[0] for s in sessions_to_process]:
            sessions_to_process.append((current_session_id, current_session_path))

    alert_msg = None
    if needs_alert and session_alert_enabled:
        alert_msg = (
            f'⚠️ [记忆提取告警] {agent_id} / {target_date_str}\n'
            f'当前 session 不在注册表中，可能存在注册延迟或极短 session 漏记。\n'
            f'已知 sessions: {[s[0][:8] for s in sessions_to_process[:-1]]}，当前: {current_session_id[:8]}...'
        )
        dbg(f'ALERT: {alert_msg}')

    merged = None
    for sid, sfile in sessions_to_process:
        dbg(f'解析 session: {sid[:8]} <- {sfile}')
        parsed = parse_session(sfile, window_start, window_end, local_tz=local_tz)
        parsed['session_id'] = sid
        parsed['session_file'] = sfile
        for turn in parsed.get('turns', []):
            turn['session_id'] = sid
        if merged is None:
            merged = parsed
        else:
            merged['turns'] += parsed['turns']
            for k in ('total_turns', 'user_turns', 'assistant_turns', 'tools_called_count'):
                merged['stats'][k] += parsed['stats'].get(k, 0)
            for k in ('tools_used', 'files_read', 'files_written', 'commands_run'):
                seen = set(merged[k])
                for item in parsed.get(k, []):
                    if item not in seen:
                        seen.add(item)
                        merged[k].append(item)

    if merged is None:
        output_failure('当天无对话或 session 解析失败')

    return {
        'sessions_to_process': sessions_to_process,
        'needs_alert': needs_alert,
        'alert_message': alert_msg,
        'merged': merged,
    }
