# 安装指南
本文档只说明 MemoquasarEterna 的安装主流程。`OverallConfig.json` 全字段说明见：`docs/A2_overall-config-reference.md`

## 顶层入口
- 安装：`Installation/INSTALL.py`
- 卸载：`Installation/UNINSTALL.py`
- 刷新：`Installation/REFRESH.py`

## 标准安装顺序
1. 从 GitHub clone 仓库到本地，作为 `{code_dir}`
2. 生成并修改本地 `Config.json`
3. 运行：
```bash
cd {code_dir}
python Installation/INSTALL.py
```
4. 如果 `memory_worker_harness` 或某个 `production_agents[*].harness` 为 `openclaw`：
   - 根据交互提示补全 prerequisites 所需信息
   - 将 `Installation/example-openclaw.json` merge 到你的 OpenClaw 配置中
   - 重启 OpenClaw gateway
   - 开一个新 session，使新安装的 plugin-shipped skill 稳定生效

## 配置文件生成
仓库跟踪的是模板文件：
- `OverallConfig-template.json`
- `Adapters/openclaw/OpenclawConfig-template.json`

本地实际运行读取的是：
- `OverallConfig.json`
- `Adapters/openclaw/OpenclawConfig.json`

`Installation/INSTALL.py` 会在本地配置缺失时，从对应模板复制生成 `Config.json`。生成后请只修改本地 `Config.json`，不要把本机私有配置提交进 git。

如果本地 `Config.json.schema_version` 与当前模板中的 `schema_version` 不一致，安装会在最前置的 config bootstrap 步骤失败。请先迁移本地配置，再重新安装。

## 安装前必须明确填写的字段
至少应填写：
- `memory_worker_agentId`
- `memory_worker_harness`
- `production_agents`
- `code_dir`
- `store_dir`
- `archive_dir`

建议安装前一并确认：
- `daily_write_cron_time`
- `weekly_decay_cron_day`
- `weekly_decay_cron_time`
- `timezone`
- `use_embedding`
- `embedding_model`
- `embedding_api_url`

其余字段请勿随意修改；如需调整，请先查阅：`docs/A2_overall-config-reference.md`

## 模型与运行环境说明
本产品的任务成功率会显著受到所用 LLM 能力影响，尤其是：
- 上下文窗口大小
- 长文本稳定性
- 工具调用服从性

在能力不足的模型上，任务失败率可能明显升高。不过，这类失败通常表现为：
- 任务未完成
- 输出不符合预期
- 需要重跑

而不会导致本地文件被破坏性改写；当前已知的最高风险通常是任务本身失败，而不是本地数据结构被破坏。

本机测试主要使用：
- MiniMax M2.7
- 上下文窗口 200k

在该配置下，整体表现稳定，任务成功率约为 95% 或更高。

如果您使用能力弱于这一配置水平的模型，则不保证任务成功率。必要时，请自行调整 `OverallConfig.layer1_write` 中的上下文预算相关参数，以适配您的 LLM。

## `INSTALL.py` 会做什么
顶层安装当前顺序为：
1. Config bootstrap
2. Harness config bootstrap
3. Core prerequisites
4. Harness memory worker prerequisites
5. Harness production agent prerequisites
6. Core install
7. Harness memory worker install
8. Harness production agent install

### Core prerequisites
至少检查：
- `OverallConfig.json` 基础合法性
- `memory_worker_agentId` 不出现在 `production_agents`
- cron 时间格式
- `code_dir` 与真实仓库路径是否一致
- Python / `crontab` 是否可用
- `use_embedding=true` 时 embedding endpoint 是否可用

### Core install
至少包括：
- 创建 `store_dir` 目录结构（若目录不存在）
- 创建 `archive_dir` 目录结构（若目录不存在）
- 安装 Layer1 / Layer3 auto cron

## OpenClaw 额外步骤
当 `memory_worker_harness` 或某个 `production_agents[*].harness` 为 `openclaw` 时：

### 1. OpenClaw 根目录检查
默认检查：
```text
~/.openclaw/
```
若不存在，会要求你输入真实 OpenClaw 根目录，并据此修正 `OpenclawConfig.json` 中相关路径模板。

### 2. `key_template` 校验
会校验：`sessions_registry_maintenance.key_template`
它必须：
- 包含 `{agentId}`
- 渲染后能在真实 `sessions.json` 中命中一个顶层 key

如果你不知道该怎么填，请去看对应 `sessions.json` 中真实存在的顶层 key。常见形式例如：
```text
agent:{agentId}:main
agent:{agentId}:telegram:direct:1234567890
```

### 3. OpenClaw 配置 merge
安装器不会自动改写你的主 OpenClaw 配置，只会生成：
```text
Installation/example-openclaw.json
```
你需要手动 merge，然后重启 OpenClaw gateway。

当前版本 merge 的重点是：
- 启用 MemoquasarEterna 的 OpenClaw read plugin
- 为相关 agent 追加 recall 工具的 allow 项

当前版本不会把 MemoquasarEterna 配置成 OpenClaw 的 active memory backend，因此不需要把 `plugins.slots.memory` 指向 MemoquasarEterna。

## snapshot 机制
每次成功的顶层 install 都会写入：
```text
Installation/.install_logs/
```
例如：
```text
install-2026-04-22T21-43-10+01:00.json
refresh-2026-04-23T09-10-42+01:00.json
```
默认只保留最近 3 份 snapshot。`UNINSTALL.py` 与 `REFRESH.py` 会优先使用这些 snapshot。

## 卸载与刷新
### 卸载
```bash
cd {code_dir}
python Installation/UNINSTALL.py
```
如果存在最新 snapshot，卸载会优先依据 snapshot 中记录的 harness、cron marker、plugin/workspace 路径等事实执行。

### 刷新
```bash
cd {code_dir}
python Installation/REFRESH.py
```
当前 refresh 的含义是：
1. 优先依据最新 snapshot 做 uninstall
2. 如有必要，迁移旧的 `store_dir` / `archive_dir`
3. 按当前 config 重新 install

## 常见问题
### Config bootstrap 失败
通常意味着：
- 本地 `Config.json` 缺失，但当前是 `--dry-run`
- `Config-template.json` 缺失
- 本地 `Config.json.schema_version` 与当前模板不一致

非 dry-run 安装会自动从模板生成缺失的本地配置；schema 不一致时需先手动迁移。

### `code_dir` 被自动修正
说明 `OverallConfig.json.code_dir` 与当前真实仓库路径不一致；core prerequisites 已自动修正。

### `key_template` 校验失败
通常意味着：
- 没包含 `{agentId}`
- 渲染后的 key 不在目标 `sessions.json` 中
- 看错了 `sessions.json`

### 找不到 OpenClaw 根目录
如果 `~/.openclaw/` 不存在，按提示输入真实 OpenClaw 根目录即可。

### refresh 无法自动迁移旧目录
如果新的 `store_dir` 或 `archive_dir` 已存在，迁移会被中止，以避免自动混合旧数据与新数据。请先手动整理目录，再重新运行 refresh。
