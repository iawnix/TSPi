---
name: method-selection
description: 选择科学方法并准备命名计算环境；用户已经指定方法时同样用于执行准备。
---

# TSPi 方法选择

[English version](SKILL.md)

选择方法或准备已指定方法的执行时使用本 Skill。辅助脚本生成通用 Job 请求，由 Agent 提交执行。

从区分相关 Claim 所需的 Finding 出发，考虑体系大小、电荷、自旋、电子态、金属或多参考
风险、溶剂、约束、目标可观测量、预期误差、候选质量与成本。使用 `job_probe` 检查所选
环境，不要只根据 Skill 描述推断软件可用。选择命名的本地或远端环境，由 Skill 构造准确
命令和参数。

只有低成本探索能回答已声明问题时才使用它。明确何时需要更高层级计算、替代方法或稳健性
检查，并把选择与理由保存在 Node 和不可变 calculation intent 中。

对于需要比较多个方法和执行环境的请求，先展开完整的
`方法 × environment × {opt, sp}` 矩阵，再逐项探测环境并分别记录单元失败。当前第一方
方法路由遵循以下规则：

| 方法 | 程序 | Job 命令 |
| --- | --- | --- |
| CF22D | PySCF | cf22d/scripts/run.py |
| GFN2-xTB | xTB | `xtb` 优化 / 单点 |
| HF、M062X 及其他 Gaussian Route Section 方法 | Gaussian | 带 `.gjf` Route Section 的 `g16` |

Gaussian 方法和基组写入 `.gjf` 的 Route Section，例如
`# M062X/6-31G** Opt` 或 `# HF/6-31G** SP`。每个 `sp` 必须依赖同一方法、同一环境的 `opt` 输出。
某个矩阵单元不可用时只阻塞该单元，不能静默替换方法或停止其他独立单元。

## 参考资料

- [method_selection.zh-CN.md](references/method_selection.zh-CN.md)：科学判据。
- [backend_contract.zh-CN.md](references/backend_contract.zh-CN.md)：科学 Job 合同与执行边界。
- [job_probes.zh-CN.md](references/job_probes.zh-CN.md)：命名的本地/远端环境及远端
  Platform 细节。
- [runtime_environment.zh-CN.md](references/runtime_environment.zh-CN.md)：安装级科学运行时诊断。

## 可执行请求准备

使用 [scripts/prepare_job.py](scripts/prepare_job.py) 从 job.toml 生成通用 Job 请求。传入 --config "$TS_JOB_CONFIG"、--environment、--backend、--skill、--xyz，-- 后是 runner 参数。远程 xTB/Gaussian 还需 --python 指定目标 Python >=3.10，或在 job.toml 的环境中配置 python；不能假定远程登录 PATH 有 python3。核对参数，补充 nodeId/timeoutSeconds 后 job_start。辅助脚本会暂存完整 scripts 目录和 `_shared` 依赖。

保留准备请求中的 requestId；同一次提交恢复时复用它，不因工具响应丢失而生成新 ID。明确重算时生成新请求。

选择方法或准备已指定方法的执行时都使用本 Skill。从列出的路径读取具体方法 Skill。读取安装配置、检查方法可用性属于 Agent 的工作，尚未验证不应自动变成用户输入门槛。
