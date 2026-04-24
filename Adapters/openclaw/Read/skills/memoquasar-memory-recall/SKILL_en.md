---
name: memoquasar-memory-recall
description: Prefer MemoquasarEterna recall tools when the user asks you to remember, recall prior context, summarize recent past work, or retrieve exact prior wording.
user-invocable: false
---

When the user is asking about **past conversation content, prior decisions, recent past work, or earlier wording**, do not rely only on the current context; prefer MemoquasarEterna recall.

## Triggers

These usually warrant recall:

- "Do you remember...?"
- "Recall / think back"
- "What did we do yesterday?"
- "What have we been working on recently?"
- "Didn't we discuss this before?"
- "What did we decide last time?"
- "What was the exact wording?"
- Any request clearly asking about **past information**

## Tool routing

- Fuzzy recall, recent overview, what happened yesterday / recently, whether something was discussed before
  -> the current agent's available `*_memory_vague_recall`
- Exact wording, exact excerpts, what was said in a specific time window
  -> the current agent's available `*_memory_exact_recall`

## Parameter rules

For `*_memory_vague_recall`:

- If the user asks about yesterday / recent days / recent work without a specific topic
  -> omit `query`
  - prefer `recent_days=1` for a very local check
  - prefer `recent_days=3` for a broader recent overview
- If the user asks about a specific topic
  -> pass a short `query`
- Only add `date_window` when you truly need to narrow by time range
- Only add `prefer_l2_ratio` when you intentionally want more dialogue-level evidence

## Response rules

- Give the conclusion first, then briefly summarize the recalled result
- Do not dump raw tool output unless the user wants it
- If the result is partial or uncertain, say so clearly
- If the user wants exact wording and you only did vague recall, follow with exact recall
