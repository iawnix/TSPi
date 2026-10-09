# ResearchAgent 测试环境与测试流程重构方案

日期：2026-10-09。

状态：统一 runner、内容寻址依赖、源码快照、短路径隔离、并行分片、只读依赖挂载、外网隔离、进程与真实 systemd unit 清理、wheel 与完整 package 安装验收入口已实现。Pi 1.0.4、科学 Python、生产 Host 锁定依赖及 Node 环境已在 local_debug 重建。测试设施故障回归、真实服务生命周期和候选 package 安装/卸载已有通过记录；整项目最终源码与最终发行字节的完整验收仍需按本文门禁执行，不能将局部通过当作项目重构完成。真实模型、远程平台和 Phone 联调未获授权或未执行，单独列为未验证。操作说明见 [tools/test/README.md](../tools/test/README.md)。

与[代码重构方案](RESEARCH_AGENT_REFACTOR_PLAN.zh-CN.md)配套。目标是在保持关键行为验证的前提下减少重复安装、重复构建和无关测试，降低状态污染、漏测与偶发失败。测试不能证明没有任何 bug；发布结论必须包含已测范围、未测范围及已知失败。

## 1. 重构前基线与需要解决的问题

删除前的旧测试根目录顶层有 280 个目录、255 个普通文件、1 个符号链接；这是历史盘点，旧环境随后已按用户明确要求整体删除。现有匹配测试文件为 Python unit 29 个、contract 11 个、integration 20 个、Node 29 个；这是文件数，不是测试用例数，也不是通过率。

| 已核对的入口 | 已有基础 | 需要解决的问题 |
| --- | --- | --- |
| `tools/test/runner.py`、`manifest.toml` | 已有 fast/source/native-pi/package/live 等统一入口 | runner 主要负责转发命令，缺少统一运行身份、资源账本、超时与最终清理验证 |
| `scripts/test_source.py` | 独立测试 lock、临时 wheel overlay、检查实际 Python 导入来源 | 每轮重建；结果按 payload 命名可能覆盖；临时 overlay 在失败时也销毁；它仍以源码根为 cwd，不等于完整安装验证 |
| `scripts/test_fast.py` | 快速源码测试 | 保留外部 PYTHONPATH，解释器可回退当前 Python；基础依赖探针要求科学依赖，轻量检查也可能需要整套科学环境 |
| `tests/node/native/test-environment.mjs` | 区分 Pi 源码与临时 fixture | Python 可按目录排序选择旧 kernel 或回退 python3，不能证明运行的是当前构建 |
| `tests/contract/test_test_manifest.py` | 防止 Node 测试遗漏 | 当前强制全部 Node 测试进入 native-pi；纯逻辑测试也要经过固定 Pi 准备与验证 |
| `tests/conftest.py` | 有环境隔离和权限恢复 | autouse fixture 无条件删除 tmp_path，失败现场也会消失；不是只清成功用例 |
| `tests/node/native/worker-research-flow.test.mjs` | 已有本地确定性模型响应驱动真实科研流程 | 可以扩展为关键路径验证基础，不能只靠真实模型随机选择覆盖分支 |
| `.github/workflows/ci.yml` | 已有 Node/Python 并行 job | 环境建立入口不统一；部分 job 使用根 environment.yml；当前没有完整的统一报告与 always 清理审计 |
| remote-smoke suite | manifest 声明了该能力 | paths 为空，而通用 scenario runner 要求一个入口；必须补成真实可执行场景或明确报告 unavailable，不能只在 list 中出现 |

因此保留 pytest、Node test runner、现有 lock 和有效测试，改进统一调度、环境与 fixture；不引入第二个测试框架来搬运相同测试。

## 2. 测试目录与环境生命周期

遵循仓库 AGENTS.md：本机所有测试安装、Python/Node 依赖、测试用 Pi checkout、缓存、构建产物及临时运行目录均在 `/home/iaw/project/TSPi/local_debug` 下。该目录只在本机使用，不提交 GitHub、不随发行物分发、不对外上传。旧根目录 `/home/iaw/debug/tspi-test-env` 不再使用或自动重建，也不创建兼容链接。现有系统软件可从 `/home/iaw/soft` 读取，测试不修改它。

