# LayerX Landmark 说明

本文档说明 LayerX landmark 的含义、作用，以及如何微调 landmark score threshold。

## 这是什么

`LayerX_LandmarkJudge/` 是 MemoquasarEterna 中负责 landmark 统计分析与判定的辅助层。

它的核心工作不是日常生产维护，而是：

- 基于长期累计的 landmark statistics records
- 对单日记忆做分析与打分
- 输出 `score + landmark` 判定结果
- 让你从更长期、统计学的角度观察自己与 agent 的对话 / 记忆行为模式

所以，LayerX 更接近一个**分析入口**，而不是安装后必须反复操作的“产品运维入口”。

---

## landmark 是什么

在当前系统里，`landmark` 可以理解为：

> 在长期统计意义上，某一天是否足够“重要”或“显著”，从而值得被标成一个记忆地标日。

LayerX 不直接看原始会话文本本身，而是消费：

```text
{store_dir}/statistics/landmark_scores/{agentId}_landmark_scores.json
```

这些 records 由 `Layer1_Write/Stage8_RecordScores.py` 维护。

换句话说，LayerX 是在已有统计 records 的基础上做二次分析，而不是重新做一整套原始记忆抽取。

---

## 它有什么作用

LayerX 的作用主要有两层：

### 1. 给系统内部提供一个 landmark 判定接口
judge 线会输出按日的：
- `score`
- `landmark`

这可以被后续 Layer3 shallow / decay 逻辑消费。

### 2. 给高级用户提供一个长期统计观察入口
如果你想：
- 看看自己和某个 agent 的哪些日子更像“地标日”
- 观察 memory worker 在长期上的统计行为模式
- 试着调整 landmark 判定标准，看看结果分布会怎么变化

那 LayerX 就是这个入口。

---

## 为什么会需要 threshold

LayerX Stage3 会把单日统计分析结果打成一个总分，然后拿这个分数和阈值比较：

- 分数 **>= threshold** → `landmark = true`
- 分数 **< threshold** → `landmark = false`

当前默认值是：

```text
LANDMARK_THRESHOLD = 5.5
```

位置在：

```text
Core/LayerX_LandmarkJudge/Stage3_Scoring.py
```

---

## 为什么可以微调

因为这个阈值本质上不是一个绝对“真理”，而是一个工程默认值。

更准确地说：
- 它带有一定程度的研发者个人 bias
- 它反映的是当前版本对“什么样的一天值得叫做 landmark”的工程取舍
- 它并不保证对每个人、每个 agent、每类对话风格都同样最优

所以，如果你觉得当前判定结果：
- 保留的 landmark day **太多**
- 或保留的 landmark day **太少**

你可以手动微调这个阈值。

---

## 什么时候需要调

默认情况下，**你完全可以不调**。

因为：
- 这不会显著影响产品主功能
- 默认值已经是当前版本的可接受工程值
- 不调也不会影响 archive 的存在与完整性

只有在你明确想“玩一玩”自己的长期统计结果，或者觉得当前判定结果明显不符合自己的直觉时，才值得调。

例如：
- 你觉得几乎每天都被判成 landmark → 可能过宽松
- 你觉得真正重要的日子却很少被判成 landmark → 可能过严格

---

## 怎么调

### 去哪里调
直接修改：

```text
Core/LayerX_LandmarkJudge/Stage3_Scoring.py
```

中的：

```python
LANDMARK_THRESHOLD = 5.5
```

### 调整方向

#### 如果你想让 landmark 判定更严格
把阈值调高。

效果通常是：
- 被保留下来的 landmark day 更少
- 只有分数更高的日子才会被判成 `landmark=true`

#### 如果你想让 landmark 判定更宽松
把阈值调低。

效果通常是：
- 被保留下来的 landmark day 更多
- 更多中等强度的日子会进入 `landmark=true`

---

## 调完以后要做什么

只改代码不会自动改写历史统计结果。

如果你调了 `LANDMARK_THRESHOLD`，又希望历史日期的 landmark 判定按新阈值重算，你应该使用：

```text
Maintenance/LayerX_Scores_Rerun.py
```

例如：

```bash
cd {code_dir}
python Maintenance/LayerX_Scores_Rerun.py --date_start 2026-04-01 --date_end 2026-04-30
```

对应维护说明见：
- `Maintenance/LayerX_Scores_Rerun_UserManual.md`

---

## 风险边界

调整 LayerX 的 threshold，当前已知的风险边界很明确：

- **不会造成 archive 损失**
- **不会破坏主功能数据结构**
- **不会显著影响产品主功能是否可用**

它主要影响的是：
- 哪些日子会被判成 landmark
- LayerX 的长期统计与分析结果分布

因此，这是一个可以玩的高级参数，但不是安装后必须处理的关键配置。

---

## 使用建议

- 如果你不确定是否需要调，就先不要调
- 如果你要调，优先做小幅调整，不要一次跳太大
- 调整后最好只对你关心的日期范围 rerun，再观察结果变化
- 如果你只是把 MemoquasarEterna 当成产品使用，而不是把 LayerX 当成分析对象研究，默认值 `5.5` 完全可以接受

---

## 一句话

LayerX landmark 是一个长期统计意义上的“记忆地标日”判定机制；它更像分析入口，而不是主产品维护入口。`LANDMARK_THRESHOLD = 5.5` 是当前默认工程值，若你觉得 landmark day 太多或太少，可以在 `Core/LayerX_LandmarkJudge/Stage3_Scoring.py` 中手动微调，并用 `Maintenance/LayerX_Scores_Rerun.py` 重建你关心的历史结果。
