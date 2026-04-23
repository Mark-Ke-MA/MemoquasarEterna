#!/usr/bin/env python3
from __future__ import annotations

import json
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from Core.Layer2_Preserve.core import L0_EMBEDDINGS_SUBSET_FILENAME, L0_INDEX_SUBSET_FILENAME, MANIFEST_FILENAME, load_preserve_config, preserve_result
from Core.Layer2_Preserve.shared import load_json_file, utc_now_iso, write_json_atomic
from Core.Layer2_Preserve.restore_Stage1_Plan import run_restore_stage1


def _safe_extract_member(tf: tarfile.TarFile, member_name: str, target_path: Path) -> bool:
    try:
        member = tf.getmember(member_name)
    except KeyError:
        return False
    extracted = tf.extractfile(member)
    if extracted is None:
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(extracted.read())
    return True


def _merge_l0_index(path: Path, incoming: list[dict[str, Any]], *, overwrite: bool) -> int:
    payload = load_json_file(path) if path.exists() else {}
    if not isinstance(payload, dict):
        payload = {}
    entries = payload.get('entries', [])
    if not isinstance(entries, list):
        entries = []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = (str(entry.get('date', '')), str(entry.get('depth', 'surface')))
        if key not in by_key:
            order.append(key)
        by_key[key] = entry
    changed = 0
    for entry in incoming:
        if not isinstance(entry, dict):
            continue
        key = (str(entry.get('date', '')), str(entry.get('depth', 'surface')))
        if key in by_key and not overwrite:
            continue
        if key not in by_key:
            order.append(key)
        by_key[key] = entry
        changed += 1
    payload['entries'] = [by_key[key] for key in order]
    write_json_atomic(path, payload)
    return changed


def _merge_l0_embeddings(path: Path, incoming: dict[str, Any], *, overwrite: bool) -> int:
    payload = load_json_file(path) if path.exists() else {}
    if not isinstance(payload, dict):
        payload = {}
    entries = payload.get('entries', {})
    if not isinstance(entries, dict):
        entries = {}
    changed = 0
    for key, value in incoming.items():
        if key in entries and not overwrite:
            continue
        entries[key] = value
        changed += 1
    payload['entries'] = entries
    write_json_atomic(path, payload)
    return changed


def _write_subset_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)


def run_restore_stage2(*, repo_root: str | None = None, week: str | None = None, date: str | None = None, agent: str | None = None, which_level: str | None = None, restore_mode: str = 'mirrored', run_name: str | None = None, stage1_result: dict[str, Any] | None = None) -> dict[str, Any]:
    load_preserve_config(repo_root)
    stage1_result = stage1_result or run_restore_stage1(repo_root=repo_root, week=week, date=date, agent=agent, which_level=which_level, restore_mode=restore_mode, run_name=run_name)
    if not stage1_result.get('success', False):
        return preserve_result(success=False, stage='Layer2_Restore_Stage2_Apply', note='Stage1 未成功，Stage2 不执行。')

    results: list[dict[str, Any]] = []
    for plan in stage1_result.get('agent_plans', []):
        if not isinstance(plan, dict):
            continue
        if plan.get('status') == 'skipped':
            results.append({
                'agent_id': plan.get('agent_id'),
                'status': 'skipped',
                'reason': plan.get('skip_reason'),
                'archive_path': plan.get('archive_path'),
                'restored_files': [],
                'active_files': [],
                'l0_index_entries_restored': 0,
                'l0_embedding_entries_restored': 0,
            })
            continue

        archive_path = Path(str(plan['archive_path']))
        target_surface_root = Path(str(plan['target_surface_root']))
        restored_files: list[str] = []
        active_files: list[str] = []
        l0_index_entries_restored = 0
        l0_embedding_entries_restored = 0
        file_conflicts: list[str] = []
        status = 'restored'
        reason = None

        with TemporaryDirectory(prefix='layer2_restore_') as tmpdir, tarfile.open(archive_path, 'r:gz') as tf:
            tmp_root = Path(tmpdir)
            for name in plan.get('files_to_restore', []):
                src_tmp_path = tmp_root / name
                if not _safe_extract_member(tf, name, src_tmp_path):
                    continue
                day_text = name[:10]
                target_path = target_surface_root / day_text[:7] / name
                if plan.get('restore_mode') == 'mirrored':
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_bytes(src_tmp_path.read_bytes())
                    restored_files.append(str(target_path))
                    continue
                if target_path.exists() and plan.get('restore_mode') == 'update':
                    file_conflicts.append(str(target_path))
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(src_tmp_path.read_bytes())
                restored_files.append(str(target_path))
                active_files.append(str(target_path))

        if plan.get('restore_mode') == 'mirrored':
            if plan.get('l0_index_entries'):
                _write_subset_json(Path(plan['l0_target_path']), {'entries': plan['l0_index_entries']})
                l0_index_entries_restored = len(plan['l0_index_entries'])
            if plan.get('l0_embedding_entries'):
                _write_subset_json(Path(plan['l0_embeddings_target_path']), {'entries': plan['l0_embedding_entries']})
                l0_embedding_entries_restored = len(plan['l0_embedding_entries'])
        else:
            l0_target_path = Path(str(plan['l0_target_path']))
            l0_target_path.parent.mkdir(parents=True, exist_ok=True)
            l0_embeddings_target_path = Path(str(plan['l0_embeddings_target_path']))
            l0_embeddings_target_path.parent.mkdir(parents=True, exist_ok=True)
            l0_index_entries_restored = _merge_l0_index(l0_target_path, plan.get('l0_index_entries', []), overwrite=(plan.get('restore_mode') == 'overwrite'))
            l0_embedding_entries_restored = _merge_l0_embeddings(l0_embeddings_target_path, plan.get('l0_embedding_entries', {}), overwrite=(plan.get('restore_mode') == 'overwrite'))

        if not restored_files and not l0_index_entries_restored and not l0_embedding_entries_restored:
            status = 'skipped'
            reason = 'no_changes_applied'
        elif file_conflicts:
            status = 'partial' if restored_files or l0_index_entries_restored or l0_embedding_entries_restored else 'skipped'
            reason = 'file_conflicts_skipped'

        results.append({
            'agent_id': plan.get('agent_id'),
            'status': status,
            'reason': reason,
            'archive_path': plan.get('archive_path'),
            'restored_files': restored_files,
            'active_files': active_files,
            'l0_index_entries_restored': l0_index_entries_restored,
            'l0_embedding_entries_restored': l0_embedding_entries_restored,
            'file_conflicts': file_conflicts,
            'restore_mode': plan.get('restore_mode'),
        })

    return preserve_result(
        success=True,
        stage='Layer2_Restore_Stage2_Apply',
        note='Stage2 已完成：按 restore 计划恢复目标对象。',
        selector_type=stage1_result.get('selector_type'),
        selector_value=stage1_result.get('selector_value'),
        week_id=stage1_result.get('week_id'),
        window_start=stage1_result.get('window_start'),
        window_end=stage1_result.get('window_end'),
        restore_mode=stage1_result.get('restore_mode'),
        run_name=stage1_result.get('run_name'),
        created_at=utc_now_iso(),
        results=results,
    )
