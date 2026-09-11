# TSPi 改善方案

> 实施状态（2026-09-12）：第一阶段的 `/3` 清理、仓内 Web 组件边界、曲线渲染
> 合约和 GitHub source-first 安装入口已完成；后续阶段保留为演进计划。

## 目标

本方案针对当前 TSPi 的实际边界，目标是：

1. 删除不再需要的 Web `/3` 兼容路径，降低发布、安装和测试复杂度。
2. 保留 `ts-web` 在 TSPi 仓库内的独立组件边界，不过早拆成单独 Git 仓库。
3. 将 `ts-phone` 作为上一级目录中的独立仓库，通过已验证的 component manifest 接入。
4. 让新环境可以稳定安装、验证和诊断。
5. 为长期的性能、可观测性和科学复现建立基础。

## 目标架构

```text
../ts-phone/
  独立 Phone 仓库
  Phone 服务、移动端、协议、签名和部署

TSPi/
  packages/ts-agent-kernel/       科学内核和 Projection Provider
  components/ts-web/              Web 客户端、HTTP 服务和静态资源
  contracts/ts-web/               Web Provider/Projection 合约
  scripts/build_web.py            Web 组件构建
  scripts/build_package.py        TSPi Suite 组装
```

TSPi 负责科学状态、只读投影协议、Provider、Suite 组装和安装。`ts-web`
只负责只读展示；`ts-phone` 负责自己的服务、移动端、认证和部署生命周期。

`ts-web` 的“独立”定义为独立组件、独立归档、独立 manifest 和独立测试，
暂时不定义为独立 Git 仓库。只有在 Web 需要独立团队、独立发布节奏、多个
后端或 CDN/SaaS 部署时，才重新评估拆仓库。

## 第一阶段：删除 Web `/3` 兼容（高优先级）

### 代码清理

删除所有历史 Web 嵌入路径和条件分支：

- `scripts/_suite.py` 中的 `SUITE_COMPAT_SCHEMA_VERSION`、兼容组件版本和旧 Web 校验。
- `scripts/_wheel.py` 中的旧版 Web 参数及 Web 嵌入判断。
- `scripts/install_package.py` 中针对 Suite `/3`、旧 Web entrypoint 和旧版 runtime 的分支。
- `scripts/install_release.py` 中仅为旧 Web 形态保留的参数和校验。
- `scripts/package_inventory.py` 中的旧版 Web inventory 常量。
- `packages/ts-agent-kernel/ts_agent/web/` 整个旧 Web 实现。
- `scripts/ts_web.py` 兼容包装器。

当前唯一受支持的 Suite 结构为：

```text
tspi-package-release/4
  agent/
  web/       可选
  phone/     可选
```

如果不选择 Web，安装结果中不应存在 `TSWeb`；如果选择 Web，launcher 只指向
`current/web/bin/ts-web`。

### 测试和文档清理

- 删除只覆盖 `/3` 的安装、回滚和旧版 Web 测试。
- 将 `tests/test_ts_web.py` 中依赖 `ts_agent.web` 的测试迁移到
  `tests/test_ts_web_component.py`，直接测试 `components/ts-web/ts_web/`。
- 新增测试，确认源码和发布包中不存在 `scripts/ts_web.py` 与
  `packages/ts-agent-kernel/ts_agent/web/`。
- 删除 README、Architecture、Installation、Maintainer Guide 中关于
  `/3` 回滚和 Agent 内嵌 Web 的说明。
- 将 `docs/adr/0002` 的状态改为“Web 组件边界已完成，旧 `/3` 兼容已终止”。

### 版本策略

停止接受 Suite `/3` 属于安装兼容性变化。建议将下一次 TSPi 包版本作为一次
明确的 breaking release；如果项目仍处于 `0.x`，至少提升 minor 版本并在
发布说明中明确写出“旧 `/3` 包不再接受”。`ts-web` 的
`ts-web-component-release/1` 不需要因为仓库内清理而升级协议版本。

### 验收标准

- `_suite.py`、`_wheel.py`、安装器和 inventory 中没有旧版 Web 分支。
- `npm run test:package` 通过。
- Suite `/4` 的 Core-only、Core+Web、Core+Phone、Core+Web+Phone 四种组合均能构建和安装。
- 旧 `/3` 包被明确拒绝，并返回可理解的升级提示。
- Web 运行时不再从 `ts_agent.web` 导入任何代码。

