# 维护者指南

[English](MAINTAINER_GUIDE.md) | 简体中文

CoRAgent 使用 Pi 原生 Harness。Host 绑定工作区、认证输入和持久调度；Python Research Memory 保存原始要求、问题 Node、不可变 Result 与关系。`runtime-bridge` 只传输命令，CoRAgent Web 只读同一查询协议。当前职责边界见[架构](ARCHITECTURE.zh-CN.md)。

## 开发环境

安装固定 Pi 源码，通过 `python3 tools/test/runner.py prepare` 安装独立测试环境。
测试使用 `tools/test/environment.lock.txt`，默认位于 `/home/iaw/project/TSPi/local_debug`，
可用 `CORAGENT_TEST_ENV_ROOT` 设置。根目录的 `environment.lock.txt` 仅用于最小 Host，
不含科学依赖或 pytest。修改包布局前运行：

```bash
python3 tools/test/runner.py list
python3 tools/test/runner.py fast -- -q
npm run lint:public
```

完整 Python 套件使用 `python3 tools/test/runner.py source -- -q`。原生 lane 覆盖 Harness
Host、Pi 原生 client、history 隔离与导入、Monitor 投递、CoRAgent Link 以及固定 Pi 的
extension/provider 边界。运行时必须使用与
`config/pi-source.json` commit 一致的准备好 checkout：

```bash
export CORAGENT_TEST_PI_RUNTIME_ROOT=/path/to/prepared/pi
npm run test:native-pi
```

Native Pi Harness 不需要 tmux，也是唯一支持的运行时。不提供后端选择开关。不要用未固定或被修改的 Pi checkout 迁就测试。远端 smoke 和真实模型评测是显式 opt-in lane，需要外部
配置，不属于默认测试套件。

权威测试清单是 `tools/test/manifest.toml`，由 `tools/test/runner.py` 调度。
Python 测试按 `tests/unit/`、`tests/contract/` 和 `tests/integration/` 分组；Node
测试位于 `tests/node/`；共享 fixture 位于 `tests/support/`。外部探针和真实场景位于
`tools/test/probes/` 与 `tools/test/scenarios/`，不能加入默认 Python 测试套件。

## 研究记忆与执行边界

`workspace_manifest.json` 使用 `research_workspace/2`。唯一命名空间是 `research_agent.research`，没有旧 state 或全局 progress 双协议。原始消息、Node 内容修订和运行事实来源分开；Node 目录保持稳定，多次尝试保留历史，不可变 Result 固定依据。

Agent 使用 research_read / research_search / research_create / research_update / research_result。创建只要求 goal，记事只要求 node_id 与 note，发布只要求 node_id 与 conclusion。身份、读取依据、修订号和事务由适配层提供。后台 Job 不修改 Node 内容版本。显式关系单次存储，反向查询自动生成；实际 uses 需要确证输入，搜索不是采用证据。

Job Runtime 拥有执行回执，Artifact Store 拥有文件和来源。Monitor next_run 只依赖事件及投递身份，不读取 Memory sequence，也不要求 checkpoint。邮件去重属于发送回执，Memory 失败不能触发重发。新旧工作区不迁移或混写。

## 研究视图修复

先检查工作区，再按诊断重建可派生视图：

```bash
"$CORAGENT_PYTHON" apps/agent-cli/workspace.py doctor --root /absolute/workspace
"$CORAGENT_PYTHON" apps/agent-cli/workspace.py rebuild --root /absolute/workspace
"$CORAGENT_PYTHON" apps/agent-cli/workspace.py doctor --root /absolute/workspace
```

重建以不可变记录和结果为依据，恢复 Node/map 索引、搜索索引与可读视图；不生成科学结果、不修改执行或邮件回执，也不迁移旧格式工作区。原始记录缺失或不一致需要修复真实来源，不能用重建伪造。研究更新通过公开工具进行；CLI 不接受旧 expected-version / observed-sequence 全局进度参数。

## 工具合同维护

科学命令构造器和解析器位于 `domains/chemical/skills/<skill>/scripts/`，共享 helper
位于 `domains/chemical/skills/_shared/`。`backend/src/research_agent/jobs/` 负责通用本地和远端执行，
`backend/src/research_agent/application/` 记录 Job 事实并将收集产物登记到 Artifact Store；公开命令字段由
`contracts/commands/` 定义，生成的 Python 与 Node 目录在构建时核验。每个 Artifact 必须有
内容摘要和经过核实的位置。记录 scheduler、Job 身份、命令及收集结果时必须保留先前证据。

独立分析由 Skill 脚本通过通用 Job 执行。注册验证器和验收 profile 在 `domains/chemical/execution.json`
中声明，`backend/src/research_agent/application/validators.py` 验证并暂存声明的验证器和输入。
Python 独立核验执行目录；Pi 按 `package.json.pi.skills` 发现产品与领域 Skill。
修改资源后使用 `scripts/update_resources.py` 更新摘要，再用 `--check` 检查。
默认发现英文 `SKILL.md`，中文入口为对照资料，须同步维护；详见 [Skill 与执行目录](EXTENSIONS.zh-CN.md)。
新增算法必须声明适用条件、反例、可重放候选，并在确定性输出语义变化时提升版本。
不要加入科学 successor routing。

Job 状态与恢复由执行运行时管理；派发意图、执行观察和收集证据必须遵守
工作区事务边界，同时保持查看、收集和取消能力。应测试 Harness client、Pi 资源与科学执行合同、Monitor
重试与回执、wheel 安装、研究快照和检索的 Web 展示 和源码篡改拒绝。当前证据以稳定的运维文档、
源码测试和组件测试为准，过时方案和一次性验收报告保留在 Git 历史中，不放入当前文档目录。

## 文档归属

- `docs/ARCHITECTURE.zh-CN.md`：运行时和科学边界。
- `docs/INSTALLATION.zh-CN.md`：安装、服务、升级和恢复。
- `docs/TERMINAL.zh-CN.md`：Pi 原生 TUI、Host、Phone 与 Monitor 使用。
- `skills/` and `domains/chemical/skills/`：面向用户的科学流程和参考资料。
- `contracts/coragent-web/`：研究上下文、Node、Result 与记录响应的浏览器传输合同。

CoRHub 文档和移动发布工具由独立的 `corhub` 仓库维护。CoRAgent 拥有小型认证 Host
bridge 和可选 browser gateway；不得新增第二个 Pi 渲染器、Phone broker 或 alternate
session owner。

## 合同变更矩阵

| 变更 | 必须同步 |
|---|---|
| CoRAgent Host 协议或服务 | `apps/agent/`、启动器测试、CoRHub 客户端、架构文档 |
| 工作区 schema | Research Memory 合同、bootstrap、验证测试、工作区参考 |
| 科学软件 | Skill 脚本/解析器、环境配置、对应 Skill 参考、测试 |
| 科学分析 | 脚本、适用时的验证器/profile manifest、输入输出验证、科学反例、扩展资源摘要 |
| Job 执行与恢复 | 派发与回执事务、原生工具、重启和协调测试 |
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
