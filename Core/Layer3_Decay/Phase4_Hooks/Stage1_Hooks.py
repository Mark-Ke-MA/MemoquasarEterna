#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from Core.shared_funcs import LoadConfig, parse_selected_production_agent_ids
from Core.harness_connector import call_optional_production_agent_connectors


def run_stage1(*, repo_root: str | Path | None = None, week: str | None = None, source_week: str | None = None, agent: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    overall_config = LoadConfig(repo_root).overall_config
    selected_agents = parse_selected_production_agent_ids(overall_config, agent)
    hook_results = call_optional_production_agent_connectors(
        repo_root=repo_root,
        key='decay',
        context={
            'repo_root': repo_root,
            'inputs': {
                'week': week,
                'source_week': source_week,
                'agent': agent,
                'dry_run': dry_run,
            },
        },
        agent_ids=selected_agents,
    )
    failed_results = [item for item in hook_results if isinstance(item, dict) and item.get('success') is False]
    return {
        'success': not failed_results,
        'failed_stage': None if not failed_results else 'Stage1',
        'results': hook_results,
        'note': 'Phase4 hooks 执行完成。' if not failed_results else 'Phase4 hooks 执行结束，但存在失败 hook。',
    }


__all__ = ['run_stage1']
