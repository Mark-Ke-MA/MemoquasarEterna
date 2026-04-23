#!/usr/bin/env python3
"""Layer1 写入层的第1阶段：调用 Layer0，并初始化本轮 plan。

职责：
- 清理上一轮残留的 plan.json 与 staging_surface 下的残留内容
- 写入本轮初始 plan.json
- 对选中的 agent 依次调用 `ENTRY_LAYER0.py`
- 根据 Layer0 结果更新 plan.json

注意：
本文件只保留阶段逻辑函数，不再承担 CLI 入口职责。
CLI 统一由 `ENTRY_LAYER1.py` 负责。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Layer1_Write.core import load_layer1_config
from Core.Layer1_Write.shared import (
    LoadConfig,
    build_layer0_artifact_paths,
    build_store_paths,
    dbg,
    get_previous_window_date,
    load_json_file,
    output_failure,
    write_json_atomic,
)
from Core.harness_connector import call_optional_connector, load_harness_connector


HARNESS = LoadConfig(ROOT).overall_config.get('harness', 'openclaw')
_CONNECTOR = load_harness_connector(repo_root=ROOT, harness=HARNESS)


# ---------------------------------------------------------------------------
# 命令构造
# ---------------------------------------------------------------------------


def build_stage1_call_layer0_command(*, agent_id: str, target_date: str, repo_root: str | None = None, stage1_staging_only: bool = False) -> list[str]:
    """拼出调用 Layer0 的命令。"""
    repo = Path(repo_root) if repo_root is not None else ROOT
    layer0_script = repo / 'Core' / 'Layer0_Extract' / 'ENTRY_LAYER0.py'
    cmd = [
        sys.executable,
        str(layer0_script),
        '--agent',
        agent_id,
        '--date',
        target_date,
        '--write-staging',
    ]
    if not stage1_staging_only:
        cmd.append('--write-l2')
        cmd.append('--write-l1-init')
    return cmd


def call_layer0_for_agents(*, agent_ids: list[str], target_date: str, repo_root: str | None = None, dry_run: bool = False, stage1_staging_only: bool = False) -> list[dict[str, Any]]:
    """按给定顺序依次调用 Layer0。"""
    results: list[dict[str, Any]] = []
    for agent_id in agent_ids:
        cmd = build_stage1_call_layer0_command(agent_id=agent_id, target_date=target_date, repo_root=repo_root, stage1_staging_only=stage1_staging_only)
        if dry_run:
            results.append({
                'agent_id': agent_id,
                'command': cmd,
                'dry_run': True,
                'returncode': None,
                'stdout_len': 0,
                'stderr_len': 0,
                'ok': True,
            })
            continue

        proc = subprocess.run(cmd, capture_output=True, text=True)
        results.append({
            'agent_id': agent_id,
            'command': cmd,
            'dry_run': False,
            'returncode': proc.returncode,
            'stdout_len': len(proc.stdout or ''),
            'stderr_len': len(proc.stderr or ''),
            'ok': proc.returncode == 0,
        })
    return results


def call_layer0_for_all_agents(*, target_date: str, repo_root: str | None = None, dry_run: bool = False, stage1_staging_only: bool = False) -> list[dict[str, Any]]:
    """对配置里的所有 agent 逐个调用 Layer0。"""
    cfg = load_layer1_config(repo_root)
    agent_ids = list(cfg.raw.get('agentId_list', []))
    return call_layer0_for_agents(agent_ids=agent_ids, target_date=target_date, repo_root=repo_root, dry_run=dry_run, stage1_staging_only=stage1_staging_only)


# ---------------------------------------------------------------------------
# 计划 / 清理
# ---------------------------------------------------------------------------


def _config_wrapper(repo_root: str | None = None) -> LoadConfig:
    return LoadConfig(repo_root)


def _staging_surface_root(repo_root: str | None = None) -> Path:
    cfg = _config_wrapper(repo_root)
    staging_cfg = cfg.overall_config['store_dir_structure']['staging']
    return Path(cfg.store_root) / staging_cfg['root'] / staging_cfg['staging_surface']


def _plan_path(repo_root: str | None = None) -> Path:
    return _staging_surface_root(repo_root) / 'plan.json'


def _agent_staging_root(agent_id: str, repo_root: str | None = None) -> Path:
    cfg = _config_wrapper(repo_root)
    paths = build_store_paths(agent_id, cfg.overall_config)
    return Path(paths['staging_surface_agent_root'])


def _remove_path(path: Path):
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _clean_agent_staging(agent_id: str, *, repo_root: str | None = None):
    """清空单个 agent 的 staging_surface 目录内容。"""
    root = _agent_staging_root(agent_id, repo_root=repo_root)
    root.parent.mkdir(parents=True, exist_ok=True)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)


def _parse_layer0_stdout_payload(stdout_text: str) -> dict[str, Any] | None:
    if not stdout_text or not stdout_text.strip():
        return None
    try:
        payload = json.loads(stdout_text)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _nocontent_marker_path(l1_path: str | Path) -> Path:
    file_path = Path(l1_path)
    name = file_path.name
    if name.endswith('_l1.json'):
        return file_path.with_name(name[:-8] + '.nocontent')
    return file_path.with_suffix(file_path.suffix + '.nocontent')


def _write_nocontent_marker(l1_path: str | Path, *, target_date: str):
    marker_path = _nocontent_marker_path(l1_path)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(f'nocontent on {target_date}\n', encoding='utf-8')


def _parse_selected_agents(agent: str | None, all_agents: list[str]) -> tuple[list[str], str]:
    if agent is None or not str(agent).strip():
        return list(all_agents), 'all'

    raw_items = [item.strip() for item in str(agent).split(',')]
    parsed: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not item or item in seen:
            continue
        seen.add(item)
        parsed.append(item)

    invalid = [item for item in parsed if item not in all_agents]
    if invalid:
        raise ValueError(f'未知 agent: {", ".join(invalid)}')
    if not parsed:
        raise ValueError('--agent 解析后为空')
    if len(parsed) == 1:
        return parsed, 'single'
    return parsed, 'multiple'


def _stage1_plan_shell(*, target_date: str, repo_root: str | None, selected_agents: list[str], all_agents: list[str], agent_mode: str) -> dict:
    layer1_cfg = load_layer1_config(repo_root)
    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    skipped_agents = [agent_id for agent_id in all_agents if agent_id not in selected_agents]
    return {
        'plan': {
            '_description': '单次 Layer1 运行的总清单。每个阶段都会读取并追加这里的内容。',
            'run_meta': {
                '_description': '本次运行的元数据。',
                'date': target_date,
                'agent_mode': agent_mode,
                'created_at': now_iso,
                'updated_at': now_iso,
                'status': 'running',
            },
            'stage1': {
                '_description': 'Stage1：初始化本轮运行并写入计划骨架。',
                'status': 'running',
                'summary': 'Stage1 已开始，正在执行 Layer0 调用。',
                'selected_agents': selected_agents,
                'agents_with_conversation': [],
                'agents_skipped': skipped_agents,
                'executions': [],
            },
            'stage2': {
                '_description': 'Chunk 规划阶段。',
                'status': 'pending',
                'chunk_budget_model': {
                    '_description': '用于推导 chunk 数的预算参数。',
                    'ct_all_max': layer1_cfg.ct_all_max,
                    'ct_all_free': layer1_cfg.ct_all_free,
                    'ct_map_prompt': layer1_cfg.ct_map_prompt,
                    'ct_reduce_prompt': layer1_cfg.ct_reduce_prompt,
                    'ct_system_prompt': layer1_cfg.ct_system_prompt,
                    'ct_reduce_output_max': layer1_cfg.ct_reduce_output_max,
                    'nprl_llm_max': layer1_cfg.nprl_llm_max,
                    'chars_per_token_estimate': layer1_cfg.chars_per_token_estimate,
                },
                'agents': [],
            },
            'stage3': {
                '_description': 'L2 chunk 处理阶段。',
                'status': 'pending',
                'map_batches': [],
            },
            'stage4': {
                '_description': 'Reduce 阶段。',
                'status': 'pending',
                'reduce_batches': [],
            },
            'stage5': {
                '_description': '把 reduce 结果写回永久存储区的 L1。',
                'status': 'pending',
                'outputs': {},
            },
            'stage6': {
                '_description': '更新 L0 索引产物。',
                'status': 'pending',
                'tasks': [],
            },
            'stage7': {
                '_description': '更新 embedding / 向量索引产物。',
                'status': 'pending',
                'tasks': [],
            },
            'stage8': {
                '_description': '记录 landmark 原始统计。',
                'status': 'pending',
                'tasks': [],
            },
            'stage9': {
                '_description': '清理阶段：清理 staging 工作区中的临时文件。',
                'status': 'pending',
            },
        }
    }


def _write_stage1_plan(plan_data: dict, *, repo_root: str | None = None):
    plan_path = _plan_path(repo_root)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(plan_path, plan_data)


def _read_stage1_plan(*, repo_root: str | None = None) -> dict:
    plan_path = _plan_path(repo_root)
    if not plan_path.exists():
        return {}
    return load_json_file(plan_path)


def _update_stage1_plan(*, repo_root: str | None = None, updater=None):
    plan = _read_stage1_plan(repo_root=repo_root)
    if not plan or updater is None:
        return
    updater(plan)
    plan.setdefault('plan', {}).setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    _write_stage1_plan(plan, repo_root=repo_root)


def _summarize_stage1_results(results: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    with_conversation: list[str] = []
    skipped: list[str] = []
    for item in results:
        if item.get('has_conversation'):
            with_conversation.append(item['agent_id'])
        else:
            skipped.append(item['agent_id'])
    return with_conversation, skipped


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------


def run_stage1(*, target_date: str, repo_root: str | None = None, agent: str | None = None, dry_run: bool = False, stage1_staging_only: bool = False, show_plan: bool = False) -> dict:
    cfg = load_layer1_config(repo_root)
    all_cfg = _config_wrapper(repo_root).overall_config
    all_agents = list(all_cfg.get('agentId_list', []))
    selected_agents, agent_mode = _parse_selected_agents(agent, all_agents)

    if dry_run or show_plan:
        commands = [build_stage1_call_layer0_command(agent_id=a, target_date=target_date, repo_root=repo_root, stage1_staging_only=stage1_staging_only) for a in selected_agents]
        plan_preview = _stage1_plan_shell(target_date=target_date, repo_root=repo_root, selected_agents=selected_agents, all_agents=all_agents, agent_mode=agent_mode)
        return {
            'success': True,
            'stage': 'ENTRY_LAYER1',
            'date': target_date,
            'max_parallel_workers': cfg.nprl_llm_max,
            'dry_run': True,
            'agent_mode': agent_mode,
            'agent': agent,
            'all': agent_mode == 'all',
            'commands': commands,
            'plan_path': str(_plan_path(repo_root)),
            'plan_preview': plan_preview,
            'note': '当前为预览模式，未执行 Layer0，也未写入 staging 变更。',
        }

    maintenance_result = None
    try:
        maintenance_result = call_optional_connector(
            _CONNECTOR,
            'harness_clean',
            context={
                'repo_root': repo_root,
                'inputs': {
                    'target_date': target_date,
                    'agent': agent,
                    'dry_run': dry_run,
                    'stage1_staging_only': stage1_staging_only,
                    'show_plan': show_plan,
                },
            },
        )
    except Exception as exc:  # noqa: BLE001
        plan_data = _stage1_plan_shell(target_date=target_date, repo_root=repo_root, selected_agents=selected_agents, all_agents=all_agents, agent_mode=agent_mode)
        plan_data.setdefault('plan', {}).setdefault('stage1', {})['status'] = 'failed'
        plan_data.setdefault('plan', {}).setdefault('stage1', {})['summary'] = 'harness_maintenance 失败，Stage1 提前结束。'
        plan_data.setdefault('plan', {}).setdefault('run_meta', {})['status'] = 'failed'
        _write_stage1_plan(plan_data, repo_root=repo_root)
        return {
            'success': False,
            'stage': 'ENTRY_LAYER1',
            'date': target_date,
            'max_parallel_workers': cfg.nprl_llm_max,
            'dry_run': False,
            'agent_mode': agent_mode,
            'agent': agent,
            'all': agent_mode == 'all',
            'plan_path': str(_plan_path(repo_root)),
            'note': f'harness_maintenance 失败：{exc}',
        }

    # 1) 清理上一轮 plan 和本轮选中 agent 的 staging 残留
    plan_path = _plan_path(repo_root)
    _remove_path(plan_path)
    cleaned_agent_roots: list[str] = []
    for agent_id in selected_agents:
        root = _agent_staging_root(agent_id, repo_root=repo_root)
        _clean_agent_staging(agent_id, repo_root=repo_root)
        cleaned_agent_roots.append(str(root))

    # 2) 写入初始 plan
    plan_data = _stage1_plan_shell(target_date=target_date, repo_root=repo_root, selected_agents=selected_agents, all_agents=all_agents, agent_mode=agent_mode)
    _write_stage1_plan(plan_data, repo_root=repo_root)

    # 3) 逐个调用 Layer0，并根据结果更新 plan
    layer0_results: list[dict[str, Any]] = []
    for agent_id in selected_agents:
        cmd = build_stage1_call_layer0_command(agent_id=agent_id, target_date=target_date, repo_root=repo_root, stage1_staging_only=stage1_staging_only)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        stdout_text = proc.stdout or ''
        layer0_payload = _parse_layer0_stdout_payload(stdout_text)
        no_conversation_today = (
            proc.returncode != 0
            and isinstance(layer0_payload, dict)
            and layer0_payload.get('success') is False
            and str(layer0_payload.get('error', '') or '').strip() == 'no conversations today'
        )
        artifact_paths = build_layer0_artifact_paths(agent_id, target_date, all_cfg)
        conversation_count = 0
        user_turn_count = 0
        has_conversation = False
        nocontent_early_skip = False
        extraction_ready_path = Path(artifact_paths['staging_ready_path'])
        if extraction_ready_path.exists():
            try:
                extraction_ready = load_json_file(extraction_ready_path)
                excerpts = extraction_ready.get('conversation_excerpts', []) if isinstance(extraction_ready, dict) else []
                if isinstance(excerpts, list):
                    conversation_count = len(excerpts)
                    has_conversation = conversation_count > 0
                    user_turn_count = sum(
                        1 for excerpt in excerpts
                        if isinstance(excerpt, dict) and str(excerpt.get('role', '')).strip().lower() == 'user'
                    )
            except Exception:
                has_conversation = False
        if no_conversation_today:
            has_conversation = False
            conversation_count = 0
            user_turn_count = 0
        elif has_conversation and user_turn_count <= 1:
            has_conversation = False
            nocontent_early_skip = True
            l1_path = Path(artifact_paths['l1_path'])
            if l1_path.exists():
                l1_path.unlink()
            _write_nocontent_marker(artifact_paths['l1_path'], target_date=target_date)
        agent_result = {
            'agent_id': agent_id,
            'command': cmd,
            'returncode': proc.returncode,
            'has_conversation': has_conversation,
            'conversation_excerpt_count': conversation_count,
            'user_turn_count': user_turn_count,
            'skip_reason': '无对话' if no_conversation_today else ('nocontent:user_turns<=1' if nocontent_early_skip else None),
            'l1_path': artifact_paths['l1_path'],
            'l2_path': artifact_paths['l2_path'],
        }
        layer0_results.append(agent_result)

        def _apply_update(plan: dict):
            p = plan.setdefault('plan', {})
            stage1 = p.setdefault('stage1', {})
            executions = stage1.setdefault('executions', [])
            executions.append({
                'agent_id': agent_id,
                'processed_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'returncode': proc.returncode,
                'has_conversation': has_conversation,
                'user_turn_count': user_turn_count,
                'skip_reason': '无对话' if no_conversation_today else ('nocontent:user_turns<=1' if nocontent_early_skip else None),
            })
            if has_conversation and agent_id not in stage1.get('agents_with_conversation', []):
                stage1['agents_with_conversation'] = stage1.get('agents_with_conversation', []) + [agent_id]
            elif (not has_conversation) and agent_id not in stage1.get('agents_skipped', []):
                stage1['agents_skipped'] = stage1.get('agents_skipped', []) + [agent_id]

            if proc.returncode == 0 or no_conversation_today:
                stage1['summary'] = f"Stage1 已处理 {len(layer0_results)} 个 agent。"
                if len(layer0_results) == len(selected_agents):
                    stage1['status'] = 'done'
                    p.setdefault('run_meta', {})['status'] = 'done'
            else:
                stage1['status'] = 'failed'
                p.setdefault('run_meta', {})['status'] = 'failed'

        _update_stage1_plan(repo_root=repo_root, updater=_apply_update)

        if proc.returncode != 0 and not no_conversation_today:
            output_failure(
                f'调用 Layer0 失败: {agent_id}; '
                f'returncode={proc.returncode}; '
                f'stdout_len={len(stdout_text or "")}; '
                f'stderr_len={len(proc.stderr or "")}. '
                '已抑制原始 stdout/stderr 内容，避免泄漏对话正文。'
            )

    with_conversation, skipped = _summarize_stage1_results(layer0_results)

    def _finalize_plan(plan: dict):
        p = plan.setdefault('plan', {})
        stage1 = p.setdefault('stage1', {})
        stage1['agents_with_conversation'] = with_conversation
        stage1['agents_skipped'] = skipped + [a for a in stage1.get('agents_skipped', []) if a not in skipped]
        stage1['status'] = 'done'
        stage1['summary'] = f'已处理 {len(layer0_results)} 个 agent；有对话 {len(with_conversation)} 个，跳过 {len(skipped)} 个。'
        p.setdefault('run_meta', {})['status'] = 'done'
        p.setdefault('run_meta', {})['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    _update_stage1_plan(repo_root=repo_root, updater=_finalize_plan)

    return {
        'success': True,
        'stage': 'ENTRY_LAYER1',
        'date': target_date,
        'max_parallel_workers': cfg.nprl_llm_max,
        'dry_run': False,
        'agent_mode': agent_mode,
        'agent': agent,
        'all': agent_mode == 'all',
        'plan_path': str(_plan_path(repo_root)),
        'cleaned_agent_roots': cleaned_agent_roots,
        'agent_results': layer0_results,
        'commands': [item['command'] for item in layer0_results],
        'maintenance_result': maintenance_result,
        'note': 'Stage1 已执行：完成了 harness maintenance、旧 plan / staging 残留清理、初始 plan 写入和 Layer0 调用。',
    }