## 第二阶段：固定 `ts-web` 的仓库内组件边界

### 保留的边界

保留以下目录和职责：

- `components/ts-web/ts_web/`：Provider client、registry、HTTP server、release watcher。
- `components/ts-web/static/`：浏览器资源。
- `components/ts-web/bin/ts-web`：组件入口。
- `contracts/ts-web/`：Provider、Projection、错误和 manifest 合约。
- `scripts/build_web.py`：生成内容寻址的 Web 组件归档。

`contracts/ts-web` 继续由 TSPi 维护，因为 Projection Provider 和工作区语义
属于 TSPi。Web 客户端不得导入 `ts_agent` 私有模块，也不得直接读取工作区物理路径。

### 构建方式

保留两种输入：

```bash
# 从当前 TSPi checkout 构建 Web
python3 scripts/build_web.py --output-dir dist/web --json

# 使用已构建、已验证的 Web manifest 组装 Suite
python3 scripts/build_package.py \
  --web-manifest /path/to/ts-web-component-release.json \
  --output-dir dist/package --json
```

默认 Suite 构建可以继续自动调用 `build_web.py`，这样单仓库开发不需要额外
步骤；发布流水线则应优先消费已生成并留存的 Web manifest。

### 暂不拆仓库的原因

目前 Web 的发布节奏、协议、主题和 Provider 都与 TSPi 紧密绑定。拆仓库会
增加协议同步、跨仓库 CI、版本协调和问题定位成本，但不会增加科学或部署能力。
当前 `components/ts-web/` 已经提供足够的源码和发布隔离。

## 第三阶段：接入上一级 `ts-phone`

TSPi 不导入 `../ts-phone` 的源码，也不使用 Git submodule。Phone 通过 manifest
接入：

```bash
cd ../ts-phone
npm ci
npm run release:component -- --output-dir dist/component --json

cd ../TSPi
python3 scripts/build_package.py \
  --phone-manifest ../ts-phone/dist/component/ts-phone-component-release.json \
  --output-dir dist/package --json
```

CI 应分别 checkout 两个仓库，先构建 Phone component，再将 manifest 传给 TSPi。
TSPi 只校验 Phone 的版本范围、协议版本、归档 digest、入口、APK 和 attestation。

应补充以下检查：

- 未提供 Phone manifest 时，Core 和 Core+Web 仍能独立构建。
- Phone manifest 指向错误仓库、旧协议或篡改归档时，组装失败。
- Phone 源码改变但 manifest 未重新生成时，组装失败。
- Phone 服务不会因为安装或 Web 启动而自动启动。

## 第四阶段：开发环境和持续集成

当前仓库在没有预先准备依赖的机器上无法执行 `typecheck` 和 `test:fast`。
已增加明确的开发初始化入口 `tools/bootstrap_dev.py`，并提供
等价的 `Makefile`/文档命令，完成：

1. `npm ci`，安装锁定的 TypeScript/Pi 开发依赖。
2. 创建或复用 Conda 环境。
3. 安装 `pyproject.toml` 的 test/render 依赖。
4. 输出实际 Python、Node、RDKit、NumPy、Pi 版本。
5. 运行一个最小 smoke test。

科学依赖已增加 Linux Conda explicit lock 文件。`environment.yml` 可以继续
作为人类可读入口，但不能作为唯一的可复现依据。

建议 CI 分为四个 job：

| Job | 内容 |
|---|---|
| Fast | Python 单元/契约测试、TypeScript typecheck、公开术语检查 |
| Component | Web 组件、Phone manifest fixture、Pi adapter、协议兼容性 |
| Candidate | 构建 Agent/Web/Phone component 和 Suite，执行受管运行时测试 |
| Release | 安装临时 Suite、检查 launcher、权限、digest 和 Core-only smoke test |

每个 job 都应上传机器可读的测试记录和版本诊断。

## 第五阶段：Web 安全和运行行为

`ts-web` 当前默认监听 `0.0.0.0`。即使是只读投影，也可能暴露研究内容，
因此应：

- 默认监听 `127.0.0.1`。
- 非 loopback 地址必须显式使用 `--allow-remote`。
- 远程模式要求 token 或反向代理认证，并在文档中说明 TLS 要求。
- 增加 Origin/CORS 策略，不允许任意浏览器来源。
- 限制 workspace ID、URL 长度、查询参数和单次响应大小。
- 在 `/api/health` 中返回 provider、projection、graph 和 release 版本。
- 为启动参数打印一份脱敏的运行配置，避免泄露物理路径和 token。

