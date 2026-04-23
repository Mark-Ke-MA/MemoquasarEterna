# MemoquasarEterna

**MemoquasarEterna**（记忆的存续）是一套面向多 agent 场景的本地记忆系统。

**核心特点：**

- 保留并总结每日与各 agent 的聊天记录（而且……不一定只是 agent）
- 归档长期记忆，并按情绪强度逐步衰减（短期记忆看事实，长期记忆看感受）
- 只在真正必要时调用 LLM，尽量把工作交给可验证的代码逻辑
- 自动计算上下文预算并切分聊天记录，避免“信息轰炸 / 小作文”导致 agent 死机
- 只在需要时读取；既不会乱污染日常使用时的上下文，又能让 agent 有“翻旧账”找原话的能力

## 当前支持范围与说明

- 当前版本只支持 macOS 与 OpenClaw，并基于本机 OpenClaw 2026.3.24 验证
- 使用本仓库需要本地 Python 环境
- 本项目的任务成功率受到所用 LLM 能力影响，尤其是上下文窗口、长文本稳定性与工具调用服从性；本机主要基于 MiniMax M2.7（200k context）验证，整体表现稳定
- 本仓库由本人和凯尔希（使用 OpenAI GPT-5.4 与 Claude Sonnet 4.6）协作开发
- 本仓库非产品/科研级正式项目，只是个因本人兴趣而诞生的 toy project。旨在提供思路，不承诺长期维护与运营
- Currently this repository only supports Chinese. An English version may or may not come later

## 二创元素声明

本项目灵感来自《明日方舟》的部分世界观，可视为非官方二次创作；其内容、立场与实现均不代表官方行为

![MemoquasarEterna README Hero Image](docs/assets/readme-hero.jpg)

## 术词与占位符解释

贯穿这个README文章，以下术语/占位符可能会高频出现：
- `store_dir`：  
所有记忆文件、运行日志、分析数据、任务中途产物所在的目录/文件夹。总大小会小幅波动，但长期导数为零
- `archive_dir`：  
所有归档文件所在的目录/文件夹。总大小会缓慢持续增长。这是最值得被备份+看管的核心数据
- memory worker：  
专门执行记忆总结的agent。因为记忆的每日一写/每周一压缩任务，推荐为它使用经济实惠的LLM。本项目虽然对LLM的“聪明程度”有隐形的下限需求，但对上限需求并不高
- L2：  
完整聊天记录原文，严禁agent直接完整读取，除非想让上下文暴毙
- L1：  
从L2中提炼总结出的重要决策、待办、情绪高点（比如您凶了骂了agent的对话）
- L0：  
从L1中原样提取的精炼总结和关键词。主要作为记忆读取时的检索信号存在
- Layer0（Extract）：  
专门负责提取原始聊天记录的代码层，将不同harness的格式统一为本项目的规范格式（L2格式）
- Layer1（Write）：  
专门负责写入日级记忆的代码层。主要过程为 调用Layer0拿到L2 -> 调用LLM拿到L1 -> 从L1提取出L0
- Layer2（Preserve）：  
专门负责将`store_dir`归档进`archive_dir`或反方向重构的代码层
- Layer3（Decay）：  
专门负责进行周度/月度衰减的代码层。主要过程为 调用Layer2做归档备份 -> 调用LLM将7个日级L1合并为1个周级L1 -> 删除日级记忆
- Layer4（Read）：  
专门负责从`store_dir`中检索&读取相关记忆。主要过程为 用query词检索L0（支持本地向量化） -> 去找命中日期的L1 + L2 -> 将最相关的几条信息拼凑成“人话” -> 甩回给请求者（通常是agent）
- LayerX（Score）：  
非生产级代码，更偏数据分析的玩具。可以告诉您与不同agents作出的决策/情绪高点的数量关于时间/日期的函数，或整体决策产出效率/情绪化程度。没什么实质作用，但属于本项目的一个有趣的副产物

## 危险性提示

### 低危风险：Layer3 会对 active `store_dir` 执行必要的清理
默认自动周级 Layer3 衰减任务会对 active `store_dir` 中的部分文件执行 destructive cleanup，但前提是相关内容已先被备份进 `archive_dir`。这是为了防止 active `store_dir` 无限增长，持续占用磁盘空间，并污染 Layer4 的读取与找回准确率，因此属于必要行为。

这类操作本质上仍然是带删除性质的危险操作，因此在此明确告知。但在正常使用条件下，您通常无需担心，也无需额外采取行动。

如果您希望从归档中恢复某天记忆，请阅读：
- `docs/B2_layer2-restore-guide.md`
并使用入口：
- `Core/Layer2_Preserve/ENTRY_LAYER2_restore.py`

### 中危风险：`harness == openclaw` 时会清理 memory worker 的 sessions
当 `harness == openclaw` 时，Layer1 / Layer3 任务开始前会先对 memory worker agent 的 `agent/{memory_worker_agentId}/sessions/` 做清理。这是为了防止任务型 LLM 调用记录无限累积。

这一默认行为成立的前提是：memory worker agent 被设计成后台一次性调用、用后即焚，因此它必须是独立的、非生产级 agent，而且不能被安排任何其他任务。这也是文档中一再强调必须为 memory worker 单独准备专用 agent 的原因。

如果您严格遵守了这一限制条件，则通常无需担心，也无需采取任何行动。反之，如果您把生产 agent 错用为 memory worker，就存在整个对话丢失的风险。

