"""Harness connector helpers.

负责：
- 加载 Adapters/{harness}/CONNECTOR.py
- 解析 connector 顶层 callable
- 解析 memory_worker / production_agent role 下的必选 / 可选 callable
- 根据 OverallConfig.memory_worker_harness / production_agents 组装 connector routing
- 统一调用固定 connector 接口
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

from Core.shared_funcs import (
    LoadConfig,
    get_memory_worker_harness,
    get_production_agent_harness,
    group_production_agents_by_harness as group_config_production_agents_by_harness,
)


def get_configured_memory_worker_harness(repo_root: str | Path | None = None) -> str:
    cfg = LoadConfig(repo_root).overall_config
    return get_memory_worker_harness(cfg)


def _connector_module_path(*, repo_root: str | Path | None = None, harness: str | None = None) -> Path:
    if not harness or not str(harness).strip():
        raise ValueError('harness 不能为空')
    repo = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
    harness_name = str(harness).strip()
    return repo / 'Adapters' / harness_name / 'CONNECTOR.py'


def load_harness_connector(*, repo_root: str | Path | None = None, harness: str | None = None) -> dict[str, Any] | None:
    """加载 harness 的 CONNECTOR.py 并返回 connector dict。"""
    module_path = _connector_module_path(repo_root=repo_root, harness=harness)
    if not module_path.exists():
        return None
    harness_name = str(harness).strip()
    module_import_path = f'Adapters.{harness_name}.CONNECTOR'
    module = importlib.import_module(module_import_path)

    candidates = [
        f'{harness_name.upper()}_CONNECTOR',
        'CONNECTOR',
    ]
    for attr_name in candidates:
        connector = getattr(module, attr_name, None)
        if connector is None:
            continue
        if not isinstance(connector, dict):
            raise TypeError(f'{module_path}:{attr_name} 必须是 dict')
        return connector
    raise KeyError(f'{module_path} 中未找到 connector dict（期望 {candidates}）')


def load_memory_worker_connector(*, repo_root: str | Path | None = None) -> dict[str, Any] | None:
    return load_harness_connector(repo_root=repo_root, harness=get_configured_memory_worker_harness(repo_root))


def production_agents_by_harness(repo_root: str | Path | None = None, agent_ids: list[str] | None = None) -> dict[str, list[str]]:
    cfg = LoadConfig(repo_root).overall_config
    return group_config_production_agents_by_harness(cfg, agent_ids=agent_ids)


def load_production_agent_connector(*, repo_root: str | Path | None = None, agent_id: str) -> dict[str, Any] | None:
    cfg = LoadConfig(repo_root).overall_config
    harness = get_production_agent_harness(cfg, agent_id)
    return load_harness_connector(repo_root=repo_root, harness=harness)


def load_production_agent_connectors(*, repo_root: str | Path | None = None) -> dict[str, dict[str, Any] | None]:
    cfg = LoadConfig(repo_root).overall_config
    connectors_by_harness: dict[str, dict[str, Any] | None] = {}
    routed: dict[str, dict[str, Any] | None] = {}
    for harness, agent_ids in group_config_production_agents_by_harness(cfg).items():
        if harness not in connectors_by_harness:
            connectors_by_harness[harness] = load_harness_connector(repo_root=repo_root, harness=harness)
        connector = connectors_by_harness[harness]
        for agent_id in agent_ids:
            routed[agent_id] = connector
    return routed


def get_connector_role(connector: dict[str, Any] | None, role: str, *, where: str = 'connector') -> dict[str, Any] | None:
    if connector is None:
        return None
    value = connector.get(role)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f'{where}.{role} 必须是 dict')
    return value


def get_required_connector_entry(connector: dict[str, Any] | None, key: str, *, where: str = 'connector') -> Callable[..., Any]:
    if connector is None:
        raise KeyError(f'{where} 缺少 connector')
    value = connector.get(key)
    if value is None:
        raise KeyError(f'{where} 缺少必选顶层接口: {key}')
    if not callable(value):
        raise TypeError(f'{where}.{key} 必须是 callable')
    return value


def get_required_connector_callable(connector: dict[str, Any] | None, role: str, key: str, *, where: str = 'connector') -> Callable[..., Any]:
    role_connector = get_connector_role(connector, role, where=where)
    if role_connector is None:
        raise KeyError(f'{where} 缺少 role: {role}')
    value = role_connector.get(key)
    if value is None:
        raise KeyError(f'{where}.{role} 缺少必选接口: {key}')
    if not callable(value):
        raise TypeError(f'{where}.{role}.{key} 必须是 callable')
    return value


def get_optional_connector_callable(connector: dict[str, Any] | None, role: str, key: str) -> Callable[..., Any] | None:
    role_connector = get_connector_role(connector, role)
    if role_connector is None:
        return None
    value = role_connector.get(key)
    if value is None:
        return None
    if not callable(value):
        raise TypeError(f'connector.{role}.{key} 必须是 callable 或 None')
    return value


def call_optional_connector(connector: dict[str, Any] | None, role: str, key: str, *, context: dict[str, Any]) -> Any | None:
    """调用可选 connector 接口；若未提供则静默跳过。"""
    fn = get_optional_connector_callable(connector, role, key)
    if fn is None:
        return None
    return fn(context)


def call_optional_memory_worker_connector(*, repo_root: str | Path | None = None, key: str, context: dict[str, Any]) -> Any | None:
    connector = load_memory_worker_connector(repo_root=repo_root)
    return call_optional_connector(connector, 'memory_worker', key, context=context)


def call_optional_production_agent_connectors(
    *,
    repo_root: str | Path | None = None,
    key: str,
    context: dict[str, Any],
    agent_ids: list[str] | None = None,
) -> list[Any]:
    results: list[Any] = []
    groups = production_agents_by_harness(repo_root=repo_root, agent_ids=agent_ids)
    for harness, grouped_agent_ids in groups.items():
        connector = load_harness_connector(repo_root=repo_root, harness=harness)
        fn = get_optional_connector_callable(connector, 'production_agent', key)
        if fn is None:
            continue
        routed_context = dict(context)
        inputs = dict(routed_context.get('inputs') or {})
        inputs['agent_ids'] = grouped_agent_ids
        routed_context['inputs'] = inputs
        routed_context['harness'] = harness
        results.append(fn(routed_context))
    return results


__all__ = [
    'get_configured_memory_worker_harness',
    'load_harness_connector',
    'load_memory_worker_connector',
    'load_production_agent_connector',
    'load_production_agent_connectors',
    'production_agents_by_harness',
    'get_connector_role',
    'get_required_connector_entry',
    'get_required_connector_callable',
    'get_optional_connector_callable',
    'call_optional_connector',
    'call_optional_memory_worker_connector',
    'call_optional_production_agent_connectors',
]