## 渲染 Skill 的职责扩展

`tspi-render` 可以统一负责分子、反应路径和科学曲线的确定性渲染。当前实现
的实际能力仍然集中在结构与轨迹，因为它调用 `xyzrender`，目前支持：

- 单个分子结构渲染；
- 多结构比较和排版；
- 轨迹动画；
- 反应机理结构序列展示。

应在同一个 Skill 中增加曲线操作，而不是另建 `tspi-plot`。建议的操作集合为：

```text
render       单个分子结构
compare      多结构比较
animate      轨迹或模式动画
mechanism    反应机理结构序列
curve        通用二维曲线
energy       反应坐标/能量剖面
scan         几何或参数扫描曲线
convergence  优化、SCF 或迭代收敛曲线
```

`curve` 是底层通用能力，`energy`、`scan` 和 `convergence` 是带有固定语义
和校验规则的便捷操作。每个操作仍然只能读取已注册 artifact，不能接受任意
本地路径或让模型直接拼接绘图命令。

曲线需要新增版本化数据合约，至少包含：

- `x`/`y` 数值序列和长度一致性；
- x/y 单位、标题和轴标签；
- 数据来源 artifact ID、digest 和 Observation 引用；
- 缺失值、异常值和不确定性区间表示；
- 排序、重复点、有限值和最大点数限制；
- 颜色、线型、尺寸等受限的展示参数。

后端可以使用 matplotlib 或等价的固定版本绘图库。绘图环境必须记录后端
版本、字体、尺寸、主题和输入 digest，以保证相同输入产生稳定产物。

曲线图属于展示产物，不能自动生成 Observation、ValidationResult 或 Claim
结论。图中的数值必须能回溯到已注册 artifact 和语义 Observation；若曲线
来自解析器，应先记录语义 Observation，再由 `ts-render` 读取它们绘图。

## GitHub 源码安装策略

生产安装建议统一采用“从 GitHub 获取源码、固定版本、构建、校验、部署”的
入口。当前的本地 manifest 安装流程可以保留为内部构建机制，但不应成为普通
用户必须理解的入口。

建议增加一个统一命令，逻辑上执行以下步骤：

```text
GitHub repository + immutable ref
        |
        v
temporary source checkout
        |
        v
source/tree/digest verification
        |
        +--> build TSPi Agent
        +--> build ts-web component
        `--> optionally fetch/build ts-phone component
        |
        v
Suite manifest + archive verification
        |
        v
staged install -> runtime probe -> atomic activation
```

实现要求：

- 默认要求 tag 或完整 commit SHA，不允许直接以可变 `main` 作为生产版本。
- 记录 repository URL、commit SHA、source tree digest、组件版本和构建工具版本。
- TSPi 和 `ts-phone` 都从 GitHub 拉取；上一级 `../ts-phone` 只作为开发便利，
  不能成为生产安装的隐式依赖。
- 构建在临时目录完成，成功后才写入 Suite manifest 和 `current` 指针。
- 任一组件构建、协议检查、digest 校验或 runtime probe 失败，都保留旧版本。
- 仍保留已构建归档作为缓存和离线部署手段，但它应由 GitHub commit 对应的
  manifest 产生，而不是另一套独立版本来源。

这样用户只需要选择 GitHub 仓库和版本；manifest、归档和组件校验成为内部
可审计结果。

## Claim 收尾与“Gate”语义

当前 TSPi 没有一等的 `Gate` 实体，也没有新的 `gate_results.json` 或
`required_gates` 字段。旧 gate 名称被作为废弃兼容术语拒绝。现有等价机制是：

```text
Claim
  -> ProofSpec                  冻结要检查什么
  -> ValidationResult           对指定 Observations 执行检查
  -> AcceptanceProfile          定义哪些维度必须通过
  -> accept_claim               生成不可变收尾快照
