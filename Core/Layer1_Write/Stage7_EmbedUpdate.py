#!/usr/bin/env python3
"""Layer1 写入层的第7阶段：向量化索引更新。

职责：
- 读取 stage7.tasks
- 从 l0_index.json 构造 embedding 文本
- 调 embedding 服务生成向量并写入 l0_embeddings.json
- 若 use_embedding=false 或 embedding 服务不可用，则跳过并在 plan 中留痕
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

from Core.Layer1_Write.json_repair import load_json_with_repair
from Core.Layer1_Write.shared import LoadConfig, load_json_file, write_json_atomic


def _active_schema_version(repo_root: str | Path | None = None) -> str:
    overall_cfg = LoadConfig(repo_root).overall_config
    return str(overall_cfg.get('active_schema_version', '') or '').strip()


def _plan_path(repo_root: str | Path | None = None) -> Path:
    overall_cfg = LoadConfig(repo_root).overall_config
    store_root = Path(str(overall_cfg['store_dir'])).expanduser()
    staging_cfg = overall_cfg['store_dir_structure']['staging']
    staging_root = store_root / staging_cfg['root'] / staging_cfg['staging_surface']
    return staging_root / 'plan.json'


def _load_plan(repo_root: str | Path | None = None) -> dict[str, Any]:
    path = _plan_path(repo_root)
    if not path.exists():
        raise FileNotFoundError(f'plan.json 不存在: {path}')
    return load_json_file(path)


def _plan_write_path(repo_root: str | Path | None = None) -> Path:
    return _plan_path(repo_root)


def _load_json_dict(path: str | Path) -> dict[str, Any]:
    ok, payload, _repaired = load_json_with_repair(path)
    if not ok or not isinstance(payload, dict):
        raise ValueError(f'无法读取合法 JSON 对象: {path}')
    return payload


def _embedding_config(repo_root: str | Path | None = None) -> tuple[bool, str, str]:
    overall_cfg = LoadConfig(repo_root).overall_config
    return (
        bool(overall_cfg.get('use_embedding', True)),
        str(overall_cfg.get('embedding_model', 'nomic-embed-text:latest') or 'nomic-embed-text:latest'),
        str(overall_cfg.get('embedding_api_url', 'http://localhost:11434/v1/embeddings') or 'http://localhost:11434/v1/embeddings'),
    )


def _build_embed_text(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    summary = str(entry.get('summary', '') or '').strip()
    tags = entry.get('tags', []) or []
    mood = str(entry.get('mood', '') or '').strip()

    if summary:
        parts.append(f'摘要：{summary}')
    if isinstance(tags, list) and tags:
        parts.append(f"标签：{', '.join(str(tag) for tag in tags if isinstance(tag, str))}")
    if mood:
        parts.append(f'情绪：{mood}')
    return '\n'.join(parts)


def _request_embedding(text: str, *, model: str, api_url: str) -> list[float] | None:
    payload = json.dumps({'model': model, 'input': text}).encode('utf-8')
    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.load(resp)
    except Exception:
        return None

    vec = (result.get('embeddings') or [[]])[0]
    if not vec:
        vec = (result.get('data') or [{}])[0].get('embedding') or []
    if not isinstance(vec, list) or not vec:
        return None
    return [float(x) for x in vec]


def _load_or_init_embed_index(path: str | Path, *, agent_id: str, model: str, repo_root: str | Path | None = None) -> dict[str, Any]:
    schema_version = _active_schema_version(repo_root)
    file_path = Path(path)
    if file_path.exists():
        ok, payload, _repaired = load_json_with_repair(file_path)
        if ok and isinstance(payload, dict):
            payload.setdefault('schema_version', schema_version)
            payload.setdefault('agent_id', agent_id)
            payload.setdefault('model', model)
            payload.setdefault('updated_at', None)
            payload.setdefault('entries', {})
            if not isinstance(payload.get('entries'), dict):
                payload['entries'] = {}
            return payload

    return {
        'schema_version': schema_version,
        'agent_id': agent_id,
        'model': model,
        'updated_at': None,
        'entries': {},
    }


def _entry_key(entry: dict[str, Any]) -> str:
    depth = str(entry.get('depth', '') or '')
    if not depth:
        raise ValueError('L0 entry 缺少 depth')
    if depth == 'surface':
        date = str(entry.get('date', '') or '')
        if not date:
            raise ValueError('surface L0 entry 缺少 date')
        return f'{date}::{depth}'
    if depth == 'shallow':
        week = str(entry.get('week', '') or '')
        if not week:
            raise ValueError('shallow L0 entry 缺少 week')
        return f'{week}::{depth}'
    if depth == 'deep':
        window = str(entry.get('window', '') or '')
        if not window:
            raise ValueError('deep L0 entry 缺少 window')
        return f'{window}::{depth}'
    raise ValueError(f'未知 L0 depth: {depth}')


def _process_single_task(task: dict[str, Any], *, model: str, api_url: str, repo_root: str | Path | None = None) -> dict[str, Any]:
    agent_id = str(task.get('agent_id', '') or '')
    l0_index_path = str(task.get('l0_index_path', '') or '')
    embedding_index_path = str(task.get('embedding_index_path', '') or '')
    if not agent_id or not l0_index_path or not embedding_index_path:
        raise ValueError('stage7 task 缺少 agent_id / l0_index_path / embedding_index_path')

    l0_payload = _load_json_dict(l0_index_path)
    entries = l0_payload.get('entries', [])
    if not isinstance(entries, list):
        entries = []

    embed_index = _load_or_init_embed_index(embedding_index_path, agent_id=agent_id, model=model, repo_root=repo_root)
    embed_entries = embed_index.setdefault('entries', {})

    updated_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = _build_embed_text(entry)
        if not text.strip():
            continue
        embedding = _request_embedding(text, model=model, api_url=api_url)
        if embedding is None:
            raise RuntimeError('embedding service unavailable')
        key = _entry_key(entry)
        embed_entry = {
            'depth': str(entry.get('depth', '') or ''),
            'embedding': embedding,
            'text_used': text,
            'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        if embed_entry['depth'] == 'surface':
            embed_entry['date'] = str(entry.get('date', '') or '')
        elif embed_entry['depth'] == 'shallow':
            embed_entry['week'] = str(entry.get('week', '') or '')
        elif embed_entry['depth'] == 'deep':
            embed_entry['window'] = str(entry.get('window', '') or '')
        embed_entries[key] = embed_entry
        updated_count += 1

    embed_index['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    write_json_atomic(embedding_index_path, embed_index)

    return {
        'agent_id': agent_id,
        'status': 'completed',
        'l0_index_path': l0_index_path,
        'embedding_index_path': embedding_index_path,
        'updated_count': updated_count,
    }


def _skip_all_tasks(stage7: dict[str, Any], tasks: list[dict[str, Any]], *, reason: str) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    skipped_agents: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        agent_id = str(task.get('agent_id', '') or '')
        task['status'] = 'skipped'
        results.append({
            'agent_id': agent_id,
            'status': 'skipped',
            'reason': reason,
            'l0_index_path': str(task.get('l0_index_path', '') or ''),
            'embedding_index_path': str(task.get('embedding_index_path', '') or ''),
        })
        if agent_id:
            skipped_agents.append(agent_id)

    stage7['status'] = 'skipped'
    stage7['skip_reason'] = reason
    stage7['results'] = results
    stage7['succeed_agents'] = []
    stage7['failed_agents'] = []
    stage7['skipped_agents'] = skipped_agents
    return {
        'success': True,
        'note': f'Stage7 已跳过：{reason}',
        'results': results,
        'succeed_agents': [],
        'failed_agents': [],
        'skipped_agents': skipped_agents,
        'skipped': True,
    }


def run_stage7(repo_root: str | Path | None = None) -> dict[str, Any]:
    plan = _load_plan(repo_root)
    root = plan.setdefault('plan', {})
    stage7 = root.setdefault('stage7', {})
    tasks = stage7.get('tasks', [])
    if not isinstance(tasks, list):
        tasks = []

    use_embedding, model, api_url = _embedding_config(repo_root)
    if not use_embedding:
        result = _skip_all_tasks(stage7, tasks, reason='use_embedding=false')
        root.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        write_json_atomic(_plan_write_path(repo_root), plan)
        return result

    results: list[dict[str, Any]] = []
    failed_agents: list[str] = []
    succeed_agents: list[str] = []

    for task in tasks:
        if not isinstance(task, dict):
            continue
        agent_id = str(task.get('agent_id', '') or '')
        try:
            result = _process_single_task(task, model=model, api_url=api_url, repo_root=repo_root)
            results.append(result)
            task['status'] = 'completed'
            if agent_id:
                succeed_agents.append(agent_id)
        except Exception as exc:  # noqa: BLE001
            if 'embedding service unavailable' in str(exc):
                result = _skip_all_tasks(stage7, tasks, reason='embedding_unavailable')
                root.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                write_json_atomic(_plan_write_path(repo_root), plan)
                return result
            results.append({
                'agent_id': agent_id,
                'status': 'failed',
                'reason': str(exc),
                'l0_index_path': str(task.get('l0_index_path', '') or ''),
                'embedding_index_path': str(task.get('embedding_index_path', '') or ''),
            })
            task['status'] = 'failed'
            if agent_id:
                failed_agents.append(agent_id)

    stage7['status'] = 'completed' if not failed_agents else 'failed'
    stage7.pop('skip_reason', None)
    stage7['results'] = results
    stage7['succeed_agents'] = succeed_agents
    stage7['failed_agents'] = failed_agents
    stage7['skipped_agents'] = []
    root.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    write_json_atomic(_plan_write_path(repo_root), plan)

    return {
        'success': not failed_agents,
        'note': 'Stage7 执行完成。' if not failed_agents else 'Stage7 执行结束，但存在失败 agent。',
        'results': results,
        'succeed_agents': succeed_agents,
        'failed_agents': failed_agents,
        'skipped_agents': [],
        'skipped': False,
    }


__all__ = [
    'run_stage7',
]
