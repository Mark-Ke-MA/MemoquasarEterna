#!/usr/bin/env python3
"""把 OpenClaw 原始 session.jsonl 解析为规范化 turns。"""
import json
from datetime import datetime, timezone

from .message_normalize import clean_user_text, redact, strip_reply_tag_prefix
from ..openclaw_shared_funcs import output_failure


def parse_session(session_file: str, window_start, window_end, local_tz=timezone.utc) -> dict:
    """读取一个 session 文件，提取窗口内所有 user/assistant turns。"""
    stats = {'total_turns': 0, 'user_turns': 0, 'assistant_turns': 0, 'tools_called_count': 0}
    tools_used_set = set()
    files_read = []
    files_written = []
    commands_run = []
    turns = []

    try:
        with open(session_file, encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        output_failure(f'读取 session 文件失败: {e}')

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if obj.get('type') != 'message':
            continue

        ts_str = obj.get('timestamp', '')
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        except ValueError:
            continue
        if not (window_start <= ts < window_end):
            continue

        msg = obj.get('message', {})
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        if role == 'toolResult':
            continue

        stats['total_turns'] += 1
        if role == 'user':
            stats['user_turns'] += 1
        elif role == 'assistant':
            stats['assistant_turns'] += 1

        text_parts = []
        message_type = 'text'

        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get('type')
                if block_type == 'text':
                    t = block.get('text', '').strip()
                    if t:
                        if role == 'assistant':
                            t = strip_reply_tag_prefix(t)
                            if t:
                                text_parts.append(t)
                        else:
                            t, block_message_type = clean_user_text(t)
                            message_type = block_message_type
                            if t:
                                text_parts.append(t)
                elif block_type == 'thinking':
                    # thinking 块不进入对话摘录
                    pass
                elif block_type == 'toolCall':
                    tool_name = block.get('name', '')
                    args = block.get('arguments', {})
                    if not isinstance(args, dict):
                        args = {}
                    tools_used_set.add(tool_name)
                    stats['tools_called_count'] += 1
                    tool_name_lower = tool_name.lower()
                    path_val = args.get('file_path') or args.get('path')
                    if tool_name_lower == 'read' and path_val:
                        if path_val not in files_read:
                            files_read.append(path_val)
                    elif tool_name_lower in ('write', 'edit') and path_val:
                        if path_val not in files_written:
                            files_written.append(path_val)
                    if tool_name_lower == 'exec':
                        cmd = args.get('command', '')
                        if cmd:
                            cmd_truncated = cmd[:200] + ('...' if len(cmd) > 200 else '')
                            commands_run.append(redact(cmd_truncated))
        elif isinstance(content, str):
            t = content.strip()
            if t:
                if role == 'assistant':
                    t = strip_reply_tag_prefix(t)
                    if t:
                        text_parts.append(t)
                else:
                    t, message_type = clean_user_text(t)
                    if t:
                        text_parts.append(t)

        if text_parts and role in ('user', 'assistant'):
            combined_text = redact(' '.join(text_parts))
            time_str = ts.astimezone(local_tz).strftime('%H:%M')
            turns.append({
                'role': role,
                'time': time_str,
                'timestamp': ts.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'content': combined_text,
                'message_type': message_type,
                'session_id': obj.get('sessionId') or obj.get('session_id') or '',
                'turn_index': len(turns),
            })

    return {
        'stats': stats,
        'tools_used': sorted(tools_used_set),
        'files_read': files_read,
        'files_written': files_written,
        'commands_run': commands_run,
        'turns': turns,
    }
