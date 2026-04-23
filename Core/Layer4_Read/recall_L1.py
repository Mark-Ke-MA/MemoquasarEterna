#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

"""Layer4 L1 recall helpers.

输入：query_terms + L0 anchors
输出：list[{information, score, depth, time_key, field, ...}]

当前实现约定：
- 只读取 recall_L0 top-k 命中的 L1 文件
- L0 仍然是纯索引层；L1 才开始提供 information source
- 每个候选只保留“最小不可拆分字符串”
- 采用与 L0 同风格的 lexical calibration：
  score = 0.4 * minmax + 0.4 * rank_score + 0.2 * sigmoid
- 本层先不接 embedding；L1 作为摘要层，当前优先提供稳定、可解释的字段级候选

字段展开规则：
- surface: summary / day_mood / topics[].name / topics[].detail / decisions[] / todos[] /
           key_items[].desc / emotional_peaks[].context
- shallow: 把 day_mood 换成 week_mood
- deep:    把 day_mood 换成 window_mood
- 跳过 tags：其召回作用已在 L0 中体现，作为 L1 information source 信息量偏低

额外 metadata：
- key_items[].desc 候选额外携带 key_item_type
- emotional_peaks[].context 候选额外携带 emotion
"""

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

from Core.shared_funcs import LoadConfig


@dataclass(frozen=True, slots=True)
class _RawCandidate:
    information: str
    depth: str
    time_key: str
    field: str
    raw_score: float
    source_path: str
    key_item_type: str | None = None
    emotion: str | None = None


@dataclass(frozen=True, slots=True)
class _ScoredCandidate:
    information: str
    depth: str
    time_key: str
    field: str
    score: float
    raw_score: float
    source_path: str
    key_item_type: str | None = None
    emotion: str | None = None


def _memory_roots(agent_id: str, overall_config: dict[str, Any]) -> tuple[Path, Path, Path]:
    store_root = Path(str(overall_config['store_dir'])).expanduser()
    structure = overall_config.get('store_dir_structure', {}) if isinstance(overall_config, dict) else {}
    memory_cfg = structure.get('memory', {}) if isinstance(structure, dict) else {}
    memory_root = str(memory_cfg.get('root', 'memory') or 'memory')
    surface_dir = str(memory_cfg.get('surface', 'surface') or 'surface')
    shallow_dir = str(memory_cfg.get('shallow', 'shallow') or 'shallow')
    deep_dir = str(memory_cfg.get('deep', 'deep') or 'deep')
    base = store_root / memory_root / agent_id
    return base / surface_dir, base / shallow_dir, base / deep_dir


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


def _anchor_depth(anchor: dict[str, Any]) -> str:
    return str(anchor.get('depth', '') or '').strip().lower()


def _anchor_time_key(anchor: dict[str, Any]) -> str:
    return str(anchor.get('time_key', '') or '').strip()


def _resolve_l1_path(*, surface_root: Path, shallow_root: Path, deep_root: Path, depth: str, time_key: str) -> Path | None:
    if depth == 'surface':
        month = time_key[:7]
        if not month or len(time_key) != 10:
            return None
        return surface_root / month / f'{time_key}_l1.json'
    if depth == 'shallow':
        return shallow_root / f'{time_key}.json'
    if depth == 'deep':
        return deep_root / f'{time_key}.json'
    return None


def _push_candidate(out: list[_RawCandidate], *, query_terms: list[str], text: str, depth: str, time_key: str, field: str, source_path: str, key_item_type: str | None = None, emotion: str | None = None) -> None:
    information = _normalize_text(text)
    if not information:
        return
    raw_score = _lexical_score(query_terms, information)
    if raw_score <= 0.0:
        return
    out.append(_RawCandidate(
        information=information,
        depth=depth,
        time_key=time_key,
        field=field,
        raw_score=raw_score,
        source_path=source_path,
        key_item_type=key_item_type,
        emotion=emotion,
    ))


