English | [中文](A1_installation-guide.md)

# Installation Guide

This document covers the main MemoquasarEterna installation flow. For the full `OverallConfig.json` field reference, see `docs/A2_overall-config-reference_en.md`.

## Top-level Entrypoints

- Install: `Installation/INSTALL.py`
- Uninstall: `Installation/UNINSTALL.py`
- Refresh: `Installation/REFRESH.py`

## Standard Installation Order

1. Clone the GitHub repository locally as `{code_dir}`.
2. Generate and edit local `Config.json` files.
3. Run:

```bash
cd {code_dir}
python Installation/INSTALL.py
```

4. If `memory_worker_harness` or any `production_agents[*].harness` is `openclaw`:
   - Complete the prerequisite prompts.
   - Merge `Installation/example-openclaw.json` into your OpenClaw configuration.
   - Restart the OpenClaw gateway.
   - Open a new session so the newly installed plugin-shipped skill is loaded reliably.
5. If any `production_agents[*].harness` is `hermes`:
   - Confirm that the corresponding `agentId` already exists as a Hermes profile.
   - The installer writes the `memoquasar-memory-recall` skill into that profile.
   - The Hermes adapter currently cannot be used as `memory_worker_harness`.

## Config File Generation

Tracked template files:

- `OverallConfig-template.json`
- `Adapters/openclaw/OpenclawConfig-template.json`
- `Adapters/hermes/HermesConfig-template.json`

Local runtime files:

- `OverallConfig.json`
- `Adapters/openclaw/OpenclawConfig.json`
- `Adapters/hermes/HermesConfig.json`

`Installation/INSTALL.py` copies missing local configs from their templates. After generation, edit only local config files and do not commit machine-private config into git.

If local `Config.json.schema_version` differs from the template `schema_version`, installation fails during the earliest config-bootstrap step. Migrate the local config first, then reinstall.

## Fields Required Before Installation

At minimum, fill in:

- `memory_worker_agentId`
- `memory_worker_harness`
- `production_agents`
- `code_dir`
- `store_dir`
- `archive_dir`

Recommended to confirm as well:

- `daily_write_cron_time`
- `weekly_decay_cron_day`
- `weekly_decay_cron_time`
- `timezone`
- `use_embedding`
- `embedding_model`
- `embedding_api_url`

Do not casually modify other fields. If adjustment is needed, read `docs/A2_overall-config-reference_en.md` first.

## Models and Runtime Environment

Task success depends heavily on the LLM used, especially:

- Context window size.
- Long-context stability.
- Tool-following reliability.

With weaker models, failure rates may increase. Such failures usually mean:

- The task did not complete.
- Output did not match expectations.
- A rerun is needed.

They should not normally corrupt local files. The highest known risk is task failure, not destructive damage to the local data structure.

Main local validation uses:

- MiniMax M2.7.
- 200k context window.

Under this setup, the system is stable in practice, with roughly 95% or higher task success. If your model is weaker, success rate is not guaranteed. Adjust `OverallConfig.layer1_write` context-budget parameters as needed.

## What `INSTALL.py` Does

Current top-level order:

1. Config bootstrap.
2. Harness config bootstrap.
3. Core prerequisites.
4. Harness memory-worker prerequisites.
5. Harness production-agent prerequisites.
6. Core install.
7. Harness memory-worker install.
8. Harness production-agent install.

### Core prerequisites

At minimum, checks:

- Basic `OverallConfig.json` validity.
- `memory_worker_agentId` is not in `production_agents`.
- Cron time formats.
- Whether `code_dir` matches the real repository path.
- Python / `crontab` availability.
- Embedding endpoint availability when `use_embedding=true`.

### Core install

At minimum:

- Creates `store_dir` structure if missing.
- Creates `archive_dir` structure if missing.
- Installs Layer1 / Layer3 auto cron jobs.

## OpenClaw Extra Steps

