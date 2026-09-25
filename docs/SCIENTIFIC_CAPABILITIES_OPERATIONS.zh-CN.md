# 科学能力：使用与运维

[English](SCIENTIFIC_CAPABILITIES_OPERATIONS.md) | 简体中文

本文描述当前独立分析和 Node 操作合同，不引入第二套研究协议。

## 软件与依赖

受管理 runtime 提供 Python、RDKit、ASE、NumPy、jsonschema、渲染支持和
`ts-agent-kernel` wheel。Gaussian、xTB、CREST 等原生程序仍由管理员配置为 Backend。
请通过版本化能力目录发现可用能力，不要假定某个命令已经安装。

## Node 操作与恢复

分析或派发属于一个 ResearchNode，只能写入该 Node 的 artifact 目录。暂停/恢复回执是
操作记录，不改变 Node 的科学状态；暂停期间仍可查看、收集、解析和精确取消作业。重启
后再次提交前必须先核对最新回执。

`compute.run` 对 local/remote 使用相同的公开操作：

```text
launch   -> prepare, submit
inspect  -> status, optional tail
finalize -> collect, parse
cancel   -> cancel
```

右侧是 child runtime 内部动作，调用方不把它们当作第二套公开生命周期。

远端完成不代表收集成功；提交或取消结果不确定时，必须先 inspect 再重试。

## Finding、报告与网页

分析输出位于 `nodes/<node_id>/outputs/analysis/`，绑定输入 digest、生成文件和临时
解析候选。Root Agent 核验候选后，通过 `research.change` 创建 `FactFinding` 或
`IssueFinding`。报告和 TS Web 直接消费规范 `ResearchMap` 序列化，不创建第二份科学
状态，也不选择下一个 Node。

热化学仅支持匹配的 HF/Kohn-Sham SCF 能、解析热修正和显式 RRHO。通用相关电子解析、
同位素 RRHO/KIE、构象系综和微观动力学不在本版本范围；缺失或不兼容证据不能用电子能
替代。

## 验证入口

迭代时运行聚焦测试，发布前运行源码测试：

```bash
python3 tools/test/runner.py fast -- -q
python3 tools/test/runner.py source -- -q
```

远端 smoke 需要 `TS_COMPUTE_CONFIG` 指向包含管理员远端环境的统一 compute TOML。
它只验证传输和 parser 集成，小分子作业不能作为真实机理证据。
