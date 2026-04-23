from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ...openclaw_shared_funcs import LoadConfig, SessionFinder, dbg

def _openclaw_schema_version(cfg: LoadConfig) -> str:
    return str(cfg.openclaw_config.get('schema_version', '') or '').strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _load_json_or_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return json.loads(json.dumps(default))
    return data if isinstance(data, dict) else json.loads(json.dumps(default))


def _parse_iso_date(text: str) -> date:
    return datetime.strptime(text, '%Y-%m-%d').date()


def _previous_iso_week_monday(today: date) -> date:
    return today - timedelta(days=today.isoweekday() - 1) - timedelta(days=7)


def _boundary_date_from_week(week: str | None) -> date:
    if week and str(week).strip():
        monday = datetime.strptime(str(week).strip() + '-1', '%G-W%V-%u').date()
    else:
        monday = _previous_iso_week_monday(datetime.now().date())
    return monday + timedelta(days=6)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _render_openclaw_path_template(cfg: LoadConfig, template: str, agent_id: str) -> Path:
    adapter_dirname = str(cfg.openclaw_config.get('adapter_dirname', cfg.adapter_root.name) or cfg.adapter_root.name)
    archive_structure = cfg.overall_config.get('archive_dir_structure', {}) if isinstance(cfg.overall_config, dict) else {}
    archive_harness_dirname = str(archive_structure.get('harness', 'harness') or 'harness')
    return Path(os.path.expanduser(template.format(
        agentId=agent_id,
        agent_id=agent_id,
        code_dir=cfg.code_root,
        store_dir=cfg.store_root,
        archive_dir=os.path.expanduser(cfg.overall_config['archive_dir']),
        adapter_dirname=adapter_dirname,
        archive_harness_dirname=archive_harness_dirname,
    )))


def _openclaw_paths(cfg: LoadConfig, agent_id: str) -> dict[str, Path]:
    sessions_path = _render_openclaw_path_template(cfg, cfg.openclaw_config['sessions_path'], agent_id)
    active_registry_path = _render_openclaw_path_template(cfg, cfg.openclaw_config['sessions_registry_path'], agent_id)
    archived_registry_path = _render_openclaw_path_template(cfg, cfg.openclaw_config['sessions_registry_archive_path'], agent_id)
    archive_session_files_root = _render_openclaw_path_template(cfg, cfg.openclaw_config['sessions_files_archive_dir'], agent_id)
    return {
        'sessions_path': sessions_path,
        'active_registry_path': active_registry_path,
        'archive_agent_root': archived_registry_path.parent,
        'archive_session_files_root': archive_session_files_root,
        'archived_registry_path': archived_registry_path,
    }


def _sorted_session_items(sessions: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any]]] = []
    for session_id, entry in sessions.items():
        if not isinstance(session_id, str) or not isinstance(entry, dict):
            continue
        items.append((session_id, entry))

    def _sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, str, str]:
        session_id, entry = item
        first_seen = str(entry.get('first_seen_min', '') or '').strip()
        missing = 1 if not first_seen else 0
        return (missing, first_seen, session_id)

    return sorted(items, key=_sort_key)