When `memory_worker_harness` or any `production_agents[*].harness` is `openclaw`:

### 1. OpenClaw root check

Default path:

```text
~/.openclaw/
```

If it does not exist, the installer asks for the real OpenClaw root and updates path templates in `OpenclawConfig.json`.

### 2. `key_template` validation

Validates `sessions_registry_maintenance.key_template`. It must:

- Contain `{agentId}`.
- Render to a top-level key that exists in the real `sessions.json`.

If unsure, inspect the top-level keys in the corresponding `sessions.json`. Common examples:

```text
agent:{agentId}:main
agent:{agentId}:telegram:direct:1234567890
```

### 3. OpenClaw config merge

The installer does not automatically rewrite your main OpenClaw config. It generates:

```text
Installation/example-openclaw.json
```

You must merge it manually, then restart the OpenClaw gateway.

The current merge mainly:

- Enables the MemoquasarEterna OpenClaw read plugin.
- Adds allow entries for recall tools to relevant agents.

MemoquasarEterna is not installed as OpenClaw's active memory backend, so do not point `plugins.slots.memory` to MemoquasarEterna.

## Hermes Extra Steps

When any `production_agents[*].harness` is `hermes`:

### 1. Hermes profile check

The Hermes adapter interprets:

```text
production_agents[*].agentId
```

as a Hermes profile name. For example:

```json
{"agentId": "hermes-init", "harness": "hermes"}
```

requires:

```text
~/.hermes/profiles/hermes-init/
```

### 2. Hermes skill installation

The installer writes the MemoquasarEterna recall skill to:

```text
~/.hermes/profiles/{agentId}/skills/memoquasar-memory-recall/SKILL.md
```

The skill calls `Core/Layer4_Read/` through terminal commands.

### 3. Current limitations

The Hermes adapter currently implements only minimal production-agent capabilities:

- Layer0 extract.
- Layer4 recall skill install / uninstall.

It does not support:

- Memory-worker LLM calls.
- Memory-worker runtime cleanup.
- Production-agent preserve.
- Production-agent decay.

Therefore, do not set `memory_worker_harness` to `hermes`.

## Snapshot Mechanism

Each successful top-level install writes a snapshot into:

```text
Installation/.install_logs/
```

Examples:

```text
install-2026-04-22T21-43-10+01:00.json
refresh-2026-04-23T09-10-42+01:00.json
```

Only the latest 3 snapshots are kept by default. `UNINSTALL.py` and `REFRESH.py` prefer these snapshots.

## Uninstall and Refresh

### Uninstall

```bash
cd {code_dir}
python Installation/UNINSTALL.py
```

If a latest snapshot exists, uninstall prefers facts recorded in that snapshot: harnesses, cron markers, plugin/workspace paths, and so on.

### Refresh

```bash
cd {code_dir}
python Installation/REFRESH.py
```

Current refresh means:

1. Prefer uninstalling according to the latest snapshot.
2. Migrate old `store_dir` / `archive_dir` if needed.
3. Install again according to current config.

## Common Issues

### Config bootstrap fails

Usually means:

- Local `Config.json` is missing while running `--dry-run`.
- `Config-template.json` is missing.
- Local `Config.json.schema_version` differs from the current template.

Non-dry-run install can generate missing local configs automatically. Schema mismatch requires manual migration.

### `code_dir` was automatically corrected

`OverallConfig.json.code_dir` did not match the real repository path; core prerequisites corrected it.

### `key_template` validation fails

Usually means:

- It does not contain `{agentId}`.
- The rendered key is not in the target `sessions.json`.
- The wrong `sessions.json` was inspected.

### OpenClaw root not found

If `~/.openclaw/` does not exist, enter the real OpenClaw root when prompted.

### Refresh cannot auto-migrate old directories

If the new `store_dir` or `archive_dir` already exists, migration stops to avoid mixing old and new data. Clean up directories manually, then run refresh again.
