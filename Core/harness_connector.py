"""Harness connector helpers.

负责：
- 加载 Adapters/{harness}/CONNECTOR.py
- 解析必选 / 可选 callable
- 统一调用固定 connector 接口
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

from Core.shared_funcs import LoadConfig


def get_configured_harness(repo_root: str | Path | None = None) -> str:
    """读取当前配置指定的 harness 名称。"""
    cfg = LoadConfig(repo_root).overall_config
    return str(cfg.get('harness', 'openclaw') or 'openclaw')


def _connector_module_path(*, repo_root: str | Path | None = None, harness: str | None = None) -> Path:
    repo = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
    harness_name = str(harness or get_configured_harness(repo)).strip()
    return repo / 'Adapters' / harness_name / 'CONNECTOR.py'


def load_harness_connector(*, repo_root: str | Path | None = None, harness: str | None = None) -> dict[str, Any] | None:
    """加载 harness 的 CONNECTOR.py 并返回 connector dict。"""
    module_path = _connector_module_path(repo_root=repo_root, harness=harness)
    if not module_path.exists():
        return None
    harness_name = str(harness or get_configured_harness(repo_root)).strip()
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


def get_required_connector_callable(connector: dict[str, Any] | None, key: str, *, where: str = 'connector') -> Callable[..., Any]:
    if connector is None:
        raise KeyError(f'{where} 不存在，无法读取必选接口: {key}')
    value = connector.get(key)
    if value is None:
        raise KeyError(f'{where} 缺少必选接口: {key}')
    if not callable(value):
        raise TypeError(f'{where}.{key} 必须是 callable')
    return value


def get_optional_connector_callable(connector: dict[str, Any] | None, key: str) -> Callable[..., Any] | None:
    if connector is None:
        return None
    value = connector.get(key)
    if value is None:
        return None
    if not callable(value):
        raise TypeError(f'connector.{key} 必须是 callable 或 None')
    return value


def call_optional_connector(connector: dict[str, Any] | None, key: str, *, context: dict[str, Any]) -> Any | None:
    """调用可选 connector 接口；若未提供则静默跳过。"""
    fn = get_optional_connector_callable(connector, key)
    if fn is None:
        return None
    return fn(context)


__all__ = [
    'get_configured_harness',
    'load_harness_connector',
    'get_required_connector_callable',
    'get_optional_connector_callable',
    'call_optional_connector',
]