```text
/home/iaw/project/TSPi/local_debug/
  registry/                   # 环境索引、锁、运行租约、旧目录迁移清单
  toolchains/                 # 固定 Python/Node 工具链与检查记录
  deps/
    python/<key>/             # 锁定的 core/science 测试依赖环境
    node/<key>/               # 锁定 Node 依赖及可供运行使用的包布局
    pi/<key>/                 # 上游 commit + 项目 patch 对应的已验证源码
  cache/                      # 下载、conda/pip/npm 缓存；不保存会话数据库
  builds/<key>/               # wheel、release 包及摘要；构建完成后只读
  runs/<short-id>/
    run.json                  # 源码/工具链/选测依据/状态/环境引用
    source/                   # 本轮源码快照，包含被测未提交改动
    install/                  # 本轮安装或 wheel overlay，按需建立
    tmp/                      # 指向 local_debug/t/<短随机名> 的受管链接
    workspaces/               # 各 case 独立 workspace 与 SQLite
    sockets/                  # 指向 local_debug/s/<4字符> 的受管链接
    services.json             # 进程组、unit、端口、远程 Job 等资源账本
    logs/                     # 按 suite/case 分开的 stdout/stderr 与事件
    report/                   # result.json、JUnit/TAP、故障诊断、清理报告
  evidence/<run-id>/          # 结束后的精简证据包
```

环境与状态分开处理：依赖和不可变构建可以复用，workspace、数据库、凭据、运行端口及安装测试的可写状态必须独立。共享环境不允许测试期间 pip/npm 安装、修改 Pi 源码或原地升级。需要修改依赖/源码的测试使用独立副本。

环境 key 包含对应 lock 内容、Python/Node 版本、平台/架构和准备脚本版本；Pi key 还包含上游 commit、patch 集合与依赖锁。构建 key 包含所有影响产物的源码/资源内容、构建参数、工具链及构建脚本，不只使用 Git HEAD。未提交与相关未跟踪文件必须进入快照和摘要，凭据与生成缓存排除。

同一个 key 的准备使用文件锁和临时目录，完成探针后原子发布；失败半成品不能命中缓存。run 持有引用租约，清理器不能删除正在使用的环境。运行报告不覆盖历史，源码在测试期间发生变化时，不把旧快照结果当作新代码通过。

Node 模块解析必须在快照/安装布局中实际验证；把依赖放在根目录之外后，不能假设任意 sibling node_modules 会被自动发现。开发快测可使用受管依赖链接；发行安装验证必须证明 first-party 模块来自安装产物，不能经链接或 loader 回到源码树。

沿用现有独立测试 lock，后续按实际导入图拆成 core 与 science 两个环境规格：core 支持普通逻辑、合同、Host/bridge 检查，science 承担 rdkit/ase/scipy 等场景；需要科学依赖的真实全链路测试仍使用 science，不能为追求轻量而跳过。

## 3. 测试分层：快反馈与真实系统分开

下列时间是 warm cache 下的优化目标，不是当前实测或硬性承诺。先记录 3—5 次基线及慢用例，再确定超时与并发配置。

