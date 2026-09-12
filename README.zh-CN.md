# TSPi Package

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi 是过渡态研究的核心产品和必选仓库。它包含确定性研究内核、Pi
集成、计算与报告工具、只读工作区投影，以及可选组件的发布和安装边界。

`ts-phone` 是独立维护的 Phone 组件仓库，负责手机端、Phone 服务和
Phone 协议。`ts-web` 是面向浏览器的可选组件目标，消费 TSPi 提供的只读、
版本化投影协议；科学状态由 TSPi 统一维护，组件通过该协议读取。

## 核心边界

```text
Root Agent
  选择问题、假设、方法、分支、回溯和停止条件
        |
        v
Research Kernel
  管理 ResearchPhase、ResearchNode、Claim、Observation、Finding 和 ProofSpec
        |
        +-- 确定性 Compute / Render / Report / Remote 工具
        +-- 隔离的 Compute 子代理
        +-- 隔离的 Review 子代理
        +-- 只读的 Web、Phone 和 Terminal 投影
```

只有 Research Kernel 可以修改规范化的科学状态。Compute 和 Review 在隔离
的子会话中运行，分别执行固定的操作计划和提供有边界的建议。

## 仓库布局

| 目录 | 责任 |
| --- | --- |
| `contracts/` | Phone、Web 和组件清单的版本化协议与 fixture |
| `packages/ts-agent-kernel/ts_agent/` | TSPi 的 Python 研究内核和确定性服务 |
| `components/ts-web/` | 独立的可选 Web 客户端、provider、server 和静态界面 |
| `apps/` | Host 和 Terminal 进程入口 |
| `extensions/` | Pi 扩展和 Phone 适配策略 |
| `skills/` | 面向模型的公开 Skill 与参考资料 |
| `scripts/` | 稳定入口和兼容性包装器；发布机制逐步迁移到命名工具目录 |
| `tools/` | 合约同步、公开术语检查和开发工具 |
| `docs/` | 架构、安装、维护和 ADR 文档 |

Python 包的源码目录和 Python 导入命名空间是两个概念：源码位于
`packages/ts-agent-kernel/`，导入仍使用 `ts_agent`。这样既能表达包的责任，
也不会破坏 Python API。

## Skill 体系

package 内包含一个编排 Skill、五个科学方法 Skill 和三个输出/交付 Skill。
编排 Skill 负责跨领域合同和任务管理；其他 Skill 只在当前问题需要相应方法
或交付能力时加载。

| Skill | 范围 |
| --- | --- |
| `tspi-orchestration` | 工作区、Decision、证据、验证、子代理和恢复合同 |
| `tspi-transition-state-search` | 候选构造和过渡态搜索策略 |
| `tspi-xtb` | xTB、CREST 计算和结果解释 |
| `tspi-gaussian` | Gaussian 输入和输出验证 |
| `tspi-qbics` | QBICS/DMECP 电子态交叉 |
| `tspi-connectivity` | 反应路径端点和分子结构身份 |
| `tspi-render` | 确定性可视化产物 |
| `tspi-report` | 由证据绑定的报告包 |
| `tspi-email` | 固定目标通知投递 |

完整目录见 [Skill Catalog](skills/README.zh-CN.md)。

## 安装

生产安装应从固定的 GitHub tag 或 commit 开始，并在激活前记录源码 provenance：

```bash
python3 scripts/install_from_github.py \
  --repo https://github.com/iawnix/TSPi.git \
  --ref v0.17.0 \
  --install-root /path/to/TSPi-installation \
  --with-render \
  --json
```

下面的 `build_package.py` 和 `install_package.py` 仍可用于离线组装和内部校验。

如需加入可选 Phone 组件，先从独立的 `ts-phone` 仓库构建并校验组件清单，
再传给 TSPi 组装器：

```bash
cd /path/to/ts-phone
npm ci
apps/mobile/tool/build_release_android.sh
python3 deploy/build-component-release.py --output-dir dist/component --json

cd /path/to/TSPi
python3 scripts/build_package.py \
  --phone-manifest /path/to/ts-phone/dist/component/ts-phone-component-release.json \
  --output-dir dist/package \
  --json
```

需要只有 Core 时传入 `--without-web`。如果收到预构建的 Package 归档和清单，
可以跳过组件构建步骤。

安装器使用一个经过校验的 TSPi Package，按组件版本、协议版本、文件大小、
SHA-256 和构建证明绑定发布内容。安装只选择内容，不自动启动 Phone 服务，
也不自动安装 Android APK。

## 启动 TSPi

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a --continue
./TSPi --workspace reaction-a --phone
./TSPi --check-remote
```

Terminal 和 Phone 共用 Host 管理的 Worker 和会话历史。只读浏览不会启动
研究；不同工作区可以并行运行。完整行为和权限边界见
[Terminal 文档](docs/TERMINAL.md)。

## 查看工作区

TSPi 提供只读的 Web projection server。它通过版本化 JSON 投影显示工作区、
ResearchNode、Claim、Attempt、Finding 和验证结果，不直接导入 Web 客户端
的私有 Python 模块，也不暴露物理路径或科学状态写接口。

```bash
/path/to/TSPi-installation/TSWeb serve \
  --state-dir /path/to/TSPi-installation/.pi/ts-web \
  --source-root /path/to/TSPi-installation/workspaces/reaction-a \
  --label "Reaction A" \
  --host 127.0.0.1 \
  --port 8766
```

## 公开术语

- `ResearchPhase`：用于导航的阶段分组，不决定执行顺序。
- `ResearchNode`：一个有边界的研究问题或决策事件。
- `Claim`：带假设和反证条件的科学陈述。
- `Observation`：绑定已验证产物和来源的不可变语义记录。
- `Finding`：异常、限制、冲突或未解决问题。
- `ProofSpec` / `ValidationResult`：冻结的验证定义及其确定性结果。
- `Decision`：由 Root Agent 发起、由内核校验并提交的原子变更。

完整术语见 [中英术语表](skills/tspi-orchestration/references/glossary.zh-CN.md)。

## 开发验证

验证应从源码 checkout 执行，而不是从已安装 release 执行。`tsc` 只检查
TypeScript 类型；快速 Python 测试覆盖当前环境中的内核；package 和 terminal
测试覆盖发布边界。完整源码测试会先构建 Python wheel，再在科学环境之上创建
临时 managed overlay，并运行全部 pytest。GitHub CI 会在每次 push 和 pull request
执行这些层次。

```bash
npm run typecheck
npm run test:fast
npm run test:package
npm run test:terminal
npm run lint:public
python3 scripts/test_source.py --conda-root /path/to/miniforge3 --with-render -- -q
git diff --check
```

修改 Pi adapter 或 subagent 时，可先运行较短的集成子集：

```bash
npm run test:pi-adapter
```

完整源码测试需要 Python、Node 和 `environment.yml` 中锁定的科学环境；如果已有
可复用的 Conda 环境，可以传入 `--base-prefix`：

```bash
python3 scripts/test_source.py --base-prefix /path/to/conda/env --conda-root /path/to/miniforge3 -- -q
```

架构和维护规则见 [Architecture](docs/ARCHITECTURE.md)、
[Installation](docs/INSTALLATION.md)、[Maintainer Guide](docs/MAINTAINER_GUIDE.md)
以及 [ADR 0002](docs/adr/0002-repository-and-component-boundaries.md)。
