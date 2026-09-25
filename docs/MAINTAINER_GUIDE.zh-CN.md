# 维护者指南

[English](MAINTAINER_GUIDE.md) | 简体中文

TSPi 是带安装级 Host 和 Pi 原生 client 启动器的 Pi package。Pi Harness worker 拥有
会话和 turn，Host 负责路由与回执，Python Research Kernel 拥有规范科学状态，可选的
TS Web 只读取工作区。

## 开发环境

安装 `environment.yml` 描述的科学环境和固定 Pi 源码。修改包布局前运行：

```bash
python3 tools/test/runner.py list
python3 tools/test/runner.py fast -- -q
npm run lint:public
```

完整 Python 套件使用 `python3 tools/test/runner.py source -- -q`。原生 lane 覆盖 Harness
Host、Pi 原生 client、history 隔离与导入、Monitor 投递、TSPi Link 以及固定 Pi 的
extension/provider 边界。运行时必须使用与
`config/pi-source.json` commit 一致的准备好 checkout：

```bash
export TSPI_PI_SOURCE=/path/to/prepared/pi
npm run test:native-pi
```

Native Pi Harness 不需要 tmux，也是唯一支持的运行时。`TSPI_HOST_BACKEND=ordinary` 与
`TSPI_TMUX` 会被拒绝。不要用未固定或被修改的 Pi checkout 迁就测试。远端 smoke 和真实模型评测是显式 opt-in lane，需要外部
配置，不属于默认测试套件。

权威测试清单是 `tools/test/manifest.toml`，由 `tools/test/runner.py` 调度。
Python 测试按 `tests/unit/`、`tests/contract/` 和 `tests/integration/` 分组；Node
测试位于 `tests/node/`；共享 fixture 位于 `tests/support/`。外部探针和真实场景位于
`tools/test/probes/` 与 `tools/test/scenarios/`，不能加入默认 Python 测试套件。

## 科学模型与验证规则

规范文件只有 `workspace.json`、`research_map.json` 与 `transactions.jsonl`。
`ResearchMap` 直接拥有 phase、claim、claim relation、node、typed finding、gate、focus
和 revision；Node 的执行记录位于 `nodes/<node_id>/`，不是另一套科学 registry。

验证必须是确定性的并绑定 revision。Gate 评估声明的 map criteria 与 evidence ref；
Root Agent 通过 ResearchMap ChangeSet 记录 Claim 或 Node 的解释。不支持的旧文件会在
bootstrap 时明确拒绝。

## 工具合同维护

后端 adapter 位于 `packages/ts-agent-kernel/ts_agent/backends/`，只能解析自己的格式。
每个 artifact 都必须有 digest 和安全的工作区相对路径。远程作业记录 scheduler、job
ID、命令和收集结果，不覆盖已有证据。

独立分析使用 `analysis/catalog.py` 的闭合 ID/version registry 和
`analysis/engine.py` 的 handler dispatch。新增算法必须声明有界输入、适用条件、反例、
可重放候选，并在确定性输出语义变化时提升版本。不要加入科学 successor routing。

Node 暂停/恢复回执属于操作状态；提交和分析边界必须保留共享工作区锁，同时保持查看、
收集和取消能力。应测试 Harness client、server extension 合同、Monitor
重试与回执、wheel 安装、直接渲染 ResearchMap 和源码篡改拒绝。当前证据以稳定的运维文档、
源码测试和组件测试为准，不把一次性验收报告提交到仓库。

## 文档归属

- `docs/ARCHITECTURE.zh-CN.md`：运行时和科学边界。
- `docs/INSTALLATION.zh-CN.md`：安装、服务、升级和恢复。
- `docs/TERMINAL.zh-CN.md`：Pi 原生 TUI、Host、Phone 与 Monitor 使用。
- `skills/`：面向用户的科学流程和参考资料。
- `contracts/ts-web/`：规范 ResearchMap 响应的浏览器传输合同。

TS Phone 文档和移动发布工具由独立的 `ts-phone` 仓库维护。TSPi 拥有小型认证 Host
bridge 和可选 browser gateway；不得新增第二个 Pi 渲染器、Phone broker 或 alternate
session owner。

## 合同变更矩阵

| 变更 | 必须同步 |
|---|---|
| TSPi Host 协议或服务 | `apps/app-server/`、启动器测试、TS Phone 客户端、架构文档 |
| 工作区 schema | Kernel 合同、bootstrap、验证测试、工作区参考 |
| 科学后端 | parser、能力 registry、对应 Skill、测试 |
| 科学分析 | registry/handler、重放验证、反例、报告/Web transport、wheel inventory |
| Node 派发 | 操作回执链、提交 guard、原生/extension 工具、重启和暂停测试 |
| 包清单 | `package.json`、`scripts/package_inventory.py`、布局测试 |
| 安装或 service 路径 | installer、卸载逻辑、安装文档 |

## 发布与回滚

1. 运行快速、完整 Python 和原生 Harness/Host lane。
2. 使用 `npm run release:agent` 构建并验证 Agent release。
3. 按发布计划构建可选 Web component。
4. 使用 `npm run release:build` 构建 suite 并检查 manifest。
5. 在新的私有目录安装并启动一个安装级 Host。

package manifest、archive digest、Agent component 和 Pi source commit 必须一致。不要
发布 dirty source，也不要修改已 content-addressed 的 release。回滚只切换已验证的
release，不删除 workspace 科学记录。
