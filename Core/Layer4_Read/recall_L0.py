#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

"""Layer4 L0 coarse recall.

输入：list[str(query_terms)]
输出：list[{time_key, depth, score}]

当前 scoring 逻辑（vague 线地基）明确如下：

1. L0 是“粗召回层”，目标是先找出值得回源的 time anchors，
   暂时不在这里做时间衰减；时间 bias 留到顶层 assemble 再加。
2. lexical 与 embedding 都先各自校准到更可比的尺度，再做融合：
   calibrated = 0.4 * minmax + 0.4 * rank_score + 0.2 * sigmoid
3. 若 embedding 可用：默认 hybrid；若不可用或失败：自动降级为 lexical-only。
4. hybrid 不用固定线性权重，而用门控融合：
   - 两路都强：平衡融合
   - lexical 强 / embedding 弱：lexical 主导
   - lexical 弱 / embedding 强：embedding 主导
   - 其他中间情况：轻微偏向 embedding

说明：
- 当前 lexical 仍是 BM25-like 的轻量词面命中分，不是严格 BM25。
- 但它在本层的作用主要是给 L0 粗召回提供稳定词面锚点。
"""

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any
import urllib.request

from Core.shared_funcs import LoadConfig

from Core.Layer4_Read.shared import L0Anchor


@dataclass(frozen=True, slots=True)
class _RawAnchor:
    depth: str
    time_key: str
    lexical_raw: float
    embedding_raw: float


@dataclass(frozen=True, slots=True)
class _ScoredAnchor:
    depth: str
    time_key: str
    lexical_raw: float
    embedding_raw: float
    lexical_score: float
    embedding_score: float
    score: float


def _surface_root(agent_id: str, overall_config: dict[str, Any]) -> Path:
    store_root = Path(str(overall_config['store_dir'])).expanduser()
    structure = overall_config.get('store_dir_structure', {}) if isinstance(overall_config, dict) else {}
    memory_cfg = structure.get('memory', {}) if isinstance(structure, dict) else {}
    memory_root = str(memory_cfg.get('root', 'memory') or 'memory')
    surface_dir = str(memory_cfg.get('surface', 'surface') or 'surface')
    return store_root / memory_root / agent_id / surface_dir


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _normalize_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ' '.join(_normalize_text(item) for item in value)
    if isinstance(value, dict):
        return ' '.join(f'{_normalize_text(k)} {_normalize_text(v)}' for k, v in value.items())
    return str(value)


def _tokenize_for_match(text: str) -> list[str]:
    lowered = str(text or '').lower()
    for ch in ['\n', '\t', ',', '，', '.', '。', '!', '！', '?', '？', ':', '：', ';', '；', '(', ')', '（', '）', '[', ']', '【', '】', '/', '\\', '|', '"', "'", '-', '_']:
        lowered = lowered.replace(ch, ' ')
    return [token for token in lowered.split() if token]


def _entry_text(entry: dict[str, Any]) -> str:
    parts = [
        _normalize_text(entry.get('summary')),
        _normalize_text(entry.get('tags')),
        _normalize_text(entry.get('mood')),
        _normalize_text(entry.get('day_mood')),
        _normalize_text(entry.get('topics')),
        _normalize_text(entry.get('decisions')),
        _normalize_text(entry.get('todos')),
        _normalize_text(entry.get('key_items')),
        _normalize_text(entry.get('emotional_peaks')),
    ]
    return ' '.join(part for part in parts if part).strip()


def _entry_depth(entry: dict[str, Any]) -> str:
    depth = str(entry.get('depth', '') or '').strip().lower()
    if depth in {'surface', 'shallow', 'deep'}:
        return depth
    granularity = str(entry.get('granularity', '') or '').strip().lower()
    if granularity in {'daily', 'surface'}:
        return 'surface'
    return depth or 'surface'


