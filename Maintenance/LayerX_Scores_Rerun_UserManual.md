# LayerX_Scores_Rerun_UserManual

`LayerX_Scores_Rerun.py` 是 LayerX landmark statistics records 的维护脚本，用于在你调整了 `LANDMARK_THRESHOLD`、修正了 LayerX 相关逻辑、或只是想重建某段日期的 landmark score records 时，批量重跑 `Layer1_Write/ENTRY_LAYER1.py` 的 `Stage1,Stage2,Stage8`。

它本身不重写 LayerX 逻辑，只负责：

- 确定 rerun 目标（哪些日期、哪些 agents）
- 串行调用 `ENTRY_LAYER1.py`
- 仅重建 LayerX 所需的 score records，不触碰 Layer1 的完整主流程

---

## 设计原则

- **最小可行性优先**：只重跑 LayerX 所依赖的最小链路：`Stage1,Stage2,Stage8`
- **分析用途优先**：这是面向分析 / 统计观察的维护脚本，不是产品主链路修复脚本
- **显式优先**：用户显式给出的日期和 agents 优先于默认推导
- **保守默认**：不改 archive，不触发 Layer3，不写入额外清理动作

---

## 支持的场景

### 1. 单日重跑
```bash
python Maintenance/LayerX_Scores_Rerun.py --date 2026-04-14
```

### 2. 单日只重跑部分 agents
```bash
python Maintenance/LayerX_Scores_Rerun.py --date 2026-04-14 --agent kaltsit,kristen
```

### 3. 日期范围批量重跑
```bash
python Maintenance/LayerX_Scores_Rerun.py --date_start 2026-04-01 --date_end 2026-04-07
```

### 4. 日期范围只重跑部分 agents
```bash
python Maintenance/LayerX_Scores_Rerun.py --date_start 2026-04-01 --date_end 2026-04-07 --agent kaltsit,kristen
```

---

## 参数说明

### `--date YYYY-MM-DD`
指定单个日期进行 rerun。

### `--date_start YYYY-MM-DD --date_end YYYY-MM-DD`
指定一个闭区间日期范围，逐天串行重跑。

限制：
- `--date` 与 `--date_start/--date_end` 不能同时使用
- 必须提供其中一种日期指定方式

### `--agent a,b,c`
指定只重跑哪些 agents。

规则：
- 支持逗号分隔多个 agent
- 原样透传给 `ENTRY_LAYER1.py --agent`
- 如果不传，则会自动读取 `OverallConfig.agentId_list`

### `--repo-root <path>`
指定仓库根目录。默认是当前脚本自动推断出来的 repo root。

---

## fixed behavior（固定行为）

本脚本调用 `ENTRY_LAYER1.py` 时，会固定传入：

```bash
--Stage Stage1,Stage2,Stage8 --stage1-staging-only
```

这意味着它只会：
- 重建 LayerX 需要的统计记录输入
- 重新执行 `Stage8_RecordScores.py`

而不会去跑 Layer1 的完整 map / reduce 主链路。

---

## 输出原则

本脚本的 stdout 只输出最小摘要：

```text
<date> <True|False>
```

其中：
- `True` 表示该日期对应的 `Stage8` 成功
- `False` 表示该日期对应的 `Stage8` 失败，或 stdout 结果无法被识别为成功

---

## 当前不支持的事

本脚本当前**不支持**：

- failed_log 驱动的自动 rerun
- chunk 级 rerun
- stage 级更细粒度选择
- 并发重跑多个日期
- 自动 diff 新旧 landmark records
- 自动分析“为什么某天 score 变高/变低”

这些都不属于第一版最小维护能力。

---

## 使用建议

- 如果你只是想观察 LayerX landmark 判定分布，默认值通常已经够用
- 只有当你明确希望重建某段时间的 landmark score records 时，再使用这个脚本
- 如果你刚刚调过 `Core/LayerX_LandmarkJudge/Stage3_Scoring.py` 中的 `LANDMARK_THRESHOLD`，那么应对你关心的日期范围重新跑一遍，才会看到新的统计结果

---

## 一句话定义

`LayerX_Scores_Rerun.py` 是 LayerX 的最小维护补跑脚本：

> 用最小链路批量重建 landmark score records，服务于 LayerX 的统计分析与阈值调参，而不是产品主功能维护。