def _expand_l1_candidates(*, query_terms: list[str], depth: str, time_key: str, payload: dict[str, Any], source_path: str) -> list[_RawCandidate]:
    out: list[_RawCandidate] = []

    _push_candidate(out, query_terms=query_terms, text=str(payload.get('summary', '') or ''), depth=depth, time_key=time_key, field='summary', source_path=source_path)

    mood_field = 'day_mood' if depth == 'surface' else 'week_mood' if depth == 'shallow' else 'window_mood'
    _push_candidate(out, query_terms=query_terms, text=str(payload.get(mood_field, '') or ''), depth=depth, time_key=time_key, field=mood_field, source_path=source_path)

    topics = payload.get('topics', [])
    if isinstance(topics, list):
        for item in topics:
            if isinstance(item, dict):
                _push_candidate(out, query_terms=query_terms, text=str(item.get('name', '') or ''), depth=depth, time_key=time_key, field='topic_name', source_path=source_path)
                _push_candidate(out, query_terms=query_terms, text=str(item.get('detail', '') or ''), depth=depth, time_key=time_key, field='topic_detail', source_path=source_path)
            elif isinstance(item, str):
                _push_candidate(out, query_terms=query_terms, text=item, depth=depth, time_key=time_key, field='topic_name', source_path=source_path)

    decisions = payload.get('decisions', [])
    if isinstance(decisions, list):
        for item in decisions:
            _push_candidate(out, query_terms=query_terms, text=str(item or ''), depth=depth, time_key=time_key, field='decision', source_path=source_path)

    todos = payload.get('todos', [])
    if isinstance(todos, list):
        for item in todos:
            _push_candidate(out, query_terms=query_terms, text=str(item or ''), depth=depth, time_key=time_key, field='todo', source_path=source_path)

    key_items = payload.get('key_items', [])
    if isinstance(key_items, list):
        for item in key_items:
            if not isinstance(item, dict):
                continue
            _push_candidate(
                out,
                query_terms=query_terms,
                text=str(item.get('desc', '') or ''),
                depth=depth,
                time_key=time_key,
                field='key_item',
                source_path=source_path,
                key_item_type=_normalize_text(item.get('type')) or None,
            )

    emotional_peaks = payload.get('emotional_peaks', [])
    if isinstance(emotional_peaks, list):
        for item in emotional_peaks:
            if not isinstance(item, dict):
                continue
            _push_candidate(
                out,
                query_terms=query_terms,
                text=str(item.get('context', '') or ''),
                depth=depth,
                time_key=time_key,
                field='emotional_peak_context',
                source_path=source_path,
                emotion=_normalize_text(item.get('emotion')) or None,
            )

    return out


def recall_l1(*, repo_root: str | None = None, agent_id: str, query_terms: list[str], anchors: list[dict[str, Any]], limit: int = 24) -> list[dict[str, Any]]:
    cfg = LoadConfig(repo_root)
    overall_config = cfg.overall_config
    surface_root, shallow_root, deep_root = _memory_roots(agent_id, overall_config)

    query_tokens = [str(term).strip().lower() for term in query_terms if str(term).strip()]
    if not query_tokens:
        return []

    raw_candidates: list[_RawCandidate] = []
    seen_paths: set[str] = set()
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        depth = _anchor_depth(anchor)
        time_key = _anchor_time_key(anchor)
        if depth not in {'surface', 'shallow', 'deep'} or not time_key:
            continue
        path = _resolve_l1_path(surface_root=surface_root, shallow_root=shallow_root, deep_root=deep_root, depth=depth, time_key=time_key)
        if path is None:
            continue
        path_key = str(path)
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        raw_candidates.extend(_expand_l1_candidates(
            query_terms=query_tokens,
            depth=depth,
            time_key=time_key,
            payload=payload,
            source_path=path_key,
        ))

    if not raw_candidates:
        return []

    calibrated_scores = _calibrate_scores([item.raw_score for item in raw_candidates])
    scored: list[_ScoredCandidate] = []
    for idx, item in enumerate(raw_candidates):
        score = calibrated_scores[idx]
        if score <= 0.0:
            continue
        scored.append(_ScoredCandidate(
            information=item.information,
            depth=item.depth,
            time_key=item.time_key,
            field=item.field,
            score=score,
            raw_score=item.raw_score,
            source_path=item.source_path,
            key_item_type=item.key_item_type,
            emotion=item.emotion,
        ))

    scored.sort(key=lambda item: (-item.score, -item.raw_score, item.depth, item.time_key, item.field, item.information))

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in scored:
        key = (item.depth, item.time_key, item.field, item.information)
        if key in seen:
            continue
        seen.add(key)
        payload: dict[str, Any] = {
            'information': item.information,
            'score': round(item.score, 6),
            'depth': item.depth,
            'time_key': item.time_key,
            'field': item.field,
            'source_path': item.source_path,
        }
        if item.key_item_type:
            payload['key_item_type'] = item.key_item_type
        if item.emotion:
            payload['emotion'] = item.emotion
        deduped.append(payload)
        if len(deduped) >= max(1, int(limit)):
            break
    return deduped


__all__ = ['recall_l1']
