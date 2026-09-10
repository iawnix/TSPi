# TSPi Package

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi 是过渡态研究的核心产品和必选仓库。它包含确定性研究内核、Pi
集成、计算与报告工具、只读工作区投影，以及可选组件的发布和安装边界。

`ts-phone` 是独立维护的 Phone 组件仓库，负责手机端、Phone 服务和
Phone 协议。`ts-web` 是面向浏览器的可选组件目标，消费 TSPi 提供的只读、
版本化投影协议。两者都不应复制 TSPi 的科学状态或取得科学状态写权限。

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
| `src/` | Pi 运行时、Host、Terminal、Compute 和 Review 的 TypeScript 代码 |
| `extensions/` | Pi 扩展和 Phone 适配策略 |
| `skills/` | 面向模型的公开 Skill 与参考资料 |
| `scripts/` | 稳定入口和兼容性包装器；发布机制逐步迁移到命名工具目录 |
| `tools/` | 合约同步、公开术语检查和开发工具 |
| `docs/` | 架构、安装、维护和 ADR 文档 |
| `build/`、`dist/`、`.runtime/` | 本地生成物，已从 Git 和发布边界排除 |

`cluster_mcp` 已废弃，不是当前组件，也没有被 Git 跟踪。运行缓存清理后，
仓库中不应再出现该目录。

Python 包的源码目录和 Python 导入命名空间是两个概念：源码位于
`packages/ts-agent-kernel/`，导入仍使用 `ts_agent`。这样既能表达包的责任，
也不会破坏 Python API。

## 安装

先从独立的 `ts-phone` 仓库构建并校验 Phone 组件，再由 TSPi 组装所选组件：

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
python3 scripts/install_package.py \
  --manifest dist/package/tspi-package-release.json \
  --install-root /path/to/TSPi-installation \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

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

完整术语见 [中英术语表](skills/transition-state-workflow/references/glossary.zh-CN.md)。

## 开发验证

```bash
npm run typecheck
npm run test:fast
npm run test:package
npm run lint:public
npm run test:terminal
```

需要发布级 Python 环境时运行完整源码测试：

```bash
python3 scripts/test_source.py --conda-root /path/to/miniforge3 --with-render -- -q
```

架构和维护规则见 [Architecture](docs/ARCHITECTURE.md)、
[Installation](docs/INSTALLATION.md)、[Maintainer Guide](docs/MAINTAINER_GUIDE.md)
以及 [ADR 0002](docs/adr/0002-repository-and-component-boundaries.md)。