| 层级/目标 suite | 覆盖内容 | 运行时机 | 初始反馈目标 |
| --- | --- | --- | --- |
| static | 类型、生成物检查、架构依赖、资源/合同清单、相关文档链接 | 每次相关修改；必要项始终运行 | 30 秒—2 分钟 |
| unit-contract | Python/Node 纯逻辑、schema、边界输入；无需真实 Pi 服务 | 编辑阶段按影响选择，提交前全量 | 1—3 分钟 |
| integration | Python bridge、Research/Job/Artifact、Host/Relay、协议与资源生命周期 | 修改对应模块或公共依赖时 | 定向 2—5 分钟 |
| native | 真实固定 Pi Server/Worker/SQLite、真实工具、确定性本地模型响应 | Pi 接入、工具、上下文、会话、Monitor、终端变更必跑 | 核心场景 3—8 分钟 |
| installed | wheel 导入、完整发行安装、外部 cwd 启动、SSH/终端与卸载清理 | 打包/路径/启动/依赖变更；发布前必跑 | 5—15 分钟 |
| resilience | 明确故障点的崩溃、取消、重连、并发、恢复与长运行 | 相关可靠性修改、完整验收和定期 CI | 按场景预算 |
| live / remote | 真实提供方、实际科学程序或远程平台、真实 Phone 联调 | 相关集成变更、发布验收；显式配置的独立通道 | 记录耗时、调用量和外部成本 |

native 的确定性提供方只替代外部模型响应，Pi、工具、文件系统、bridge 和状态存储都实际运行。它验证工程链路，不能证明真实模型兼容或科研结论质量。保留已有 live-eval/live-recovery，并分别记录真实提供方结果；相关发布验收未跑 live 时标记未完成，不能用 deterministic 代替；用户禁止外发的 local_debug 内容不得为了通过验收发送给提供方，外部验证须另有明确授权的数据范围。

科学验证分三层：小型已知输入和解析器 fixture；本地真实执行器小算例；必要时远端/昂贵科学算例。数值比较按方法定义容差和证据，不按模型回答字面匹配。

## 4. 每次修改的标准流程

### 4.1 编辑阶段

1. runner 检查选定工具链、lock、Pi pin/patch、根路径和空闲资源；缺少依赖直接报环境问题，不逐个测试 skip。
2. 生成本轮 ID、源码快照、变更清单与测试计划。修改列表包含指定 base 与当前工作区之间的提交、暂存、未暂存和相关未跟踪文件。
3. 始终执行必要的静态/合同检查；根据影响规则选择 unit/integration/native。首次未知路径、测试公共支持代码或无法判断的动态依赖采用扩大范围策略。
4. 独立测试并行；同一 case 的构建→安装→启动→调用→清理保持顺序。失败时尽早展示失败证据，不用自动重试掩盖首次失败。
5. 收集报告并执行资源清理，确认清理通过后才结束。修复 bug 后重跑失败用例及其受影响套件；代码不变且已通过时不机械重复跑全部。

### 4.2 提交/PR 与发布

- 提交前：全量 static、unit-contract，加受影响 integration/native/installed；报告明确列出未选择的套件。
- PR CI：全量 static、unit-contract、integration 和核心 native；完整安装 smoke 必须存在。打包、依赖、Pi pin、公共合同和测试设施变更扩大到完整 installed/resilience 对应场景。
- 定期完整 CI：全量确定性套件、不同顺序/种子的关键可靠性检查、冷缓存安装。定期运行是 CI 配置目标，不在本次方案中启动任何自动任务。
- 发布前：对最终待发布的同一份产物执行完整 installed 与关键恢复测试；按改动验证真实提供方和科学平台，记录 Phone 的实际联调状态。测试报告绑定产物摘要，不能测试 A 后重建 B 再直接发布。

### 4.3 目标命令接口

统一入口为 `tools/test/runner.py`；旧 test_fast.py、test_source.py 与 bootstrap_dev.py CLI 已删除。以下命令已实现；外部模型/远程通道仍要求另行授权，remote-smoke 尚无真实场景时明确不可用：

```bash
python3 tools/test/runner.py doctor
python3 tools/test/runner.py prepare
python3 tools/test/runner.py plan --changed --base origin/main
python3 tools/test/runner.py check --changed --base origin/main
python3 tools/test/runner.py check --scope pi,tools
python3 tools/test/runner.py verify
python3 tools/test/runner.py release --artifact /absolute/path/to/release.tar.gz
python3 tools/test/runner.py replay --run <run-id> --failed
python3 tools/test/runner.py gc --dry-run
```

