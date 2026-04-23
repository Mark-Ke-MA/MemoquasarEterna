#!/usr/bin/env python3
"""Layer1 写入层的第2阶段：chunk 规划。

这一阶段负责把 Stage1 已经写入的初始 plan 和 extraction_ready 进一步变成：
- 每个 agent 的 chunk 策略
- `l2_chunk_XXX.json` 计划文件
- Stage3 / Stage4 / Stage6 / Stage7 所需的批次与顺序信息

注意：
- 这是纯脚本层，不调用任何 LLM
- 允许读取完整 excerpt 文本，用于更准确的 token 预算估算
- 不把全文内容注入到任何模型上下文里
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import math
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer1_Write.core import (
    load_layer1_config,
    map_input_budget_max,
    map_output_budget_max,
    min_chunk_count,
    reduce_input_budget_max,
)
from Core.Layer1_Write.shared import (
    LoadConfig,
    build_layer0_artifact_paths,
    build_store_paths,
    dbg,
    estimate_tokens_from_text,
    load_json_file,
    write_json_atomic,
)


def _landmark_scores_path(agent_id: str, repo_root: str | Path | None = None) -> str:
    overall_cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(overall_cfg['store_dir'])).expanduser()
    stats_cfg = overall_cfg['store_dir_structure']['statistics']
    return str(store_root / stats_cfg['root'] / stats_cfg['landmark_scores'] / f'{agent_id}_landmark_scores.json')



# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Stage2Fragment:
    """一个可切分的 excerpt 片段。"""

    excerpt_index: int
    role: str
    time: str
    timestamp: str
    message_type: str
    text: str
    token_estimate: int


# ---------------------------------------------------------------------------
# 基础路径 / 计划读写
# ---------------------------------------------------------------------------


def _repo_root(repo_root: str | Path | None = None) -> Path:
    return Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]


def _plan_path(repo_root: str | Path | None = None) -> Path:
    overall_cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(overall_cfg['store_dir'])).expanduser()
    staging_cfg = overall_cfg['store_dir_structure']['staging']
    staging_root = store_root / staging_cfg['root'] / staging_cfg['staging_surface']
    return staging_root / 'plan.json'


def _agent_staging_root(agent_id: str, repo_root: str | Path | None = None) -> Path:
    overall_cfg = LoadConfig(repo_root).overall_config
    store_paths = build_store_paths(agent_id, overall_cfg)
    return Path(store_paths['staging_surface_agent_root'])


def _extraction_ready_path(agent_id: str, repo_root: str | Path | None = None) -> Path:
    return _agent_staging_root(agent_id, repo_root=repo_root) / 'extraction_ready.json'


def _chunk_path(agent_id: str, chunk_id: int, repo_root: str | Path | None = None) -> Path:
    return _agent_staging_root(agent_id, repo_root=repo_root) / f'l2_chunk_{chunk_id:03d}.json'


def _l1_chunk_path(agent_id: str, chunk_id: int, repo_root: str | Path | None = None) -> Path:
    return _agent_staging_root(agent_id, repo_root=repo_root) / f'l1_chunk_{chunk_id:03d}.json'


def _load_stage_plan(repo_root: str | Path | None = None) -> dict:
    path = _plan_path(repo_root)
    if not path.exists():
        raise FileNotFoundError(f'plan.json 不存在: {path}')
    return load_json_file(path)


def _write_stage_plan(plan: dict, repo_root: str | Path | None = None):
    path = _plan_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, plan)


def _update_stage_plan(repo_root: str | Path | None, updater):
    plan = _load_stage_plan(repo_root)
    updater(plan)
    plan.setdefault('plan', {}).setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    _write_stage_plan(plan, repo_root=repo_root)


# ---------------------------------------------------------------------------
# 预算 / 切块
# ---------------------------------------------------------------------------


def _excerpt_text(excerpt: dict[str, Any]) -> str:
    return str(excerpt.get('content', '') or '')


def _estimate_excerpt_tokens(excerpt: dict[str, Any], chars_per_token: int) -> int:
    return max(1, estimate_tokens_from_text(_excerpt_text(excerpt), chars_per_token=chars_per_token)) if _excerpt_text(excerpt) else 0


def _split_text_by_chars(text: str, parts: int) -> list[str]:
    if parts <= 1:
        return [text]
    if not text:
        return [''] * parts
    step = max(1, math.ceil(len(text) / parts))
    out = [text[i:i + step] for i in range(0, len(text), step)]
    while len(out) < parts:
        out.append('')
    return out[:parts]


def _normalize_role(role: Any) -> str:
    return str(role or '').strip().lower()


def _build_fragments(excerpts: list[dict[str, Any]], *, target_chunk_count: int, chars_per_token: int) -> list[Stage2Fragment]:
    """把 conversation_excerpts 先规整成可递归切分的基础单位。"""
    fragments: list[Stage2Fragment] = []
    for excerpt_index, excerpt in enumerate(excerpts):
        text = _excerpt_text(excerpt)
        token_estimate = _estimate_excerpt_tokens(excerpt, chars_per_token)
        if text and token_estimate <= 0:
            token_estimate = 1
        fragments.append(Stage2Fragment(
            excerpt_index=excerpt_index,
            role=str(excerpt.get('role', 'unknown')),
            time=str(excerpt.get('time', '')),
            timestamp=str(excerpt.get('timestamp', '')),
            message_type=str(excerpt.get('message_type', 'text')),
            text=text,
            token_estimate=token_estimate,
        ))
    return fragments


def _chunk_metrics(fragments: list[Stage2Fragment]) -> tuple[int, int]:
    return sum(f.token_estimate for f in fragments), len(fragments)


def _is_assistant_to_user_boundary(left: Stage2Fragment, right: Stage2Fragment) -> bool:
    return _normalize_role(left.role) == 'assistant' and _normalize_role(right.role) == 'user'


def _split_fragment_text(fragment: Stage2Fragment, chars_per_token: int) -> list[Stage2Fragment]:
    if len(fragment.text) <= 1:
        return [fragment]
    pieces = _split_text_by_chars(fragment.text, 2)
    if len(pieces) <= 1:
        return [fragment]
    total_parts = len(pieces)
    split_frags: list[Stage2Fragment] = []
    for piece_index, piece in enumerate(pieces):
        piece_tokens = max(1, estimate_tokens_from_text(piece, chars_per_token=chars_per_token)) if piece else 0
        split_frags.append(Stage2Fragment(
            excerpt_index=fragment.excerpt_index,
            role=fragment.role,
            time=fragment.time,
            timestamp=fragment.timestamp,
            message_type=fragment.message_type,
            text=piece,
            token_estimate=piece_tokens,
        ))
    return split_frags


def _pick_split_index(fragments: list[Stage2Fragment]) -> int:
    if len(fragments) <= 1:
        return 1

    total_tokens, total_turns = _chunk_metrics(fragments)
    midpoint_tokens = total_tokens / 2 if total_tokens else 0
    midpoint_turns = total_turns / 2 if total_turns else 0

    boundaries = list(range(1, len(fragments)))
    valid_boundaries = [i for i in boundaries if _is_assistant_to_user_boundary(fragments[i - 1], fragments[i])]
    candidates = valid_boundaries or boundaries

    best_idx = candidates[0]
    best_score = None
    for idx in candidates:
        left = fragments[:idx]
        left_tokens, left_turns = _chunk_metrics(left)
        token_score = abs(left_tokens - midpoint_tokens) / max(1, total_tokens)
        turn_score = abs(left_turns - midpoint_turns) / max(1, total_turns)
        boundary_penalty = 0.0 if (valid_boundaries or _is_assistant_to_user_boundary(fragments[idx - 1], fragments[idx])) else 0.25
        score = token_score + turn_score + boundary_penalty
        if best_score is None or score < best_score:
            best_score = score
            best_idx = idx
    return best_idx


def _split_chunk_once(fragments: list[Stage2Fragment], chars_per_token: int) -> tuple[list[Stage2Fragment], list[Stage2Fragment]]:
    if len(fragments) <= 1:
        split_frags = _split_fragment_text(fragments[0], chars_per_token)
        if len(split_frags) <= 1:
            return fragments, []
        return [split_frags[0]], split_frags[1:]

    split_idx = _pick_split_index(fragments)
    left = fragments[:split_idx]
    right = fragments[split_idx:]
    if not left or not right:
        mid = max(1, len(fragments) // 2)
        left = fragments[:mid]
        right = fragments[mid:]
    return left, right


def _partition_fragments_into_chunks(fragments: list[Stage2Fragment], chunk_count: int, chunk_budget: int, chars_per_token: int, max_turns_per_chunk: int) -> list[list[Stage2Fragment]]:
    if chunk_count <= 0:
        return []
    if not fragments:
        return [[] for _ in range(chunk_count)]

    turn_budget = max(1, min(max_turns_per_chunk, math.ceil(len(fragments) / chunk_count)))
    chunks: list[list[Stage2Fragment]] = [list(fragments)]

    while True:
        worst_idx = None
        worst_score = 0.0
        for idx, chunk in enumerate(chunks):
            chunk_tokens, chunk_turns = _chunk_metrics(chunk)
            over_tokens = chunk_tokens - chunk_budget
            over_turns = chunk_turns - turn_budget
            if over_tokens <= 0 and over_turns <= 0:
                continue
            token_score = over_tokens / max(1, chunk_budget) if over_tokens > 0 else 0.0
            turn_score = over_turns / max(1, turn_budget) if over_turns > 0 else 0.0
            score = max(token_score, turn_score)
            if score > worst_score:
                worst_score = score
                worst_idx = idx

        if worst_idx is None:
            break

        chunk = chunks.pop(worst_idx)
        left, right = _split_chunk_once(chunk, chars_per_token)
        if not left or not right:
            # 实在无法再切时就回填，防止死循环。
            chunks.insert(worst_idx, chunk)
            break
        chunks.insert(worst_idx, right)
        chunks.insert(worst_idx, left)

    return chunks


# ---------------------------------------------------------------------------
# 计划构建
# ---------------------------------------------------------------------------


def _chunk_payload(agent_id: str, date: str, chunk_id: int, total_chunks: int, *, chunk_fragments: list[Stage2Fragment], extraction_ready: dict, layer0_paths: dict[str, str], layer1_cfg) -> dict[str, Any]:
    token_estimate = sum(f.token_estimate for f in chunk_fragments)
    return {
        'stage': 'Stage2_ChunkPlan',
        'agent_id': agent_id,
        'date': date,
        'chunk_id': chunk_id,
        'chunk_name': f'l2_chunk_{chunk_id:03d}.json',
        'total_chunks': total_chunks,
        'input': {
            'fragment_count': len(chunk_fragments),
            'token_estimate': token_estimate,
            'fragments': [
                {
                    'excerpt_index': f.excerpt_index,
                    'role': f.role,
                    'time': f.time,
                    'timestamp': f.timestamp,
                    'message_type': f.message_type,
                    'text': f.text,
                    'token_estimate': f.token_estimate,
                }
                for f in chunk_fragments
            ],
        },
    }


def _chunk_plan_for_agent(*, agent_id: str, date: str, plan: dict, repo_root: str | Path | None = None) -> dict[str, Any]:
    cfg = load_layer1_config(repo_root)
    overall_cfg = LoadConfig(repo_root).overall_config
    layer0_paths = build_layer0_artifact_paths(agent_id, date, overall_cfg)
    ready_path = Path(layer0_paths['staging_ready_path'])
    if not ready_path.exists():
        return {
            'agent_id': agent_id,
            'status': 'skipped',
            'skip_reason': 'extraction_ready.json 不存在',
            'chunks': [],
            'l2_total_tokens': 0,
            'target_chunk_count': 0,
            'actual_chunk_count': 0,
            'warnings': [],
        }

    extraction_ready = load_json_file(ready_path)
    excerpts = extraction_ready.get('conversation_excerpts', []) if isinstance(extraction_ready, dict) else []
    if not isinstance(excerpts, list):
        excerpts = []

    chars_per_token = cfg.chars_per_token_estimate
    l2_total_tokens = sum(_estimate_excerpt_tokens(ex, chars_per_token) for ex in excerpts)
    target_chunk_count = min_chunk_count(cfg, l2_total_tokens) if l2_total_tokens > 0 else 1

    # 如果某个 excerpt 很长，确保 chunk_budget 至少能容纳它；
    # 这一步只影响预算推导，不改变“纯脚本”的属性。
    while True:
        chunk_budget = map_input_budget_max(cfg, target_chunk_count)
        max_excerpt_tokens = max(((_estimate_excerpt_tokens(ex, chars_per_token)) for ex in excerpts), default=0)
        if max_excerpt_tokens <= chunk_budget or target_chunk_count >= max(1, len(excerpts)):
            break
        target_chunk_count += 1

    chunk_budget = map_input_budget_max(cfg, target_chunk_count)
    reduce_budget = reduce_input_budget_max(cfg)

    fragments = _build_fragments(excerpts, target_chunk_count=target_chunk_count, chars_per_token=chars_per_token)
    chunk_fragments = _partition_fragments_into_chunks(fragments, target_chunk_count, chunk_budget, chars_per_token, cfg.chunk_max_turns)
    actual_chunk_count = len(chunk_fragments)
    map_output_budget = map_output_budget_max(cfg, actual_chunk_count)

    warnings: list[str] = []
    if actual_chunk_count != target_chunk_count:
        warnings.append(f'实际 chunk 数 {actual_chunk_count} 与目标 chunk 数 {target_chunk_count} 不一致')

    chunks: list[dict[str, Any]] = []
    for idx, frag_list in enumerate(chunk_fragments, start=1):
        chunk_path = _chunk_path(agent_id, idx, repo_root=repo_root)
        l1_chunk_path = _l1_chunk_path(agent_id, idx, repo_root=repo_root)
        payload = _chunk_payload(
            agent_id,
            date,
            idx,
            actual_chunk_count,
            chunk_fragments=frag_list,
            extraction_ready=extraction_ready,
            layer0_paths=layer0_paths,
            layer1_cfg=type('Budget', (), {
                'chunk_budget_max': chunk_budget,
                'reduce_input_budget_max': reduce_budget,
                'map_output_budget_max': map_output_budget,
            })(),
        )
        chunks.append({
            'chunk_id': idx,
            'chunk_name': f'l2_chunk_{idx:03d}.json',
            'l2_chunk_path': str(chunk_path),
            'l1_chunk_path': str(l1_chunk_path),
            'token_estimate': payload['input']['token_estimate'],
            'fragment_count': payload['input']['fragment_count'],
        })
    return {
        'agent_id': agent_id,
        'status': 'pending',
        'skip_reason': None,
        'l1_path': layer0_paths['l1_path'],
        'l2_total_tokens': l2_total_tokens,
        'target_chunk_count': target_chunk_count,
        'actual_chunk_count': actual_chunk_count,
        'map_input_budget_base': cfg.ct_all_max - cfg.ct_all_free - cfg.ct_map_prompt - cfg.ct_system_prompt,
        'reduce_input_budget_max': reduce_budget,
        'map_output_budget_max': map_output_budget,
        'chunk_budget_max': chunk_budget,
        'warnings': warnings,
        'chunks': chunks,
        'chunk_payloads': [
            _chunk_payload(
                agent_id,
                date,
                idx,
                actual_chunk_count,
                chunk_fragments=frag_list,
                extraction_ready=extraction_ready,
                layer0_paths=layer0_paths,
                layer1_cfg=type('Budget', (), {
                    'chunk_budget_max': chunk_budget,
                    'reduce_input_budget_max': reduce_budget,
                    'map_output_budget_max': map_output_budget,
                })(),
            )
            for idx, frag_list in enumerate(chunk_fragments, start=1)
        ],
    }


def _build_stage3_batches(agent_chunk_plans: list[dict[str, Any]], max_parallel_workers: int) -> list[list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    for agent_plan in agent_chunk_plans:
        if agent_plan.get('status') != 'pending':
            continue
        for chunk in agent_plan.get('chunks', []):
            items.append({
                'agent_id': agent_plan['agent_id'],
                'chunk_id': chunk['chunk_id'],
                'output_path': chunk['l1_chunk_path'],
                'status': 'pending',
            })
    return [items[i:i + max_parallel_workers] for i in range(0, len(items), max_parallel_workers)]


def _build_stage4_batches(agent_chunk_plans: list[dict[str, Any]], max_parallel_workers: int) -> list[list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    for agent_plan in agent_chunk_plans:
        if agent_plan.get('status') != 'pending':
            continue
        items.append({
            'agent_id': agent_plan['agent_id'],
            'input_paths': [chunk['l1_chunk_path'] for chunk in agent_plan.get('chunks', [])],
            'output_path': str(_agent_staging_root(agent_plan['agent_id']) / 'reduced_results.json'),
            'status': 'pending',
        })
    return [items[i:i + max_parallel_workers] for i in range(0, len(items), max_parallel_workers)]


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def run_stage2(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    """执行 Stage2：读取 plan，生成 chunk 计划，写入 staging_surface 下的 l2_chunk 文件。"""
    plan = _load_stage_plan(repo_root)
    root_plan = plan.get('plan', {})
    stage1 = root_plan.get('stage1', {})
    if stage1.get('status') not in ('running', 'done'):
        raise RuntimeError('Stage1 尚未准备好，不能进入 Stage2')

    run_meta = root_plan.get('run_meta', {})
    target_date = run_meta.get('date')
    if not target_date:
        raise RuntimeError('plan.json 中缺少 run_meta.date')

    selected_agents = stage1.get('selected_agents', [])
    if not isinstance(selected_agents, list):
        selected_agents = []
    agents_with_conversation = stage1.get('agents_with_conversation', [])
    if not isinstance(agents_with_conversation, list):
        agents_with_conversation = []
    agents_with_conversation_set = {str(agent) for agent in agents_with_conversation if str(agent).strip()}

    # 先把 Stage2 置为 running
    def _set_running(p: dict):
        stage2 = p.setdefault('plan', {}).setdefault('stage2', {})
        stage2['status'] = 'running'
        p['plan'].setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    _update_stage_plan(repo_root, _set_running)

    cfg = load_layer1_config(repo_root)
    agent_plans: list[dict[str, Any]] = []
    for agent_id in selected_agents:
        if agent_id not in agents_with_conversation_set:
            agent_plans.append({
                'agent_id': agent_id,
                'status': 'skipped',
                'skip_reason': '无对话或 Stage1 未标记为有对话',
                'chunks': [],
                'l2_total_tokens': 0,
                'target_chunk_count': 0,
                'actual_chunk_count': 0,
                'warnings': [],
            })
            continue
        agent_plans.append(_chunk_plan_for_agent(agent_id=agent_id, date=target_date, plan=plan, repo_root=repo_root))

    stage3_batches = _build_stage3_batches(agent_plans, cfg.nprl_llm_max)
    stage4_batches = _build_stage4_batches(agent_plans, cfg.nprl_llm_max)

    stage6_tasks = []
    stage7_tasks = []
    stage5_outputs = {}
    for agent_plan in agent_plans:
        if agent_plan.get('status') != 'pending':
            continue
        agent_id = agent_plan['agent_id']
        surface_root = Path(agent_plan['l1_path']).parent.parent
        l0_index_path = str(surface_root / 'l0_index.json')
        embedding_index_path = str(surface_root / 'l0_embeddings.json')
        stage6_tasks.append({
            'agent_id': agent_id,
            'l1_path': agent_plan['l1_path'],
            'l0_index_path': l0_index_path,
            'status': 'pending',
        })
        stage7_tasks.append({
            'agent_id': agent_id,
            'l0_index_path': l0_index_path,
            'embedding_index_path': embedding_index_path,
            'status': 'pending',
        })
        stage5_outputs[agent_id] = {
            'l1_path': agent_plan['l1_path'],
            'reduce_output_path': str(_agent_staging_root(agent_id, repo_root=repo_root) / 'reduced_results.json'),
        }

    if dry_run:
        return {
            'success': True,
            'stage': 'Stage2_ChunkPlan',
            'dry_run': True,
            'plan_path': str(_plan_path(repo_root)),
            'target_date': target_date,
            'agents': agent_plans,
            'stage3_batches': stage3_batches,
            'stage4_batches': stage4_batches,
            'stage5_outputs': stage5_outputs,
            'stage6_tasks': stage6_tasks,
            'stage7_tasks': stage7_tasks,
        }

    # 写 chunk 文件
    for agent_plan in agent_plans:
        if agent_plan.get('status') != 'pending':
            continue
        for chunk_payload in agent_plan.get('chunk_payloads', []):
            path = _chunk_path(agent_plan['agent_id'], chunk_payload['chunk_id'], repo_root=repo_root)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(path, chunk_payload)

    def _finalize(p: dict):
        stage2 = p.setdefault('plan', {}).setdefault('stage2', {})
        stage2['status'] = 'done'
        stage2['target_date'] = target_date
        stage2['agents'] = [
            {
                'agent_id': item['agent_id'],
                'status': item['status'],
                'skip_reason': item.get('skip_reason'),
                'l1_path': item.get('l1_path'),
                'l2_total_tokens': item.get('l2_total_tokens', 0),
                'target_chunk_count': item.get('target_chunk_count', 0),
                'actual_chunk_count': item.get('actual_chunk_count', 0),
                'map_input_budget_base': item.get('map_input_budget_base', 0),
                'reduce_input_budget_max': item.get('reduce_input_budget_max', 0),
                'map_output_budget_max': item.get('map_output_budget_max', 0),
                'chunk_budget_max': item.get('chunk_budget_max', 0),
                'warnings': item.get('warnings', []),
                'chunks': item.get('chunks', []),
            }
            for item in agent_plans
        ]
        p['plan']['stage3']['status'] = 'pending'
        p['plan']['stage3']['map_batches'] = stage3_batches
        p['plan']['stage4']['status'] = 'pending'
        p['plan']['stage4']['reduce_batches'] = stage4_batches
        p['plan']['stage5']['status'] = 'pending'
        p['plan']['stage5']['outputs'] = stage5_outputs
        p['plan']['stage6']['status'] = 'pending'
        p['plan']['stage6']['tasks'] = stage6_tasks
        p['plan']['stage7']['status'] = 'pending'
        p['plan']['stage7']['tasks'] = stage7_tasks
        p['plan']['stage8']['status'] = 'pending'
        p['plan']['stage8']['tasks'] = [
            {
                'agent_id': agent_id,
                'l1_path': output_info['l1_path'],
                'record_path': _landmark_scores_path(agent_id, repo_root=repo_root),
                'status': 'pending',
            }
            for agent_id, output_info in stage5_outputs.items()
            if isinstance(output_info, dict) and str(output_info.get('l1_path', '') or '')
        ]
        p['plan']['stage9']['status'] = 'pending'
        p['plan'].setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        p['plan'].setdefault('run_meta', {})['status'] = 'running'

    _update_stage_plan(repo_root, _finalize)

    return {
        'success': True,
        'stage': 'Stage2_ChunkPlan',
        'dry_run': False,
        'plan_path': str(_plan_path(repo_root)),
        'target_date': target_date,
        'agents': agent_plans,
        'stage3_batches': stage3_batches,
        'stage4_batches': stage4_batches,
        'stage5_outputs': stage5_outputs,
        'stage6_tasks': stage6_tasks,
        'stage7_tasks': stage7_tasks,
    }


def describe_stage2_plan(result: dict[str, Any]) -> str:
    lines = [f"Stage2 target_date={result.get('target_date')}" ]
    for agent in result.get('agents', []):
        lines.append(
            f"- {agent['agent_id']}: status={agent.get('status')} chunks={agent.get('actual_chunk_count', 0)} tokens={agent.get('l2_total_tokens', 0)}"
        )
    return '\n'.join(lines)


__all__ = [
    'Stage2Fragment',
    'run_stage2',
    'describe_stage2_plan',
]
