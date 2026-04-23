# Layer1_Write_Rerun_UserManual

`Layer1_Write_Rerun.py` 是 Layer1 的维护脚本，用于在**单天失败**、**部分 agents 失败**、或**人工决定需要重跑**时，重新调用 `Layer1_Write/ENTRY_LAYER1.py`。

它本身不重写 Layer1 逻辑，只负责：

- 确定 rerun 目标（哪天、哪些 agents）
- 串行调用 `ENTRY_LAYER1.py`
- 在使用 `failed_log` 时，必要时回写 `rerun_done` 标记

---

## 设计原则

- **最小可行性优先**：按“天”或“天+agents”重跑，不做 chunk 级修复
- **显式优先**：用户显式给出的日期/agents 优先于自动推导
- **manual log 强制化**：本脚本调用 Layer1 时，固定传 `--log-mode manual`
- **可追踪**：若从 `failed_log` 触发，成功后会把该 log 标记为已 rerun

---

## 支持的场景

### 1. 某天完全失败，整天重跑
```bash
python Maintenance/Layer1_Write_Rerun.py --date 2026-04-14
```

### 2. 某天只有部分 agents 需要重跑
```bash
python Maintenance/Layer1_Write_Rerun.py --date 2026-04-14 --agent agent_a,agent_b
```

### 3. 某个日期范围整段重跑
```bash
python Maintenance/Layer1_Write_Rerun.py --start-date 2026-04-01 --end-date 2026-04-07
```

### 4. 某个日期范围只重跑部分 agents
```bash
python Maintenance/Layer1_Write_Rerun.py --start-date 2026-04-01 --end-date 2026-04-07 --agent agent_a,agent_b
```

### 5. 从 failed_log 自动推导 rerun
```bash
python Maintenance/Layer1_Write_Rerun.py --failed-log path/to/2026-04-14_failed_log.json
```

逻辑是：
- 若 failed_log 中能提取出 failed agents，则只重跑这些 agents
- 若提取不出 agent 级失败信息，则退化成整天全量重跑

---

## 参数说明

### `--date YYYY-MM-DD`
指定单个日期进行 rerun。

### `--start-date YYYY-MM-DD --end-date YYYY-MM-DD`
指定一个闭区间日期范围，逐天串行重跑。

### `--failed-log <path>`
从某个 failed_log 文件中读取 rerun 目标。

限制：
- 不能与 `--date`
- 不能与 `--start-date/--end-date`
同时使用。

### `--agent a,b,c`
指定只重跑哪些 agents。

规则：
- 支持逗号分隔多个 agent
- 会自动去重
- 如果配合 `--failed-log` 使用，则视为人工覆盖 failed_log 中的 agent 选择

### `--run-name <name>`
透传给 `ENTRY_LAYER1.py --run-name`。

如果不传，则默认生成：
```text
Rerun_from_script_<UTC时间戳>
```

---

## fixed behavior（固定行为）

本脚本调用 `ENTRY_LAYER1.py` 时，会**强制添加**：

```bash
--log-mode manual
```

原因：
- rerun 属于人工维护行为
- 不应写入 auto failed logs

---

## failed_log 的 rerun 标记逻辑

如果使用：
```bash
--failed-log <path>
```

则脚本会先检查该 failed_log 是否已有：

```json
"rerun_done": true
```

### 若已存在
脚本会直接跳过，并提示：
- 该日期已经通过本脚本成功 rerun
- 若要再次覆写，请手动处理该 failed_log 后重跑

### 若不存在
脚本会正常执行 rerun。

### 若 rerun 整体成功
脚本会回写该 failed_log：

```json
"rerun_done": true,
"rerun_at": "...",
"rerun_run_name": "..."
```

注意：
- 只有本次 rerun **整体成功** 时，才会写入这些字段
- 如果任一 target 失败，则不会标记 `rerun_done=true`

---

## 输出原则

本脚本的 stdout 只保留必要摘要，不回显 Layer1 内部大对象。

典型输出会包含：
- 本次 rerun 是否成功
- rerun 模式（manual / failed-log）
- run_name
- target 数量
- 每个 target 的：
  - `date`
  - `agents`
  - `success`
  - `returncode`
  - `entry_note`
  - `fail_log_needed`
  - `fail_log_path`

---

## 当前不支持的事

本脚本当前**不支持**：

- chunk 级 rerun
- stage 级 selective rerun
- 并发重跑多个日期
- 自动遍历整个 failed_logs 目录批量补跑
- 自动 diff 新旧结果

这些都不属于第一版最小可行维护能力。

---

## 一句话定义

`Layer1_Write_Rerun.py` 是 Layer1 的最小维护补跑脚本：

> 用统一入口处理“按天”或“按天+agents”的 rerun，并在消费 failed_log 时留下最小闭环标记。
