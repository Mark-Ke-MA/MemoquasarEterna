# Layer3_Decay_Rerun_UserManual

`Layer3_Decay_Rerun.py` 是 Layer3 的维护脚本，用于在**某个 target week 失败**、**某个 Phase 失败**、或**人工决定需要重跑**时，重新调用 `Layer3_Decay/ENTRY_LAYER3.py`。

它本身不重写 Layer3 逻辑，只负责：

- 确定 rerun 目标（哪一周、哪个 Phase、哪些 agents）
- 串行调用 `ENTRY_LAYER3.py`
- 在使用 `failed_log` 时，必要时回写 `rerun_done` 标记

---

## 设计原则

- **最小可行性优先**：按 week / week+phase / week+phase+agents 重跑，不做 stage 级修复
- **显式优先**：用户显式给出的 `--Phase` / `--agent` 优先于 failed_log 自动推导
- **manual run 强制化**：本脚本调用 Layer3 时，固定传 `--run-mode manual`
- **cleanup 保守默认**：rerun 默认不带 `--apply_cleanup`；如果确实要做 destructive cleanup，必须显式传参
- **可追踪**：若从 `failed_log` 触发，成功后会把该 log 标记为已 rerun

---

## 支持的场景

### 1. 按日期重跑
```bash
python Maintenance/Layer3_Decay_Rerun.py --date 2026-04-28
```

脚本会先把日期自动换算为所属 ISO week，再调用 Layer3。

### 2. 按 week 重跑
```bash
python Maintenance/Layer3_Decay_Rerun.py --week 2026-W18
```

### 3. 只重跑某个 Phase
```bash
python Maintenance/Layer3_Decay_Rerun.py --week 2026-W18 --Phase Phase3
```

### 4. 只重跑某些 agents
```bash
python Maintenance/Layer3_Decay_Rerun.py --week 2026-W18 --agent agent_a,agent_b
```

### 5. 同时限制 Phase 和 agents
```bash
python Maintenance/Layer3_Decay_Rerun.py --week 2026-W18 --Phase Phase2 --agent agent_a,agent_b
```

### 6. 从 failed_log 自动推导 rerun
```bash
python Maintenance/Layer3_Decay_Rerun.py --failed-log path/to/2026-W18.json
```

逻辑是：
- 自动读取 `week`
- 若 log 中有 `failed_phase`，则默认只 rerun 该 Phase
- 若 log 中有 `failed_agents`，则默认只 rerun 这些 agents
- 若用户又显式传了 `--Phase` 或 `--agent`，则以用户参数为准

### 7. rerun 时显式允许 cleanup
```bash
python Maintenance/Layer3_Decay_Rerun.py --week 2026-W18 --Phase Phase2 --apply_cleanup
```

注意：
- 这是危险操作
- 默认 rerun 不做 cleanup
- 只有你显式传了 `--apply_cleanup`，脚本才会把它透传给 `ENTRY_LAYER3.py`

---

## 参数说明

### `--date YYYY-MM-DD`
指定某个日期进行 rerun。

脚本会自动：
- 解析这个日期所属的 ISO week
- 再把该 week 作为 `target week` 传给 `ENTRY_LAYER3.py`

原因是：
- Layer3 的自然入口是 week
- 但人类通常对 date 比对 week 更直观

### `--week YYYY-WXX`
直接指定 rerun 的 target week。

### `--agent a,b,c`
指定只重跑哪些 agents。

规则：
- 支持逗号分隔多个 agent
- 会自动去重
- 如果配合 `--failed-log` 使用，则视为人工覆盖 log 中的 `failed_agents`

### `--failed-log <path>`
从某个 Layer3 failed log 文件中读取 rerun 目标。

限制：
- 不能与 `--date`
- 不能与 `--week`
同时使用

### `--run-name <name>`
透传给 `ENTRY_LAYER3.py --run-name`。

如果不传，则默认生成：

```text
Rerun_from_script_<UTC时间戳>
```

### `--Phase Phase0|Phase1|Phase2|Phase3|Phase4`
指定只重跑哪个 Phase。

规则：
- 若不传，则默认重跑整个 Layer3
- 若与 `--failed-log` 同时使用，则用户显式 `--Phase` 优先于 log 自动推导

### `--apply_cleanup`
显式允许 rerun 执行 destructive cleanup。

默认：
- 不传
- rerun 只做重建 / 重跑，不做删除

这与 Layer1 不同，是 Layer3 维护脚本的额外安全边界。

---

## fixed behavior（固定行为）

本脚本调用 `ENTRY_LAYER3.py` 时，会固定添加：

```bash
--run-mode manual
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
- 该 week 已经通过本脚本成功 rerun
- 若要再次覆写，请手动处理该 failed_log 后重跑

### 若不存在
脚本会正常执行 rerun。

### 若 rerun 成功
脚本会回写该 failed_log：

```json
"rerun_done": true,
"rerun_at": "...",
"rerun_run_name": "..."
```

注意：
- 只有本次 rerun **成功** 时，才会写入这些字段
- 如果 rerun 失败，则不会标记 `rerun_done=true`

---

## 输出原则

本脚本的 stdout 只保留必要摘要，不回显 Layer3 内部大对象。

典型输出会包含：
- rerun 是否成功
- rerun 模式（manual / failed-log）
- run_name
- 是否显式启用了 cleanup
- 本次 target 的：
  - `week`
  - `phase`
  - `agents`
  - `success`
  - `returncode`
  - `entry_note`
  - `failed_phase`
  - `fail_log_needed`
  - `fail_log_path`

---

## 当前不支持的事

本脚本当前**不支持**：

- date 范围批量 rerun
- stage 级 selective rerun
- 并发重跑多个 week
- 自动遍历整个 Layer3 failed_logs 目录批量补跑
- 自动 diff 新旧结果

这些都不属于第一版最小可行维护能力。

---

## 一句话定义

`Layer3_Decay_Rerun.py` 是 Layer3 的最小维护补跑脚本：

> 用统一入口处理“按 week”或“按 week+phase(+agents)”的 rerun，并在消费 failed_log 时留下最小闭环标记。