def _entry_time_key(entry: dict[str, Any]) -> str:
    depth = _entry_depth(entry)
    if depth == 'surface':
        return str(entry.get('date', '') or '').strip()
    if depth == 'shallow':
        return str(entry.get('week', '') or '').strip()
    if depth == 'deep':
        return str(entry.get('window', '') or '').strip()
    return str(entry.get('date', '') or entry.get('week', '') or entry.get('window', '') or '').strip()


def _lexical_score(query_terms: list[str], entry: dict[str, Any]) -> float:
    text = _entry_text(entry)
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


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _embedding_config(overall_config: dict[str, Any]) -> tuple[bool, str, str]:
    return (
        bool(overall_config.get('use_embedding', True)),
        str(overall_config.get('embedding_model', 'nomic-embed-text:latest') or 'nomic-embed-text:latest'),
        str(overall_config.get('embedding_api_url', 'http://localhost:11434/v1/embeddings') or 'http://localhost:11434/v1/embeddings'),
    )


def _load_query_embedding(query_terms: list[str], overall_config: dict[str, Any]) -> list[float] | None:
    use_embedding, model, api_url = _embedding_config(overall_config)
    if not use_embedding:
        return None
    text = ' '.join(str(term).strip() for term in query_terms if str(term).strip()).strip()
    if not text:
        return None
    payload = json.dumps({'model': model, 'input': [text]}).encode('utf-8')
    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None

    vectors = raw.get('data') if isinstance(raw, dict) else None
    if isinstance(vectors, list) and vectors:
        vector = vectors[0].get('embedding') if isinstance(vectors[0], dict) else None
        if isinstance(vector, list):
            try:
                return [float(x) for x in vector]
            except Exception:
                return None
    vectors = raw.get('embeddings') if isinstance(raw, dict) else None
    if isinstance(vectors, list) and vectors and isinstance(vectors[0], list):
        try:
            return [float(x) for x in vectors[0]]
        except Exception:
            return None
    return None


def _embedding_lookup_map(payload: Any) -> dict[tuple[str, str], list[float]]:
    lookup: dict[tuple[str, str], list[float]] = {}
    if isinstance(payload, dict):
        entries = payload.get('entries')
        if isinstance(entries, dict):
            for _, item in entries.items():
                if not isinstance(item, dict):
                    continue
                depth = _entry_depth(item)
                time_key = _entry_time_key(item)
                vector = item.get('embedding')
                if not time_key or not isinstance(vector, list):
                    continue
                try:
                    lookup[(depth, time_key)] = [float(x) for x in vector]
                except Exception:
                    continue
            return lookup
        if isinstance(entries, list):
            payload = entries
    if not isinstance(payload, list):
        return lookup
    for item in payload:
        if not isinstance(item, dict):
            continue
        depth = _entry_depth(item)
        time_key = _entry_time_key(item)
        vector = item.get('embedding')
        if not time_key or not isinstance(vector, list):
            continue
        try:
            lookup[(depth, time_key)] = [float(x) for x in vector]
        except Exception:
            continue
    return lookup


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
    """Calibrate one score family onto a more comparable [0, 1]-ish scale.

    按已定方案：
    calibrated = 0.4 * minmax + 0.4 * rank_score + 0.2 * sigmoid
    """
    if not raw_values:
        return []
    minmax_values = _minmax_norm(raw_values)
    rank_values = _rank_norm(raw_values)
    sigmoid_values = _sigmoid_norm(raw_values)
    return [
        0.4 * minmax_values[i] + 0.4 * rank_values[i] + 0.2 * sigmoid_values[i]
        for i in range(len(raw_values))
    ]


