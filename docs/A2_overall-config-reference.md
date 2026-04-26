# OverallConfig.json 字段说明

本文档是 `OverallConfig.json` 的字段参考，不是安装教程。首次安装请先看 `docs/A1_installation-guide.md`。

仓库跟踪 `OverallConfig-template.json`，本地运行读取 `OverallConfig.json`；缺失时 `Installation/INSTALL.py` 会从模板生成。请不要提交本机私有配置。

## 使用原则

- 安装前必须明确填写身份、路径、agent 与 embedding 相关字段。
- schema、目录结构、window、Layer1/Layer3 参数属于系统级字段，默认不要改。
- 如果本地 `schema_version` 与模板不一致，安装会中止，需先手动迁移配置。

## 必填与常用字段

| 字段 | 含义 | 修改建议 |
| --- | --- | --- |
| `memory_worker_agentId` | 专用 MW agent id，不能出现在 `production_agents` 中 | 必填；必须是非 PA 的内部 agent |
| `memory_worker_harness` | MW 使用的 harness | 当前生产推荐 `openclaw`；不要设为 `hermes` |
| `production_agents` | 被服务的 PA 列表，每项含 `agentId`、`harness` | 必填；`agentId` 不应重复 |
| `code_dir` | 当前仓库根目录 | 必填；prerequisites 会自动修正为真实 repo root |
| `store_dir` | active memory、staging、logs、statistics 根目录 | 必填；运行期会读写与清理 |
| `archive_dir` | archive memory 根目录 | 必填；最值得备份 |
| `timezone` | 日期、window、cron 相关时区 | 建议明确填写 |
| `use_embedding` | 是否启用 embedding recall | 按本机能力设置 |
| `embedding_model` | embedding model 名 | `use_embedding=true` 时需可用 |
| `embedding_api_url` | embedding endpoint | `use_embedding=true` 时 prerequisites 会检查连通性 |

`production_agents[*].harness` 当前主要支持：

| harness | 状态 | 说明 |
| --- | --- | --- |
| `openclaw` | production | 支持 MW、PA、Layer0、Layer4、preserve / decay |
| `hermes` | experimental | 仅支持 PA 的 Layer0 extract 与 Layer4 recall skill；`agentId` 等同 Hermes profile 名 |

## 产品与 schema 字段

| 字段 | 含义 | 修改建议 |
| --- | --- | --- |
| `schema_version` | core config schema 版本 | 不要手动改 |
| `active_schema_version` | active memory schema 版本 | 不要手动改 |
| `archive_schema_version` | archive memory schema 版本 | 不要手动改 |
| `product_name` | 产品名；影响 plugin id、cron 标题、安装产物命名 | 可改，但会影响衍生名称 |
| `layer1_auto_cron_marker` | Layer1 auto cron block 唯一 marker | 不建议改；install/uninstall 必须一致 |
| `layer3_auto_cron_marker` | Layer3 auto cron block 唯一 marker | 不建议改；install/uninstall 必须一致 |

## 定时与 window

| 字段 | 含义 | 格式 / 备注 |
| --- | --- | --- |
| `daily_write_cron_time` | Layer1 auto write 每日运行时间 | `HH:MM` |
| `weekly_decay_cron_day` | Layer3 auto decay 每周运行日 | `Sun`-`Sat` |
| `weekly_decay_cron_time` | Layer3 auto decay 每周运行时间 | `HH:MM` |
| `window.start.day_offset` | memory day 起点相对 boundary 的天数偏移 | 系统级字段 |
| `window.start.hour` / `minute` | memory day 起点时间 | 系统级字段 |
| `window.end.day_offset` | memory day 终点相对 boundary 的天数偏移 | 系统级字段 |
| `window.end.hour` / `minute` | memory day 终点时间 | 系统级字段 |
| `window.boundary.hour` / `minute` | 推导 target date 的每日边界 | 系统级字段 |

## Layer1 写入参数

