English | [中文](README.md)

# MemoquasarEterna

**MemoquasarEterna** ("the persistence of memory") is a local-first memory infrastructure project for multi-agent AI workflows.

**Core features:**

- Preserves and summarizes daily conversations with agents (and, in practice, not necessarily only agents).
- Archives long-term memory and gradually decays it by emotional / semantic intensity: short-term memory focuses on facts, long-term memory focuses on what mattered.
- Calls LLMs only when needed, and delegates as much work as possible to verifiable code paths.
- Automatically estimates context budgets and chunks conversations, reducing the risk of overloading agents with very large transcripts.
- Reads memory only on demand: it avoids polluting normal context, while still allowing agents to recover old conversations and exact wording.

## Repository Notes

- This repository now provides Chinese documentation plus English mirror documents.
- This is not a polished commercial or research-grade product. It is a personal toy project built from real needs and shared as an open-source reference.
- The repository is developed collaboratively by the maintainer and Kal'tsit, using OpenAI GPT-5.4 and Claude Sonnet 4.6 during development.

## Current Support Scope

- macOS only.
- Requires a local Python environment. It has been validated mainly with Python 3.10.8 / 3.14.3 on the maintainer's machines.
- Currently supported harnesses:
  - `OpenClaw` -> primary production harness, validated with OpenClaw 2026.4.23.
  - `Hermes` -> experimental harness with minimal write/read support, validated with Hermes 0.11.0.
- Task success depends on the LLM used by the memory worker. The current baseline is MiniMax M2.7 with a 200k context window, where the system is stable in practice (roughly >= 95% task success rate).

## Fan-work Notice

This project is partly inspired by the world and themes of *Arknights*. It should be understood as unofficial fan work; its content, views, and implementation do not represent any official entity.

![MemoquasarEterna README Hero Image](docs/assets/readme-hero.jpg)

## Terms and Placeholders

| Term | Meaning | Notes |
| --- | --- | --- |
| `code_dir` | Local root path of this repository | User-defined; `~/` is recommended |
| `store_dir` | Runtime root for memory, logs, staging, and statistics | Dynamic data that may be read, written, or cleaned during normal operation |
| `archive_dir` | Root for compressed / archived memory backups | More static, append-oriented data; the most important target for backups |
| MW | Memory Worker: internal agent dedicated to memory writing and decay | Must be separate from production agents; an economical model is recommended |
| PA | Production Agent: real agent served by the memory system | Agents from different harnesses can be served together |
| harness | External runtime platform or agent framework | e.g. `openclaw`, `hermes`, `codex`, `claudecode` |
| adapter | MemoquasarEterna integration layer for a harness | Located under `Adapters/{harness}/` |
| L2 | Daily raw transcript | Highest fidelity and highest context cost; avoid injecting full L2 into PA context unless you really know why |
| L1 | Daily structured summary extracted from L2 | Main material for reading, decay, and statistics |
| L0 | Lightweight retrieval index extracted from L1 | Used by Layer4 recall, embeddings, and keyword retrieval |
| Layer0 Extract | Standardized extraction from harness data to L2 | Adapter handles platform differences; core handles canonical output |
| Layer1 Write | Daily write pipeline | L2 -> L1 -> L0 |
| Layer2 Preserve | Archive / restore layer between active and archived memory | Creates safety copies before destructive cleanup |
| Layer3 Decay | Periodic thinning and long-term organization layer | Handles trim, shallow, deep, and cleanup phases |
| Layer4 Read | Recall and reading layer | Uses queries to hit L0, then retrieves relevant L1 / L2 evidence |
| LayerX Score | Non-mainline statistics and landmark judge | Analytical layer for observing long-term trends |

## Risk Warnings

| Risk | Trigger | Default | Impact | Recommendation |
| --- | --- | --- | --- | --- |
| Layer3 cleans active `store_dir` | Weekly decay runs | Enabled | Deletes archived active daily files to control active memory size | Ensure `archive_dir` is reliable; see `docs/B2_layer2-restore-guide_en.md` |
| MW session cleanup | `memory_worker_harness == "openclaw"` | Enabled | Deletes task-like MW sessions to prevent unbounded accumulation | MW must be a dedicated internal agent, never mixed with PA |
| Production agent raw session-file decay | `production_agents[*].harness == "openclaw"` and `sessions_registry_maintenance.session_files_decay` manually enabled | Disabled | Deletes archived OpenClaw raw session files | Enable only after fully understanding the consequences |

Notes:

- Layer3 cleanup is safe only because Layer2 preserve has already archived the relevant data.
- If a PA is accidentally configured as MW, OpenClaw MW cleanup may delete real conversation sessions.
- Production-agent raw session-file decay is an advanced high-risk feature. Enable it only by editing `{code_dir}/Adapters/openclaw/OpenclawConfig.json` and setting `sessions_registry_maintenance.session_files_decay` to `true`.

---

