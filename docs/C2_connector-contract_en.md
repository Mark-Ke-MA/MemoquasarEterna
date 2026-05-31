English | [中文](C2_connector-contract.md)

# Connector Contract

This document defines the fixed capability boundary between `Core/` and `Adapters/`. For concrete adapter implementations, see `docs/C3_adapter-openclaw_en.md` and `docs/C4_adapter-hermes_en.md`.

## Goals

The connector contract answers three questions:

- How core locates the connector for the current harness.
- Which keys `Adapters/{harness}/CONNECTOR.py` must expose.
- How required interfaces, optional hooks, call parameters, and return values are agreed upon.

Core principle: `Core/` depends only on capability names; adapters decide their own internal directories and implementation details.

## File Location and Loading

```text
Adapters/{harness}/CONNECTOR.py
```

Core uses `Core/harness_connector.py` to:

- Read `memory_worker_harness` and `production_agents[*].harness`.
- Load the corresponding `CONNECTOR.py`.
- Build PA agent-wise / harness-wise routing.
- Get required / optional callables and invoke them.

`CONNECTOR.py` should expose a dict. Core tries, in order:

1. `{HARNESS_NAME_UPPER}_CONNECTOR`
2. `CONNECTOR`

Recommended:

```python
CONNECTOR = {...}
```

## Fixed Structure

```python
CONNECTOR = {
    'ensure_config': ...,
    'memory_worker': {
        'call_llm': ...,
        'clean_runtime': ...,
        'prerequisites': ...,
        'install': ...,
        'uninstall': ...,
    },
    'production_agent': {
        'extract': ...,
        'preserve': ...,
        'decay': ...,
        'prerequisites': ...,
        'install': ...,
        'uninstall': ...,
    },
}
```

## Top-level Interface

| Interface | Required | Meaning |
| --- | --- | --- |
| `ensure_config` | yes | Check / generate local adapter config and validate `schema_version` |

`ensure_config` belongs to the harness adapter top level, not MW or PA.

## memory_worker Interfaces

| Interface | Type | Main Consumers | Meaning |
| --- | --- | --- | --- |
| `call_llm` | required | Layer1 Map/Reduce, Layer3 reduce | Send core prompts / tasks to the current harness model-call capability |
| `clean_runtime` | optional hook | Layer1 Stage1, Layer3 Phase0 | Clean MW runtime / worker sessions and other task-like state |
| `prerequisites` | required | `Installation/INSTALL.py` | MW-side pre-install checks |
| `install` | required | `Installation/INSTALL.py` | MW-side install actions |
| `uninstall` | required | `Installation/UNINSTALL.py` | MW-side uninstall actions |

MW is a dedicated internal worker and should not be mixed with PA.

## production_agent Interfaces

| Interface | Type | Main Consumers | Meaning |
| --- | --- | --- | --- |
| `extract` | required | Layer0 | Read raw harness input and normalize it into Layer0 standard input |
| `preserve` | optional hook | Layer2 | Preserve PA-side platform state, such as session registry archives |
| `decay` | optional hook | Layer3 | Decay PA-side platform state, such as session-watch cleanup |
| `prerequisites` | required | `Installation/INSTALL.py` | PA-side pre-install checks, grouped by harness via `agent_ids` |
| `install` | required | `Installation/INSTALL.py` | PA-side install actions, grouped by harness via `agent_ids` |
| `uninstall` | required | `Installation/UNINSTALL.py` | PA-side uninstall actions, grouped by harness via `agent_ids` |

## Call Rules

| Accessor | Behavior |
| --- | --- |
| `get_required_connector_callable(...)` | Missing connector / role / key or non-callable value raises an error |
| `get_optional_connector_callable(...)` | Missing returns `None`; present but non-callable raises an error |
| `call_optional_connector(...)` | Calls the optional callable only when present |

Required interfaces form the mainline; optional hooks are for platform-specific extensions.

## Hook Parameters

Current optional hooks receive:

```python
def some_hook(context: dict) -> Any:
    ...
```

Minimal common structure:

```python
{
  "repo_root": <repo_root>,
  "inputs": {...}
}
```

For PA hooks grouped by harness, core places the current harness's agent list in `context["inputs"]["agent_ids"]`.

## Return Values

Return values are intentionally loose:

- Adapters may return their own structures.
- Core reads only fields needed at the current callsite.
- Stable schemas should be documented by the corresponding Layer or adapter.

Install-like interfaces should preferably return:

```python
{
  "success": True,
  "status": "...",
  "dry_run": False,
  "steps": [...],
  "warnings": [...]
}
```

## Current Implementation Matrix

| Interface | OpenClaw | Hermes |
| --- | --- | --- |
| `ensure_config` | yes | yes |
| `memory_worker.call_llm` | yes | no |
| `memory_worker.clean_runtime` | yes | no |
| `memory_worker.prerequisites` | yes | no |
| `memory_worker.install` | yes | no |
| `memory_worker.uninstall` | yes | no |
| `production_agent.extract` | yes | yes |
| `production_agent.preserve` | yes | no |
| `production_agent.decay` | yes | no |
| `production_agent.prerequisites` | yes | yes |
| `production_agent.install` | yes | yes |
| `production_agent.uninstall` | yes | yes |

Notes:

- OpenClaw is the current production/default adapter and fully integrates MW and PA mainlines.
- Hermes is an experimental PA adapter, only supporting Layer0 extract and Layer4 recall skill install lifecycle.
- Do not set `memory_worker_harness` to `hermes`.

## Layer4 Position

Layer4 read is not a fixed connector key. Read logic lives in `Core/Layer4_Read/`; adapters only wrap it into platform-consumable forms:

| Adapter | Layer4 wrapper |
| --- | --- |
| OpenClaw | Plugin tools + skill guidance |
| Hermes | Profile-local `memoquasar-memory-recall` skill |

## Evolution Principles

- Only cross-harness common capabilities should enter the fixed contract.
- Prefer adding optional hooks before adding required interfaces.
- Adapters may split internally, but `CONNECTOR.py` must remain the single external entrypoint.
- When changing the contract, update this document, the corresponding adapter docs, and `Core/harness_connector.py`.

## One-sentence Summary

The connector contract lets `Core/` depend on stable capability boundaries while `Adapters/` remain free to organize their internal implementation, all converging through `CONNECTOR.py`.
