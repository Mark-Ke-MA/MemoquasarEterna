English | [中文](C4_adapter-hermes.md)

# Hermes Adapter

This document explains the current capability boundary of `Adapters/hermes/`. The Hermes adapter is experimental and is not the default production harness.

## Current Positioning

The Hermes adapter targets only production agents and provides two minimal paths:

| Capability | Status | Notes |
| --- | --- | --- |
| Layer0 extract | yes | Generates MemoquasarEterna L2 from a Hermes profile `state.db` |
| Layer4 read | yes | Installs recall skill into a Hermes profile |
| memory worker | no | Does not provide `call_llm` / runtime cleanup / MW install |
| preserve / decay | no | Does not manage long-term Hermes-side state |

Recommended combination:

```json
{
  "memory_worker_harness": "openclaw",
  "production_agents": [
    {"agentId": "hermes-init", "harness": "hermes"}
  ]
}
```

## agentId and Profile

In the Hermes adapter:

```text
production_agents[*].agentId == Hermes profile name
```

For example, `agentId = "hermes-init"` corresponds to:

```text
~/.hermes/profiles/hermes-init/
```

There is no additional mapping layer, which keeps configuration simpler.

## Config

```text
Adapters/hermes/HermesConfig.json
Adapters/hermes/HermesConfig-template.json
```

Current fields:

```json
{
  "schema_version": "1.0",
  "profiles_root": "~/.hermes/profiles",
  "state_db_name": "state.db"
}
```

`INSTALL.py` uses connector top-level `ensure_config` to generate missing `HermesConfig.json` automatically.

## Layer0 Extract

Default source:

```text
~/.hermes/profiles/{agentId}/state.db
```

Normalization rules:

- Keep only `user` / `assistant`.
- Skip `tool` / `session_meta`.
- Skip empty content.
- Set `message_type` to `text`.
- Sort stably by `messages.timestamp, messages.id`.

The source ref in `sessions_to_process` is written as `sqlite:{state_db_path}` only to satisfy the existing Core Layer0 contract. The adapter does not continue reading session JSON / JSONL.

## Source of Truth and Limitations

Current source of truth is `state.db` only. Reading `state.db`, session JSON, and session JSONL together was considered, but three-source reconciliation would require cross-file matching, conflict resolution, and priority rules whose maintenance cost exceeds the benefit.

Known limitations:

- Compaction may create replay rows in `state.db`; they need filtering.
- Timestamp is closer to Hermes persistence time and may differ from client display time.
- Under gateway stop / no-op `/compress` paths, session files or logs may contain messages that do not appear as corresponding user messages in `state.db`.

Therefore, Hermes is currently suitable for validating Layer0 / Layer4 integration, but should not replace OpenClaw as the default production solution.

## Layer4 Recall Skill

Skill install path:

```text
~/.hermes/profiles/{agentId}/skills/memoquasar-memory-recall/SKILL.md
```

Skill command entrypoints:

```bash
python Adapters/hermes/Read/memoquasar_recall.py vague --agent "{agentId}" --query "..."
python Adapters/hermes/Read/memoquasar_recall.py exact --agent "{agentId}" --date YYYY-MM-DD --window-start HH:MM --window-end HH:MM
```

| Mode | Purpose |
| --- | --- |
| `vague` | Fuzzy recall, recent overview, query-related memory |
| `exact` | Read L2 transcript for a specific date and time window |

Layer4 read is not part of the connector contract. It is still provided by `Core/Layer4_Read/`; the Hermes adapter only wraps it as a Hermes skill.

## Installation Lifecycle

| Interface | Behavior |
| --- | --- |
| `ensure_config` | Ensures `HermesConfig.json` exists |
| `production_agent.prerequisites` | Checks recall entrypoint, skill template, profile directory |
| `production_agent.install` | Renders and writes `memoquasar-memory-recall/SKILL.md` |
| `production_agent.uninstall` | Deletes `memoquasar-memory-recall/` under the profile |

Install and uninstall do not rewrite Hermes `state.db` and do not delete Hermes profiles.

## Unimplemented Interfaces

```text
memory_worker.call_llm
memory_worker.clean_runtime
memory_worker.prerequisites / install / uninstall
production_agent.preserve
production_agent.decay
```

Therefore, do not use:

```json
"memory_worker_harness": "hermes"
```

as production config.

## One-sentence Summary

The Hermes adapter is currently a minimal experimental PA adapter: it can write Hermes `state.db` into MemoquasarEterna and install a Layer4 recall skill into a Hermes profile, but it does not handle MW, preserve, or decay.
