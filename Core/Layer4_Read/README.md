# Layer4_Read

## 这一层做什么

`Layer4_Read/` 是 **MemoquasarEterna** 中负责 **记忆读取与召回** 的层。

它的职责不是生成新记忆，也不是做长期衰减，而是在已有的：

- L0 索引
- L1 摘要层
- L2 对话层
- shallow / deep 聚合层

之上，提供两类读取能力：

- `vague recall`
- `exact recall`

一句话说：

> Layer1 负责写，Layer3 负责减薄，Layer4 负责读。

---

## 输入

Layer4 的输入主要来自三部分：

### 1. 已写成的 memory 结构

Layer4 会读取：

- `l0_index.json`
- `l0_embeddings.json`
- surface `L1`
- shallow `L1`
- deep `L1`
- surface `L2`
- archived `L2`（exact 模式在需要时使用）

### 2. 查询参数

Layer4 当前支持两类查询：

#### vague recall

输入包括：

- `query`
- `date_window`（可选）
- `prefer_l2_ratio`（可选）

#### exact recall

输入包括：

- `date`
- `window_start`
- `window_end`

### 3. 总配置

Layer4 会读取 `OverallConfig.json` 中与以下内容相关的字段：

- `store_dir`
- `store_dir_structure`
- `use_embedding`
- `embedding_model`
- `embedding_api_url`
- `timezone`
- `layer3_decay`

---

## 输出

Layer4 当前提供两类最终输出。

### 1. Vague recall

输出字段：

- `success`
- `assembled_text`

其中：

- `assembled_text` 是面向 agent 或上层 harness 可直接消费的召回文本
- 当前内部会按条组装，不允许简单对整串字符串做硬截断

### 2. Exact recall

输出字段：

- `success`
- `transcript_text`

其中：

- `transcript_text` 是在给定日期与时间窗口下提取出的对话文本
- 若目标时间范围内没有可用对话，则返回固定无对话文本

---

## 主入口

### `ENTRY_LAYER4_vague.py`

这是 vague recall 的统一入口。

常见示例：

```bash
python3 ENTRY_LAYER4_vague.py --agent <agent_id> --query "<query>"
```

带 `date_window`：

```bash
python3 ENTRY_LAYER4_vague.py --agent <agent_id> --query "<query>" --date-window <YYYY-MM-DD,YYYY-MM-DD>
```

带 `prefer_l2_ratio`：

```bash
python3 ENTRY_LAYER4_vague.py --agent <agent_id> --query "<query>" --prefer-l2-ratio 0.5
```

### `ENTRY_LAYER4_exact.py`

这是 exact recall 的统一入口。

常见示例：

```bash
python3 ENTRY_LAYER4_exact.py --agent <agent_id> --date <YYYY-MM-DD> --window-start <HH:MM> --window-end <HH:MM>
```

---

## 内部结构

Layer4 当前主要由以下部分组成：

- `ENTRY_LAYER4_vague.py`
  - vague recall 顶层入口
  - 调用 L0 / L1 / L2 recall helper
  - 执行 layer weighting、bounded recency modulation、dedupe 与 assemble

- `ENTRY_LAYER4_exact.py`
  - exact recall 顶层入口
  - 调用 L2 exact recall helper

- `recall_L0.py`
  - coarse recall
  - 负责找 time anchors
  - 默认 lexical + embedding hybrid；embedding 不可用时自动降级 lexical-only

- `recall_L1.py`
  - 从 L1 层提取字段级候选
  - 提供可解释、可混排的信息片段

- `recall_L2.py`
  - 提供两种能力：
    - vague 模式下的 surface excerpt 召回
    - exact 模式下的时间窗口对话提取

- `shared.py`
  - Layer4 共用数据结构与辅助函数

---

## Vague recall 设计

Layer4 vague 当前遵循这些核心原则：

### 1. L0 只做索引，不做最终信息源

L0 的职责是：

- 先找出值得回源的 time anchors

但最终进入 `assembled_text` 的内容来源只包括：

- L1 candidates
- L2 vague candidates

### 2. Layer weighting 固定有界

当前默认层权重是：

- `L1 = 0.7`
- `L2 = 0.3`

若传入 `prefer_l2_ratio`，则：

- 对外合法范围是 `0 <= x <= 1`
- 内部映射为安全权重，并保持权重调整的有界性与稳定性

### 3. 时间调制保持 `[0, 1]` 有界

当前不使用裸加法时间 bias，而使用有界乘法调制：

```text
final = weighted_layer_score * (1 - alpha + alpha * recency_score)
```

### 4. 时间衰减统一只依赖 characterized date

- `surface`：直接用 `date`
- `shallow`：用 week bin center
- `deep`：用 window bin center

### 5. 支持 `date_window`

若传入 `date_window`，recency 会从该 window 向两侧衰减，并强于默认模式。

### 6. 内建轻量 dedupe / diversity

当前实现包含：

- normalize 后文本硬去重
- 同一 `time_key` 数量限制
- 同一 `time_key + field` 限制
- token overlap 去重
- 对疑似 runtime-context / internal-event 风格文本只做 soft penalty，不硬删

---

## Exact recall 设计

Layer4 exact 当前遵循这些核心原则：

### 1. 信息源只来自 L2

exact recall 不走 L1 摘要拼装，而是直接从 L2 层提取目标时间窗口对应的 transcript。

### 2. Active / archived 路由受时间与状态约束

当前约定是：

- 近 `trimL2_interval` 周：优先 active surface `L2`，缺失时再查 archived `L2`
- 更早：优先 archived `L2`
- 若 active `L2` 已被标记 trimmed，则不能把它当作 exact 的正常来源

### 3. 缺失或无对话时固定返回

若目标时间范围内没有可用对话，则返回固定文本：

```text
该时间范围内无可用对话记录。
```

### 4. 全局字符上限固定

当前 exact 输出遵守固定全局字符上限，超限时会按既定策略减载。

---

## 与 harness 的关系

Layer4 有一个重要边界：

> 它作为 core 读取层，被 harness / adapter 反向调用。

也就是说：

- `Layer4_Read/` 本身是纯脚本读取层
- 上层 adapter 或 plugin 调用 `ENTRY_LAYER4_vague.py` / `ENTRY_LAYER4_exact.py`
- 读取能力由 Layer4 作为独立读取层提供

这也是当前 OpenClaw Read 适配的设计基础。

---

## 角色边界

Layer4 聚焦于读取与召回本身。

围绕它的其他职责分布为：

- Layer1_Write：生成新记忆
- Layer3_Decay：处理衰减与删除
- Layer2_Preserve：处理 preserve / archive
- Installation / Adapters：承载安装、初始化与外部平台包装

---

## 与其他层的关系

### 向上游

Layer4 读取：

- Layer1 生成的 surface 结构
- Layer3 生成的 shallow / deep 结构
- Layer2 preserve 提供的 archived `L2`（在 exact 模式需要时）

### 在整体结构中的位置

Layer4 位于当前产品 memory core 的读取端。

因此 Layer4 在整个产品中的位置是：

> 把已经写成并经过衰减整理的记忆结构，重新转换为可供 agent 或外部 harness 直接消费的召回结果。
