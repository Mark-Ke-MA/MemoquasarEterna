#!/usr/bin/env python3
"""Layer2_Preserve core contract.

当前阶段只定义：
- 配置读取
- archive 路径 contract
- 固定命名常量
- preserve 结果 envelope

不在这里放入口调度逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Core.shared_funcs import LoadConfig

DEFAULT_DEPTH = 'surface'
ARCHIVE_FILENAME_TEMPLATE = '{week_id}.tar.gz'
MANIFEST_FILENAME = 'manifest.json'
L0_INDEX_SUBSET_FILENAME = 'l0_index_entries.json'
L0_EMBEDDINGS_SUBSET_FILENAME = 'l0_embeddings_entries.json'
PRESERVE_MARKER_FILENAME = 'preserved_weeks.json'


@dataclass(frozen=True, slots=True)
class PreserveConfig:
    repo_root: Path
    code_root: Path
    store_root: Path
    archive_root: Path
    archive_core_dirname: str
    archive_harness_dirname: str
    overall_config: dict[str, Any]


def load_preserve_config(repo_root: str | Path | None = None) -> PreserveConfig:
    cfg = LoadConfig(repo_root)
    overall = cfg.overall_config
    archive_dir = Path(str(overall['archive_dir'])).expanduser()
    archive_structure = overall.get('archive_dir_structure', {}) if isinstance(overall.get('archive_dir_structure'), dict) else {}
    return PreserveConfig(
        repo_root=Path(cfg.repo_root),
        code_root=Path(cfg.code_root),
        store_root=Path(cfg.store_root),
        archive_root=archive_dir,
        archive_core_dirname=str(archive_structure.get('core', 'core')),
        archive_harness_dirname=str(archive_structure.get('harness', 'harness')),
        overall_config=overall,
    )


def archive_core_root(cfg: PreserveConfig) -> Path:
    return cfg.archive_root / cfg.archive_core_dirname


def archive_harness_root(cfg: PreserveConfig) -> Path:
    return cfg.archive_root / cfg.archive_harness_dirname


def archive_agent_root(cfg: PreserveConfig, agent_id: str) -> Path:
    return archive_core_root(cfg) / agent_id


def archive_tarball_path(cfg: PreserveConfig, agent_id: str, week_id: str) -> Path:
    filename = ARCHIVE_FILENAME_TEMPLATE.format(week_id=week_id)
    return archive_agent_root(cfg, agent_id) / filename


def _logs_cfg(cfg: PreserveConfig) -> tuple[Path, dict[str, Any]]:
    store_structure = cfg.overall_config.get('store_dir_structure', {}) if isinstance(cfg.overall_config, dict) else {}
    logs_cfg = store_structure.get('logs', {}) if isinstance(store_structure, dict) else {}
    logs_root_name = str(logs_cfg.get('root', 'logs') or 'logs')
    return cfg.store_root / logs_root_name, logs_cfg


def layer2_preserve_logs_root(cfg: PreserveConfig) -> Path:
    logs_root, logs_cfg = _logs_cfg(cfg)
    layer2_cfg = logs_cfg.get('layer2_preserve', {}) if isinstance(logs_cfg.get('layer2_preserve'), dict) else {}
    layer2_root = str(layer2_cfg.get('root', 'Layer2_Preserve_logs') or 'Layer2_Preserve_logs')
    return logs_root / layer2_root


def sanitize_run_name(name: str | None) -> str:
    raw = str(name or '').strip()
    if not raw:
        return datetime.now(timezone.utc).strftime('manual_%Y-%m-%dT%H-%M-%SZ')
    keep: list[str] = []
    for ch in raw:
        if ch.isalnum() or ch in {'-', '_', '.'}:
            keep.append(ch)
        else:
            keep.append('_')
    cleaned = ''.join(keep).strip('._-')
    return cleaned or datetime.now(timezone.utc).strftime('manual_%Y-%m-%dT%H-%M-%SZ')


def archive_log_path(cfg: PreserveConfig, *, week_id: str, run_mode: str, run_name: str | None = None) -> Path:
    base = layer2_preserve_logs_root(cfg) / 'archive'
    filename = f'{week_id}.json' if week_id else 'unknown_week.json'
    if run_mode == 'auto':
        return base / 'auto' / filename
    return base / 'manual' / sanitize_run_name(run_name) / filename


def restored_root(cfg: PreserveConfig) -> Path:
    store_structure = cfg.overall_config.get('store_dir_structure', {}) if isinstance(cfg.overall_config, dict) else {}
    restored_cfg = store_structure.get('restored', {}) if isinstance(store_structure, dict) else {}
    restored_root_name = str(restored_cfg.get('root', 'restored') or 'restored')
    return cfg.store_root / restored_root_name


def restored_run_root(cfg: PreserveConfig, run_name: str | None) -> Path:
    return restored_root(cfg) / sanitize_run_name(run_name)


def restore_log_path(cfg: PreserveConfig, *, week_id: str, run_mode: str, run_name: str | None = None) -> Path:
    base = layer2_preserve_logs_root(cfg) / 'restore'
    filename = f'{week_id}.json' if week_id else 'unknown_week.json'
    if run_mode == 'auto':
        return base / 'auto' / filename
    return base / 'manual' / sanitize_run_name(run_name) / filename


def preserve_result(*, success: bool, stage: str, note: str, **kwargs: Any) -> dict[str, Any]:
    payload = {
        'success': success,
        'stage': stage,
        'note': note,
    }
    payload.update(kwargs)
    return payload


__all__ = [
    'DEFAULT_DEPTH',
    'ARCHIVE_FILENAME_TEMPLATE',
    'MANIFEST_FILENAME',
    'L0_INDEX_SUBSET_FILENAME',
    'L0_EMBEDDINGS_SUBSET_FILENAME',
    'PRESERVE_MARKER_FILENAME',
    'PreserveConfig',
    'load_preserve_config',
    'archive_core_root',
    'archive_harness_root',
    'archive_agent_root',
    'archive_tarball_path',
    'layer2_preserve_logs_root',
    'sanitize_run_name',
    'archive_log_path',
    'restored_root',
    'restored_run_root',
    'restore_log_path',
    'preserve_result',
]