### 高危风险：可选启用生产 agent 原始 sessions 文件衰减
当 `harness == openclaw` 时，系统还提供一项默认关闭的高级功能：将每个生产 agent 已自动归档的原始会话文件，从 `agent/{agentId}/sessions/` 中进一步清除。它的目的，是从项目外部协助控制 OpenClaw 会话内存的无限膨胀。

启用方式：
- 打开 `{code_dir}/Adapters/openclaw/OpenclawConfig.json`
- 将 `sessions_registry_maintenance.session_files_decay` 设置为 `true`

注意：这是一项高危操作，项目默认关闭。只有在您已经充分理解其含义、边界与潜在后果时，才应手动启用；启用决策需自行承担。

---

## 仓库结构

当前仓库根目录采用如下组织：

```text
{code_dir}/
  Core/
  Adapters/
  Installation/
  Maintenance/
  docs/
  OverallConfig.json
  README.md
```

### `Core/`
记忆系统本体。

当前主要承载：

- Layer0–Layer4 与 LayerX 逻辑
- `shared_funcs.py`
- `harness_connector.py`

### `Adapters/`
外部 harness 接入层。

当前主要实现：

- `Adapters/openclaw/`

它负责把 `Core/` 接到具体运行平台，并通过 `CONNECTOR.py` 暴露统一接口。

### `Installation/`
安装生命周期入口。

当前包括：

- `INSTALL.py`
- `UNINSTALL.py`
- `REFRESH.py`
- `Core/`
- `Backfill/`
- `.install_logs/`（运行后生成）

### `Maintenance/`
维护、补跑与人工运维脚本。

### `docs/`
项目文档主入口。

---

## 快速开始

### 1. clone 仓库

```bash
git clone <repo-url> {code_dir}
cd {code_dir}
```

### 2. 修改配置

先编辑：

- `OverallConfig.json`

安装前至少应明确填写：

- `harness`
- `memory_worker_agentId`
- `agentId_list`
- `code_dir`
- `store_dir`
- `archive_dir`

完整字段说明见：

- `docs/A2_overall-config-reference.md`

### 3. 执行安装

```bash
python Installation/INSTALL.py
```

如果 `harness == openclaw`，安装过程中还会执行 harness-specific prerequisites，并在需要时要求您：

- 确认 OpenClaw 根目录
- 补全 `key_template`
- 将 `Installation/example-openclaw.json` merge 到您的 OpenClaw 配置中
- 重启 OpenClaw gateway

---

## 顶层命令

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

`REFRESH.py` 会：

1. 优先依据最新 install snapshot 做 uninstall
2. 在安全条件下迁移旧的 `store_dir` / `archive_dir`
3. 按当前 config 重新 install

---

## install snapshot

每次成功的顶层 install 都会在以下目录写入 snapshot：

```text
Installation/.install_logs/
```

这些 snapshot 会记录：

- 安装上下文
- config 快照
- resolved install facts
- core / harness install 结果

默认只保留最近 3 份。

`UNINSTALL.py` 与 `REFRESH.py` 会优先依据最新 snapshot 回滚，而不是只依赖当前 config。

---

## 文档入口

### 初次阅读建议顺序

1. `docs/A1_installation-guide.md`
2. `docs/A2_overall-config-reference.md`
3. `docs/B1_maintenance-guide.md`
4. `docs/B2_layer2-restore-guide.md`
5. `docs/B3_layerx-landmark-guide.md`
6. `docs/C1_architecture.md`
7. `docs/C2_connector-contract.md`
8. `docs/C3_adapter-openclaw.md`

### 各文档用途

- `docs/A1_installation-guide.md`
  - 安装、卸载、刷新主流程

- `docs/A2_overall-config-reference.md`
  - `OverallConfig.json` 全字段说明

- `docs/B1_maintenance-guide.md`
  - 日常维护入口、常见问题与最常见恢复动作

- `docs/B2_layer2-restore-guide.md`
  - 从 `archive_dir` 恢复某天 / 某周记忆的 restore 说明

- `docs/B3_layerx-landmark-guide.md`
  - LayerX landmark 的含义、作用与 threshold 微调说明

- `docs/C1_architecture.md`
  - 仓库整体架构与分层设计

- `docs/C2_connector-contract.md`
  - connector 固定接口与 contract

- `docs/C3_adapter-openclaw.md`
  - OpenClaw adapter 的结构与职责

---

## 当前主要安装链路

顶层 `INSTALL.py` 当前按以下顺序编排：

1. Core prerequisites
2. Harness prerequisites
3. Core install
4. Harness install

顶层 `UNINSTALL.py` 当前按以下顺序编排：

1. Core uninstall
2. Harness uninstall

这使得：

- 项目级逻辑留在 `Installation/Core/`
- harness-specific 逻辑留在 `Adapters/{harness}/Installation/`
- 顶层入口只负责编排与用户可读输出

---

## 当前主要 harness

### OpenClaw

当前 `openclaw` adapter 已接入以下固定能力：

- `call_llm`
- `prerequisites`
- `install`
- `uninstall`
- `extract`
- `harness_clean`
- `harness_preserve`
- `harness_decay`

对应目录位于：

```text
Adapters/openclaw/
```

更多说明见：

- `Adapters/openclaw/README.md`
- `docs/C3_adapter-openclaw.md`

---

## 开发与维护提示

- 修改安装流程前，优先同步更新：
  - `docs/A1_installation-guide.md`
  - `docs/A2_overall-config-reference.md`
- 修改 connector 固定接口前，优先同步更新：
  - `docs/C2_connector-contract.md`
- 修改 OpenClaw adapter 结构前，优先同步更新：
  - `docs/C3_adapter-openclaw.md`

如需理解整体设计，请先从 `docs/C1_architecture.md` 开始。