`check` 用于日常定向验证；`verify` 为完整确定性验证；`release` 对指定不可变产物运行发布验证并显式报告外部项。`replay` 固定原有快照、工具链、种子和场景；验证修复必须创建新 run，不能混淆“复现旧失败”与“新代码回归通过”。旧 suite 在迁移阶段仍映射到同一调度实现；产品旧命名按主方案切换，不增加另一套长期维护入口。

## 5. 自动选择测试与避免漏测

扩展 `manifest.toml` 表达 suite 的 discovered paths、scope、requires、resource class、timeout、serial group 和外部依赖。通过 glob/标准命名发现测试，仅维护分类规则和例外，不维护每个 Node 文件的手工列表。

将“全部 Node 文件必须属于 native-pi”的合同改为“每个测试文件必须属于一个主 suite；聚合 suite 可以引用它；没有孤儿、重复调度或不存在的入口”。支持精确文件、case、目录和 scope 选择，不以参数是否以 .py 结尾猜测用户意图。

| 修改范围（目标结构） | 最低追加验证 |
| --- | --- |
| `backend/.../research` | research unit/contract、application 跨域集成、一个真实 Worker 科研流程 |
| `jobs` / `artifacts` | 提交/取消/收集、幂等与证据、Job→Monitor→Pi 场景；相关故障注入 |
| `apps/agent/pi` 或基础工具 | 核心 native、七工具、流式/取消/恢复；涉及加载与路径时加 installed |
| `host` / `transport` / `packages/link` / relay | 认证、路由、配对、撤销、重连、背压、并发客户端；加 Host 与真实 Worker 联通 |
| `terminal` | 命令与渲染契约、PTY 集成、resize/退出/重连；必要时人工检查 |
| `skills` / prompts / domain 声明 | 原生资源发现、引用与加载、执行声明校验；影响工具调用策略时加 native 和有预算的 live |
| 构建/安装/lock/Pi patch/公共合同 | 全量相关套件、独立安装与卸载、导入来源及恢复场景 |
| runner/fixtures/环境管理 | 所有受影响 suite，并验证并发、超时、证据保留与服务清理 |
| 纯说明文字 | 链接/格式/相关声明检查；可执行配置、prompt、Skill 文本不视为纯文档 |

选择依据写入 report；依赖图结合显式影响规则，不只依赖静态 import。选测只加速日常反馈，不替代 PR/发布的完整必要检查。

## 6. 并行、缓存和耗时优化

1. 环境按内容 key 复用；只在 lock/工具链变化时准备，安装前探针只做必要检查。构建一次 wheel/release，由多个隔离运行读取，不在每个测试函数重建同一产物。
2. 提取昂贵但不可变的输入 fixture；每个测试创建新可写状态。不要共享运行中的 Host、SQLite 或科研 workspace 来节省启动时间，除非 suite 明确只有一个拥有者且能证明逐 case 复位。
3. 先完成隔离再启用 pytest-xdist（锁定测试依赖）和 Node 文件级并行。runner 管理总 CPU/内存/IO 预算，避免每个子 runner 各自开满核。
4. 初始纯逻辑并行度可按 `min(8, 可用CPU的一半)` 起步，最少 1；真实 Pi/安装任务从 2 个并发开始，以峰值内存与 p95 时长调整。科学库线程由测试子进程配置，避免多个测试各自启动整机 BLAS/OpenMP 线程。
5. 分离 CPU、真实 Pi 进程、安装/磁盘、真实模型/远端四类资源限额；需要同一系统资源的用例加命名锁，不把整个 suite 串行化。
6. 端口优先让服务绑定 0 并回报实际端口，避免“找空闲端口后再绑定”的竞争；Unix socket 用短 run/case ID，并检查平台路径长度。
7. 等待通过 ready 事件、健康探针、进程退出和有截止时间的条件完成，不用固定长 sleep。故障测试等待明确阶段屏障后注入故障，提高重现性。
8. 记录环境准备、构建、case、清理各阶段耗时，按最慢用例和等待原因优化。warm/cold 成绩分开；不缓存一次旧测试成功来冒充新运行的结果。

