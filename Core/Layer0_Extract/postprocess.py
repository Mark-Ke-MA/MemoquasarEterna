#!/usr/bin/env python3
"""Layer0 后处理：把 adapter 返回的原始数据清洗并组装成写入结构。"""
from datetime import datetime, timezone

from Core.shared_funcs import LoadConfig


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _initial_l2_status(initialized_at: str) -> dict:
    return {
        'initialized': True,
        'initialized_at': initialized_at,
        'archived': False,
        'archived_at': None,
        'trimmed': False,
        'trimmed_at': None,
        'restored': False,
        'restored_at': None,
    }


def _initial_l1_status(initialized_at: str) -> dict:
    return {
        'initialized': True,
        'initialized_at': initialized_at,
        'filled': False,
        'filled_at': None,
        'archived': False,
        'archived_at': None,
        'restored': False,
        'restored_at': None,
    }


def _sort_turns(turns: list[dict]) -> list[dict]:
    """按时间与会话顺序排序，保证输出稳定。"""
    def key(t):
        return (
            t.get('timestamp', ''),
            t.get('session_id', ''),
            t.get('turn_index', 0),
        )
    return sorted(turns, key=key)


def _public_excerpt(turn: dict, turn_index: int) -> dict:
    """只保留 active 版 L2 conversation_excerpts 需要的字段。"""
    return {
        'role': turn.get('role', ''),
        'time': turn.get('time', ''),
        'content': turn.get('content', ''),
        'message_type': turn.get('message_type', 'text'),
        'turn_index': turn_index,
    }


def _active_schema_version() -> str:
    overall_cfg = LoadConfig().overall_config
    return str(overall_cfg.get('active_schema_version', '') or '').strip()


def _truncate_excerpts(excerpts: list, target_tokens: int = 20000) -> list:
    """历史保留的 digest 采样函数。

    背景：它最初用于旧版 Stage 2 的 LLM 入口，在上下文预算紧张时对
    conversation_excerpts 做均匀降采样，减少输入体积。

    现状：它不参与任何主流程；当前代码中也不再有对它的调用。
    未来如果重新出现需要“轻量视图”或调试采样的需求，可以再显式接回。
    """
    total_chars = sum(len(e.get('content', '')) for e in excerpts)
    estimated_tokens = total_chars / 3 if total_chars else 0
    if estimated_tokens <= target_tokens:
        return excerpts
    step = max(2, int(estimated_tokens / target_tokens))
    return excerpts[::step]


def assemble_layer0_payload(*, agent_id: str, target_date_str: str, turns: list[dict], stats: dict,
                            source_sessions: list[dict]) -> dict:
    """把清洗后的 turns 组装成 Layer0 的标准 payload。"""
    turns_sorted = _sort_turns(turns)
    public_excerpts = [_public_excerpt(t, idx) for idx, t in enumerate(turns_sorted)]
    generated_at = _now_iso()
    active_schema_version = _active_schema_version()
    return {
        'schema_version': active_schema_version,
        'agent_id': agent_id,
        'date': target_date_str,
        'generated_at': generated_at,
        'source_sessions': source_sessions,
        'stats': stats,
        'conversation_excerpts': public_excerpts,
    }


def build_write_bundle(*, agent_id: str, target_date_str: str, merged: dict, sessions_to_process: list,
                       l1_path: str, l2_path: str) -> dict:
    """组装 L1/L2/staging 写入包；本函数不执行写入，更新策略由入口层处理。"""
    payload = assemble_layer0_payload(
        agent_id=agent_id,
        target_date_str=target_date_str,
        turns=merged['turns'],
        stats=merged['stats'],
        source_sessions=[{'session_id': sid, 'session_file': sfile} for sid, sfile in sessions_to_process],
    )

    initialized_at = payload['generated_at']
    active_schema_version = _active_schema_version()
    l1_result = {
        'success': True,
        'schema_version': active_schema_version,
        'date': target_date_str,
        'agent_id': agent_id,
        'status': _initial_l1_status(initialized_at),
        'generated_at': payload['generated_at'],
        '_l1_path': l1_path,
        '_l2_path': l2_path,
        'stats': payload['stats'],
        'memory_signal': 'normal',
        'summary': None,
        'tags': None,
        'day_mood': None,
        'topics': None,
        'decisions': None,
        'todos': None,
        'key_items': None,
        'emotional_peaks': None,
        '_compress_hints': None,
    }
    l2_result = {
        'schema_version': active_schema_version,
        'date': target_date_str,
        'agent_id': agent_id,
        'status': _initial_l2_status(initialized_at),
        'conversation_excerpts': payload['conversation_excerpts'],
    }

    staging_ready = {
        'l1_path': l1_path,
        'l2_path': l2_path,
        'conversation_excerpts': payload['conversation_excerpts'],
        'generated_at': payload['generated_at'],
        'date': target_date_str,
        'agent_id': agent_id,
    }

    return {
        'l1_result': l1_result,
        'l2_result': l2_result,
        'staging_ready': staging_ready,
        'payload': payload,
    }


