English | [中文](C3_adapter-openclaw.md)

# Adapter: OpenClaw

This document explains the responsibilities, capability domains, and current maturity of `Adapters/openclaw/`. For the fixed connector interface, see `docs/C2_connector-contract_en.md`.

## Positioning

`Core/` is the memory engine and does not directly understand OpenClaw sessions, plugins, worker runtime, or registries. The OpenClaw adapter organizes these platform capabilities into fixed interfaces callable by core.

```text
Core/
  ↕ connector contract
Adapters/openclaw/
  ↕
OpenClaw runtime / plugin / session environment
```

In one sentence: the OpenClaw adapter wraps OpenClaw session input, model calls, runtime hooks, plugin packaging, and session-watch lifecycle logic into stable capabilities exposed through `CONNECTOR.py`.

## External Entrypoint

```text
Adapters/openclaw/CONNECTOR.py
```

Currently exposes:

| Interface | Implementation Direction |
| --- | --- |
| `ensure_config` | OpenClaw adapter config bootstrap |
| `memory_worker.call_llm` | Call OpenClaw worker runtime |
| `memory_worker.clean_runtime` | Clean MW runtime / sessions |
| `memory_worker.prerequisites` / `install` / `uninstall` | MW-side install lifecycle |
| `production_agent.extract` | OpenClaw sessions -> Layer0 input |
| `production_agent.preserve` / `decay` | Sessions_Watch preserve / decay |
| `production_agent.prerequisites` / `install` / `uninstall` | PA-side install lifecycle |

## Capability Domains

| Directory / File | Responsibility |
| --- | --- |
| `Extract/` | Reads OpenClaw sessions, known-direct-sessions registry, `.jsonl` files, and normalizes them into Layer0 input |
| `openclaw_call_LLM.py` | Converts Layer1 / Layer3 prompts into OpenClaw MW session execution |
| `openclaw_runtime_maintenance.py` | Implements `memory_worker.clean_runtime` by cleaning task-like runtime state |
| `Read/` | Wraps `Core/Layer4_Read/` as OpenClaw plugin tools and plugin-shipped skills |
| `Sessions_Watch/` | Maintains OpenClaw active session registry and implements preserve / decay hooks |
| `Installation/` | OpenClaw-specific prerequisites / install / uninstall |

## Supported Core Mainlines

Layer0:

```text
OpenClaw sessions / registry -> Adapters/openclaw/Extract -> Core/Layer0_Extract
```

Layer1 / Layer3 LLM:

```text
Core Layer1 / Layer3 -> memory_worker.call_llm -> openclaw_call_LLM.py -> OpenClaw gateway agent run
```

`openclaw_call_LLM.py` starts an independent MW session through OpenClaw gateway `agent` / `agent.wait`:

```text
agent:{memory_worker_agentId}:subagent:{uuid}
```

This path does not depend on OpenClaw dist chunk private `spawnSubagentDirect`, nor on `.jsonl.lock`. MW sessions only execute prompts and write files; they do not report completion messages back to PA / main sessions.

Layer2 / Layer3 hook:

```text
Core Layer2 / Layer3 -> production_agent.preserve / decay -> Sessions_Watch
```

Layer4 read:

```text
Core/Layer4_Read -> Adapters/openclaw/Read -> OpenClaw plugin tools + skill
```

## Read and Layer4

Read logic itself belongs to `Core/Layer4_Read/`. OpenClaw `Read/` only provides the platform wrapper:

- plugin `index.ts`
- plugin manifest
- recall tools
- plugin-shipped skill

Current OpenClaw integration is **tool plugin + skill guidance**, not an OpenClaw memory backend. Do not point `plugins.slots.memory` to MemoquasarEterna.

## Sessions_Watch and Preserve / Decay

`Sessions_Watch/` handles OpenClaw platform-side state lifecycle:

| Direction | Core Side | OpenClaw Side |
| --- | --- | --- |
| Preserve | Layer2 archive memory surface | Preserve session registry / session files |
| Decay | Layer3 trim / shallow / deep | Carefully clean session-watch data |

Production-agent raw session-file decay is disabled by default. Enable `sessions_registry_maintenance.session_files_decay` in `OpenclawConfig.json` only after understanding the risk.

OpenClaw 2026.4.x writes trajectory sidecars next to main session transcripts:

```text
{sessionUUID}.trajectory.jsonl
{sessionUUID}.trajectory-path.json
```

They are runtime/debug flight recorders, not Layer0 input, and are not archived by preserve by default. If `session_files_decay` is enabled, the adapter only tries to delete the two same-basename trajectory sidecars when deleting a confirmed decayed `{sessionUUID}.jsonl`; missing files are skipped, with no glob or UUID inference.

## Config System

| Config | Responsibility |
| --- | --- |
| `OverallConfig.json` | Harness routing, agent list, code/store/archive, timezone/window, product name |
| `Adapters/openclaw/OpenclawConfig.json` | OpenClaw path templates, sessions, registry, maintenance, archive, preserve / decay config |

Templates are tracked by git; local runtime uses actual config files. Top-level install auto-generates missing configs and stops early on `schema_version` mismatch.

## Current Maturity

OpenClaw is the current production/default adapter. Stable pieces include:

- `CONNECTOR.py`
- Layer0 `Extract/`
- MW `call_llm`
- MW runtime cleanup
- Layer4 read plugin templates and install scripts
- `Sessions_Watch/` preserve / decay business domain
- OpenClaw-specific install / uninstall

Still requires caution:

- More aggressive Sessions_Watch decay features are disabled by default.
- The main OpenClaw config requires manual merge of `Installation/example-openclaw.json`.
- MW must be a dedicated internal agent and must not be mixed with PA.

## Recommended Reading Order

1. `docs/A1_installation-guide_en.md`
2. `docs/B1_maintenance-guide_en.md`
3. `docs/C1_architecture_en.md`
4. `docs/C2_connector-contract_en.md`
5. `Adapters/openclaw/README.md`
6. `Adapters/openclaw/CONNECTOR.py`
7. Dive into `Extract/`, `Read/`, or `Sessions_Watch/` as needed.

## One-sentence Summary

The OpenClaw adapter is the most complete production harness: it handles session input, LLM calls, runtime cleanup, Layer4 plugin wrapping, and OpenClaw session-watch preserve / decay lifecycle.
