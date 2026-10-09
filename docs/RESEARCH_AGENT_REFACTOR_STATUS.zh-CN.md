# ResearchAgent 重构实施记录

状态：服务端重构及本地确定性验收已完成，包括实际安装产物的真实 Pi Worker。真实 Phone、真实模型、真实远程计算及生产切换未验证。未发布、部署或迁移生产数据。

## 已实施的边界

研究对象、检查证据、统一受管 Python 入口与当前判断修订见[研究证据架构](RESEARCH_EVIDENCE_ARCHITECTURE.zh-CN.md)。Memory 保持通用，不将科学验证通过作为发布结论或继续研究的前提。

- Pi SDK、Server、Durable 和原生终端保留；Node 适配集中到 `apps/agent/`，私有 Pi 源码入口集中在 `pi/source.mjs`。
- Python 合并为 `backend/src/research_agent/`，分别管理 research、jobs、artifacts、application、foundation 和 bootstrap。
- 产品 Skills 位于 `skills/`，领域 Skills 与科学声明位于 `domains/chemical/`。Pi 负责 Skill 加载，Python 独立解析科学执行目录。
- Link 合同位于 `packages/link/`，Relay 位于 `services/relay/`。产品协议更名，不提供旧标识兼容接口；真实 Phone 待独立更新及联调。
- 根 `package.json.version` 是产品版本源。`tools/version.py set <version>` 同步关联声明，`check` 只检查；本次保留 `0.18.0`，不代表已发布。
- `config/source-layout.json` 声明发布目录边界，`tools/layout.py` 生成 npm 清单；`scripts/update_resources.py` 生成资源摘要。生成文件不能独立维护。

## Skill 与计算平台

绑定链为 Skill 指导 → executor id/version → backend 软件能力 → 所选 environment 的 `job.toml` binding → 固定准备请求 → Job platform。Skill 不绑定特定机器；执行资源校验不依赖 Pi Skill 注册表。具体约束与最低验收见[重构方案第 8.7 节](RESEARCH_AGENT_REFACTOR_PLAN.zh-CN.md#87-skill科学执行入口与计算平台的绑定)。

以 xTB 为例：`domains/chemical/skills/xtb/SKILL.md` 提供使用方法；`domains/chemical/execution.json` 的 `chemical.xtb@1` 指定脚本、输入输出、资源摘要和 `backend=xtb`；安装级 `etc/job.toml` 的 `environments.local.backends.xtb` 或 `environments.remote.backends.xtb` 指定实际程序、解释器、激活脚本及提交资源。选中的目标 `kind` 决定本地进程或 SSH/调度器实现。配置示例见 `config/job.example.toml`。

`application/execution_catalog.py` 负责声明和资源身份，`application/execution_environment.py` 负责解释器与环境验证，Job 层负责执行生命周期。当前目录含 12 个 executor 和 4 个 validator。存在某个 Skill 不等于安装了求解器；平台可达也不等于科学软件及其依赖已就绪。准备后的平台、命令和环境不能在提交时任意替换。不新增 Skill×机器映射表。

## Pi 与合同边界

- 继续固定 Pi **1.0.4**、commit `7c10bd4337495ee613f2224843ecdf349b80d1df` 和已有补丁；没有声称升级到 1.1.0。
- 模型循环、流式响应、工具结果回传、持久化恢复由真实 Pi Server/Durable 执行。普通测试的模型响应来自本机确定性 provider，不代表真实模型验收。
- `read/write/edit/bash` 直接使用 Durable 工具；`grep/find/ls` 使用 Pi 工具及最小 Durable 适配。安装时要求 `rg` 和 `fd`/`fdfind`。不增加 PowerShell 工具。
- Pi 原生加载 Skills，产品常驻原则通过显式 prompt section 注入；科学执行目录独立于 Skill 发现。未宣称覆盖普通 Pi CLI 的全部插件、MCP 或其他未经验证的能力。
- 19 个业务命令的请求和返回合同统一生成 Python/TypeScript 定义，可信工作区、会话和操作身份来自适配层。
- 新协议为 `research-agent-host/2`、`research-agent-link.v1`，凭据前缀为 `rah_`、`rad_`。旧协议及旧前缀明确拒绝；Phone 按交接文档后续修改。
- 基线已经只支持 research 工作区，本次保持此行为。原方案中的 light/research 双模式验收已更正，不增加未授权的新模式。

## 验证状态

完整确定性验收 `1009075936-a060ef` 的 static、fast、node-fast、integration、native-pi、package、source、system-services 八项均通过，清理通过。Python fast 为 344 例，integration 为 249 例，独立 wheel source 为 593 例；真实 systemd 故障清理为 3 例，均无失败或跳过。源码真实 Worker 已覆盖七工具以及 Job → Monitor next_run → 重启 → 不可变 Result 链路。

安装验收 `1009080911-22f42c` 已通过实际完整包安装、外部 cwd 的 CLI、安装后真实 Pi Worker、七工具及科研链路、安装自带卸载器和根目录删除。两项 Worker 测试均通过，无跳过；清理通过。驱动显式验证产品和 Pi 来自安装根，Python 五个业务模块来自受管 wheel，移除源码 PYTHONPATH。Pi 第三方缓存只在安装根离线复用，并由安装产物自带准备器验证 pin/补丁和绑定，不复制源码来修补产品包。

发布候选始终按实际归档摘要验收，安装验收记录包含 `artifact_sha256`；最终文档冻结后构建的候选也必须重新通过同一入口，不能用早期归档替代。每次运行的状态与清理结果由私有测试 registry 记录。真实 Phone、真实模型、真实远程计算和生产切换另列未验证；服务器结构交付不自动授权这些外部操作。

所有测试环境、依赖、缓存、日志和证据只保存在本机 `local_debug/`，不得提交或外发。旧测试根已删除，源码树旧测试结果、依赖和缓存已清理；历史构建归档移入私有测试根。日常测试使用 `python3 tools/test/runner.py`；服务清理是每轮成功条件的一部分。

## 日常修改与交付

- 局部修改先运行 `python3 tools/test/runner.py check --scope pi,tools` 等对应范围；共享合同、安装或测试设施修改执行 `verify`。
- `verify` 统一运行八项本地确定性套件；`source` 验证独立 wheel，`release --artifact <归档绝对路径>` 验证完整安装字节。未准备依赖时先运行 `prepare`，测试阶段不联网补装。
- 版本只通过 `python3 tools/version.py set <version>` 更新，构建执行 check。当前保留 0.18.0；本地脏工作区候选显式使用 `--allow-dirty`，不视为正式发行。
- 生产安装切换需另行指定安装根、release、服务及数据恢复策略。旧协议、旧工作区记录和旧令牌不增加兼容读取器；Phone 更新后需重新配对。