| 字段 | 含义 |
| --- | --- |
| `layer1_write.ct_all_max` | Layer1 使用的整体 context 上限 |
| `layer1_write.ct_all_free` | 预留 free context |
| `layer1_write.ct_map_prompt` | map prompt 预算 |
| `layer1_write.ct_reduce_prompt` | reduce prompt 预算 |
| `layer1_write.ct_system_prompt` | system prompt 预算 |
| `layer1_write.ct_reduce_output_max` | reduce 输出预算 |
| `layer1_write.Nretry_map` | map 阶段重试次数 |
| `layer1_write.Nretry_reduce` | reduce 阶段重试次数 |
| `layer1_write.chunk_max_turns` | 单个 chunk 最大 turn 数 |
| `layer1_write.chars_per_token_estimate` | 字符 / token 粗估系数 |

这些参数影响 chunk 数、LLM 上下文压力与失败率。除非要适配不同模型上下文窗口，否则不建议改。

## Layer3 衰减参数

| 字段 | 含义 |
| --- | --- |
| `layer3_decay._interval_in_units` | interval 的单位标签，当前为 week 语义 |
| `layer3_decay.trimL2_interval` | trim L2 的 interval |
| `layer3_decay.shallow_interval` | shallow decay 的 interval |
| `layer3_decay.deep_max_shallow` | 进入 deep 前允许保留的 shallow 上限 |
| `layer3_decay.Nretry_shallow` | shallow 阶段重试次数 |
| `layer3_decay.Nretry_deep` | deep 阶段重试次数 |

Layer3 会在 Layer2 preserve 后执行 active memory 减薄。修改前请确认自己理解归档与恢复流程。

## 目录结构字段

这些字段定义 `store_dir` / `archive_dir` 内部目录名。一般只在初始化项目前设计一次，运行后不建议改。

| 字段 | 含义 |
| --- | --- |
| `archive_dir_structure.core` | archive 侧 core 根目录名 |
| `archive_dir_structure.harness` | archive 侧 harness 根目录名 |
| `store_dir_structure.memory.root` | memory 子树根目录名 |
| `store_dir_structure.memory.surface` | surface memory 目录名 |
| `store_dir_structure.memory.shallow` | shallow memory 目录名 |
| `store_dir_structure.memory.deep` | deep memory 目录名 |
| `store_dir_structure.staging.root` | staging 子树根目录名 |
| `store_dir_structure.staging.staging_surface` | staging surface 目录名 |
| `store_dir_structure.staging.staging_shallow` | staging shallow 目录名 |
| `store_dir_structure.staging.staging_deep` | staging deep 目录名 |
| `store_dir_structure.logs.root` | logs 子树根目录名 |
| `store_dir_structure.logs.harness.root` | harness log 根目录名 |
| `store_dir_structure.logs.layer1_write.root` | Layer1 log 根目录名 |
| `store_dir_structure.logs.layer1_write.auto` | Layer1 auto log 子目录名 |
| `store_dir_structure.logs.layer1_write.manual` | Layer1 manual log 子目录名 |
| `store_dir_structure.logs.layer2_preserve.root` | Layer2 preserve log 目录名 |
| `store_dir_structure.logs.layer3_decay.root` | Layer3 decay log 目录名 |
| `store_dir_structure.restored.root` | restored 子树目录名 |
| `store_dir_structure.statistics.root` | statistics 子树目录名 |
| `store_dir_structure.statistics.graphs` | statistics graphs 目录名 |
| `store_dir_structure.statistics.landmark_scores` | landmark scores 目录名 |

## 其他字段

| 字段 | 含义 |
| --- | --- |
| `nprl_llm_max` | core 逻辑使用的正整数限制值 |
| `store_dir_structure.logs.layer1_write._note` | Layer1 log 结构的人类备注 |
| `empty_conversation_marker_suffix` | 空会话 marker 文件后缀 |

## 修改建议

安装前重点填写：

```text
memory_worker_agentId / memory_worker_harness / production_agents
code_dir / store_dir / archive_dir
timezone / use_embedding / embedding_model / embedding_api_url
daily_write_cron_time / weekly_decay_cron_day / weekly_decay_cron_time
```

默认不要改：

```text
schema_version / active_schema_version / archive_schema_version
cron marker / window.* / layer1_write.* / layer3_decay.*
archive_dir_structure.* / store_dir_structure.*
```
