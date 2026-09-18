# 维护者指南

[English](MAINTAINER_GUIDE.md) | 简体中文

TSPi 是带原生 App Server 启动器的 Pi package。App Server 拥有会话，Python Research
Kernel 拥有规范科学状态，可选的 TS Web 只读取工作区。

## 开发环境

安装 `environment.yml` 描述的科学环境和固定 Pi 源码。修改包布局前运行：

```bash
python3 tools/test/runner.py list
python3 tools/test/runner.py fast -- -q
npm run lint:public
```

完整 Python 套件使用 `python3 tools/test/runner.py source -- -q`。原生 App Server
测试使用 `npm run test:native-pi`，需要 `TSPI_PI_SOURCE` 指向准备好的 Pi checkout。
远端 smoke 和真实模型评测是显式 opt-in lane，需要外部配置，不属于默认测试套件。

权威测试清单是 `tools/test/manifest.toml`，由 `tools/test/runner.py` 调度。
Python 测试按 `tests/unit/`、`tests/contract/` 和 `tests/integration/` 分组；Node
测试位于 `tests/node/`；共享 fixture 位于 `tests/support/`。外部探针和真实场景位于
`tools/test/probes/` 与 `tools/test/scenarios/`，不能加入默认 Python 测试套件。

## 科学模型与验证规则

规范文件包括 `workspace.json`、`research_state.json`、`phases.json`、`claims.json`、
`claim_relations.json`、`research_nodes.json`、`observations.json`、`proof_specs.json`、
`validation_results.json`、`findings.json` 和 `acceptances/`。显式 Gate 工作区可以额外
使用 `gate_specs.json` 与 `gate_results.json`，旧工作区没有这两个文件仍然有效。

验证必须是确定性的并绑定 revision。谓词只能读取声明的输入；被接受的 Claim 必须
引用已记录的 Observation 或 Finding。不支持的文件应保留，并在 bootstrap 时返回明确
错误。

## 工具合同维护

后端 adapter 位于 `packages/ts-agent-kernel/ts_agent/backends/`，只能解析自己的格式。
每个 artifact 都必须有 digest 和安全的工作区相对路径。远程作业记录 scheduler、job
ID、命令和收集结果，不覆盖已有证据。

独立分析使用 `analysis/catalog.py` 的闭合 ID/version registry 和
`analysis/engine.py` 的 handler dispatch。新增算法必须声明有界输入、适用条件、反例、
可重放候选，并在确定性输出语义变化时提升版本。不要加入科学 successor routing。

Node 暂停/恢复回执属于操作状态；提交和分析边界必须保留共享工作区锁，同时保持查看、
收集和取消能力。应测试原生 App Server、extension 入口、wheel 安装、projection 和
源码篡改拒绝。当前证据以稳定的运维文档、源码测试和组件测试为准，不把一次性验收
报告提交到仓库。

## 文档归属

- `docs/ARCHITECTURE.zh-CN.md`：运行时和科学边界。
- `docs/INSTALLATION.zh-CN.md`：安装、服务、升级和恢复。
- `docs/TERMINAL.zh-CN.md`：原生 TUI/App Server 使用。
- `skills/`：面向用户的科学流程和参考资料。
- `contracts/ts-web/`：可选浏览器投影合同。

TS Phone 文档和移动发布工具由独立的 `ts-phone` 仓库维护。TSPi 不应重新引入 Phone
server、bridge、REST/SSE 兼容层或终端 Host。

## 合同变更矩阵

| 变更 | 必须同步 |
|---|---|
| App Server 协议或服务 | `apps/app-server/`、启动器测试、TS Phone 客户端、架构文档 |
| 工作区 schema | Kernel 合同、bootstrap、验证测试、工作区参考 |
| 科学后端 | parser、能力 registry、对应 Skill、测试 |
| 科学分析 | registry/handler、重放验证、反例、报告/Web transport、wheel inventory |
| Node 派发 | 操作回执链、提交 guard、原生/extension 工具、重启和暂停测试 |
| 包清单 | `package.json`、`scripts/package_inventory.py`、布局测试 |
| 安装或 service 路径 | installer、卸载逻辑、安装文档 |

## 发布与回滚

1. 运行快速、完整 Python 和原生 App Server 测试。
2. 使用 `npm run release:agent` 构建并验证 Agent release。
3. 按发布计划构建可选 Web component。
4. 使用 `npm run release:build` 构建 suite 并检查 manifest。
5. 在新的私有目录安装并启动一个安装级 Host。

package manifest、archive digest、Agent component 和 Pi source commit 必须一致。不要
发布 dirty source，也不要修改已 content-addressed 的 release。回滚只切换已验证的
release，不删除 workspace 科学记录。
