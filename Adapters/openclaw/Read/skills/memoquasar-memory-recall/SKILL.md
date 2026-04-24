---
name: memoquasar-memory-recall
description: 当用户要求你回忆、记住、总结前情，或检索过去对话中的精确表述时，优先使用 MemoquasarEterna 的记忆召回工具。
user-invocable: false
---

当用户在问**过去的对话、之前的决定、前几天做过的事、以前说过的话**时，不要只凭当前上下文猜测；优先调用 MemoquasarEterna recall。

## 触发信号

以下表达通常应触发 recall：

- “你还记得吗”
- “回忆一下”
- “昨天我们做了什么”
- “最近在忙什么”
- “之前是不是讨论过”
- “上次怎么定的”
- “原话是什么”
- 任何明显在问**过去信息**的问题

## 工具分流

- 模糊回忆、最近概览、昨天/最近几天做了什么、之前是否讨论过
  -> 当前 agent 可用的 `*_memory_vague_recall`
- 原话、精确摘录、某个具体时间窗口里说过的话
  -> 当前 agent 可用的 `*_memory_exact_recall`

## 参数规则

对 `*_memory_vague_recall`：

- 用户问“昨天 / 最近几天 / 最近在做什么”，但没有明确主题
  -> 不传 `query`
  - 很近的检查优先 `recent_days=1`
  - 更宽一点的近期概览优先 `recent_days=3`
- 用户问某个具体主题
  -> 传简短 `query`
- 只有在确实需要按日期范围收窄时，才加 `date_window`
- 只有在明确需要更多对话级证据时，才加 `prefer_l2_ratio`

## 回答要求

- 先给结论，再简要总结 recall 结果
- 不要在用户没要求时原样倾倒整段工具输出
- 如果结果不完整或不确定，要明确说明
- 如果用户要原话而你只做了模糊回忆，继续调用 exact recall