## 7. 清理服务与保留失败现场

所有测试启动服务必须经过统一 fixture/supervisor，创建时立即登记资源，不能等启动成功才登记。覆盖 Host、Pi coordinator/worker、Python bridge、Monitor、Job supervisor、本地执行器、Relay、SSH proxy 与临时服务 unit。

资源账本记录 run/case 身份、PID 与启动身份、进程组或 cgroup、unit 名、socket/端口和远程 Job ID。优先使用可用的独立 cgroup/测试 scope；否则使用受控进程组并禁止未登记的 detached 子进程。临时 systemd unit 必须使用带 run ID 的独立名称，不接管正常运行的产品服务。

完成/失败/超时/用户中断统一执行：

1. 停止输入与任务投递，保存诊断；通过正常 API 取消/关闭本轮 Job 与服务。
2. 在明确期限内等待退出；仅对已验证属于本轮的残留进程发送 TERM，仍不退出再 KILL。
3. 停止并删除本轮 unit，清除其运行状态；撤销本轮配对，删除 socket/临时注册和资源租约。远程场景核实本轮 Job 终态。
4. 检查账本与实际进程/监听资源，无残留才标记 cleanup=passed。功能通过但清理失败，整轮也不能为 passed。

finally/teardown 负责第一层清理，独立 supervisor 负责子 runner 异常退出。若 supervisor 被 SIGKILL 或机器掉电，不能声称已完成清理；下次 doctor/reaper 根据持久账本与启动身份核实后回收，并标记前次运行 interrupted。PID 可能复用，不能只按 PID 或 `pkill -f pi` 等名称杀进程。

成功用例及时删除大体积可写临时数据。失败用例先保留日志、输入、事件、相关文件和停机后的一致性数据库副本，再清理运行资源；取消 conftest 无条件删除失败 tmp_path 的做法。数据库证据包含必要 WAL 或通过一致性备份生成，不能运行中只复制 sqlite 主文件。证据保留不代表允许服务继续运行。

测试子进程的临时、XDG、Pi agent/server 和包缓存路径显式指向本轮/受管目录，不读取真实用户 Pi 凭据或全局插件。使用框架支持的专用目录参数；不在调度 shell 中复用 HOME/CODEX_HOME 等保留变量作任务路径。离线确定性套件使用固定假凭据与本地提供方，必要时隔离外部网络；live/remote 默认为未授权外发：有凭据不等于可以发送私有测试内容。需要外发时，必须先取得用户对具体数据、目的地和范围的明确授权；日志和证据不得保存令牌。

## 8. 优先补强的缺陷场景

| 关键边界 | 必测故障与不变量 |
| --- | --- |
| Pi 核心循环与七工具 | 增量文本、分段工具参数、工具结果后继续生成、错误与取消；read/write/edit/bash/grep/find/ls 实际副作用/读取结果正确 |
| 输入与恢复 | 同一输入重复提交、已接受但回执丢失、Worker 在持久化前后退出；消费身份保持，不额外创建用户 turn |
| 工具与 shell | 参数错误、权限/文件不存在、输出过大、执行中断；不擅自重放任意 shell 命令；明确无法确认副作用的恢复状态 |
| Research/Job/Artifact | 过期读依据、并发写、重复 Job 请求、收集回执丢失、材料摘要不符；Result 不可变与身份/证据关系成立 |
| 科学入口与计算目标绑定 | 同 executor 多目标、同 backend 多入口、缺失绑定、Python 优先级、资源合并、环境漂移与既有 Job 恢复；平台可达不能冒充软件就绪，不静默切换平台或科学方法；真实远端数据外发须明确授权 |
| Monitor | busy 时延后、多事件批次、重启、通知已发送但确认丢失；不丢事件，不把重复投递变成重复消费 |
| Host/Relay | 多端连接、配对令牌重用、撤销、Host 离线、重连风暴、慢客户端；无越权路由，队列有界 |
| 安装 | 从仓库外 cwd 启动、缺少资源/依赖、只读 release、路径有空格、卸载；无源码树回退或用户环境碰巧补齐 |
| 测试设施自身 | case 超时、runner 被杀、进程派生、并发 run、锁持有者崩溃、磁盘不足；缓存不半成品命中、服务残留被检测 |

