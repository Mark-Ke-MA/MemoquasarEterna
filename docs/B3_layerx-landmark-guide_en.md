English | [中文](B3_layerx-landmark-guide.md)

# LayerX Landmark Guide

This document explains what LayerX landmark means, what it is used for, and how to tune the landmark score threshold.

## What This Is

`LayerX_LandmarkJudge/` is an auxiliary layer for landmark statistical analysis and judgment in MemoquasarEterna.

Its purpose is not daily production maintenance. Instead, it:

- Uses long-term accumulated landmark statistics records.
- Analyzes and scores daily memories.
- Outputs `score + landmark` decisions.
- Helps observe conversation / memory behavior patterns with agents from a longer-term statistical perspective.

LayerX is therefore closer to an **analysis entrypoint** than a required product-operations entrypoint.

---

## What Is a Landmark?

In the current system, `landmark` means:

> Whether a day is important or significant enough, in long-term statistical terms, to be marked as a memory landmark day.

LayerX does not read raw conversation text directly. It consumes:

```text
{store_dir}/statistics/landmark_scores/{agentId}_landmark_scores.json
```

These records are maintained by `Layer1_Write/Stage8_RecordScores.py`.

In other words, LayerX performs secondary analysis on existing statistics records instead of re-running the full raw memory extraction pipeline.

---

## What It Does

LayerX mainly serves two purposes.

### 1. Provides an internal landmark decision interface

The judge line outputs daily:

- `score`
- `landmark`

These results can be consumed later by Layer3 shallow / decay logic.

### 2. Provides an advanced long-term statistics view

Use LayerX if you want to:

- See which days with an agent look like “landmark days”.
- Observe long-term statistical behavior of the memory worker.
- Adjust landmark criteria and observe how result distribution changes.

---

## Why a Threshold Is Needed

LayerX Stage3 turns daily statistical analysis into a total score, then compares it with a threshold:

- Score **>= threshold** -> `landmark = true`
- Score **< threshold** -> `landmark = false`

Current default:

```text
LANDMARK_THRESHOLD = 5.5
```

Location:

```text
Core/LayerX_LandmarkJudge/Stage3_Scoring.py
```

---

## Why It Can Be Tuned

The threshold is not an absolute truth; it is an engineering default.

More precisely:

- It contains some developer bias.
- It reflects the current engineering tradeoff for what deserves to be called a landmark day.
- It is not guaranteed to be optimal for every person, agent, or conversation style.

If current results preserve too many or too few landmark days, you may tune it manually.

---

## When to Tune

By default, **you do not need to tune it**.

Because:

- It does not significantly affect the main product function.
- The default is an acceptable current engineering value.
- Leaving it unchanged does not affect archive existence or completeness.

Tune only when you intentionally want to explore your long-term statistics, or when results are clearly inconsistent with your intuition.

Examples:

- Almost every day becomes landmark -> threshold may be too loose.
- Truly important days are rarely landmark -> threshold may be too strict.

---

## How to Tune

### Where to tune

Edit:

```text
Core/LayerX_LandmarkJudge/Stage3_Scoring.py
```

Value:

```python
LANDMARK_THRESHOLD = 5.5
```

### Direction

#### To make landmark detection stricter

Increase the threshold.

Typical effect:

- Fewer landmark days are preserved.
- Only higher-scoring days become `landmark=true`.

#### To make landmark detection looser

Decrease the threshold.

Typical effect:

- More landmark days are preserved.
- More medium-intensity days become `landmark=true`.

---

## What to Do After Tuning

Changing code does not automatically rewrite historical statistics.

If you tune `LANDMARK_THRESHOLD` and want historical landmark decisions recalculated under the new threshold, use:

```text
Maintenance/LayerX_Scores_Rerun.py
```

Example:

```bash
cd {code_dir}
python Maintenance/LayerX_Scores_Rerun.py --date_start 2026-04-01 --date_end 2026-04-30
```

Maintenance notes:

- `Maintenance/LayerX_Scores_Rerun_UserManual.md`

---

## Risk Boundary

Current risk boundary for tuning LayerX threshold is clear:

- **It does not cause archive loss.**
- **It does not break main data structures.**
- **It does not significantly affect whether the main product remains usable.**

It mainly affects:

- Which days are marked as landmark.
- The distribution of LayerX long-term statistics and analysis results.

This is an advanced parameter you can experiment with, not a critical post-installation configuration.

---

## Usage Advice

- If unsure, do not tune it.
- If tuning, make small changes rather than large jumps.
- After tuning, rerun only the date range you care about first, then observe result changes.
- If you use MemoquasarEterna as a product rather than as an analysis object, the default `5.5` is acceptable.

---

## One-sentence Summary

LayerX landmark is a long-term statistical “memory landmark day” mechanism. It is more like an analysis entrypoint than a main product maintenance entrypoint. `LANDMARK_THRESHOLD = 5.5` is the current engineering default; if landmark days feel too many or too few, tune it in `Core/LayerX_LandmarkJudge/Stage3_Scoring.py` and rerun selected history with `Maintenance/LayerX_Scores_Rerun.py`.
