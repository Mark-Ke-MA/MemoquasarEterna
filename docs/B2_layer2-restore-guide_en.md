English | [中文](B2_layer2-restore-guide.md)

# Layer2 Restore Guide

This document explains how to use the Layer2 restore entrypoint to recover memory files for a specific date or week from `archive_dir`.

## What Problem This Solves

When Layer3 has already cleaned active `store_dir`, and you want to view, compare, or recover memory from a day, use Layer2 restore.

Core entrypoint:

```bash
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py
```

## What to Know Before Restore

- Restore depends on existing archives in `archive_dir`.
- Restore is mainly for archived content recovery, not high-frequency daily use.
- Prefer `mirrored` mode first; it is more conservative.

## Common Parameters

- `--week`: target ISO week, e.g. `2026-W15`.
- `--date`: target date, e.g. `2026-04-14`.
- `--agent`: process only specific agents; comma-separated list supported.
- `--which-level`: restore granularity, default `all`; also supports `l0` / `l1` / `l2` / comma-separated lists.
- `--restore-mode`: `mirrored` / `update` / `overwrite`.
- `--run-name`: optional run name for this restore.
- `--clear`: clear restored content; supports `all` or a specific `run_name`.

## Recommended Usage

### 1. Conservative restore first (recommended)

Restore by date with default `mirrored` mode:

```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --date 2026-04-14
```

Restore by week:

```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --week 2026-W15
```

Restore only one agent:

```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --date 2026-04-14 --agent kaltsit
```

### 2. Specify levels

For example, restore only `l1`:

```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --date 2026-04-14 --which-level l1
```

### 3. Use more aggressive restore modes

If you clearly understand what you are doing, use:

- `update`
- `overwrite`

Example:

```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --date 2026-04-14 --restore-mode update
```

Warning: `update` / `overwrite` are riskier than `mirrored`; use only when you understand their effects.

## Where Restore Output Goes

Restore-related content goes to:

```text
{store_dir}/restored/
```

The restore log also shows which files were restored.

## Clear Restored Content

Clear all restored content:

```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --clear all
```

Clear one restore run:

```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --clear <run_name>
```

## Common Advice

- Prefer `mirrored` mode.
- Start with one date and one agent before expanding scope.
- If you only want to check whether a day has been archived, inspect `archive_dir` first instead of doing a broad restore.
- If unsure whether restore is needed, read:
  - `docs/B1_maintenance-guide_en.md`

## One-sentence Summary

Layer2 restore is not a replacement for daily active memory. It is a controlled recovery entrypoint for cases where memory has been archived and cleaned, but needs to be retrieved again.