```

一次正常收尾的顺序是：

1. `create_claim` 预注册 statement、assumptions、predictions 和 falsifiers。
2. `freeze_proof_spec` 将一个验证维度的模板或定义展开，并绑定 predicate
   registry digest 和 `proof_digest`。
3. `evaluate_proof` 使用明确的 Observation 引用执行确定性谓词，输出
   `pass`、`fail`、`inconclusive` 或 `error`。
4. 对 Claim 的每个 ProofSpec 都产生最新 ValidationResult。
5. `update_claim` 将 Claim 明确解释为 `supported`，并引用 Observation 或
   ValidationResult；Kernel 不会根据结果自动改变 Claim 状态。
6. `accept_claim` 根据 AcceptanceProfile 检查所有附加 ProofSpec、所需维度、
   每个规格的最新结果、digest 和未解决的 blocking Finding。
7. 检查通过后写入不可变 Acceptance record。后续 Claim、ProofSpec、结果或
   Finding 改变时，旧 Acceptance 自动变为 stale，必须重新评估。

以 `accepted-ts@3` 为例，必须具备 `stationary_point`、
`reaction_coordinate`、`connectivity` 三个维度；所有附加 ProofSpec 的最新
结果都必须是 `pass`，并且不能存在开放的 blocking Finding。

这里的 `ProofSpec` 相当于“gate definition”，`ValidationResult` 相当于
“gate execution result”，`Acceptance` 才是最终收尾记录。若 UI 需要显示
“Gate”，建议只做一个由这三类记录推导出的展示别名，不要重新建立平行的
`gate_results` 状态源。

## 第六阶段：可观测性和故障诊断

目前大量错误会被转成普通字符串，部分 HTTP 日志被静默丢弃。建议：

- 统一结构化日志格式，至少包含 `release_id`、`workspace_id`、`node_id`、
  `attempt_id`、`job_id` 和 `correlation_id`。
- 将 provider、remote、scheduler、parser、validation 和 installation 错误
  映射到统一 taxonomy。
- 为 Host、Web、Compute、Review 增加启动、就绪、失败和恢复指标。
- 保留用户可读错误，同时把详细诊断写入受权限保护的运行日志。
- 对外部副作用记录“未发生、已发生、结果未知”三类状态，禁止未知状态自动重试。

## 第七阶段：工作区规模和科学验证

当前 JSON/JSONL 状态和全工作区 dry-run 适合中小型研究，但长期需要：

- 为 Observation、Finding、Attempt、Activity 建立索引或 SQLite/WAL 存储评估。
- 增加日志轮转、快照、校验和修复工具。
- 对大工作区测试读取、投影、恢复和备份耗时。
- 对 Gaussian、xTB、CREST parser 增加 property/fuzz tests。
- 建立小型真实分子黄金数据集，验证结构比较、频率、能量和失败分类。
- 记录外部软件版本、编译器、运行参数和输入输出 digest，支持结果复现。

## 推荐排期

### M0：边界冻结（1 天）

- 决定不再支持 Suite `/3`。
- 决定 `ts-web` 继续留在 TSPi 仓库。
- 确认 `../ts-phone` 只通过 manifest 接入。

### M1：兼容清理（1–2 天）

- 删除旧 Web 代码、兼容分支、旧测试和旧文档。
- 迁移 Web 测试到 `components/ts-web`。
- 让 Suite `/4` 成为唯一发布路径。

### M2：构建和 CI（2–4 天）

- 增加开发环境初始化。
- 增加四层 CI。
- 锁定 Python 科学环境。
- 加入上一级 `ts-phone` 的 manifest 集成测试。

### M3：安全和诊断（2–3 天）

- 修改 Web 默认监听地址。
- 增加远程访问保护和版本化 health 诊断。
- 统一结构化日志和 correlation id。

### M4：规模化和科学质量（持续迭代）

- 评估 SQLite/WAL 或索引层。
- 增加真实软件和黄金数据集验证。
- 按实际工作区规模决定是否升级存储模型。

## 最终验收清单

- [ ] 仓库和发布包中不存在 Web `/3` 旧版 runtime。
- [ ] TSPi Core 不依赖 `ts-phone` 或 `ts-web` 才能启动和测试。
- [ ] Web 只通过 `ts-web-provider/1` 访问 TSPi 投影。
- [ ] Phone 只通过上一级仓库生成的 manifest 接入。
- [ ] 新机器能按文档完成环境准备并执行 fast checks。
- [ ] CI 覆盖源码、组件、候选发布和最终安装。
- [ ] Web 默认只监听 loopback，远程访问有显式安全门槛。
- [ ] 安装、运行、远程计算和解析失败都有可追踪诊断。
- [ ] 至少有一套真实科学输入输出用于 parser 和结构比较回归。
