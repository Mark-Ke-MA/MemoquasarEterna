#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

"""Layer4 L2 recall helpers.

- vague_mode: query_terms + L0 anchors -> list[{information, score, depth, time_key, role, time, ...}]
- exact_mode: date + window_start + window_end -> str

当前约定：
- vague mode 只读取 recall_L0 top-k 中 `depth == surface` 的 active L2 文件
- exact mode 读取 active surface L2 或 archived L2
- exact mode 绝不依赖 trimmed active L2：
  - 近 trimL2_interval 周：优先 active，若缺失再查 archive
  - 更早：优先 archive，必要时可回退查 active，但若 active 标记 trimmed 则拒用
- 若目标日期无可用对话内容，则返回固定无对话文本，不报错
"""

from dataclasses import dataclass
from datetime import date as DateType, datetime, timedelta
import json
import math
from pathlib import Path
import tarfile
from typing import Any

from Core.shared_funcs import LoadConfig
from Core.Layer2_Preserve.core import archive_tarball_path, load_preserve_config


NO_TRANSCRIPT_TEXT = '该时间范围内无可用对话记录。'
EXACT_GLOBAL_HARD_CAP = 10_000
EXACT_INTERNAL_MAX_WINDOW_MINUTES = 24 * 60


@dataclass(frozen=True, slots=True)
class _RawExcerpt:
    information: str
    depth: str
    time_key: str
    raw_score: float
    role: str | None
    time: str | None
    turn_index: int | None
    source_path: str


@dataclass(frozen=True, slots=True)
class _ScoredExcerpt:
    information: str
    depth: str
    time_key: str
    score: float
    raw_score: float
    role: str | None
    time: str | None
    turn_index: int | None
    source_path: str


def _surface_root(agent_id: str, overall_config: dict[str, Any]) -> Path:
    store_root = Path(str(overall_config['store_dir'])).expanduser()
    structure = overall_config.get('store_dir_structure', {}) if isinstance(overall_config, dict) else {}
    memory_cfg = structure.get('memory', {}) if isinstance(structure, dict) else {}
    memory_root = str(memory_cfg.get('root', 'memory') or 'memory')
    surface_dir = str(memory_cfg.get('surface', 'surface') or 'surface')
    return store_root / memory_root / agent_id / surface_dir


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding='utf-8') as f:
            payload = json.load(f)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return str(value).strip()


def _tokenize_for_match(text: str) -> list[str]:
    lowered = str(text or '').lower()
    for ch in ['\n', '\t', ',', '，', '.', '。', '!', '！', '?', '？', ':', '：', ';', '；', '(', ')', '（', '）', '[', ']', '【', '】', '/', '\\', '|', '"', "'", '-', '_']:
        lowered = lowered.replace(ch, ' ')
    return [token for token in lowered.split() if token]


def _lexical_score(query_terms: list[str], text: str) -> float:
    if not text:
        return 0.0
    haystack = set(_tokenize_for_match(text))
    if not haystack:
        return 0.0
    matched = 0.0
    for term in query_terms:
        normalized = str(term or '').strip().lower()
        if not normalized:
            continue
        if normalized in haystack:
            matched += 1.0
        else:
            for token in haystack:
                if normalized in token or token in normalized:
                    matched += 0.5
                    break
    return matched


def _safe_sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _minmax_norm(values: list[float]) -> list[float]:
    if not values:
        return []
    min_v = min(values)
    max_v = max(values)
    if math.isclose(min_v, max_v):
        return [1.0 if max_v > 0.0 else 0.0 for _ in values]
    return [(v - min_v) / (max_v - min_v) for v in values]


def _rank_norm(values: list[float]) -> list[float]:
    if not values:
        return []
    n = len(values)
    if n == 1:
        return [1.0 if values[0] > 0.0 else 0.0]
    order = sorted(range(n), key=lambda i: values[i], reverse=True)
    ranks = [0.0] * n
    for pos, idx in enumerate(order):
        ranks[idx] = 1.0 - (pos / (n - 1))
    return ranks


def _sigmoid_norm(values: list[float]) -> list[float]:
    if not values:
        return []
    positives = [v for v in values if v > 0.0]
    if not positives:
        return [0.0 for _ in values]
    center = sum(positives) / len(positives)
    spread = max(center, 1e-6)
    return [_safe_sigmoid((v - center) / spread) if v > 0.0 else 0.0 for v in values]