优先用最小回归用例复现真实 bug，在产生缺陷的最低边界修复并验证，必要时追加一条跨边界场景。不为简单移动文件写镜像实现测试，不用海量全量文本快照约束无关格式。公共 schema 和发布接口可保留有意义的合同断言；把只检查源码字符串/目录名称的脆弱断言改成运行行为或真实导入验证。

可靠性测试在“已持久化、未回执”等明确阶段注入故障，记录种子与事件序列；定期探索顺序组合，但不在每次编辑重复进行随机压力测试。偶发失败先记录首次证据，允许诊断性重跑，不能靠重试变绿抹去首次失败；隔离 flaky 用例必须有原因、负责人/跟踪项和期限，核心准入/恢复测试不能因此从门禁消失。

## 9. 报告与 CI

统一 result.json 至少记录：run ID、源码摘要/commit/dirty 状态、产物摘要、依赖与 Pi pin/patch、测试计划和选测原因、种子、开始结束时间、case 数及 passed/failed/skipped/blocked 状态、首次失败、外部依赖、各阶段耗时、服务清理结果和证据路径。JUnit/TAP 供 CI 展示，结构化 JSON 是汇总依据。

required suite 缺环境或必要 case 被跳过，不能给出完整通过结论；明确区分产品失败、测试设施失败、外部服务不可用与未运行。源码验证、wheel 验证、完整安装验证和真实 Phone 联调分别报告。

版本检查遵循主方案第 9.5 节：产品源版本、生成声明、wheel/组件版本及 manifest 一致，预发布按 SemVer/PEP 440 规范映射；Pi 和协议版本分别验证。报告同时记录 CLI 与实际连接服务的自报版本及 build ID。普通测试不得自动 bump 版本，缓存身份使用内容摘要，不只使用产品版本号；正式发布验收绑定最终产物字节。

CI 与本地使用相同 runner/manifest/lock，CI 只编排自己的独立合成测试数据与资源，不读取或复制本机 local_debug，不复制另一套测试命令逻辑。CI 的环境准备也通过测试目录契约完成；本机根路径固定，托管 CI 可在 runner 临时目录提供等价根，所有测试安装仍聚集其下，不能误用本机生产路径。实施时将这一 CI 例外明确记录到测试说明。

