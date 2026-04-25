#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Adapters.openclaw.openclaw_shared_funcs import LoadConfig, output_failure, output_success
from Core.shared_funcs import get_production_agents

TEMPLATE_PATH = Path(__file__).resolve().parent / 'example-openclaw.json'
DEFAULT_OUTPUT_PATH = ROOT / 'Installation' / 'example-openclaw.json'

Scope = Literal['memory_worker', 'production_agent', 'all']
Action = Literal['upsert', 'remove']


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


def _context(cfg: LoadConfig, *, agent_ids: list[str] | None = None) -> dict[str, Any]:
    product_name = str(cfg.overall_config.get('product_name', '') or '').strip()
    if not product_name:
        raise KeyError('OverallConfig.json 缺少 product_name')
    memory_worker_agent_id = str(cfg.overall_config.get('memory_worker_agentId', '') or '').strip()
    if not memory_worker_agent_id:
        raise KeyError('OverallConfig.json 缺少 memory_worker_agentId')
    agent_id_list = [item['agentId'] for item in get_production_agents(cfg.overall_config) if item['harness'] == 'openclaw'] if agent_ids is None else [str(x).strip() for x in agent_ids if str(x).strip()]
    if not agent_id_list:
        raise ValueError('production agent 列表为空')
    return {
        'product_name': product_name,
        'read_plugin_id': _plugin_id_from_product_name(product_name),
        'memory_worker_agentId': memory_worker_agent_id,
        'memory_worker_workspace_path': _memory_worker_workspace_path(cfg),
        'production_agent_ids': [str(x).strip() for x in agent_id_list],
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
            if isinstance(item, str) and item.strip() == 'for agentId in {{production_agent_ids}}: (script expands into per-agent tool patch objects)':
                continue
            rendered_list.append(_render_node(item, ctx, agent_id=agent_id))
        return rendered_list
    if isinstance(node, str):
        return _replace_text(node, ctx, agent_id=agent_id)
    return node


def _template_agent_entries(template_payload: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    agents = template_payload.get('agents', {}) if isinstance(template_payload, dict) else {}
    entries = agents.get('list', []) if isinstance(agents, dict) else []
    memory_worker_template = None
    production_agent_template = None
    for item in entries:
        if isinstance(item, dict) and item.get('id') == '{{memory_worker_agentId}}':
            memory_worker_template = item
        elif isinstance(item, dict) and item.get('id') == '{{agentId}}':
            production_agent_template = item
    return memory_worker_template, production_agent_template


def _blank_payload_from_template(template_payload: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in template_payload.items():
        if key == 'agents':
            payload[key] = {'list': []}
        elif key == 'plugins':
            payload[key] = {'entries': {}}
        else:
            payload[key] = value
    payload.setdefault('agents', {'list': []})
    payload.setdefault('plugins', {'entries': {}})
    return payload


def _load_existing_or_blank(target: Path, template_payload: dict[str, Any]) -> dict[str, Any]:
    if not target.exists():
        return _blank_payload_from_template(template_payload)
    data = json.loads(target.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'OpenClaw example json 格式错误: {target}')
    agents = data.setdefault('agents', {})
    if not isinstance(agents, dict):
        data['agents'] = {'list': []}
    elif not isinstance(agents.get('list'), list):
        agents['list'] = []
    plugins = data.setdefault('plugins', {})
    if not isinstance(plugins, dict):
        data['plugins'] = {'entries': {}}
    elif not isinstance(plugins.get('entries'), dict):
        plugins['entries'] = {}
    return data


def _upsert_agent_entries(payload: dict[str, Any], entries: list[dict[str, Any]]) -> list[str]:
    agents = payload.setdefault('agents', {})
    agent_list = agents.setdefault('list', [])
    if not isinstance(agent_list, list):
        agents['list'] = []
        agent_list = agents['list']
    changed_ids: list[str] = []
    index_by_id = {
        str(item.get('id')): idx
        for idx, item in enumerate(agent_list)
        if isinstance(item, dict) and str(item.get('id', '') or '').strip()
    }
    for entry in entries:
        entry_id = str(entry.get('id', '') or '').strip()
        if not entry_id:
            continue
        if entry_id in index_by_id:
            agent_list[index_by_id[entry_id]] = entry
        else:
            index_by_id[entry_id] = len(agent_list)
            agent_list.append(entry)
        changed_ids.append(entry_id)
    return changed_ids


def _remove_agent_entries(payload: dict[str, Any], entry_ids: set[str]) -> list[str]:
    agents = payload.setdefault('agents', {})
    agent_list = agents.setdefault('list', [])
    if not isinstance(agent_list, list):
        agents['list'] = []
        return []
    removed: list[str] = []
    kept: list[Any] = []
    for item in agent_list:
        item_id = str(item.get('id', '') or '').strip() if isinstance(item, dict) else ''
        if item_id and item_id in entry_ids:
            removed.append(item_id)
            continue
        kept.append(item)
    agents['list'] = kept
    return removed


def _upsert_plugin_entry(payload: dict[str, Any], *, plugin_id: str) -> list[str]:
    plugins = payload.setdefault('plugins', {})
    entries = plugins.setdefault('entries', {})
    if not isinstance(entries, dict):
        plugins['entries'] = {}
        entries = plugins['entries']
    entries[plugin_id] = {'enabled': True}
    return [plugin_id]


def _remove_plugin_entry(payload: dict[str, Any], *, plugin_id: str) -> list[str]:
    plugins = payload.setdefault('plugins', {})
    entries = plugins.setdefault('entries', {})
    if not isinstance(entries, dict):
        plugins['entries'] = {}
        return []
    if plugin_id in entries:
        del entries[plugin_id]
        return [plugin_id]
    return []


def _render_memory_worker_entry(template_payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    memory_worker_template, _ = _template_agent_entries(template_payload)
    if memory_worker_template is None:
        raise KeyError('example-openclaw.json 模板缺少 memory worker entry')
    return _render_node(memory_worker_template, ctx)


def _render_production_agent_entries(template_payload: dict[str, Any], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    _, production_agent_template = _template_agent_entries(template_payload)
    if production_agent_template is None:
        raise KeyError('example-openclaw.json 模板缺少 production agent entry')
    return [_render_node(production_agent_template, ctx, agent_id=agent_id) for agent_id in ctx['production_agent_ids']]


def update_example_openclaw_json(*, repo_root: str | Path | None = None, output_path: str | Path | None = None, scope: Scope, action: Action, dry_run: bool = False, agent_ids: list[str] | None = None) -> dict[str, Any]:
    cfg = _cfg(repo_root)
    ctx = _context(cfg, agent_ids=agent_ids)
    template_payload = json.loads(TEMPLATE_PATH.read_text(encoding='utf-8'))
    target = Path(output_path) if output_path is not None else DEFAULT_OUTPUT_PATH
    target = target.expanduser()
    if action == 'remove' and not target.exists():
        return {
            'success': True,
            'dry_run': dry_run,
            'action': action,
            'scope': scope,
            'template_path': str(TEMPLATE_PATH),
            'output_path': str(target),
            'read_plugin_id': ctx['read_plugin_id'],
            'memory_worker_agentId': ctx['memory_worker_agentId'],
            'memory_worker_workspace_path': ctx['memory_worker_workspace_path'],
            'agent_count': len(ctx['production_agent_ids']),
            'agent_ids_changed': [],
            'plugin_ids_changed': [],
            'status': 'absent',
        }
    payload = _load_existing_or_blank(target, template_payload)

    agent_ids_changed: list[str] = []
    plugin_ids_changed: list[str] = []

    if scope in {'memory_worker', 'all'}:
        if action == 'upsert':
            agent_ids_changed.extend(_upsert_agent_entries(payload, [_render_memory_worker_entry(template_payload, ctx)]))
        else:
            agent_ids_changed.extend(_remove_agent_entries(payload, {ctx['memory_worker_agentId']}))

    if scope in {'production_agent', 'all'}:
        production_ids = set(ctx['production_agent_ids'])
        if action == 'upsert':
            agent_ids_changed.extend(_upsert_agent_entries(payload, _render_production_agent_entries(template_payload, ctx)))
            plugin_ids_changed.extend(_upsert_plugin_entry(payload, plugin_id=ctx['read_plugin_id']))
        else:
            agent_ids_changed.extend(_remove_agent_entries(payload, production_ids))
            plugin_ids_changed.extend(_remove_plugin_entry(payload, plugin_id=ctx['read_plugin_id']))

    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    return {
        'success': True,
        'dry_run': dry_run,
        'action': action,
        'scope': scope,
        'template_path': str(TEMPLATE_PATH),
        'output_path': str(target),
        'read_plugin_id': ctx['read_plugin_id'],
        'memory_worker_agentId': ctx['memory_worker_agentId'],
        'memory_worker_workspace_path': ctx['memory_worker_workspace_path'],
        'agent_count': len(ctx['production_agent_ids']),
        'agent_ids_changed': agent_ids_changed,
        'plugin_ids_changed': plugin_ids_changed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Update OpenClaw config merge example for MemoquasarEterna')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--output-path', default=None, help='输出路径（默认写到 repo/Installation/example-openclaw.json）')
    parser.add_argument('--scope', required=True, choices=('memory_worker', 'production_agent', 'all'))
    parser.add_argument('--action', required=True, choices=('upsert', 'remove'))
    parser.add_argument('--dry-run', action='store_true', help='只输出计划，不写文件')
    args = parser.parse_args()

    try:
        result = update_example_openclaw_json(
            repo_root=args.repo_root,
            output_path=args.output_path,
            scope=args.scope,
            action=args.action,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001
        output_failure(str(exc))
    output_success(result)


if __name__ == '__main__':
    main()
