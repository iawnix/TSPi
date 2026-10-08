# 维护者指南

[English](MAINTAINER_GUIDE.md) | 简体中文

TSPi 是带安装级 Host 和 Pi 原生 client 启动器的 Pi package。Pi Harness worker 拥有
会话和 turn，Host 负责路由与回执，Python Research State 拥有规范科学状态。Node
侧只提供 Research State transport bridge 和 port，不再包含另一套 Research State filesystem boundary 实现；可选的
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
export TSPI_TEST_PI_RUNTIME_ROOT=/path/to/prepared/pi
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

规范身份文件是 `workspace_manifest.json`。Research workspace 的科学状态位于
`research_map/context.json`，生命周期位于 `lifecycle/liveness.json`，Research State 元数据投影位于
`memory/index.json`。规范 JSON 记录包括 phase、claim、claim relation、node、finding、gate、
requirement、Attempt、Artifact、focus 和 revision，由 Research State 合同及 ChangeSet 校验；
`research.map` 提供客户端投影。Job 输入、日志和回执位于 `runs/jobs/<job_id>/`，已登记
payload 位于 `artifacts/`。已废弃的 `workspace.json`、`research_map.json` 和
`transactions.jsonl` 不是运行时权威。

验证必须是确定性的并绑定 revision。Gate 评估声明的 map criteria 与 evidence ref；
Root Agent 通过 ResearchMap ChangeSet 记录 Claim 或 Node 的解释。不支持的旧文件会在
bootstrap 时明确拒绝。

## 工具合同维护

科学命令构造器和解析器位于 `extensions/chemical/skills/<skill>/scripts/`，共享 helper
位于 `extensions/chemical/skills/_shared/`。`packages/job-runtime/` 负责通用本地和远端执行，
`packages/tspi-runtime/` 将 Job 回执和收集产物接入 Research State；公开命令字段由
`packages/tspi-runtime/tspi_runtime/command_catalog.json` 定义。每个 Artifact 必须有
内容摘要和经过核实的位置。记录 scheduler、Job 身份、命令及收集结果时必须保留先前证据。

独立分析由 Skill 脚本通过通用 Job 执行。注册验证器和验收 profile 在 extension manifest
中声明，`packages/tspi-runtime/tspi_runtime/validators.py` 验证并暂存声明的验证器和输入。
扩展 manifest 合同位于 `contracts/tspi-extension/1/`。Provider 元数据发现仍受支持，但不
负责派发科学执行。新增算法必须声明有界输入、适用条件、反例、
可重放候选，并在确定性输出语义变化时提升版本。不要加入科学 successor routing。

Node 状态与依赖准入由 Research State 管理；派发意图、执行观察和收集证据必须遵守
工作区事务边界，同时保持查看、收集和取消能力。应测试 Harness client、server extension 合同、Monitor
重试与回执、wheel 安装、直接渲染 ResearchMap 和源码篡改拒绝。当前证据以稳定的运维文档、
源码测试和组件测试为准，不把一次性验收报告提交到仓库。

## 文档归属

- `docs/ARCHITECTURE.zh-CN.md`：运行时和科学边界。
- `docs/INSTALLATION.zh-CN.md`：安装、服务、升级和恢复。
- `docs/TERMINAL.zh-CN.md`：Pi 原生 TUI、Host、Phone 与 Monitor 使用。
- `extensions/*/skills/`：面向用户的科学流程和参考资料。
- `contracts/ts-web/`：规范 ResearchMap 响应的浏览器传输合同。

TS Phone 文档和移动发布工具由独立的 `ts-phone` 仓库维护。TSPi 拥有小型认证 Host
bridge 和可选 browser gateway；不得新增第二个 Pi 渲染器、Phone broker 或 alternate
session owner。

## 合同变更矩阵

| 变更 | 必须同步 |
|---|---|
| TSPi Host 协议或服务 | `apps/app-server/`、启动器测试、TS Phone 客户端、架构文档 |
| 工作区 schema | Research State 合同、bootstrap、验证测试、工作区参考 |
| 科学软件 | Skill 脚本/解析器、环境配置、对应 Skill 参考、测试 |
| 科学分析 | 脚本、适用时的验证器/profile manifest、输入输出验证、科学反例、扩展资源摘要 |
| Node 与 Job 准入 | Research State 准入/依赖、派发与回执事务、原生工具、重启和协调测试 |
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