def _normalize_archived_registry(data: dict[str, Any] | None, agent_id: str, *, schema_version: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    sessions = data.get('sessions', {})
    if not isinstance(sessions, dict):
        sessions = {}
    normalized: dict[str, Any] = {
        'schema_version': str(data.get('schema_version', schema_version) or schema_version),
        'agent_id': str(data.get('agent_id', agent_id) or agent_id),
        'sessions': {},
    }
    for session_id, entry in _sorted_session_items(sessions):
        dates = sorted({str(item) for item in entry.get('dates', []) if str(item).strip()})
        archived_files = []
        seen_files: set[str] = set()
        for item in entry.get('archived_files', []):
            name = str(item or '').strip()
            if not name or name in seen_files:
                continue
            seen_files.add(name)
            archived_files.append(name)
        normalized['sessions'][session_id] = {
            'dates': dates,
            'first_seen_min': str(entry.get('first_seen_min', '') or ''),
            'archived_files': archived_files,
            'archived_at': str(entry.get('archived_at', '') or ''),
        }
    return normalized


def _collect_sessions_from_active_registry(path: Path, *, boundary_date: date) -> dict[str, dict[str, Any]]:
    data = _load_json_or_default(path, {'history_sessions': []})
    history = data.get('history_sessions', []) if isinstance(data, dict) else []
    aggregated: dict[str, dict[str, Any]] = {}
    for day_entry in history:
        if not isinstance(day_entry, dict):
            continue
        date_text = str(day_entry.get('date', '') or '').strip()
        if not date_text:
            continue
        try:
            day = _parse_iso_date(date_text)
        except Exception:
            continue
        if day > boundary_date:
            continue
        for session in day_entry.get('sessions', []):
            if not isinstance(session, dict):
                continue
            session_id = str(session.get('sessionId', '') or '').strip()
            if not session_id:
                continue
            first_seen = str(session.get('first_seen', '') or '').strip()
            item = aggregated.setdefault(session_id, {
                'dates': set(),
                'first_seen_min': '',
            })
            item['dates'].add(date_text)
            if first_seen and (not item['first_seen_min'] or first_seen < item['first_seen_min']):
                item['first_seen_min'] = first_seen
    return aggregated


def _find_session_file_candidates(sessions_path: Path, session_id: str) -> list[Path]:
    if not sessions_path.exists() or not sessions_path.is_dir():
        return []
    plain = sessions_path / f'{session_id}.jsonl'
    candidates: list[Path] = []
    if plain.exists() and plain.is_file():
        candidates.append(plain)
    for path in sorted(sessions_path.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if name == f'{session_id}.jsonl':
            continue
        if name.startswith(session_id) and '.reset.' in name:
            candidates.append(path)
    # 去重并稳定保序
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _copy_candidates(candidates: list[Path], archive_session_files_root: Path, *, dry_run: bool) -> tuple[list[str], list[str], list[str]]:
    archived_files: list[str] = []
    copied_files: list[str] = []
    skipped_existing: list[str] = []
    for src in candidates:
        basename = src.name
        archived_files.append(basename)
        dst = archive_session_files_root / basename
        if dst.exists():
            skipped_existing.append(basename)
            continue
        if dry_run:
            copied_files.append(basename)
            continue
        archive_session_files_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied_files.append(basename)
    return archived_files, copied_files, skipped_existing


def _merge_archived_session(existing: dict[str, Any] | None, *, dates: list[str], first_seen_min: str, archived_files: list[str], archived_at: str) -> dict[str, Any]:
    current = existing if isinstance(existing, dict) else {}
    merged_dates = sorted({str(item) for item in current.get('dates', []) + dates if str(item).strip()})
    merged_files: list[str] = []
    seen_files: set[str] = set()
    for item in list(current.get('archived_files', [])) + list(archived_files):
        name = str(item or '').strip()
        if not name or name in seen_files:
            continue
        seen_files.add(name)
        merged_files.append(name)
    old_first_seen = str(current.get('first_seen_min', '') or '').strip()
    chosen_first_seen = first_seen_min or old_first_seen
    if old_first_seen and chosen_first_seen:
        chosen_first_seen = min(old_first_seen, chosen_first_seen)
    elif old_first_seen:
        chosen_first_seen = old_first_seen
    return {
        'dates': merged_dates,
        'first_seen_min': chosen_first_seen,
        'archived_files': merged_files,
        'archived_at': archived_at,
    }


def _should_run_harness(harness_only: bool, core_only: bool) -> bool:
    if harness_only:
        return True
    if core_only:
        return False
    return True


def _selected_agents(cfg: LoadConfig, raw_agent: str | None) -> list[str]:
    all_agents = list(cfg.overall_config.get('agentId_list', []))
    if raw_agent is None or not str(raw_agent).strip():
        return all_agents
    selected: list[str] = []
    seen: set[str] = set()
    for item in str(raw_agent).split(','):
        agent_id = item.strip()
        if not agent_id or agent_id in seen:
            continue
        if agent_id not in all_agents:
            raise ValueError(f'未知 agent: {agent_id}')
        seen.add(agent_id)
        selected.append(agent_id)
    return selected


def entry(context: dict):
    repo_root = context.get('repo_root')
    inputs = context.get('inputs', {}) if isinstance(context, dict) else {}
    cfg = LoadConfig(repo_root)

    run_mode = str(inputs.get('run_mode', 'manual') or 'manual')
    harness_only = bool(inputs.get('harness_only', False))
    core_only = bool(inputs.get('core_only', False))
    dry_run = bool(inputs.get('dry_run', False))
    week = inputs.get('week')
    agent = inputs.get('agent') or inputs.get('agent_id')

    if run_mode not in {'auto', 'manual'}:
        return {
            'success': False,
            'stage': 'OpenClaw_Sessions_Watch_Preserve',
            'error': f'未知 run_mode: {run_mode}',
        }

    if not _should_run_harness(harness_only, core_only):
        return {
            'success': True,
            'stage': 'OpenClaw_Sessions_Watch_Preserve',
            'status': 'skipped',
            'reason': 'core_only',
            'run_mode': run_mode,
            'harness_only': harness_only,
            'core_only': core_only,
        }

    try:
        target_agents = _selected_agents(cfg, agent)
    except Exception as exc:
        return {
            'success': False,
            'stage': 'OpenClaw_Sessions_Watch_Preserve',
            'error': str(exc),
        }

    openclaw_schema_version = _openclaw_schema_version(cfg)
    results: list[dict[str, Any]] = []
    now_iso = _utc_now_iso()
    boundary_date = _boundary_date_from_week(str(week).strip() if week is not None else None)
    for agent_id in target_agents:
        paths = _openclaw_paths(cfg, agent_id)
        dbg(f'[Sessions_Watch Preserve] agent={agent_id}, boundary={boundary_date.isoformat()}')
        active_sessions = _collect_sessions_from_active_registry(paths['active_registry_path'], boundary_date=boundary_date)
        current_session_id = SessionFinder(repo_root=repo_root, agentId=agent_id).find_current_session_id()
        target_session_ids = sorted(sid for sid in active_sessions.keys() if sid and sid != current_session_id)

        archived_registry = _normalize_archived_registry(
            _load_json_or_default(paths['archived_registry_path'], {'schema_version': openclaw_schema_version, 'agent_id': agent_id, 'sessions': {}}),
            agent_id,
            schema_version=openclaw_schema_version,
        )

        archived_files_count = 0
        copied_count = 0
        skipped_existing_count = 0
        missing_file_session_ids: list[str] = []
        archived_session_ids: list[str] = []

        for session_id in target_session_ids:
            meta = active_sessions.get(session_id, {})
            candidates = _find_session_file_candidates(paths['sessions_path'], session_id)
            archived_files, copied_files, skipped_existing = _copy_candidates(candidates, paths['archive_session_files_root'], dry_run=dry_run)
            if not candidates:
                missing_file_session_ids.append(session_id)
            archived_registry['sessions'][session_id] = _merge_archived_session(
                archived_registry['sessions'].get(session_id),
                dates=sorted(meta.get('dates', set())),
                first_seen_min=str(meta.get('first_seen_min', '') or ''),
                archived_files=archived_files,
                archived_at=now_iso,
            )
            archived_files_count += len(archived_files)
            copied_count += len(copied_files)
            skipped_existing_count += len(skipped_existing)
            archived_session_ids.append(session_id)

        archived_registry = _normalize_archived_registry(archived_registry, agent_id, schema_version=openclaw_schema_version)
        if not dry_run:
            _write_json_atomic(paths['archived_registry_path'], archived_registry)

        results.append({
            'agent_id': agent_id,
            'current_session_id': current_session_id,
            'boundary_date': boundary_date.isoformat(),
            'active_registry_path': str(paths['active_registry_path']),
            'archived_registry_path': str(paths['archived_registry_path']),
            'archive_session_files_root': str(paths['archive_session_files_root']),
            'candidate_session_ids': len(active_sessions),
            'target_session_ids': len(target_session_ids),
            'archived_session_ids': archived_session_ids,
            'archived_files_count': archived_files_count,
            'copied_files_count': copied_count,
            'skipped_existing_count': skipped_existing_count,
            'missing_file_session_ids': missing_file_session_ids,
            'dry_run': dry_run,
        })

    return {
        'success': True,
        'stage': 'OpenClaw_Sessions_Watch_Preserve',
        'run_mode': run_mode,
        'harness_only': harness_only,
        'core_only': core_only,
        'dry_run': dry_run,
        'results': results,
    }
