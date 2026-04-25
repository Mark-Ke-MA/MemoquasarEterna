# OverallConfig.json 字段说明

本文档详尽说明 `OverallConfig.json` 中的全部字段。

它是一份配置参考手册，不是安装步骤文档。
如果你只是第一次安装系统，请先阅读：

- `docs/A1_installation-guide.md`

仓库跟踪的默认模板是 `OverallConfig-template.json`。本地实际运行读取 `OverallConfig.json`；如果它不存在，`Installation/INSTALL.py` 会从模板生成一份。请只修改本地 `OverallConfig.json`，不要提交本机私有配置。

---

## 使用原则

- 本文档解释 **全部字段**，不代表所有字段都适合日常修改。
- 其中一部分字段是安装前必须明确填写的。
- 还有一部分字段属于运行策略或系统级参数，默认不要随意修改。
- 如确需修改系统级字段，请先理解它在代码中的实际用途。

---

## 产品与 schema 字段

### `schema_version`
- core 侧配置 schema 版本号。
- 用于标识当前 core 配置格式版本。

### `active_schema_version`
- active memory 数据的 schema 版本号。
- 供 active memory 读写逻辑使用。

### `archive_schema_version`
- archive memory 数据的 schema 版本号。
- 供 archive 侧逻辑使用。

### `product_name`
- 产品名。
- 会影响一些用户可见名称与衍生安装产物，例如：
  - plugin id 推导
  - cron 标题文字
  - 部分安装结果命名

---

## core 安装身份字段

### `layer1_auto_cron_marker`
- Layer1 auto cron block 的唯一 marker。
- install / uninstall / refresh 会通过它识别正确的 cron block。
- 不建议随意修改；如果改动，务必确保 install / uninstall 使用同一值。

### `layer3_auto_cron_marker`
- Layer3 auto cron block 的唯一 marker。
- install / uninstall / refresh 会通过它识别正确的 cron block。
- 不建议随意修改；如果改动，务必确保 install / uninstall 使用同一值。

---

## 安装前必须明确的字段

### `harness`
- 指定使用哪个 adapter harness。
- 当前主要值为：
  - `openclaw`

### `memory_worker_agentId`
- 专用内部 memory worker 的 agent id。
- 该值不能出现在 `agentId_list` 中。
- 这是一个专用内部 worker，不应与普通业务 agent 混用。

### `agentId_list`
- 普通业务 agent 列表。
- 系统会用它来构建存储结构、session-watch 相关产物等。
- 不应包含重复项。

### `code_dir`
- 本地仓库根目录。
- 应当与当前 clone 下来的真实仓库路径一致。
- 如果 core prerequisites 发现其与真实 `repo_root` 不一致，会自动修正为当前仓库路径。

### `store_dir`
- active storage 根目录。
- active memory / staging / logs / restored / statistics 等目录结构会建在这里。
- 如果 refresh 检测到旧 snapshot 使用的是另一个 `store_dir`，会在安全条件下尝试迁移。

### `archive_dir`
- archive storage 根目录。
- archive 侧目录结构会建在这里。
- 如果 refresh 检测到旧 snapshot 使用的是另一个 `archive_dir`，会在安全条件下尝试迁移。

---

## 运行策略字段

### `nprl_llm_max`
- core 逻辑使用的正整数限制值。
- 必须保持为正整数。

### `timezone`
- 时区设置。
- 日期 / window 相关逻辑会使用它。
- 同时会影响一些按本地时间计算的行为。

### `use_embedding`
- 布尔值。
- 如果为 `true`，core prerequisites 会检查 embedding 配置与 embedding endpoint 是否可用。

### `embedding_model`
- 当 `use_embedding=true` 时使用的 embedding model。

### `embedding_api_url`
- 当 `use_embedding=true` 时使用的 embedding API endpoint。
- core prerequisites 会对其执行最小连通性检查。

---

## 定时运行字段

### `daily_write_cron_time`
- Layer1 auto write 的每日运行时间。
- 格式：
  - `HH:MM`

### `weekly_decay_cron_day`
- Layer3 auto decay 的每周运行日。
- 期望值：
  - `Sun`, `Mon`, `Tue`, `Wed`, `Thu`, `Fri`, `Sat`

### `weekly_decay_cron_time`
- Layer3 auto decay 的每周运行时间。
- 格式：
  - `HH:MM`

---

## Window 字段

### `window.start`
- window 起点的 offset 与时间定义。
- core 的日期 / window 逻辑会使用它。

#### `window.start.day_offset`
- 起点相对 boundary 的天数偏移。

#### `window.start.hour`
- 起点小时。

#### `window.start.minute`
- 起点分钟。

### `window.end`
- window 终点的 offset 与时间定义。
- core 的日期 / window 逻辑会使用它。

