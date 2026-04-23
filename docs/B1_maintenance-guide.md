# 日常维护指引

本文档说明 MemoquasarEterna 的日常维护入口、常见问题与最常见恢复动作。

## 维护入口

### 安装
```bash
python Installation/INSTALL.py
```

### 卸载
```bash
python Installation/UNINSTALL.py
```

### 刷新
```bash
python Installation/REFRESH.py
```

### Layer1 补跑
```bash
python Maintenance/Layer1_Write_Rerun.py
```

### Layer3 补跑
```bash
python Maintenance/Layer3_Decay_Rerun.py
```

### 初始 backfill
```bash
python Installation/Backfill/Layer1_Write_Initial_Backfill.py ...
python Installation/Backfill/Layer3_Decay_Initial_Backfill.py ...
```

---

## 最常见的维护原则

- 大多数问题优先考虑 **重跑**，不要先手改 active 数据结构
- 如需整体重建当前安装，优先使用 `Installation/REFRESH.py`
- 如需查看上一轮安装到底装了什么，先看：
  - `Installation/.install_logs/`

---

## 常见问题与建议动作

### 1. install 某一步失败
建议顺序：
1. 看顶层 `INSTALL.py` 输出的是哪一步失败
2. 修正对应 prerequisites / config 问题
3. 重新执行 `python Installation/INSTALL.py`

### 2. OpenClaw `key_template` 校验失败
优先动作：
1. 按提示打开对应 `sessions.json`
2. 找到真实存在的顶层 key
3. 把 agent 名替换为 `{agentId}` 后重填
4. 重新运行安装

### 3. Layer1 某天 / 某 agent 失败
优先动作：
1. 先用 `Maintenance/Layer1_Write_Rerun.py` 重跑
2. 如果怀疑是 chunk 太大或模型不稳，可临时调整 `OverallConfig.layer1_write` 的相关上下文预算参数（比如调小 `chunk_max_turns`）再重跑
3. 同时查看：
   - `{store_dir}/logs/Layer1_Write_logs/auto/`

当前来看，这里是最稳定的任务失败判断入口：
- 如果没有对应 failed 文件，通常说明该任务没有出问题
- 因此也建议定期查看确认

目前这一套失败提醒机制还不算优雅，但后续可以继续优化

### 4. Layer3 某周失败
优先动作：
1. 先用 `Maintenance/Layer3_Decay_Rerun.py` 重跑
2. 如涉及历史数据初始化，再考虑用 Layer3 initial backfill 补灌

### 5. refresh 无法自动迁移旧目录
如果新的 `store_dir` 或 `archive_dir` 已存在，refresh 会中止自动迁移，以避免混合数据。
建议动作：
1. 先手动整理旧目录与新目录
2. 确认目标路径状态
3. 再重新执行 `python Installation/REFRESH.py`

### 6. cron 任务需要临时停用
如遇到 backfill 与自动 cron 可能冲突的情况：
- 可以临时摘掉对应 cron block
- backfill 完成后再补回

优先原则：
- 只做局部人工运维操作
- 不要误删无关 cron

---

## 不建议直接做的事

- 不要随意手改 active memory 目录结构
- 不要在不理解时随意修改系统级 config 字段
- 不要把 install snapshot 当作普通运行日志随意删除
- 不要为了极少数异常样本立刻改动全局核心逻辑

---

## 关于任务失败

当前已知情况下，绝大多数失败的最高风险是：
- 任务本身失败
- 结果缺失
- 需要重跑

而不是：
- 本地文件被破坏性改写
- active 数据结构被不可逆污染

因此，面对异常时，优先采用：
- 保守观察
- 精确补跑
- 最小修改
