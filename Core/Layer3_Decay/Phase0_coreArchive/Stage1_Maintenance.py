#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from Core.harness_connector import call_optional_connector, load_harness_connector


def run_stage1(*, repo_root: str | Path | None = None) -> dict[str, Any]:
    connector = load_harness_connector(repo_root=repo_root)
    result = call_optional_connector(
        connector,
        'memory_worker',
        'clean_runtime',
        context={
            'repo_root': repo_root,
            'inputs': {},
        },
    )
    hook_results = [] if result is None else [result]
    failed_results = [item for item in hook_results if isinstance(item, dict) and item.get('success') is False]
    return {
        'success': not failed_results,
        'failed_stage': None if not failed_results else 'Stage1',
        'results': hook_results,
        'note': 'Phase0 Stage1 执行完成。' if not failed_results else 'Phase0 Stage1 执行结束，但存在失败 hook。',
    }


__all__ = ['run_stage1']