#### `window.end.day_offset`
- 终点相对 boundary 的天数偏移。

#### `window.end.hour`
- 终点小时。

#### `window.end.minute`
- 终点分钟。

### `window.boundary`
- 每日 boundary 的定义。
- 用于推导实际 target date。

#### `window.boundary.hour`
- boundary 小时。

#### `window.boundary.minute`
- boundary 分钟。

---

## Layer1 配置字段

### `layer1_write.ct_all_max`
- Layer1 的整体 token/context 上限。

### `layer1_write.ct_all_free`
- 预留的 free context 预算。

### `layer1_write.ct_map_prompt`
- map 阶段 prompt 预算。

### `layer1_write.ct_reduce_prompt`
- reduce 阶段 prompt 预算。

### `layer1_write.ct_system_prompt`
- system prompt 预算。

### `layer1_write.ct_reduce_output_max`
- reduce 阶段输出预算上限。

### `layer1_write.Nretry_map`
- map 阶段重试次数。

### `layer1_write.Nretry_reduce`
- reduce 阶段重试次数。

### `layer1_write.chunk_max_turns`
- 每个 chunk 的最大 turn 数。

### `layer1_write.chars_per_token_estimate`
- Layer1 使用的字符 / token 估算值。

---

## Layer3 配置字段

### `layer3_decay._interval_in_units`
- Layer3 interval 语义对应的单位标签。

### `layer3_decay.trimL2_interval`
- trimL2 所使用的 interval。

### `layer3_decay.shallow_interval`
- shallow decay 所使用的 interval。

### `layer3_decay.deep_max_shallow`
- 进入 deep 前允许的 shallow 上限。

### `layer3_decay.Nretry_shallow`
- shallow 阶段重试次数。

### `layer3_decay.Nretry_deep`
- deep 阶段重试次数。

---

## Archive 结构字段

### `archive_dir_structure.core`
- archive 侧 core 根目录名。

### `archive_dir_structure.harness`
- archive 侧 harness 根目录名。

---

## Store 结构字段

### `store_dir_structure.memory.root`
- memory 子树根目录名。

### `store_dir_structure.memory.surface`
- memory root 下的 surface 子目录名。

### `store_dir_structure.memory.shallow`
- memory root 下的 shallow 子目录名。

### `store_dir_structure.memory.deep`
- memory root 下的 deep 子目录名。

### `store_dir_structure.staging.root`
- staging 子树根目录名。

### `store_dir_structure.staging.staging_surface`
- staging surface 子目录名。

### `store_dir_structure.staging.staging_shallow`
- staging shallow 子目录名。

### `store_dir_structure.staging.staging_deep`
- staging deep 子目录名。

### `store_dir_structure.logs.root`
- logs 子树根目录名。

### `store_dir_structure.logs.harness.root`
- harness log 根目录名。

### `store_dir_structure.logs.layer1_write._note`
- Layer1 log 结构的人类备注。

### `store_dir_structure.logs.layer1_write.root`
- Layer1 log 根目录名。

### `store_dir_structure.logs.layer1_write.auto`
- Layer1 auto log 子目录名。

### `store_dir_structure.logs.layer1_write.manual`
- Layer1 manual log 子目录名。

### `store_dir_structure.logs.layer2_preserve.root`
- Layer2 preserve log 根目录名。

### `store_dir_structure.logs.layer3_decay.root`
- Layer3 decay log 根目录名。

### `store_dir_structure.restored.root`
- restored 子树根目录名。

### `store_dir_structure.statistics.root`
- statistics 子树根目录名。

### `store_dir_structure.statistics.graphs`
- statistics 下 graphs 子目录名。

### `store_dir_structure.statistics.landmark_scores`
- statistics 下 landmark_scores 子目录名。

---

## 其他系统字段

### `empty_conversation_marker_suffix`
- 空会话场景下使用的后缀标记。

---

## 修改建议

### 建议安装前明确填写的字段
- `harness`
- `memory_worker_agentId`
- `agentId_list`
- `code_dir`
- `store_dir`
- `archive_dir`
- `daily_write_cron_time`
- `weekly_decay_cron_day`
- `weekly_decay_cron_time`
- `timezone`
- `use_embedding`
- `embedding_model`
- `embedding_api_url`

### 默认不要随意修改的字段
- `schema_version`
- `active_schema_version`
- `archive_schema_version`
- `layer1_auto_cron_marker`
- `layer3_auto_cron_marker`
- `window.*`
- `layer1_write.*`
- `layer3_decay.*`
- `archive_dir_structure.*`
- `store_dir_structure.*`
- `empty_conversation_marker_suffix`

如果确需修改这些系统级字段，请先确认对应代码路径与实际消费逻辑。 