def _calibrate_scores(raw_values: list[float]) -> list[float]:
    if not raw_values:
        return []
    minmax_values = _minmax_norm(raw_values)
    rank_values = _rank_norm(raw_values)
    sigmoid_values = _sigmoid_norm(raw_values)
    return [
        0.4 * minmax_values[i] + 0.4 * rank_values[i] + 0.2 * sigmoid_values[i]
        for i in range(len(raw_values))
    ]


def _resolve_l2_path(surface_root: Path, time_key: str) -> Path | None:
    month = time_key[:7]
    if not month or len(time_key) != 10:
        return None
    return surface_root / month / f'{time_key}_l2.json'


def _push_excerpt(out: list[_RawExcerpt], *, query_terms: list[str], excerpt: dict[str, Any], time_key: str, source_path: str) -> None:
    information = _normalize_text(excerpt.get('content'))
    if not information:
        return
    raw_score = _lexical_score(query_terms, information)
    if raw_score <= 0.0:
        return
    role = _normalize_text(excerpt.get('role')) or None
    time = _normalize_text(excerpt.get('time')) or None
    turn_index_value = excerpt.get('turn_index')
    turn_index = int(turn_index_value) if isinstance(turn_index_value, int) else None
    out.append(_RawExcerpt(
        information=information,
        depth='surface',
        time_key=time_key,
        raw_score=raw_score,
        role=role,
        time=time,
        turn_index=turn_index,
        source_path=source_path,
    ))


def recall_l2_vague(*, repo_root: str | None = None, agent_id: str, query_terms: list[str], anchors: list[dict[str, Any]], limit: int = 24) -> list[dict[str, Any]]:
    cfg = LoadConfig(repo_root)
    overall_config = cfg.overall_config
    surface_root = _surface_root(agent_id, overall_config)

    query_tokens = [str(term).strip().lower() for term in query_terms if str(term).strip()]
    if not query_tokens:
        return []

    raw_excerpts: list[_RawExcerpt] = []
    seen_paths: set[str] = set()
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        depth = str(anchor.get('depth', '') or '').strip().lower()
        time_key = str(anchor.get('time_key', '') or '').strip()
        if depth != 'surface' or not time_key:
            continue
        path = _resolve_l2_path(surface_root, time_key)
        if path is None:
            continue
        path_key = str(path)
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        excerpts = payload.get('conversation_excerpts', [])
        if not isinstance(excerpts, list):
            continue
        for excerpt in excerpts:
            if not isinstance(excerpt, dict):
                continue
            _push_excerpt(raw_excerpts, query_terms=query_tokens, excerpt=excerpt, time_key=time_key, source_path=path_key)

    if not raw_excerpts:
        return []

    calibrated_scores = _calibrate_scores([item.raw_score for item in raw_excerpts])
    scored: list[_ScoredExcerpt] = []
    for idx, item in enumerate(raw_excerpts):
        score = calibrated_scores[idx]
        if score <= 0.0:
            continue
        scored.append(_ScoredExcerpt(
            information=item.information,
            depth=item.depth,
            time_key=item.time_key,
            score=score,
            raw_score=item.raw_score,
            role=item.role,
            time=item.time,
            turn_index=item.turn_index,
            source_path=item.source_path,
        ))

    scored.sort(key=lambda item: (-item.score, -item.raw_score, item.time_key, item.time or '', item.role or '', item.information))

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in scored:
        key = (item.time_key, item.role or '', item.time or '', item.information, item.source_path)
        if key in seen:
            continue
        seen.add(key)
        payload: dict[str, Any] = {
            'information': item.information,
            'score': round(item.score, 6),
            'depth': item.depth,
            'time_key': item.time_key,
            'field': 'conversation_excerpt',
            'role': item.role,
            'time': item.time,
            'source_path': item.source_path,
        }
        if item.turn_index is not None:
            payload['turn_index'] = item.turn_index
        deduped.append(payload)
        if len(deduped) >= max(1, int(limit)):
            break
    return deduped


def _local_today(overall_config: dict[str, Any]) -> DateType:
    tz_name = str(overall_config.get('timezone', 'Europe/London') or 'Europe/London')
    try:
        tz = ZoneInfo(tz_name)  # type: ignore[name-defined]
    except Exception:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('Europe/London')
    return datetime.now(tz).date()


def _parse_day(text: str) -> DateType:
    return datetime.strptime(str(text).strip(), '%Y-%m-%d').date()


def _parse_hhmm(text: str) -> str:
    value = str(text).strip()
    datetime.strptime(value, '%H:%M')
    return value


