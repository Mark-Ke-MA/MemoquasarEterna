#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

"""Layer4 vague recall entry.

职责：
- 接收 query
- 调用 recall_L0 / recall_L1 / recall_L2(vague)
- 对 L1 / L2 候选做 layer weighting + bounded recency modulation
- 做轻量去重 / diversity 控制
- 组装为可直接给 agent 使用的字符串

当前实现要点：
1. L0 只做索引，不直接作为 information source。
2. 最终混排只使用：
   - L1 candidates
   - L2 vague candidates
3. 时间衰减统一只看 characterized date：
   - surface: 直接用 date
   - shallow: 用 week bin center
   - deep: 用 window bin center
4. 时间调制不做裸加法，而使用有界乘法调制，避免破坏 [0, 1] 分数范围：
   final = weighted_layer_score * (1 - alpha + alpha * recency_score)
5. 支持两个高级参数：
   - date_window：重定义 recency 的时间中心；若传入，衰减会比默认模式更强
   - prefer_l2_ratio：对外使用 0~1 直观区间，但内部会映射为 effective_l2_weight = 0.6 * ratio
6. 第一版 diversity / dedupe 规则：
   - 同 normalize 后文本硬去重
   - 同一 time_key 最多保留 3 条
   - 同一 time_key + field 最多保留 1 条
   - 同一 time_key 下 token overlap >= 0.75 时，去掉较低分项
   - 若某个 time_key 有合格 L2，尽量保留 1 条，但不强行保留纯重复项
7. 对疑似 runtime-context / internal-event 风格文本，只做 soft penalty，不硬删。
"""

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

from Core.shared_funcs import LoadConfig, output_failure, output_success

from Core.Layer4_Read.recall_L0 import recall_l0
from Core.Layer4_Read.recall_L1 import recall_l1
from Core.Layer4_Read.recall_L2 import recall_l2_vague
from Core.Layer4_Read.recall_recent import DEFAULT_RECENT_DAYS, recall_recent


DEFAULT_L0_LIMIT = 12
DEFAULT_L1_LIMIT = 24
DEFAULT_L2_LIMIT = 24
DEFAULT_FINAL_LIMIT = 8
DEFAULT_L1_WEIGHT = 0.7
DEFAULT_L2_WEIGHT = 0.3
DEFAULT_RECENCY_ALPHA = 0.15
DEFAULT_RECENCY_HORIZON_DAYS = 30.0
WINDOW_RECENCY_HORIZON_DAYS = 14.0
DEFAULT_TIME_KEY_LIMIT = 3
DEFAULT_TIME_KEY_FIELD_LIMIT = 1
DEFAULT_OVERLAP_THRESHOLD = 0.75
DEFAULT_MAX_CHARS = 12000
RUNTIME_CONTEXT_PENALTY = 0.3


def _tokenize_query(text: str) -> list[str]:
    lowered = str(text or '').strip().lower()
    for ch in ['\n', '\t', ',', '，', '.', '。', '!', '！', '?', '？', ':', '：', ';', '；', '(', ')', '（', '）', '[', ']', '【', '】', '/', '\\', '|', '"', "'", '-', '_']:
        lowered = lowered.replace(ch, ' ')
    return [token for token in lowered.split() if token]


def _normalize_text_for_dedupe(text: str) -> str:
    lowered = str(text or '').lower().strip()
    lowered = re.sub(r'\s+', ' ', lowered)
    lowered = re.sub(r'[\W_]+', ' ', lowered, flags=re.UNICODE)
    lowered = re.sub(r'\s+', ' ', lowered).strip()
    return lowered


def _token_set_for_overlap(text: str) -> set[str]:
    normalized = _normalize_text_for_dedupe(text)
    return {token for token in normalized.split() if token}


def _token_overlap_ratio(a: str, b: str) -> float:
    set_a = _token_set_for_overlap(a)
    set_b = _token_set_for_overlap(b)
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    denom = min(len(set_a), len(set_b))
    if denom <= 0:
        return 0.0
    return inter / denom


def _current_local_date(overall_config: dict[str, Any]) -> date:
    tz_name = str(overall_config.get('timezone', 'Europe/London') or 'Europe/London')
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo('Europe/London')
    return datetime.now(tz).date()


def _parse_iso_date(text: str) -> date:
    return datetime.strptime(text.strip(), '%Y-%m-%d').date()


