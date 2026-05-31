English | [中文](B1_maintenance-guide.md)

# Maintenance Guide

This document covers daily MemoquasarEterna maintenance entrypoints, common issues, and common recovery actions.

## Maintenance Entrypoints

### Install

```bash
python Installation/INSTALL.py
```

### Uninstall

```bash
python Installation/UNINSTALL.py
```

### Refresh

```bash
python Installation/REFRESH.py
```

### Layer1 rerun

```bash
python Maintenance/Layer1_Write_Rerun.py
```

### Layer3 rerun

```bash
python Maintenance/Layer3_Decay_Rerun.py
```

### Initial backfill

```bash
python Installation/Backfill/Layer1_Write_Initial_Backfill.py ...
python Installation/Backfill/Layer3_Decay_Initial_Backfill.py ...
```

---

## Most Common Maintenance Principles

- For most issues, prefer rerun first; do not manually edit active data structures as the first response.
- To rebuild the current installation, prefer `Installation/REFRESH.py`.
- To inspect what the previous install actually installed, check:
  - `Installation/.install_logs/`

---

## Common Issues and Suggested Actions

### 1. An install step fails

Recommended order:

1. Check which top-level `INSTALL.py` step failed.
2. Fix the corresponding prerequisites / config issue.
3. Run `python Installation/INSTALL.py` again.

### 2. OpenClaw `key_template` validation fails

Preferred action:

1. Open the corresponding `sessions.json`.
2. Find a real top-level key.
3. Replace the agent name with `{agentId}`.
4. Run install again.

### 3. Layer1 fails for a date / agent

Preferred action:

1. Rerun with `Maintenance/Layer1_Write_Rerun.py`.
2. If chunk size or model instability is suspected, temporarily adjust context-budget parameters in `OverallConfig.layer1_write` (for example, reduce `chunk_max_turns`) and rerun.
3. Also inspect:
   - `{store_dir}/logs/Layer1_Write_logs/auto/`

This is currently the most stable task-failure signal:

- If there is no corresponding failed file, the task usually did not fail.
- It is therefore useful to check it periodically.

The current failure-alert mechanism is not elegant yet, but can be improved later.

### 4. Layer3 fails for a week

Preferred action:

1. Rerun with `Maintenance/Layer3_Decay_Rerun.py`.
2. If historical initialization is involved, consider Layer3 initial backfill.

### 5. Refresh cannot auto-migrate old directories

If the new `store_dir` or `archive_dir` already exists, refresh stops automatic migration to avoid mixing data.

Recommended action:

1. Manually organize old and new directories.
2. Confirm target path state.
3. Run `python Installation/REFRESH.py` again.

### 6. Cron jobs need to be temporarily disabled

If backfill may conflict with automatic cron jobs:

- Temporarily remove the relevant cron block.
- Add it back after backfill completes.

Principles:

- Make only local manual maintenance changes.
- Do not delete unrelated cron entries.

---

## Things Not Recommended

- Do not casually edit active memory directory structure by hand.
- Do not modify system-level config fields without understanding them.
- Do not treat install snapshots as ordinary logs and delete them casually.
- Do not change global core logic immediately for a very small number of exceptional samples.

---

## About Task Failures

In currently known cases, the highest risk of most failures is:

- The task fails.
- Results are missing.
- A rerun is needed.

Not:

- Local files are destructively rewritten.
- Active data structures are irreversibly polluted.

Therefore, when handling anomalies, prefer:

- Conservative observation.
- Precise rerun.
- Minimal changes.
