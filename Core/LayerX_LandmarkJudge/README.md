# LayerX_LandmarkJudge

## 这一层做什么

`LayerX_LandmarkJudge/` 是 **MemoquasarEterna** 中负责 **landmark 分析与判定** 的辅助判定层。

它的定位是：

> 基于长期保留的 landmark statistics records，对单日记忆进行分析、打分，并输出可供衰减层消费的 landmark 判定结果。

在整体结构中，LayerX 承担的是：

- 统计分析层
- 判定辅助层
- 供其他层消费的 judge 层

---

## 输入

LayerX 的输入主要来自两部分：

### 1. Landmark statistics records

LayerX 当前直接消费：

```text
{store_dir}/statistics/landmark_scores/{agentId}_landmark_scores.json
```

这些 records 由 `Layer1_Write/Stage8_RecordScores.py` 持续维护。

当前 LayerX 以长期保留的统计 records 作为分析底座。

### 2. 查询参数

LayerX 当前支持：

- `--agent`
- `--date`
- `--date_start`
- `--date_end`
- `--analysis`
- `--graphs_path`
- `--landmark_ratio`
- `--recent-days`

其中：

- judge 线用于输出 `score + landmark`
- analysis 线用于输出统计 summary，并在需要时画图

---

## 输出

LayerX 当前有两类输出。

### 1. Judge 输出

judge 线的标准输出是按日的 landmark 判定结果，例如：

```json
[
  {
    "agentId": "<agent_id>",
    "target_date": "<YYYY-MM-DD>",
    "score": 5.7,
    "landmark": true
  }
]
```

这就是后续 Layer3 shallow / decay 逻辑应直接消费的接口。

### 2. Analysis 输出

analysis 线会输出：

- 精简统计 summary
- 可选图像结果
- 若传了 `--landmark_ratio`，则还会输出分析阈值相关信息

如果没有传 `--graphs_path`，则不画图。

---

## 主入口

### `ENTRY_LAYERX.py`

这是 LayerX 的统一入口。

常见示例：

按单日 judge：

```bash
python3 ENTRY_LAYERX.py --agent <agent_id> --date <YYYY-MM-DD>
```

按日期范围 judge：

```bash
python3 ENTRY_LAYERX.py --agent <agent_id> --date_start <YYYY-MM-DD> --date_end <YYYY-MM-DD>
```

analysis 模式：

```bash
python3 ENTRY_LAYERX.py --agent <agent_id> --analysis
```

最近 N 天 analysis：

```bash
python3 ENTRY_LAYERX.py --agent <agent_id> --analysis --recent-days <N>
```

---

## 内部结构

LayerX 当前固定分为 4 个 stage。

### Stage1 — Collect

- 从 records 文件中收集指定 agent / 日期窗口内的 `counts[]`
- 输出的最小分析单位是：
  - `agent_id`
  - `target_date`
  - `count_entry`

### Stage2 — Analyze

- 对单个 `count_entry` 做结构化分析
- 读取：
  - `key_items`
  - `emotional_intensities`
- 生成：
  - `key_item_counts`
  - `intensities`
  - `simple_mean_intensity`
  - `weighted_mean_intensity`
  - `intensity5_count`

### Stage3 — Scoring

- 对 Stage2 的分析结果打分
- 输出 `score` 与 `landmark` 判定
- 当前使用固定工程阈值

### Stage4 — Finalize

- judge 模式下：输出按日的 `score + landmark`
- analysis 模式下：输出统计 summary，并在需要时画图

---

## Records schema

当前每个 agent 的 records 文件结构是：

```json
{
  "agentId": "<agent_id>",
  "counts": [
    {
      "date": "<YYYY-MM-DD>",
      "key_items": {
        "milestone": 1,
        "bug_fix": 0,
        "config_change": 0,
        "decision": 2,
        "incident": 0,
        "question": 1
      },
      "emotional_intensities": {
        "3": 1,
        "4": 2,
        "5": 1
      }
    }
  ]
}
```

当前约束是：

- 同一 `agentId + date` 只保留一条 entry
- 后写覆盖前写
- `emotional_intensities` 只记录实际出现过的分值

---

## 当前打分策略

LayerX 当前的打分由两部分组成：

### 1. Key item 分支

当前会对部分 `key_items` 类型加权：

- `milestone`
- `bug_fix`
- `incident`

另外，当前版本的加权重点主要放在更强 landmark 信号相关的 key item 类型上。

### 2. Emotion 分支

当前会基于：

- `weighted_mean_intensity`
- `intensity == 5` 的出现情况

计算情绪贡献分。

### 当前工程阈值

当前使用固定 landmark 阈值：

```text
5.5
```

这是当前版本供 Layer3 shallow / decay 判定使用的工程阈值。

---

## Analysis 模式

当传入 `--analysis` 时，LayerX 进入分析模式。

### 默认分析窗口

若：

- 开启 `--analysis`
- 且不传 `date / date_start / date_end`

则默认分析：

- 所有早于今天、且已经存在于 records 中的日期

### `--recent-days N`

若同时传入 `--recent-days N`，则分析窗口改为：

- 最近 `N` 天（截至昨天）

这适合只观察近期分布。

---

## 与其他层的关系

### 向上游

LayerX 依赖：

- Layer1 Stage8 持续维护的 landmark statistics records

### 向下游

LayerX 的 judge 结果主要被：

- Layer3 Decay

消费，尤其用于：

- shallow 阶段的 landmark 判定
- surface 删除候选与保留边界的决策辅助

也就是说，LayerX 在整个产品中的位置是：

> 为 Layer3 提供“哪些日记忆应被视为 landmark”的统计判定依据。

---

## 角色边界

LayerX 聚焦于 landmark statistics records 的结构化分析、打分与判定输出。

围绕它的其他职责分布为：

- Layer1_Write Stage8：维护 records 写入
- Layer1 / Layer2 / Layer3：承载日级写入、surface 归档与后续多层级整理

因此 LayerX 当前承担的是：

> 从长期保留的 landmark statistics records 中做结构化分析、打分，并输出可供衰减层消费的 landmark 判定结果。
