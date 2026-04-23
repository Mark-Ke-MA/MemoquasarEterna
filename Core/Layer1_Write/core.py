"""Layer1 写入层核心门面。

这一层把配置、预算、规划、计划解释统一收束在一起。
真正的 Stage 执行与 harness 接入会放在 Stage 文件里。
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Protocol, runtime_checkable

from Core.Layer1_Write.shared import (
    LoadConfig,
    build_layer0_artifact_paths,
    build_layer1_work_paths,
    estimate_tokens_from_excerpts,
    group_into_batches,
    require_keys,
)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Layer1Config:
    """Layer1 的配置对象。"""

    ct_all_max: int
    ct_all_free: int
    ct_map_prompt: int
    ct_reduce_prompt: int
    ct_system_prompt: int
    ct_reduce_output_max: int
    nprl_llm_max: int
    chunk_max_turns: int
    chars_per_token_estimate: int

    raw: dict[str, Any]


# ---------------------------------------------------------------------------
# 数据契约
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Layer1ArtifactPaths:
    """Layer1 各类产物路径。"""

    agent_id: str
    date: str
    month_dir: str
    l1_path: str
    l2_path: str
    staging_ready_path: str
    staging_alert_path: str
    work_root: str
    plan_path: str
    chunk_root: str
    map_root: str
    reduce_root: str
    reduce_output_path: str


@dataclass(frozen=True, slots=True)
class Layer1ChunkJob:
    """单个 Map chunk 任务。"""

    agent_id: str
    date: str
    chunk_index: int
    total_chunks: int
    chunk_path: str
    map_result_path: str
    chunk_token_budget_max: int
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class Layer1ReduceJob:
    """单个 Reduce 任务。"""

    agent_id: str
    date: str
    map_result_paths: tuple[str, ...]
    reduce_output_path: str
    reduce_input_budget_max: int
    total_map_tokens: int


@dataclass(frozen=True, slots=True)
class Layer1AgentPlan:
    """单个 agent 的写入计划。"""

    agent_id: str
    date: str
    l2_total_tokens: int
    chunk_count: int
    map_input_budget_base: int
    reduce_input_budget_max: int
    map_output_budget_max: int
    artifact_paths: Layer1ArtifactPaths
    chunk_jobs: tuple[Layer1ChunkJob, ...]
    reduce_job: Layer1ReduceJob


@dataclass(frozen=True, slots=True)
class Layer1SupervisorPlan:
    """整天的 supervisor 计划。"""

    date: str
    max_parallel_workers: int
    agents: tuple[Layer1AgentPlan, ...]
    map_batches: tuple[tuple[Layer1ChunkJob, ...], ...]
    reduce_batches: tuple[tuple[Layer1ReduceJob, ...], ...]
    total_map_jobs: int
    total_reduce_jobs: int
    raw: dict[str, Any]


# ---------------------------------------------------------------------------
# 运行时接口（占位）
# ---------------------------------------------------------------------------


@runtime_checkable
class Layer1WorkerRuntime(Protocol):
    """未来 worker runtime 适配器必须满足的接口。"""

    def spawn_map(self, job: Layer1ChunkJob) -> Any:
        ...

    def spawn_reduce(self, job: Layer1ReduceJob) -> Any:
        ...

    def wait(self, handle: Any, *, timeout_seconds: int | None = None) -> dict:
        ...

    def cleanup(self, handle: Any) -> None:
        ...


class Layer1RuntimeNotImplementedError(RuntimeError):
    """当前阶段还没实现的运行时能力。"""

    pass


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


def load_layer1_config(repo_root: str | None = None) -> Layer1Config:
    """读取 Layer1 的配置段并整理成结构化对象。"""
    cfg = LoadConfig(repo_root).overall_config
    section = cfg['layer1_write']
    require_keys(
        section,
        (
            'ct_all_max',
            'ct_all_free',
            'ct_map_prompt',
            'ct_reduce_prompt',
            'ct_system_prompt',
            'ct_reduce_output_max',
            'chunk_max_turns',
            'chars_per_token_estimate',
        ),
        where='OverallConfig.json.layer1_write',
    )
    if 'nprl_llm_max' not in cfg:
        raise KeyError('OverallConfig.json 缺少 nprl_llm_max')
    return Layer1Config(
        ct_all_max=int(section['ct_all_max']),
        ct_all_free=int(section['ct_all_free']),
        ct_map_prompt=int(section['ct_map_prompt']),
        ct_reduce_prompt=int(section['ct_reduce_prompt']),
        ct_system_prompt=int(section['ct_system_prompt']),
        ct_reduce_output_max=int(section['ct_reduce_output_max']),
        nprl_llm_max=int(cfg['nprl_llm_max']),
        chunk_max_turns=int(section['chunk_max_turns']),
        chars_per_token_estimate=int(section['chars_per_token_estimate']),
        raw=dict(section),
    )


# ---------------------------------------------------------------------------
# 预算公式
# ---------------------------------------------------------------------------


def reduce_input_budget_max(cfg: Layer1Config) -> int:
    """Reduce worker 可用的最大输入预算。"""
    return (
        cfg.ct_all_max
        - cfg.ct_all_free
        - cfg.ct_reduce_prompt
        - cfg.ct_system_prompt
        - cfg.ct_reduce_output_max
    )


def map_input_budget_base(cfg: Layer1Config) -> int:
    """Map worker 在不考虑输出切分时的基础输入预算。"""
    return (
        cfg.ct_all_max
        - cfg.ct_all_free
        - cfg.ct_map_prompt
        - cfg.ct_system_prompt
    )


def map_output_budget_max(cfg: Layer1Config, n_chunk: int) -> int:
    """把 Reduce 的总输入预算均分给每个 Map 输出。"""
    if n_chunk <= 0:
        raise ValueError('n_chunk 必须为正整数')
    return reduce_input_budget_max(cfg) // n_chunk


def map_input_budget_max(cfg: Layer1Config, n_chunk: int) -> int:
    """单个 Map worker 允许的最大 chunk 输入预算。"""
    if n_chunk <= 0:
        raise ValueError('n_chunk 必须为正整数')
    return map_input_budget_base(cfg) - map_output_budget_max(cfg, n_chunk)


def is_feasible(cfg: Layer1Config, l2_total_tokens: int, n_chunk: int) -> bool:
    """判断给定 chunk 数是否能覆盖完整 L2。"""
    if l2_total_tokens < 0:
        raise ValueError('l2_total_tokens 不能为负数')
    if n_chunk <= 0:
        return False
    return n_chunk * map_input_budget_max(cfg, n_chunk) >= l2_total_tokens


def min_chunk_count(cfg: Layer1Config, l2_total_tokens: int) -> int:
    """推导最小 chunk 数。"""
    if l2_total_tokens < 0:
        raise ValueError('l2_total_tokens 不能为负数')

    r = reduce_input_budget_max(cfg)
    a = map_input_budget_base(cfg)

    if a <= 0:
        raise ValueError('map 输入基础预算 <= 0，模型无解')
    if r < 0:
        raise ValueError('reduce 输入预算 < 0，模型无解')

    return max(1, ceil((l2_total_tokens + r) / a))


# ---------------------------------------------------------------------------
# 计划生成
# ---------------------------------------------------------------------------


def estimate_l2_total_tokens(conversation_excerpts: list[dict[str, Any]], cfg: Layer1Config) -> int:
    """根据 conversation_excerpts 粗估整天 L2 的 token 总量。"""
    return estimate_tokens_from_excerpts(conversation_excerpts, chars_per_token=cfg.chars_per_token_estimate)


def _approximate_chunk_tokens(l2_total_tokens: int, chunk_count: int) -> int:
    """粗略估计每个 chunk 平均需要承载的 token 数。"""
    if chunk_count <= 0:
        raise ValueError('chunk_count 必须为正整数')
    return max(1, ceil(l2_total_tokens / chunk_count))


def build_agent_artifact_paths(agent_id: str, date: str, *, repo_root: str | None = None) -> Layer1ArtifactPaths:
    """组装单个 agent 的 Layer0 / Layer1 产物路径。"""
    overall_cfg = LoadConfig(repo_root).overall_config
    layer0_paths = build_layer0_artifact_paths(agent_id, date, overall_cfg)
    layer1_paths = build_layer1_work_paths(agent_id, date, overall_cfg)
    return Layer1ArtifactPaths(
        agent_id=agent_id,
        date=date,
        month_dir=layer0_paths['month_dir'],
        l1_path=layer0_paths['l1_path'],
        l2_path=layer0_paths['l2_path'],
        staging_ready_path=layer0_paths['staging_ready_path'],
        staging_alert_path=layer0_paths['staging_alert_path'],
        work_root=layer1_paths['base_root'],
        plan_path=layer1_paths['plan_path'],
        chunk_root=layer1_paths['chunk_root'],
        map_root=layer1_paths['map_root'],
        reduce_root=layer1_paths['reduce_root'],
        reduce_output_path=layer1_paths['reduce_output_path'],
    )


def build_agent_plan_from_excerpts(*, agent_id: str, date: str, conversation_excerpts: list[dict[str, Any]], cfg: Layer1Config, repo_root: str | None = None) -> Layer1AgentPlan:
    """把一个 agent 的 conversation_excerpts 转成完整写入计划。"""
    l2_total_tokens = estimate_l2_total_tokens(conversation_excerpts, cfg)
    chunk_count = min_chunk_count(cfg, l2_total_tokens)
    if not is_feasible(cfg, l2_total_tokens, chunk_count):
        raise ValueError(f'对 {agent_id} / {date} 计算出的 chunk 数仍不可行')

    artifact_paths = build_agent_artifact_paths(agent_id, date, repo_root=repo_root)
    chunk_budget = map_input_budget_max(cfg, chunk_count)
    reduce_budget = reduce_input_budget_max(cfg)
    map_output_budget = map_output_budget_max(cfg, chunk_count)
    approx_tokens_per_chunk = _approximate_chunk_tokens(l2_total_tokens, chunk_count)

    chunk_jobs: list[Layer1ChunkJob] = []
    for idx in range(1, chunk_count + 1):
        chunk_name = f"l2_chunk_{idx:03d}.json"
        map_name = f"l1_chunk_{idx:03d}.json"
        chunk_jobs.append(
            Layer1ChunkJob(
                agent_id=agent_id,
                date=date,
                chunk_index=idx,
                total_chunks=chunk_count,
                chunk_path=f"{artifact_paths.chunk_root}/{chunk_name}",
                map_result_path=f"{artifact_paths.map_root}/{map_name}",
                chunk_token_budget_max=chunk_budget,
                estimated_tokens=approx_tokens_per_chunk,
            )
        )

    reduce_job = Layer1ReduceJob(
        agent_id=agent_id,
        date=date,
        map_result_paths=tuple(job.map_result_path for job in chunk_jobs),
        reduce_output_path=artifact_paths.reduce_output_path,
        reduce_input_budget_max=reduce_budget,
        total_map_tokens=l2_total_tokens,
    )

    return Layer1AgentPlan(
        agent_id=agent_id,
        date=date,
        l2_total_tokens=l2_total_tokens,
        chunk_count=chunk_count,
        map_input_budget_base=map_input_budget_base(cfg),
        reduce_input_budget_max=reduce_budget,
        map_output_budget_max=map_output_budget,
        artifact_paths=artifact_paths,
        chunk_jobs=tuple(chunk_jobs),
        reduce_job=reduce_job,
    )


def build_supervisor_plan_from_layer0(
    *,
    date: str,
    agent_payloads: dict[str, dict[str, Any]],
    cfg: Layer1Config,
) -> Layer1SupervisorPlan:
    """把 Layer0 风格的 payload 组装成整天的 supervisor 计划。"""
    agents: list[Layer1AgentPlan] = []
    for agent_id, payload in agent_payloads.items():
        excerpts = payload.get('conversation_excerpts') if isinstance(payload, dict) else None
        if excerpts is None:
            raise KeyError(f'{agent_id} 的 Layer0 payload 缺少 conversation_excerpts')
        agents.append(build_agent_plan_from_excerpts(agent_id=agent_id, date=date, conversation_excerpts=excerpts, cfg=cfg))

    map_jobs = [job for agent in agents for job in agent.chunk_jobs]
    reduce_jobs = [agent.reduce_job for agent in agents]

    map_batches = tuple(tuple(batch) for batch in group_into_batches(map_jobs, cfg.nprl_llm_max))
    reduce_batches = tuple(tuple(batch) for batch in group_into_batches(reduce_jobs, cfg.nprl_llm_max))

    return Layer1SupervisorPlan(
        date=date,
        max_parallel_workers=cfg.nprl_llm_max,
        agents=tuple(agents),
        map_batches=map_batches,
        reduce_batches=reduce_batches,
        total_map_jobs=len(map_jobs),
        total_reduce_jobs=len(reduce_jobs),
        raw={
            'date': date,
            'agent_ids': [agent.agent_id for agent in agents],
            'max_parallel_workers': cfg.nprl_llm_max,
        },
    )


def build_supervisor_plan_from_layer0_payloads(*, date: str, layer0_payloads: dict[str, dict[str, Any]], repo_root: str | None = None) -> Layer1SupervisorPlan:
    """把多 agent 的 Layer0 payload 汇总成 supervisor 计划。"""
    cfg = load_layer1_config(repo_root)
    return build_supervisor_plan_from_layer0(date=date, agent_payloads=layer0_payloads, cfg=cfg)


def explain_plan(plan: Layer1SupervisorPlan) -> str:
    """把计划压成便于阅读的文本。"""
    lines = [
        f'date={plan.date}',
        f'max_parallel_workers={plan.max_parallel_workers}',
        f'total_agents={len(plan.agents)}',
        f'total_map_jobs={plan.total_map_jobs}',
        f'total_reduce_jobs={plan.total_reduce_jobs}',
    ]
    for agent_plan in plan.agents:
        lines.append(
            f"- {agent_plan.agent_id}: tokens={agent_plan.l2_total_tokens}, chunks={agent_plan.chunk_count}, l1={agent_plan.artifact_paths.l1_path}"
        )
    return '\n'.join(lines)


__all__ = [
    'Layer1Config',
    'Layer1ArtifactPaths',
    'Layer1ChunkJob',
    'Layer1ReduceJob',
    'Layer1AgentPlan',
    'Layer1SupervisorPlan',
    'Layer1WorkerRuntime',
    'Layer1RuntimeNotImplementedError',
    'load_layer1_config',
    'reduce_input_budget_max',
    'map_input_budget_base',
    'map_input_budget_max',
    'map_output_budget_max',
    'is_feasible',
    'min_chunk_count',
    'estimate_l2_total_tokens',
    'build_agent_artifact_paths',
    'build_agent_plan_from_excerpts',
    'build_supervisor_plan_from_layer0',
    'build_supervisor_plan_from_layer0_payloads',
    'explain_plan',
]