## Repository Structure

```text
{code_dir}/
  Core/
  Adapters/
  Installation/
  Maintenance/
  docs/
  OverallConfig-template.json
  README.md
  README_en.md
```

### `Core/`

The memory engine itself. It contains Layer0-Layer4 and LayerX logic, plus shared utilities and the harness connector.

### `Adapters/`

External harness integration layer. Current implementations:

- `Adapters/openclaw/`
- `Adapters/hermes/`

Adapters connect `Core/` to concrete runtimes and expose a unified interface through `CONNECTOR.py`.

### `Installation/`

Install lifecycle entrypoints:

- `INSTALL.py`
- `UNINSTALL.py`
- `REFRESH.py`
- `Core/`
- `Backfill/`
- `.install_logs/` (generated after runs)

### `Maintenance/`

Manual maintenance, rerun, and recovery scripts.

### `docs/`

Main project documentation.

---

## Quick Start

### 1. Clone the repository

```bash
git clone <repo-url> {code_dir}
cd {code_dir}
```

### 2. Generate and edit local configs

On first install, `Installation/INSTALL.py` generates local config files from templates when they are missing:

- `OverallConfig.json`
- `Adapters/{harness}/{Harness}Config.json`

You may also copy them manually before installation:

```bash
cp OverallConfig-template.json OverallConfig.json
cp Adapters/{harness}/{Harness}Config-template.json Adapters/{harness}/{Harness}Config.json
```

Edit only local config files without `-template` in their names. Do not commit machine-private config into git.

At minimum, fill in:

- `memory_worker_agentId`
- `memory_worker_harness`
- `production_agents`
- `code_dir`
- `store_dir`
- `archive_dir`

See the full config reference:

- `docs/A2_overall-config-reference_en.md`

### 3. Install

```bash
python3 Installation/INSTALL.py
```

If `memory_worker_harness` or any `production_agents[*].harness` is `openclaw`, the installer will run OpenClaw-specific prerequisites and may ask you to:

- Confirm the OpenClaw root directory.
- Fill in `key_template`.
- Merge `Installation/example-openclaw.json` into your OpenClaw config.
- Restart the OpenClaw gateway.

If any `production_agents[*].harness` is `hermes`, the installer checks that the corresponding Hermes profile exists and installs the `memoquasar-memory-recall` skill into that profile. The Hermes adapter currently cannot be used as `memory_worker_harness`.

---

## Current Harnesses

| Harness | Status | MW | PA | Layer0 Extract | Layer1 Write | Layer2 Preserve | Layer3 Decay | Layer4 Read |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `openclaw` | production | yes | yes | yes | yes | yes | yes | yes |
| `hermes` | experimental | no | yes | yes | yes | no | no | yes |

More details:

- `Adapters/openclaw/README.md`
- `docs/C3_adapter-openclaw_en.md`
- `Adapters/hermes/README.md`
- `docs/C4_adapter-hermes_en.md`

---

## Documentation Entry Points

Recommended reading order:

1. `docs/A1_installation-guide_en.md`
2. `docs/A2_overall-config-reference_en.md`
3. `docs/B1_maintenance-guide_en.md`
4. `docs/B2_layer2-restore-guide_en.md`
5. `docs/B3_layerx-landmark-guide_en.md`
6. `docs/C1_architecture_en.md`
7. `docs/C2_connector-contract_en.md`
8. `docs/C3_adapter-openclaw_en.md`
9. `docs/C4_adapter-hermes_en.md`

Document purposes:

- `docs/A1_installation-guide_en.md` — install, uninstall, and refresh flows.
- `docs/A2_overall-config-reference_en.md` — all `OverallConfig.json` fields.
- `docs/B1_maintenance-guide_en.md` — maintenance entrypoints, common issues, recovery actions.
- `docs/B2_layer2-restore-guide_en.md` — restoring memory from `archive_dir`.
- `docs/B3_layerx-landmark-guide_en.md` — LayerX landmark scoring and threshold tuning.
- `docs/C1_architecture_en.md` — architecture and layer design.
- `docs/C2_connector-contract_en.md` — fixed connector interface contract.
- `docs/C3_adapter-openclaw_en.md` — OpenClaw adapter structure and responsibilities.
- `docs/C4_adapter-hermes_en.md` — Hermes adapter capability boundary and known limitations.

---

## Development and Maintenance Notes

| Change | Update these docs first |
| --- | --- |
| Install flow / config bootstrap | `docs/A1_installation-guide_en.md`, `docs/A2_overall-config-reference_en.md` |
| Connector fixed interface | `docs/C2_connector-contract_en.md` |
| OpenClaw adapter | `docs/C3_adapter-openclaw_en.md` |
| Hermes adapter | `docs/C4_adapter-hermes_en.md` |
| Memory schema / layer relations | `docs/C1_architecture_en.md` |

To understand the overall design, start with `docs/C1_architecture_en.md`.
