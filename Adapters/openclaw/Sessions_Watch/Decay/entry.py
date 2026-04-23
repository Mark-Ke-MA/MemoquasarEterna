from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ...openclaw_shared_funcs import LoadConfig, SessionFinder, dbg


STAGE_NAME = 'OpenClaw_Sessions_Watch_Decay'


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


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _parse_iso_date(text: str) -> date:
    return datetime.strptime(text, '%Y-%m-%d').date()


def _previous_iso_week_monday(today: date) -> date:
    return today - timedelta(days=today.isoweekday() - 1) - timedelta(days=7)


def _target_week_monday(week: str | None) -> date:
    if week and str(week).strip():
        return datetime.strptime(str(week).strip() + '-1', '%G-W%V-%u').date()
    return _previous_iso_week_monday(datetime.now().date())


def _boundary_date_from_week(week: str | None, *, decay_week_interval: int) -> date:
    monday = _target_week_monday(week)
    cutoff_monday = monday - timedelta(days=7 * int(decay_week_interval))
    return cutoff_monday + timedelta(days=6)


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
        'archived_registry_path': archived_registry_path,
        'archive_session_files_root': archive_session_files_root,
    }


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


def _decay_config(cfg: LoadConfig) -> dict[str, Any]:
    raw = cfg.openclaw_config.get('sessions_registry_maintenance', {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        'session_registry_decay': bool(raw.get('session_registry_decay', True)),
        'session_files_decay': bool(raw.get('session_files_decay', False)),
        'decay_week_interval': int(raw.get('decay_week_interval', 2) or 0),
    }


def _archive_dates_set(archived_registry: dict[str, Any]) -> set[str]:
    sessions = archived_registry.get('sessions', {}) if isinstance(archived_registry, dict) else {}
    if not isinstance(sessions, dict):
        return set()
    out: set[str] = set()
    for entry in sessions.values():
        if not isinstance(entry, dict):
            continue
        for item in entry.get('dates', []):
            text = str(item).strip()
            if text:
                out.add(text)
    return out


def _active_registry_candidates(active_registry: dict[str, Any], *, boundary_date: date) -> tuple[list[str], list[str], set[str], dict[str, list[str]]]:
    history = active_registry.get('history_sessions', []) if isinstance(active_registry, dict) else []
    candidate_dates: list[str] = []
    candidate_session_ids: list[str] = []
    outside_window_session_ids: set[str] = set()
    date_to_session_ids: dict[str, list[str]] = {}
    seen_candidate_dates: set[str] = set()
    seen_candidate_session_ids: set[str] = set()

    for day_entry in history if isinstance(history, list) else []:
        if not isinstance(day_entry, dict):
            continue
        date_text = str(day_entry.get('date', '') or '').strip()
        if not date_text:
            continue
        try:
            day = _parse_iso_date(date_text)
        except Exception:
            continue
        sessions = day_entry.get('sessions', [])
        if not isinstance(sessions, list):
            sessions = []
        session_ids_for_day: list[str] = []
        for session in sessions:
            if not isinstance(session, dict):
                continue
            session_id = str(session.get('sessionId', '') or '').strip()
            if not session_id:
                continue
            session_ids_for_day.append(session_id)
            if day <= boundary_date:
                if session_id not in seen_candidate_session_ids:
                    seen_candidate_session_ids.add(session_id)
                    candidate_session_ids.append(session_id)
            else:
                outside_window_session_ids.add(session_id)
        if day <= boundary_date:
            if date_text not in seen_candidate_dates:
                seen_candidate_dates.add(date_text)
                candidate_dates.append(date_text)
            date_to_session_ids[date_text] = session_ids_for_day
    return candidate_dates, candidate_session_ids, outside_window_session_ids, date_to_session_ids


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
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _build_candidate_session_files_list(sessions_path: Path, session_ids: list[str]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for session_id in session_ids:
        for path in _find_session_file_candidates(sessions_path, session_id):
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
    return out


def _filter_archived_files(candidates: list[Path], archive_session_files_root: Path) -> tuple[list[Path], list[str]]:
    kept: list[Path] = []
    removed_missing_archive: list[str] = []
    for path in candidates:
        basename = path.name
        if (archive_session_files_root / basename).exists():
            kept.append(path)
        else:
            removed_missing_archive.append(basename)
    return kept, removed_missing_archive


def _prune_active_registry(active_registry: dict[str, Any], target_dates: set[str]) -> tuple[dict[str, Any], list[str]]:
    history = active_registry.get('history_sessions', []) if isinstance(active_registry, dict) else []
    if not isinstance(history, list):
        history = []
    new_history: list[dict[str, Any]] = []
    removed_dates: list[str] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        date_text = str(item.get('date', '') or '').strip()
        if date_text and date_text in target_dates:
            removed_dates.append(date_text)
            continue
        new_history.append(item)
    new_registry = dict(active_registry) if isinstance(active_registry, dict) else {}
    new_registry['history_sessions'] = new_history
    return new_registry, removed_dates


def _delete_active_session_files(candidates: list[Path], *, dry_run: bool) -> tuple[list[str], list[str], list[dict[str, str]]]:
    deleted: list[str] = []
    missing: list[str] = []
    failed: list[dict[str, str]] = []
    for path in candidates:
        try:
            if not path.exists():
                missing.append(path.name)
                continue
            if dry_run:
                deleted.append(path.name)
                continue
            path.unlink()
            deleted.append(path.name)
        except Exception as exc:
            failed.append({'file': path.name, 'reason': str(exc)})
    return deleted, missing, failed


def entry(context: dict):
    repo_root = context.get('repo_root') if isinstance(context, dict) else None
    inputs = context.get('inputs', {}) if isinstance(context, dict) else {}
    cfg = LoadConfig(repo_root)

    week = inputs.get('week')
    agent = inputs.get('agent') or inputs.get('agent_id')
    dry_run = bool(inputs.get('dry_run', False))

    decay_cfg = _decay_config(cfg)
    decay_week_interval = int(decay_cfg['decay_week_interval'])
    if decay_week_interval < 0:
        return {
            'success': False,
            'stage': STAGE_NAME,
            'error': 'OpenclawConfig.json.sessions_registry_maintenance.decay_week_interval 不能为负数',
        }

    try:
        target_agents = _selected_agents(cfg, agent)
    except Exception as exc:
        return {
            'success': False,
            'stage': STAGE_NAME,
            'error': str(exc),
        }

    boundary_date = _boundary_date_from_week(str(week).strip() if week is not None else None, decay_week_interval=decay_week_interval)
    now_iso = _utc_now_iso()
    results: list[dict[str, Any]] = []

    for agent_id in target_agents:
        paths = _openclaw_paths(cfg, agent_id)
        active_registry = _load_json_or_default(paths['active_registry_path'], {'history_sessions': []})
        archived_registry = _load_json_or_default(paths['archived_registry_path'], {'schema_version': str(cfg.openclaw_config.get('schema_version', '') or '').strip(), 'agent_id': agent_id, 'sessions': {}})
        archive_dates = _archive_dates_set(archived_registry)
        archived_sessions = archived_registry.get('sessions', {}) if isinstance(archived_registry, dict) else {}
        if not isinstance(archived_sessions, dict):
            archived_sessions = {}

        current_session_id = SessionFinder(repo_root=repo_root, agentId=agent_id).find_current_session_id()
        candidate_dates_initial, candidate_session_ids_initial, outside_window_session_ids, _date_to_session_ids = _active_registry_candidates(active_registry, boundary_date=boundary_date)

        candidate_dates_final = [date_text for date_text in candidate_dates_initial if date_text in archive_dates]
        removed_dates_missing_archive = [date_text for date_text in candidate_dates_initial if date_text not in archive_dates]

        candidate_session_ids_final: list[str] = []
        removed_sessions_missing_archive: list[str] = []
        removed_sessions_outside_window: list[str] = []
        removed_sessions_current: list[str] = []
        seen_session_ids: set[str] = set()
        for session_id in candidate_session_ids_initial:
            if session_id in seen_session_ids:
                continue
            seen_session_ids.add(session_id)
            if current_session_id and session_id == current_session_id:
                removed_sessions_current.append(session_id)
                continue
            if session_id not in archived_sessions:
                removed_sessions_missing_archive.append(session_id)
                continue
            if session_id in outside_window_session_ids:
                removed_sessions_outside_window.append(session_id)
                continue
            candidate_session_ids_final.append(session_id)

        candidate_session_files_initial_paths = _build_candidate_session_files_list(paths['sessions_path'], candidate_session_ids_final)
        candidate_session_files_final_paths, removed_files_missing_archive = _filter_archived_files(candidate_session_files_initial_paths, paths['archive_session_files_root'])

        registry_dates_deleted: list[str] = []
        session_files_deleted: list[str] = []
        session_files_missing_on_delete: list[str] = []
        session_files_delete_failed: list[dict[str, str]] = []

        if decay_cfg['session_registry_decay'] and candidate_dates_final and not dry_run:
            new_registry, registry_dates_deleted = _prune_active_registry(active_registry, set(candidate_dates_final))
            _write_json_atomic(paths['active_registry_path'], new_registry)
        elif decay_cfg['session_registry_decay'] and candidate_dates_final and dry_run:
            registry_dates_deleted = list(candidate_dates_final)

        if decay_cfg['session_files_decay'] and candidate_session_files_final_paths:
            deleted, missing, failed = _delete_active_session_files(candidate_session_files_final_paths, dry_run=dry_run)
            session_files_deleted = deleted
            session_files_missing_on_delete = missing
            session_files_delete_failed = failed

        dbg(f'[Sessions_Watch Decay] agent={agent_id}, boundary={boundary_date.isoformat()}, candidate_dates={len(candidate_dates_final)}, candidate_sessions={len(candidate_session_ids_final)}, candidate_files={len(candidate_session_files_final_paths)}')
        results.append({
            'agent_id': agent_id,
            'current_session_id': current_session_id,
            'boundary_date': boundary_date.isoformat(),
            'active_registry_path': str(paths['active_registry_path']),
            'archived_registry_path': str(paths['archived_registry_path']),
            'active_sessions_path': str(paths['sessions_path']),
            'archive_session_files_root': str(paths['archive_session_files_root']),
            'session_registry_decay': bool(decay_cfg['session_registry_decay']),
            'session_files_decay': bool(decay_cfg['session_files_decay']),
            'dry_run': dry_run,
            'candidate_dates_initial': candidate_dates_initial,
            'candidate_dates_final': candidate_dates_final,
            'removed_dates_missing_archive': removed_dates_missing_archive,
            'candidate_sessionUUIDs_initial': candidate_session_ids_initial,
            'candidate_sessionUUIDs_final': candidate_session_ids_final,
            'removed_sessionUUIDs_missing_archive': removed_sessions_missing_archive,
            'removed_sessionUUIDs_outside_window': removed_sessions_outside_window,
            'removed_sessionUUIDs_current': removed_sessions_current,
            'candidate_session_files_initial': [path.name for path in candidate_session_files_initial_paths],
            'candidate_session_files_final': [path.name for path in candidate_session_files_final_paths],
            'removed_session_files_missing_archive': removed_files_missing_archive,
            'registry_dates_deleted': registry_dates_deleted,
            'session_files_deleted': session_files_deleted,
            'session_files_missing_on_delete': session_files_missing_on_delete,
            'session_files_delete_failed': session_files_delete_failed,
            'evaluated_at': now_iso,
        })

    return {
        'success': True,
        'stage': STAGE_NAME,
        'week': str(week).strip() if week is not None else None,
        'dry_run': dry_run,
        'decay_week_interval': decay_week_interval,
        'results': results,
    }
