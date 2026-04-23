#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Adapters.openclaw.openclaw_shared_funcs import LoadConfig, output_failure, output_success

TEMPLATE_PATH = Path(__file__).resolve().parent / 'example-openclaw.json'
DEFAULT_OUTPUT_PATH = ROOT / 'Installation' / 'example-openclaw.json'


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[5]


def _cfg(repo_root: str | Path | None = None) -> LoadConfig:
    return LoadConfig(Path(repo_root) if repo_root is not None else _repo_root_from_here())


def _plugin_id_from_product_name(product_name: str) -> str:
    plugin_id = ''.join(ch.lower() if ch.isalnum() else '_' for ch in product_name).strip('_')
    return plugin_id or 'memoquasar_read'


def _memory_worker_workspace_path(cfg: LoadConfig) -> str:
    worker_agent_id = str(cfg.overall_config.get('memory_worker_agentId', '') or '').strip()
    if not worker_agent_id:
        raise KeyError('OverallConfig.json 缺少 memory_worker_agentId')
    template = str(cfg.openclaw_config.get('memory_worker_agent_workspace_path', '') or '').strip()
    if not template:
        raise KeyError('OpenclawConfig.json 缺少 memory_worker_agent_workspace_path')
    return str(Path(template.format(memory_worker_agentId=worker_agent_id)).expanduser())


def _context(cfg: LoadConfig) -> dict[str, Any]:
    product_name = str(cfg.overall_config.get('product_name', '') or '').strip()
    if not product_name:
        raise KeyError('OverallConfig.json 缺少 product_name')
    memory_worker_agent_id = str(cfg.overall_config.get('memory_worker_agentId', '') or '').strip()
    if not memory_worker_agent_id:
        raise KeyError('OverallConfig.json 缺少 memory_worker_agentId')
    agent_id_list = cfg.overall_config.get('agentId_list', [])
    if not isinstance(agent_id_list, list) or not all(isinstance(x, str) and x.strip() for x in agent_id_list):
        raise ValueError('OverallConfig.json.agentId_list 非法')
    return {
        'product_name': product_name,
        'read_plugin_id': _plugin_id_from_product_name(product_name),
        'memory_worker_agentId': memory_worker_agent_id,
        'memory_worker_workspace_path': _memory_worker_workspace_path(cfg),
        'agentId_list': [str(x).strip() for x in agent_id_list],
    }


def _replace_text(text: str, ctx: dict[str, Any], *, agent_id: str | None = None) -> str:
    value = text.replace('{{memory_worker_agentId}}', ctx['memory_worker_agentId'])
    value = value.replace('{{memory_worker_workspace_path}}', ctx['memory_worker_workspace_path'])
    value = value.replace('{{read_plugin_id}}', ctx['read_plugin_id'])
    if agent_id is not None:
        value = value.replace('{{agentId}}', agent_id)
    return value


def _render_node(node: Any, ctx: dict[str, Any], *, agent_id: str | None = None) -> Any:
    if isinstance(node, dict):
        rendered: dict[str, Any] = {}
        for key, value in node.items():
            rendered_key = _replace_text(key, ctx, agent_id=agent_id) if isinstance(key, str) else key
            rendered[rendered_key] = _render_node(value, ctx, agent_id=agent_id)
        return rendered
    if isinstance(node, list):
        rendered_list: list[Any] = []
        for item in node:
            if isinstance(item, str) and item.strip() == 'for agentId in {{agentId_list}}: (script expands into per-agent tool patch objects)':
                continue
            rendered_list.append(_render_node(item, ctx, agent_id=agent_id))
        return rendered_list
    if isinstance(node, str):
        return _replace_text(node, ctx, agent_id=agent_id)
    return node


def _expand_agent_examples(template_payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(template_payload))
    agents = payload.get('agents', {}) if isinstance(payload, dict) else {}
    entries = agents.get('list', []) if isinstance(agents, dict) else []
    if not isinstance(entries, list):
        return _render_node(payload, ctx)

    memory_worker_template = None
    per_agent_template = None
    for item in entries:
        if isinstance(item, dict) and item.get('id') == '{{memory_worker_agentId}}':
            memory_worker_template = item
        elif isinstance(item, dict) and item.get('id') == '{{agentId}}':
            per_agent_template = item

    rendered_entries: list[Any] = []
    if memory_worker_template is not None:
        rendered_entries.append(_render_node(memory_worker_template, ctx))

    for agent_id in ctx['agentId_list']:
        if per_agent_template is not None:
            rendered_entries.append(_render_node(per_agent_template, ctx, agent_id=agent_id))

    agents['list'] = rendered_entries
    payload['agents'] = agents
    rendered = _render_node(payload, ctx)
    return rendered


def render_example_openclaw_json(*, repo_root: str | Path | None = None, output_path: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    cfg = _cfg(repo_root)
    ctx = _context(cfg)
    template_payload = json.loads(TEMPLATE_PATH.read_text(encoding='utf-8'))
    rendered = _expand_agent_examples(template_payload, ctx)

    target = Path(output_path) if output_path is not None else DEFAULT_OUTPUT_PATH
    target = target.expanduser()
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(rendered, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    return {
        'success': True,
        'dry_run': dry_run,
        'template_path': str(TEMPLATE_PATH),
        'output_path': str(target),
        'read_plugin_id': ctx['read_plugin_id'],
        'memory_worker_agentId': ctx['memory_worker_agentId'],
        'memory_worker_workspace_path': ctx['memory_worker_workspace_path'],
        'agent_count': len(ctx['agentId_list']),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Render OpenClaw config merge example for MemoquasarEterna')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--output-path', default=None, help='输出路径（默认写到 repo/Installation/example-openclaw.json）')
    parser.add_argument('--dry-run', action='store_true', help='只输出计划，不写文件')
    args = parser.parse_args()

    try:
        result = render_example_openclaw_json(repo_root=args.repo_root, output_path=args.output_path, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        output_failure(str(exc))
    output_success(result)


if __name__ == '__main__':
    main()