def _gated_fuse(*, lexical_score: float, embedding_score: float, use_hybrid: bool) -> float:
    """Fuse calibrated lexical / embedding scores with simple gating.

    规则：
    - 两路都强（>=0.7）：平衡融合 0.5 / 0.5
    - lexical 强、embedding 弱：lexical 主导 0.65 / 0.35
    - lexical 弱、embedding 强：embedding 主导 0.35 / 0.65
    - 其他中间情况：轻微偏 embedding 0.45 / 0.55

    若不启用 hybrid，则直接返回 lexical_score。
    """
    if not use_hybrid:
        return lexical_score
    lex = max(0.0, min(1.0, lexical_score))
    emb = max(0.0, min(1.0, embedding_score))
    strong = 0.7
    weak = 0.4
    if lex >= strong and emb >= strong:
        w_lex, w_emb = 0.5, 0.5
    elif lex >= strong and emb < weak:
        w_lex, w_emb = 0.65, 0.35
    elif lex < weak and emb >= strong:
        w_lex, w_emb = 0.35, 0.65
    else:
        w_lex, w_emb = 0.45, 0.55
    return w_lex * lex + w_emb * emb


def recall_l0(*, repo_root: str | None = None, agent_id: str, query_terms: list[str], limit: int = 12) -> list[dict[str, Any]]:
    cfg = LoadConfig(repo_root)
    overall_config = cfg.overall_config
    surface_root = _surface_root(agent_id, overall_config)
    index_path = surface_root / 'l0_index.json'
    embeddings_path = surface_root / 'l0_embeddings.json'

    index_payload = _load_json(index_path, {'entries': []})
    entries = index_payload.get('entries', []) if isinstance(index_payload, dict) else []
    if not isinstance(entries, list):
        return []

    query_tokens = [str(term).strip().lower() for term in query_terms if str(term).strip()]
    if not query_tokens:
        return []

    query_embedding = _load_query_embedding(query_tokens, overall_config)
    embedding_lookup = _embedding_lookup_map(_load_json(embeddings_path, {'entries': {}})) if query_embedding is not None else {}
    use_hybrid = query_embedding is not None and bool(embedding_lookup)

    raw_items: list[_RawAnchor] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        depth = _entry_depth(item)
        time_key = _entry_time_key(item)
        if depth not in {'surface', 'shallow', 'deep'} or not time_key:
            continue
        lexical_raw = _lexical_score(query_tokens, item)
        embedding_raw = 0.0
        if use_hybrid:
            embedding_raw = max(0.0, _cosine_similarity(query_embedding or [], embedding_lookup.get((depth, time_key), [])))
        raw_items.append(_RawAnchor(
            depth=depth,
            time_key=time_key,
            lexical_raw=lexical_raw,
            embedding_raw=embedding_raw,
        ))

    if not raw_items:
        return []

    lexical_calibrated = _calibrate_scores([item.lexical_raw for item in raw_items])
    embedding_calibrated = _calibrate_scores([item.embedding_raw for item in raw_items]) if use_hybrid else [0.0 for _ in raw_items]

    scored: list[_ScoredAnchor] = []
    for idx, item in enumerate(raw_items):
        lexical_score = lexical_calibrated[idx]
        embedding_score = embedding_calibrated[idx]
        score = _gated_fuse(
            lexical_score=lexical_score,
            embedding_score=embedding_score,
            use_hybrid=use_hybrid,
        )
        if score <= 0.0:
            continue
        scored.append(_ScoredAnchor(
            depth=item.depth,
            time_key=item.time_key,
            lexical_raw=item.lexical_raw,
            embedding_raw=item.embedding_raw,
            lexical_score=lexical_score,
            embedding_score=embedding_score,
            score=score,
        ))

    scored.sort(key=lambda item: (-item.score, -item.lexical_score, -item.embedding_score, item.depth, item.time_key))

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in scored:
        key = (item.depth, item.time_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({
            'depth': item.depth,
            'time_key': item.time_key,
            'score': round(item.score, 6),
        })
        if len(deduped) >= max(1, int(limit)):
            break
    return deduped


__all__ = ['recall_l0', 'L0Anchor']
