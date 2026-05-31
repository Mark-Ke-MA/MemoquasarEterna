English | [中文](A2_overall-config-reference.md)

# OverallConfig.json Field Reference

This is a field reference for `OverallConfig.json`, not an installation tutorial. For first-time setup, read `docs/A1_installation-guide_en.md` first.

The repository tracks `OverallConfig-template.json`; local runtime reads `OverallConfig.json`. If the local file is missing, `Installation/INSTALL.py` generates it from the template. Do not commit machine-private config.

## Principles

- Before installation, explicitly fill identity, path, agent, and embedding-related fields.
- Schema, directory structure, window, Layer1, and Layer3 parameters are system-level fields. Keep defaults unless you know why.
- If local `schema_version` differs from the template, installation stops; migrate local config first.

## Required and Common Fields

| Field | Meaning | Recommendation |
| --- | --- | --- |
| `memory_worker_agentId` | Dedicated MW agent id; must not appear in `production_agents` | Required; must be an internal non-PA agent |
| `memory_worker_harness` | Harness used by MW | Production recommendation: `openclaw`; do not use `hermes` |
| `production_agents` | Served PA list, each with `agentId` and `harness` | Required; `agentId` should not repeat |
| `code_dir` | Repository root | Required; prerequisites auto-correct to real repo root |
| `python_bin_path` | Python interpreter used by the OpenClaw read plugin after install | Prefer absolute venv / pyenv path; installer falls back if empty/unavailable |
| `store_dir` | Root for active memory, staging, logs, and statistics | Required; runtime reads/writes/cleans it |
| `archive_dir` | Root for archived memory | Required; most important backup target |
| `timezone` | Timezone for dates, windows, and cron | Fill explicitly |
| `use_embedding` | Whether embedding recall is enabled | Match local capabilities |
| `embedding_model` | Embedding model name | Required when `use_embedding=true` |
| `embedding_api_url` | Embedding endpoint | Checked by prerequisites when `use_embedding=true` |

`production_agents[*].harness` currently supports:

| Harness | Status | Notes |
| --- | --- | --- |
| `openclaw` | production | Supports MW, PA, Layer0, Layer4, preserve / decay |
| `hermes` | experimental | Only PA Layer0 extract and Layer4 recall skill; `agentId` equals Hermes profile name |

## Product and Schema Fields

| Field | Meaning | Recommendation |
| --- | --- | --- |
| `schema_version` | Core config schema version | Do not edit manually |
| `active_schema_version` | Active memory schema version | Do not edit manually |
| `archive_schema_version` | Archive memory schema version | Do not edit manually |
| `product_name` | Product name; affects plugin id, cron titles, install artifact names | Editable, but derived names change |
| `layer1_auto_cron_marker` | Unique marker for Layer1 auto cron block | Do not edit unless necessary; install/uninstall must match |
| `layer3_auto_cron_marker` | Unique marker for Layer3 auto cron block | Do not edit unless necessary; install/uninstall must match |

## Schedule and Window

| Field | Meaning | Format / Notes |
| --- | --- | --- |
| `daily_write_cron_time` | Daily Layer1 auto write time | `HH:MM` |
| `weekly_decay_cron_day` | Weekly Layer3 auto decay day | `Sun`-`Sat` |
| `weekly_decay_cron_time` | Weekly Layer3 auto decay time | `HH:MM` |
| `window.start.day_offset` | Memory-day start offset relative to boundary | System-level field |
| `window.start.hour` / `minute` | Memory-day start time | System-level field |
| `window.end.day_offset` | Memory-day end offset relative to boundary | System-level field |
| `window.end.hour` / `minute` | Memory-day end time | System-level field |
| `window.boundary.hour` / `minute` | Daily boundary used to infer target date | System-level field |

## Layer1 Write Parameters