def _window_minutes(window_start: str, window_end: str) -> int:
    t1 = datetime.strptime(window_start, '%H:%M')
    t2 = datetime.strptime(window_end, '%H:%M')
    minutes = int((t2 - t1).total_seconds() // 60)
    if minutes < 0:
        raise ValueError('window_end 不能早于 window_start')
    return minutes


def _active_safe_cutoff(today: DateType, *, trim_interval_weeks: int) -> DateType:
    return today - timedelta(days=max(0, trim_interval_weeks) * 7)


def _compute_exact_budget(delta_minutes: int, *, max_chars: int | None = None) -> int:
    if delta_minutes < 0:
        raise ValueError('delta_minutes 不能为负数')
    if delta_minutes > EXACT_INTERNAL_MAX_WINDOW_MINUTES:
        delta_minutes = EXACT_INTERNAL_MAX_WINDOW_MINUTES
    budget = EXACT_GLOBAL_HARD_CAP
    if max_chars is not None:
        budget = min(budget, max(1, int(max_chars)))
    return max(1, budget)


def _excerpt_in_window(excerpt: dict[str, Any], *, window_start: str, window_end: str) -> bool:
    t = _normalize_text(excerpt.get('time'))
    if not t:
        return True
    return window_start <= t <= window_end


def _extract_conversation_excerpts(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    excerpts = payload.get('conversation_excerpts', [])
    return [item for item in excerpts if isinstance(item, dict)] if isinstance(excerpts, list) else []


def _format_excerpt(excerpt: dict[str, Any], *, content_override: str | None = None) -> str:
    role = _normalize_text(excerpt.get('role')) or 'unknown'
    tm = _normalize_text(excerpt.get('time'))
    content = _normalize_text(content_override if content_override is not None else excerpt.get('content'))
    if tm:
        return f'[{role} {tm}] {content}'
    return f'[{role}] {content}'


def _total_chars(excerpts: list[dict[str, Any]], *, overrides: dict[int, str] | None = None) -> int:
    overrides = overrides or {}
    return sum(len(_format_excerpt(excerpt, content_override=overrides.get(idx))) for idx, excerpt in enumerate(excerpts))


def _drop_short_assistant_excerpts(excerpts: list[dict[str, Any]], *, budget: int) -> list[dict[str, Any]]:
    kept = list(excerpts)
    while kept and _total_chars(kept) > budget:
        assistant_indexes = [
            idx for idx, excerpt in enumerate(kept)
            if _normalize_text(excerpt.get('role')).lower() == 'assistant'
        ]
        if not assistant_indexes:
            break
        victim = min(assistant_indexes, key=lambda idx: len(_normalize_text(kept[idx].get('content'))))
        del kept[victim]
    return kept


def _downsample_excerpts(excerpts: list[dict[str, Any]], *, budget: int) -> list[dict[str, Any]]:
    if len(excerpts) <= 2:
        return excerpts
    best = excerpts
    for stride in range(2, len(excerpts) + 1):
        sampled = excerpts[::stride]
        if sampled and sampled[-1] is not excerpts[-1]:
            sampled = sampled + [excerpts[-1]]
        deduped: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for item in sampled:
            marker = id(item)
            if marker in seen_ids:
                continue
            seen_ids.add(marker)
            deduped.append(item)
        best = deduped
        if _total_chars(best) <= budget:
            return best
    return best


def _middle_trim_text(text: str, target_len: int) -> str:
    content = _normalize_text(text)
    if len(content) <= target_len:
        return content
    if target_len <= 8:
        return content[:target_len]
    usable = target_len - 3
    head = int(usable * 0.6)
    tail = usable - head
    return f'{content[:head]}...{content[-tail:]}'


def _compress_excerpt_contents(excerpts: list[dict[str, Any]], *, budget: int) -> dict[int, str]:
    overrides = {idx: _normalize_text(excerpt.get('content')) for idx, excerpt in enumerate(excerpts)}
    if _total_chars(excerpts, overrides=overrides) <= budget:
        return overrides
    while _total_chars(excerpts, overrides=overrides) > budget:
        longest_idx = max(range(len(excerpts)), key=lambda idx: len(overrides.get(idx, '')))
        current = overrides.get(longest_idx, '')
        if len(current) <= 24:
            break
        shrink_to = max(24, int(len(current) * 0.85))
        if shrink_to >= len(current):
            break
        overrides[longest_idx] = _middle_trim_text(current, shrink_to)
    return overrides


def _iso_week_id(day: DateType) -> str:
    y, w, _ = day.isocalendar()
    return f'{y}-W{w:02d}'


def _load_active_l2_payload(*, repo_root: str | None, agent_id: str, target_day: DateType) -> dict[str, Any] | None:
    overall_config = LoadConfig(repo_root).overall_config
    surface_root = _surface_root(agent_id, overall_config)
    path = _resolve_l2_path(surface_root, target_day.strftime('%Y-%m-%d'))
    if path is None:
        return None
    return _load_json(path)


def _load_archived_l2_payload(*, repo_root: str | None, agent_id: str, target_day: DateType) -> dict[str, Any] | None:
    cfg = load_preserve_config(repo_root)
    week_id = _iso_week_id(target_day)
    tar_path = archive_tarball_path(cfg, agent_id, week_id)
    if not tar_path.exists():
        return None
    member_name = f'{target_day.strftime("%Y-%m-%d")}_l2.json'
    try:
        with tarfile.open(tar_path, 'r:gz') as tf:
            try:
                member = tf.getmember(member_name)
            except KeyError:
                return None
            extracted = tf.extractfile(member)
            if extracted is None:
                return None
            payload = json.loads(extracted.read().decode('utf-8'))
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _is_trimmed_l2(payload: dict[str, Any] | None) -> bool:
    status = payload.get('status') if isinstance(payload, dict) else None
    return bool(status.get('trimmed', False)) if isinstance(status, dict) else False


def _select_exact_payload(*, repo_root: str | None, agent_id: str, target_day: DateType, trim_interval_weeks: int) -> dict[str, Any] | None:
    overall_config = LoadConfig(repo_root).overall_config
    today = _local_today(overall_config)
    cutoff = _active_safe_cutoff(today, trim_interval_weeks=trim_interval_weeks)

    active_payload = _load_active_l2_payload(repo_root=repo_root, agent_id=agent_id, target_day=target_day)
    archived_payload = _load_archived_l2_payload(repo_root=repo_root, agent_id=agent_id, target_day=target_day)

    if target_day >= cutoff:
        if isinstance(active_payload, dict) and not _is_trimmed_l2(active_payload):
            return active_payload
        return archived_payload if isinstance(archived_payload, dict) else None

    if isinstance(archived_payload, dict):
        return archived_payload
    if isinstance(active_payload, dict) and not _is_trimmed_l2(active_payload):
        return active_payload
    return None


def exact_recall_l2(*, repo_root: str | None = None, agent_id: str, date: str, window_start: str, window_end: str, max_chars: int | None = None) -> str:
    cfg = LoadConfig(repo_root)
    overall_config = cfg.overall_config
    target_day = _parse_day(date)
    start = _parse_hhmm(window_start)
    end = _parse_hhmm(window_end)
    delta_minutes = _window_minutes(start, end)
    budget = _compute_exact_budget(delta_minutes, max_chars=max_chars)

    layer3_cfg = overall_config.get('layer3_decay', {}) if isinstance(overall_config.get('layer3_decay'), dict) else {}
    trim_interval_weeks = int(layer3_cfg.get('trimL2_interval', 2) or 2)
    payload = _select_exact_payload(repo_root=repo_root, agent_id=agent_id, target_day=target_day, trim_interval_weeks=trim_interval_weeks)
    excerpts = [excerpt for excerpt in _extract_conversation_excerpts(payload) if _excerpt_in_window(excerpt, window_start=start, window_end=end)]
    if not excerpts:
        return NO_TRANSCRIPT_TEXT

    # Step 1: direct return if under budget.
    if _total_chars(excerpts) <= budget:
        return '\n'.join(_format_excerpt(excerpt) for excerpt in excerpts)

    # Step 2+: iterative reduction until under GLOBAL_HARD_CAP.
    current = list(excerpts)
    while current and _total_chars(current) > budget:
        reduced = _drop_short_assistant_excerpts(current, budget=budget)
        if reduced != current:
            current = reduced
            if _total_chars(current) <= budget:
                break

        reduced = _downsample_excerpts(current, budget=budget)
        if reduced != current:
            current = reduced
            if _total_chars(current) <= budget:
                break

        overrides = _compress_excerpt_contents(current, budget=budget)
        transcript = '\n'.join(_format_excerpt(excerpt, content_override=overrides.get(idx)) for idx, excerpt in enumerate(current))
        if len(transcript) <= budget:
            return transcript or NO_TRANSCRIPT_TEXT

        # If content compression cannot reduce enough, stop to avoid infinite loop.
        return transcript[:budget] or NO_TRANSCRIPT_TEXT

    if not current:
        return NO_TRANSCRIPT_TEXT
    transcript = '\n'.join(_format_excerpt(excerpt) for excerpt in current)
    return transcript[:budget] if len(transcript) > budget else (transcript or NO_TRANSCRIPT_TEXT)


__all__ = ['recall_l2_vague', 'exact_recall_l2', 'NO_TRANSCRIPT_TEXT']