def _characterized_date(depth: str, time_key: str) -> date | None:
    """Translate surface/shallow/deep time identifiers into one unified date axis.

    - surface: point date itself
    - shallow: week window center (ISO week Monday + 3 days)
    - deep: window bin center, floor to natural day
    """
    try:
        if depth == 'surface':
            return _parse_iso_date(time_key)
        if depth == 'shallow':
            monday = datetime.strptime(time_key + '-1', '%G-W%V-%u').date()
            return monday + timedelta(days=3)
        if depth == 'deep':
            start_text, _, span_text = str(time_key).partition('+')
            start_day = _parse_iso_date(start_text)
            span_days = int(str(span_text).rstrip('d') or '1')
            return start_day + timedelta(days=max(0, span_days // 2))
    except Exception:
        return None
    return None


def _parse_date_window(value: str | None) -> tuple[date, date] | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = [part.strip() for part in text.split(',') if part.strip()]
    if len(parts) == 1:
        anchor = _parse_iso_date(parts[0])
        return anchor, anchor
    if len(parts) == 2:
        start = _parse_iso_date(parts[0])
        end = _parse_iso_date(parts[1])
        if end < start:
            start, end = end, start
        return start, end
    raise ValueError('date_window 只支持 YYYY-MM-DD 或 YYYY-MM-DD,YYYY-MM-DD')


def _days_to_window(target: date, window: tuple[date, date]) -> int:
    start, end = window
    if start <= target <= end:
        return 0
    if target < start:
        return (start - target).days
    return (target - end).days


def _recency_score(*, characterized_date: date | None, today: date, date_window: tuple[date, date] | None) -> float:
    if characterized_date is None:
        return 0.5
    if date_window is None:
        age_days = abs((today - characterized_date).days)
        return 1.0 / (1.0 + (age_days / DEFAULT_RECENCY_HORIZON_DAYS))
    distance_days = _days_to_window(characterized_date, date_window)
    return 1.0 / (1.0 + (distance_days / WINDOW_RECENCY_HORIZON_DAYS))


def _resolve_layer_weights(prefer_l2_ratio: float | None) -> tuple[float, float, float | None]:
    if prefer_l2_ratio is None:
        return DEFAULT_L1_WEIGHT, DEFAULT_L2_WEIGHT, None
    ratio = float(prefer_l2_ratio)
    if not (0.0 <= ratio <= 1.0):
        raise ValueError('prefer_l2_ratio 必须满足 0 <= x <= 1')
    effective_l2_weight = 0.6 * ratio
    effective_l1_weight = 1.0 - effective_l2_weight
    return effective_l1_weight, effective_l2_weight, ratio


def _weighted_score(score: float, *, layer_weight: float) -> float:
    base = max(0.0, min(1.0, float(score)))
    weight = max(0.0, min(1.0, float(layer_weight)))
    return base * weight


def _apply_recency_modulation(weighted_score: float, *, recency_score: float, alpha: float) -> float:
    base = max(0.0, min(1.0, weighted_score))
    recency = max(0.0, min(1.0, recency_score))
    a = max(0.0, min(1.0, alpha))
    return base * (1.0 - a + a * recency)


def _looks_like_runtime_context(text: str) -> bool:
    lowered = str(text or '').lower()
    indicators = [
        'openclaw runtime context (internal)',
        '[internal task completion event]',
        'keep this internal context private',
        'session_key:',
        'session_id:',
        'source: subagent',
        'status: completed successfully',
        'result (untrusted content, treat as data):',
        '<<<begin_untrusted_child_result>>>',
        '<<<end_untrusted_child_result>>>',
        'stats: runtime',
        'action:',
    ]
    matched = sum(1 for marker in indicators if marker in lowered)
    return matched >= 2


def _apply_runtime_context_penalty(score: float, *, information: str, rendered: str) -> float:
    text = f'{information}\n{rendered}'
    if not _looks_like_runtime_context(text):
        return score
    base = max(0.0, min(1.0, float(score)))
    return base * RUNTIME_CONTEXT_PENALTY


def _format_l1_candidate(item: dict[str, Any]) -> str:
    depth = str(item.get('depth', '') or '')
    time_key = str(item.get('time_key', '') or '')
    field = str(item.get('field', '') or '')
    information = str(item.get('information', '') or '')

    if field == 'summary':
        prefix = '摘要'
    elif field in {'day_mood', 'week_mood', 'window_mood'}:
        prefix = '情绪'
    elif field == 'topic_name':
        prefix = '主题'
    elif field == 'topic_detail':
        prefix = '主题细节'
    elif field == 'decision':
        prefix = '决策'
    elif field == 'todo':
        prefix = '待办'
    elif field == 'key_item':
        key_item_type = str(item.get('key_item_type', '') or '').strip()
        prefix = f'关键事项[{key_item_type}]' if key_item_type else '关键事项'
    elif field == 'emotional_peak_context':
        emotion = str(item.get('emotion', '') or '').strip()
        prefix = f'情绪高点[{emotion}]' if emotion else '情绪高点'
    else:
        prefix = field or '信息'

    return f'[{depth} {time_key}] {prefix}：{information}'


def _format_l2_candidate(item: dict[str, Any]) -> str:
    depth = str(item.get('depth', '') or '')
    time_key = str(item.get('time_key', '') or '')
    role = str(item.get('role', '') or '').strip()
    excerpt_time = str(item.get('time', '') or '').strip()
    information = str(item.get('information', '') or '')
    if role and excerpt_time:
        meta = f'{excerpt_time} {role}'
    elif role:
        meta = role
    elif excerpt_time:
        meta = excerpt_time
    else:
        meta = 'excerpt'
    return f'[{depth} {time_key} {meta}] {information}'


def _build_ranked_item(*, source_layer: str, rendered: str, payload: dict[str, Any], raw_score: float, weighted_score: float, recency_score: float, final_score: float, depth: str, time_key: str, characterized: date | None) -> dict[str, Any]:
    return {
        'source_layer': source_layer,
        'depth': depth,
        'time_key': time_key,
        'characterized_date': characterized.strftime('%Y-%m-%d') if characterized else None,
        'raw_score': round(raw_score, 6),
        'weighted_score': round(weighted_score, 6),
        'recency_score': round(recency_score, 6),
        'final_score': round(final_score, 6),
        'rendered': rendered,
        'payload': payload,
        'field': str(payload.get('field', '') or ''),
        'normalized_information': _normalize_text_for_dedupe(str(payload.get('information', '') or '')),
    }


def _dedupe_and_diversify_ranked(items: list[dict[str, Any]], *, limit: int, time_key_limit: int = DEFAULT_TIME_KEY_LIMIT, time_key_field_limit: int = DEFAULT_TIME_KEY_FIELD_LIMIT, overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD) -> list[dict[str, Any]]:
    """Apply lightweight dedupe / diversity rules.

    Default policy:
    1. hard dedupe by normalized information text
    2. per time_key keep at most 3 items
    3. per time_key + field keep at most 1 item
    4. within same time_key, if token overlap >= 0.75, drop the weaker item
    5. try to preserve at most one non-redundant L2 item per time_key
    """
    if not items:
        return []

    # Step 1: hard text dedupe, keeping the stronger one.
    by_text: dict[str, dict[str, Any]] = {}
    for item in items:
        normalized = str(item.get('normalized_information', '') or '')
        if not normalized:
            continue
        incumbent = by_text.get(normalized)
        if incumbent is None or float(item.get('final_score', 0.0) or 0.0) > float(incumbent.get('final_score', 0.0) or 0.0):
            by_text[normalized] = item

    candidates = list(by_text.values())
    candidates.sort(key=lambda item: (-float(item.get('final_score', 0.0) or 0.0), -float(item.get('weighted_score', 0.0) or 0.0), item.get('source_layer', ''), item.get('time_key', '')))

    selected: list[dict[str, Any]] = []
    selected_by_time_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    selected_l2_count_by_time_key: dict[str, int] = defaultdict(int)
    field_count_by_time_key: dict[tuple[str, str], int] = defaultdict(int)

    def _can_add(item: dict[str, Any]) -> bool:
        time_key = str(item.get('time_key', '') or '')
        field = str(item.get('field', '') or '')
        same_time = selected_by_time_key[time_key]

        if len(same_time) >= time_key_limit:
            return False
        if field_count_by_time_key[(time_key, field)] >= time_key_field_limit:
            return False

        current_text = str(item.get('normalized_information', '') or '')
        current_layer = str(item.get('source_layer', '') or '')
        for existing in same_time:
            overlap = _token_overlap_ratio(current_text, str(existing.get('normalized_information', '') or ''))
            if overlap >= overlap_threshold:
                # If current one is L2 and the time_key has no L2 yet, allow one evidence-like patch to survive.
                if current_layer == 'l2' and selected_l2_count_by_time_key[time_key] < 1:
                    continue
                return False
        return True

    for item in candidates:
        if len(selected) >= max(1, int(limit)):
            break
        if not _can_add(item):
            continue
        selected.append(item)
        time_key = str(item.get('time_key', '') or '')
        field = str(item.get('field', '') or '')
        selected_by_time_key[time_key].append(item)
        field_count_by_time_key[(time_key, field)] += 1
        if str(item.get('source_layer', '') or '') == 'l2':
            selected_l2_count_by_time_key[time_key] += 1

    return selected


def _assemble_text_with_cap(*, l1_lines: list[str], l2_lines: list[str], max_chars: int) -> str:
    max_len = max(1, int(max_chars))
    parts: list[str] = []
    current_len = 0

    def _try_append(line: str) -> bool:
        nonlocal current_len
        addition = line if not parts else '\n' + line
        if current_len + len(addition) > max_len:
            return False
        parts.append(line)
        current_len += len(addition)
        return True

    if l1_lines:
        if _try_append('### 相关摘要'):
            for line in l1_lines:
                if not _try_append(f'- {line}'):
                    break
    if l2_lines:
        if _try_append('### 相关对话摘录'):
            for line in l2_lines:
                if not _try_append(f'- {line}'):
                    break
    return '\n'.join(parts).strip()


def _assemble_semantic_vague(*, repo_root: str | None = None, agent_id: str, query: str, l0_limit: int = DEFAULT_L0_LIMIT, l1_limit: int = DEFAULT_L1_LIMIT, l2_limit: int = DEFAULT_L2_LIMIT, final_limit: int = DEFAULT_FINAL_LIMIT, recency_alpha: float = DEFAULT_RECENCY_ALPHA, date_window: str | None = None, prefer_l2_ratio: float | None = None, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    cfg = LoadConfig(repo_root)
    overall_config = cfg.overall_config
    today = _current_local_date(overall_config)
    parsed_date_window = _parse_date_window(date_window)
    l1_weight, l2_weight, resolved_prefer_l2_ratio = _resolve_layer_weights(prefer_l2_ratio)

    query_terms = _tokenize_query(query)
    if not query_terms:
        return {
            'success': False,
            'note': 'query 为空，无法执行 Layer4 vague recall。',
            'query_terms': [],
            'assembled_text': '',
        }

    anchors = recall_l0(repo_root=repo_root, agent_id=agent_id, query_terms=query_terms, limit=l0_limit)
    l1_candidates = recall_l1(repo_root=repo_root, agent_id=agent_id, query_terms=query_terms, anchors=anchors, limit=l1_limit)
    l2_candidates = recall_l2_vague(repo_root=repo_root, agent_id=agent_id, query_terms=query_terms, anchors=anchors, limit=l2_limit)

    ranked_items: list[dict[str, Any]] = []

    for item in l1_candidates:
        depth = str(item.get('depth', '') or '')
        time_key = str(item.get('time_key', '') or '')
        characterized = _characterized_date(depth, time_key)
        raw_score = float(item.get('score', 0.0) or 0.0)
        text_score = _weighted_score(raw_score, layer_weight=l1_weight)
        recency = _recency_score(characterized_date=characterized, today=today, date_window=parsed_date_window)
        rendered = _format_l1_candidate(item)
        final_score = _apply_recency_modulation(text_score, recency_score=recency, alpha=recency_alpha)
        final_score = _apply_runtime_context_penalty(
            final_score,
            information=str(item.get('information', '') or ''),
            rendered=rendered,
        )
        ranked_items.append(_build_ranked_item(
            source_layer='l1',
            rendered=rendered,
            payload=item,
            raw_score=raw_score,
            weighted_score=text_score,
            recency_score=recency,
            final_score=final_score,
            depth=depth,
            time_key=time_key,
            characterized=characterized,
        ))

    for item in l2_candidates:
        depth = str(item.get('depth', '') or '')
        time_key = str(item.get('time_key', '') or '')
        characterized = _characterized_date(depth, time_key)
        raw_score = float(item.get('score', 0.0) or 0.0)
        text_score = _weighted_score(raw_score, layer_weight=l2_weight)
        recency = _recency_score(characterized_date=characterized, today=today, date_window=parsed_date_window)
        rendered = _format_l2_candidate(item)
        final_score = _apply_recency_modulation(text_score, recency_score=recency, alpha=recency_alpha)
        final_score = _apply_runtime_context_penalty(
            final_score,
            information=str(item.get('information', '') or ''),
            rendered=rendered,
        )
        ranked_items.append(_build_ranked_item(
            source_layer='l2',
            rendered=rendered,
            payload=item,
            raw_score=raw_score,
            weighted_score=text_score,
            recency_score=recency,
            final_score=final_score,
            depth=depth,
            time_key=time_key,
            characterized=characterized,
        ))

    ranked_items.sort(key=lambda item: (-float(item.get('final_score', 0.0) or 0.0), -float(item.get('weighted_score', 0.0) or 0.0), item.get('source_layer', ''), item.get('time_key', '')))
    final_items = _dedupe_and_diversify_ranked(ranked_items, limit=final_limit)

    l1_lines = [item['rendered'] for item in final_items if item.get('source_layer') == 'l1']
    l2_lines = [item['rendered'] for item in final_items if item.get('source_layer') == 'l2']

    assembled_text = _assemble_text_with_cap(
        l1_lines=l1_lines,
        l2_lines=l2_lines,
        max_chars=max_chars,
    )

    return {
        'success': True,
        'mode': 'semantic_vague',
        'query': query,
        'query_terms': query_terms,
        'agent_id': agent_id,
        'today': today.strftime('%Y-%m-%d'),
        'date_window': None if parsed_date_window is None else [parsed_date_window[0].strftime('%Y-%m-%d'), parsed_date_window[1].strftime('%Y-%m-%d')],
        'l0_limit': l0_limit,
        'l1_limit': l1_limit,
        'l2_limit': l2_limit,
        'final_limit': final_limit,
        'max_chars': max_chars,
        'l1_weight': l1_weight,
        'l2_weight': l2_weight,
        'prefer_l2_ratio': resolved_prefer_l2_ratio,
        'recency_alpha': recency_alpha,
        'anchors': anchors,
        'l1_candidates': l1_candidates,
        'l2_candidates': l2_candidates,
        'ranked_items': final_items,
        'assembled_text': assembled_text,
        'note': 'Layer4 vague recall 执行完成。',
    }


def assemble_vague(*, repo_root: str | None = None, agent_id: str, query: str | None = None, recent_days: int = DEFAULT_RECENT_DAYS, l0_limit: int = DEFAULT_L0_LIMIT, l1_limit: int = DEFAULT_L1_LIMIT, l2_limit: int = DEFAULT_L2_LIMIT, final_limit: int = DEFAULT_FINAL_LIMIT, recency_alpha: float = DEFAULT_RECENCY_ALPHA, date_window: str | None = None, prefer_l2_ratio: float | None = None, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    normalized_query = str(query or '').strip()
    if not normalized_query:
        return recall_recent(
            repo_root=repo_root,
            agent_id=agent_id,
            recent_days=recent_days,
            max_chars=max_chars,
        )
    return _assemble_semantic_vague(
        repo_root=repo_root,
        agent_id=agent_id,
        query=normalized_query,
        date_window=date_window,
        prefer_l2_ratio=prefer_l2_ratio,
        l0_limit=l0_limit,
        l1_limit=l1_limit,
        l2_limit=l2_limit,
        final_limit=final_limit,
        recency_alpha=recency_alpha,
        max_chars=max_chars,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Layer4 vague recall entry')
    parser.add_argument('--agent', required=True, help='目标 agent_id')
    parser.add_argument('--query', default=None, help='vague recall 查询文本；不传时进入 recent fallback')
    parser.add_argument('--recent-days', type=int, default=DEFAULT_RECENT_DAYS, help='仅在 query 为空时生效；默认 3')
    parser.add_argument('--date-window', default=None, help='可选：YYYY-MM-DD 或 YYYY-MM-DD,YYYY-MM-DD；仅在 query 非空时生效')
    parser.add_argument('--prefer-l2-ratio', type=float, default=None, help='可选：0 <= x <= 1；内部映射为 effective_l2_weight = 0.6 * x')
    parser.add_argument('--l0-limit', type=int, default=DEFAULT_L0_LIMIT)
    parser.add_argument('--l1-limit', type=int, default=DEFAULT_L1_LIMIT)
    parser.add_argument('--l2-limit', type=int, default=DEFAULT_L2_LIMIT)
    parser.add_argument('--final-limit', type=int, default=DEFAULT_FINAL_LIMIT)
    parser.add_argument('--repo-root', default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = assemble_vague(
            repo_root=args.repo_root,
            agent_id=args.agent,
            query=args.query,
            recent_days=args.recent_days,
            date_window=args.date_window,
            prefer_l2_ratio=args.prefer_l2_ratio,
            l0_limit=args.l0_limit,
            l1_limit=args.l1_limit,
            l2_limit=args.l2_limit,
            final_limit=args.final_limit,
        )
        output_success({
            'success': bool(result.get('success', False)),
            'mode': str(result.get('mode', '') or ''),
            'assembled_text': str(result.get('assembled_text', '') or ''),
        })
    except Exception as exc:  # noqa: BLE001
        output_failure(str(exc))


if __name__ == '__main__':
    main()