CI 用 parallel jobs 或 shards 运行独立套件，设置整体超时；`always` 阶段执行清理并输出 CI 自己的最小脱敏结果，取消运行也应触发清理。本机 local_debug 禁止上传到 CI artifacts/cache；CI 的上传路径只能显式允许其自行产生的非私有结果，不得使用仓库全量、local_debug/** 或整个测试根的通配上传。可外部缓存的公开依赖须与运行证据分开，缓存仅命中完整 key 且验证完整性，避免不可信 PR 缓存覆盖可信基线。无真实凭据的 PR 运行完整确定性链路，外部验收单列，不能把 absent secrets 转成已验证。

建议保留策略：成功 run 精简报告 14 天；失败证据 30 天；发布证据按版本长期归档；共享环境保留当前有效 key 与最近两个健康 key，其余按引用与配额回收。先报告磁盘占用再应用配额；活跃、有保留标记或未归档的关键失败不自动删除。

## 10. 已完成的旧环境删除与后续保密约束

用户已明确要求删除所有旧测试环境，不保留迁移备份。已核实旧根目录 `/home/iaw/debug/tspi-test-env` 无进程文件引用、嵌套挂载或已加载服务配置引用，并删除整个目录，包括旧 Python 环境、Pi checkout、缓存、产物、工作区及测试日志。现有产品服务不属于该目录，没有作为测试资源停止。

新根目录 `/home/iaw/project/TSPi/local_debug` 已设置 0700 权限，并加入 `.gitignore`、`.npmignore`、Git archive 与 Docker context 排除；发行源码捕获拒绝被强制加入 Git 或未被忽略的 local_debug 文件，包边界检查拒绝携带该目录。默认测试路径已更新，测试入口将临时文件和包缓存导向该根；环境与运行隔离设施已经重建；整项目最终验收仍按 T0—T4 退出条件核对，不以环境就绪替代应用验收。

保密规则：

1. local_debug 中的所有环境、模型配置、数据库、日志、输入、输出与证据留在本机；禁止 Git/GitHub 提交、release/npm/wheel/容器打包、CI artifacts/cache、网盘同步、遥测和 issue/PR 附件上传。
2. 禁止将目录内容作为外部模型 prompt、工具结果或远程执行输入发送。有外部测试需求时，先明确数据与目的地并取得授权；日常用本地确定性提供方与合成数据验证。
3. 新文件默认使用私有权限；日志不得记录令牌。忽略规则负责提交/打包边界，不等于网络隔离；runner 已通过独立 Linux 网络命名空间对默认套件限制外部网络，真实 systemd 测试单元也使用 PrivateNetwork，外发通路不得自动开启。
4. 每次提交前检查 Git index 中没有 local_debug；发布前检查源码快照、npm/wheel/release 成员与 CI 上传路径。被强制暂存时阻止发行构建，不通过静默过滤掩盖已暂存私有文件。
5. 未来 GC 只处理新根中归属明确且无活跃租约的运行资源，先生成本机 dry-run 清单；保留期也只在本机执行。不要对旧根做自动恢复，不把历史验证记录中的旧路径当成当前配置。

后续从仓库中的 lock、Pi pin 和已入库 patches 重建环境；旧 checkout 不再可作为读取或修复来源。源码快照允许建立在被忽略的 local_debug 子目录，始终排除私有目录本身，避免目录递归拷贝或把本地数据带入发行物。

## 11. 实施顺序与完成条件

| 阶段 | 工作 | 退出条件 |
| --- | --- | --- |
| T0 盘点与基线 | 精确目录/服务引用清单，环境与用例耗时，首次失败与 skip 原因 | 有可追溯基线；不假定现有套件全绿 |
| T1 运行隔离与清理 | run ID、显式解释器、fixture/supervisor、证据保留与 cleanup 审计 | 两轮测试同时运行不串数据；失败/取消不留本轮服务 |
| T2 环境与构建缓存 | 内容 key、锁、依赖准备、只读产物、每轮 overlay | 同 key 不重复安装；源码/lock/patch 改动正确失效；冷启动可重建 |
| T3 分层与选测 | 拆 Node fast/native，glob 发现，影响规则、精确过滤、统一报告 | 无孤儿测试；缺依赖不静默 skip；选测原因可检查 |
| T4 关键行为与 CI | 七工具、真实 Pi 流程、故障场景、安装产物、CI 分片 | 必要行为与清理门禁生效；本地/CI 使用同一合同 |
| T5 持续清理与保密验收 | 新根内按租约回收；检查 Git/打包/上传排除和网络边界 | 无私有数据进入发行物或外部上传，测试服务与过期运行状态可控 |

旧环境已按用户要求提前删除。现在从新根实施 T0/T1，作为代码重构 P1—P4 的基础；T2/T3 随新目录迁移更新；T4 配合 P4/P6 验收；T5 持续检查资源清理和私有数据边界。完整依赖重建完成前，不把环境缺失或跳过当作应用测试通过。

完成标准：日常测试有单一入口和明确范围；七工具与 Pi 核心循环经过真实执行；关键业务不变量和恢复场景可复现；测试环境不隐式回退；同机并发无状态污染；首次失败证据可重放；安装与源码验证可区分；服务清理失败会阻止通过；warm/cold 耗时与空间数据证明优化有效。具体提速比例在实施后测量，不预先承诺。
