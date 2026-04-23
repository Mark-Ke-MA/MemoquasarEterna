#!/usr/bin/env python3
from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path
from typing import Any

from Core.Layer2_Preserve.core import (
    load_preserve_config,
    preserve_result,
    MANIFEST_FILENAME,
    L0_INDEX_SUBSET_FILENAME,
    L0_EMBEDDINGS_SUBSET_FILENAME,
)
from Core.Layer2_Preserve.shared import load_json_file, utc_now_iso
from Core.Layer2_Preserve.archive_Stage1_ListFiles import run_archive_stage1


def _filter_l0_index_entries(path: Path, window_start: str, window_end: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = load_json_file(path)
    entries = payload.get('entries', []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        return []
    return [
        entry for entry in entries
        if isinstance(entry, dict)
        and str(entry.get('date', '')) >= window_start
        and str(entry.get('date', '')) <= window_end
        and str(entry.get('depth', '')) == 'surface'
    ]


def _filter_l0_embedding_entries(path: Path, window_start: str, window_end: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = load_json_file(path)
    entries = payload.get('entries', {}) if isinstance(payload, dict) else {}
    if not isinstance(entries, dict):
        return {}
    kept: dict[str, Any] = {}
    for key, value in entries.items():
        if not isinstance(key, str) or '::' not in key:
            continue
        date_part, depth_part = key.split('::', 1)
        if depth_part != 'surface':
            continue
        if window_start <= date_part <= window_end:
            kept[key] = value
    return kept


def _add_json_bytes(tf: tarfile.TarFile, arcname: str, payload: Any) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
    info = tarfile.TarInfo(name=arcname)
    info.size = len(raw)
    tf.addfile(info, BytesIO(raw))


def _manifest_for_plan(cfg, plan: dict[str, Any], *, l0_index_entries: list[dict[str, Any]], l0_embedding_entries: dict[str, Any]) -> dict[str, Any]:
    archive_schema_version = str(cfg.overall_config.get('archive_schema_version', '') or '').strip()
    return {
        'schema_version': archive_schema_version,
        'layer': 'Layer2_Preserve',
        'agent_id': plan['agent_id'],
        'week_id': plan['week_id'],
        'window_start': plan['window_start'],
        'window_end': plan['window_end'],
        'created_at': utc_now_iso(),
        'included_files': [Path(path).name for path in plan.get('candidate_files', [])],
        'l0_index_dates': [str(entry.get('date', '')) for entry in l0_index_entries],
        'l0_embedding_keys': sorted(l0_embedding_entries.keys()),
    }


def run_archive_stage2(*, repo_root: str | None = None, week: str | None = None, agent: str | None = None, overwrite: bool = False, run_mode: str = 'manual', harness_only: bool = False, dry_run: bool = False, stage1_result: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_preserve_config(repo_root)
    stage1_result = stage1_result or run_archive_stage1(repo_root=repo_root, week=week, agent=agent, overwrite=overwrite, run_mode=run_mode, harness_only=harness_only, dry_run=dry_run)
    if not stage1_result.get('success', False):
        return preserve_result(success=False, stage='Layer2_Archive_Stage2_Archive', note='Stage1 未成功，Stage2 不执行。')

    results: list[dict[str, Any]] = []
    for plan in stage1_result.get('agent_plans', []):
        if not isinstance(plan, dict):
            continue
        if plan.get('status') == 'skipped':
            results.append({
                'agent_id': plan.get('agent_id'),
                'status': 'skipped',
                'skip_reason': plan.get('skip_reason'),
                'archive_path': plan.get('archive_path'),
            })
            continue
        archive_path = Path(str(plan['archive_path']))
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        l0_index_entries = _filter_l0_index_entries(Path(plan['l0_index_path']), plan['window_start'], plan['window_end'])
        l0_embedding_entries = _filter_l0_embedding_entries(Path(plan['l0_embeddings_path']), plan['window_start'], plan['window_end'])
        manifest = _manifest_for_plan(cfg, plan, l0_index_entries=l0_index_entries, l0_embedding_entries=l0_embedding_entries)
        mode = 'w:gz'
        with tarfile.open(archive_path, mode) as tf:
            for path_str in plan.get('candidate_files', []):
                path = Path(path_str)
                if path.exists() and path.is_file():
                    tf.add(path, arcname=path.name)
            _add_json_bytes(tf, L0_INDEX_SUBSET_FILENAME, l0_index_entries)
            _add_json_bytes(tf, L0_EMBEDDINGS_SUBSET_FILENAME, l0_embedding_entries)
            _add_json_bytes(tf, MANIFEST_FILENAME, manifest)
        results.append({
            'agent_id': plan['agent_id'],
            'status': 'archived',
            'archive_path': str(archive_path),
            'file_count': len(plan.get('candidate_files', [])),
            'l0_index_entry_count': len(l0_index_entries),
            'l0_embedding_entry_count': len(l0_embedding_entries),
        })

    return preserve_result(
        success=True,
        stage='Layer2_Archive_Stage2_Archive',
        note='Stage2 已完成：生成周级 archive tar.gz。',
        week_id=stage1_result.get('week_id'),
        window_start=stage1_result.get('window_start'),
        window_end=stage1_result.get('window_end'),
        results=results,
    )
