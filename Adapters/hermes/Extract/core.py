#!/usr/bin/env python3
"""Hermes Layer0 adapter: read state.db and normalize messages into Memoquasar turns."""
from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .message_normalize import normalize_message_content
from ..hermes_shared_funcs import LoadConfig, profile_state_db_path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPACTION_MARKER_PREFIX = '[CONTEXT COMPACTION'


def _epoch_seconds(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _utc_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)


def _query_messages(db_path: Path, *, start_ts: float, end_ts: float) -> list[sqlite3.Row]:
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
              m.id AS message_id,
              m.session_id AS session_id,
              m.role AS role,
              m.content AS content,
              m.timestamp AS timestamp,
              s.source AS session_source,
              s.title AS session_title,
              s.parent_session_id AS parent_session_id
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE m.timestamp >= ?
              AND m.timestamp < ?
              AND m.role IN ('user', 'assistant')
              AND m.content IS NOT NULL
              AND trim(m.content) != ''
            ORDER BY m.timestamp ASC, m.id ASC
            """,
            (start_ts, end_ts),
        ).fetchall()
    finally:
        conn.close()
    return rows


def _query_tool_call_rows(db_path: Path, *, start_ts: float, end_ts: float) -> list[sqlite3.Row]:
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT tool_calls
            FROM messages
            WHERE timestamp >= ?
              AND timestamp < ?
              AND role = 'assistant'
              AND tool_calls IS NOT NULL
              AND trim(tool_calls) != ''
            ORDER BY timestamp ASC, id ASC
            """,
            (start_ts, end_ts),
        ).fetchall()
    finally:
        conn.close()
    return rows


def _tool_call_items(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _tool_call_name(item: dict[str, Any]) -> str:
    direct_name = str(item.get('name', '') or '').strip()
    if direct_name:
        return direct_name
    function = item.get('function')
    if isinstance(function, dict):
        return str(function.get('name', '') or '').strip()
    return ''


def _tool_call_arguments(item: dict[str, Any]) -> dict[str, Any]:
    function = item.get('function')
    raw_args: Any = item.get('arguments')
    if raw_args is None and isinstance(function, dict):
        raw_args = function.get('arguments')
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _tool_stats(db_path: Path, *, start_ts: float, end_ts: float) -> dict[str, Any]:
    tools_used: set[str] = set()
    files_read: list[str] = []
    files_written: list[str] = []
    commands_run: list[str] = []
    count = 0

    for row in _query_tool_call_rows(db_path, start_ts=start_ts, end_ts=end_ts):
        for item in _tool_call_items(row['tool_calls']):
            tool_name = _tool_call_name(item)
            if not tool_name:
                continue
            count += 1
            tools_used.add(tool_name)
            args = _tool_call_arguments(item)
            path_val = args.get('file_path') or args.get('path')
            tool_name_lower = tool_name.lower()
            if tool_name_lower in {'read', 'read_file'} and path_val:
                value = str(path_val)
                if value not in files_read:
                    files_read.append(value)
            elif tool_name_lower in {'write', 'write_file', 'edit'} and path_val:
                value = str(path_val)
                if value not in files_written:
                    files_written.append(value)
            elif tool_name_lower in {'terminal', 'exec'}:
                cmd = str(args.get('command', '') or '').strip()
                if cmd:
                    commands_run.append(cmd[:200] + ('...' if len(cmd) > 200 else ''))

    return {
        'tools_called_count': count,
        'tools_used': sorted(tools_used),
        'files_read': files_read,
        'files_written': files_written,
        'commands_run': commands_run,
    }


def _is_compaction_marker(role: str, content: str | None) -> bool:
    if role != 'assistant':
        return False
    return str(content or '').lstrip().startswith(COMPACTION_MARKER_PREFIX)


def _compaction_replay_message_ids(rows: list[sqlite3.Row]) -> set[int]:
    marker_positions: dict[str, int] = {}
    for index, row in enumerate(rows):
        session_id = str(row['session_id'] or '').strip()
        parent_session_id = str(row['parent_session_id'] or '').strip()
        role = str(row['role'] or '').strip()
        if (
            session_id
            and parent_session_id
            and session_id not in marker_positions
            and _is_compaction_marker(role, row['content'])
        ):
            marker_positions[session_id] = index

    if not marker_positions:
        return set()

    skipped_ids: set[int] = set()
    for index, row in enumerate(rows):
        session_id = str(row['session_id'] or '').strip()
        marker_index = marker_positions.get(session_id)
        if marker_index is not None and index <= marker_index:
            skipped_ids.add(int(row['message_id']))
    return skipped_ids


def _source_sessions(rows: list[sqlite3.Row], db_path: Path) -> list[tuple[str, str]]:
    seen: set[str] = set()
    sessions: list[tuple[str, str]] = []
    source_ref = f'sqlite:{db_path}'
    for row in rows:
        session_id = str(row['session_id'] or '').strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        sessions.append((session_id, source_ref))
    return sessions


def fetch_hermes_layer0_input(
    agent_id: str,
    target_date_str: str,
    window_start,
    window_end,
    *,
    session_file: str | None = None,
    session_alert_enabled: bool = False,
) -> dict:
    if session_file:
        raise ValueError('Hermes adapter 不支持 --session-file；state.db 是唯一数据源')

    config = LoadConfig(REPO_ROOT)
    db_path = profile_state_db_path(config, agent_id)
    if not db_path.exists():
        raise FileNotFoundError(f'Hermes state.db 不存在: {db_path}')

    local_tz = ZoneInfo(str(config.overall_config.get('timezone', 'Europe/London') or 'Europe/London'))
    start_ts = _epoch_seconds(window_start)
    end_ts = _epoch_seconds(window_end)
    rows = _query_messages(
        db_path,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    tool_stats = _tool_stats(db_path, start_ts=start_ts, end_ts=end_ts)
    compaction_replay_ids = _compaction_replay_message_ids(rows)

    stats = {
        'total_turns': 0,
        'user_turns': 0,
        'assistant_turns': 0,
        'tools_called_count': tool_stats['tools_called_count'],
    }
    turns: list[dict] = []
    for row in rows:
        if int(row['message_id']) in compaction_replay_ids:
            continue

        role = str(row['role'] or '').strip()
        content = normalize_message_content(role, row['content'])
        if not content:
            continue

        ts = _utc_datetime(float(row['timestamp']))
        stats['total_turns'] += 1
        if role == 'user':
            stats['user_turns'] += 1
        elif role == 'assistant':
            stats['assistant_turns'] += 1

        turns.append({
            'role': role,
            'time': ts.astimezone(local_tz).strftime('%H:%M'),
            'timestamp': ts.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'content': content,
            'message_type': 'text',
            'session_id': str(row['session_id'] or ''),
            'turn_index': len(turns),
        })

    source_sessions = _source_sessions(rows, db_path)
    return {
        'sessions_to_process': source_sessions,
        'needs_alert': False,
        'alert_message': None,
        'merged': {
            'stats': stats,
            'tools_used': tool_stats['tools_used'],
            'files_read': tool_stats['files_read'],
            'files_written': tool_stats['files_written'],
            'commands_run': tool_stats['commands_run'],
            'turns': turns,
        },
        'source': {
            'harness': 'hermes',
            'agent_id': agent_id,
            'profile': agent_id,
            'state_db': str(db_path),
            'target_date': target_date_str,
            'session_alert_enabled': bool(session_alert_enabled),
        },
    }