| Field | Meaning |
| --- | --- |
| `layer1_write.ct_all_max` | Overall context limit used by Layer1 |
| `layer1_write.ct_all_free` | Reserved free context |
| `layer1_write.ct_map_prompt` | Map prompt budget |
| `layer1_write.ct_reduce_prompt` | Reduce prompt budget |
| `layer1_write.ct_system_prompt` | System prompt budget |
| `layer1_write.ct_reduce_output_max` | Reduce output budget |
| `layer1_write.Nretry_map` | Retry count for map stage |
| `layer1_write.Nretry_reduce` | Retry count for reduce stage |
| `layer1_write.chunk_max_turns` | Max turns per chunk |
| `layer1_write.chars_per_token_estimate` | Rough characters-per-token estimate |

These affect chunk count, LLM context pressure, and failure rate. Do not edit unless adapting to a different model context window.

## Layer3 Decay Parameters

| Field | Meaning |
| --- | --- |
| `layer3_decay._interval_in_units` | Unit label for intervals; currently week semantics |
| `layer3_decay.trimL2_interval` | Interval for trimming L2 |
| `layer3_decay.shallow_interval` | Interval for shallow decay |
| `layer3_decay.deep_max_shallow` | Maximum shallow memories before deep aggregation |
| `layer3_decay.Nretry_shallow` | Retry count for shallow stage |
| `layer3_decay.Nretry_deep` | Retry count for deep stage |

Layer3 runs active-memory thinning after Layer2 preserve. Change these only after understanding archive and restore behavior.

## Directory Structure Fields

These define internal directory names under `store_dir` / `archive_dir`. They are normally designed once during initialization and should not be changed after the system is running.

| Field | Meaning |
| --- | --- |
| `archive_dir_structure.core` | Core root name in archive |
| `archive_dir_structure.harness` | Harness root name in archive |
| `store_dir_structure.memory.root` | Memory subtree root |
| `store_dir_structure.memory.surface` | Surface memory directory |
| `store_dir_structure.memory.shallow` | Shallow memory directory |
| `store_dir_structure.memory.deep` | Deep memory directory |
| `store_dir_structure.staging.root` | Staging subtree root |
| `store_dir_structure.staging.staging_surface` | Staging surface directory |
| `store_dir_structure.staging.staging_shallow` | Staging shallow directory |
| `store_dir_structure.staging.staging_deep` | Staging deep directory |
| `store_dir_structure.logs.root` | Logs subtree root |
| `store_dir_structure.logs.harness.root` | Harness log root |
| `store_dir_structure.logs.layer1_write.root` | Layer1 log root |
| `store_dir_structure.logs.layer1_write.auto` | Layer1 auto log subdirectory |
| `store_dir_structure.logs.layer1_write.manual` | Layer1 manual log subdirectory |
| `store_dir_structure.logs.layer2_preserve.root` | Layer2 preserve log directory |
| `store_dir_structure.logs.layer3_decay.root` | Layer3 decay log directory |
| `store_dir_structure.restored.root` | Restored subtree directory |
| `store_dir_structure.statistics.root` | Statistics subtree directory |
| `store_dir_structure.statistics.graphs` | Statistics graphs directory |
| `store_dir_structure.statistics.landmark_scores` | Landmark scores directory |

## Other Fields

| Field | Meaning |
| --- | --- |
| `nprl_llm_max` | Positive integer limit used by core logic |
| `store_dir_structure.logs.layer1_write._note` | Human note for Layer1 log structure |
| `empty_conversation_marker_suffix` | Suffix for empty-conversation marker files |

## Edit Recommendations

Before installation, focus on:

```text
memory_worker_agentId / memory_worker_harness / production_agents
code_dir / store_dir / archive_dir
python_bin_path
timezone / use_embedding / embedding_model / embedding_api_url
daily_write_cron_time / weekly_decay_cron_day / weekly_decay_cron_time
```

Do not normally edit:

```text
schema_version / active_schema_version / archive_schema_version
cron marker / window.* / layer1_write.* / layer3_decay.*
archive_dir_structure.* / store_dir_structure.*
```
