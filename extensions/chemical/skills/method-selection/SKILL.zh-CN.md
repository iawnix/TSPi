---
name: method-selection
description: 为有边界的研究问题选择科学方法、已注册 Backend workflow 以及命名的本地或远端计算环境。
---

# TSPi 方法选择

[English version](SKILL.md)

在方法、Backend、workflow 或计算环境尚未确定时，先使用本 Skill。方法选择属于科学
决策；本 Skill 不启动计算。

从区分相关 Claim 所需的 Finding 出发，考虑体系大小、电荷、自旋、电子态、金属或多参考
风险、溶剂、约束、目标可观测量、预期误差、候选质量与成本。查询实时 workflow 和环境
目录，不要根据 Skill 描述推断软件可用。选择一个命名的本地或远端环境，并确认其 Backend
绑定支持准确的 workflow 与参数。

只有低成本探索能回答已声明问题时才使用它。明确何时需要更高层级计算、替代方法或稳健性
检查，并把选择与理由保存在 Node 和不可变 calculation intent 中。

对于需要比较多个方法和执行环境的请求，先展开完整的
`方法 × environment × {opt, sp}` 矩阵，再逐项查询 workflow 和 readiness。当前第一方
方法路由遵循以下规则：

| 方法 | Provider | workflow |
| --- | --- | --- |
| CF22D | PySCF | `pyscf.opt` / `pyscf.sp` |
| GFN1-xTB、GFN2-xTB | xTB | `xtb.opt` / `xtb.sp` |
| HF、M062X 及其他 Gaussian Route Section 方法 | Gaussian | `gaussian` |

Gaussian 方法和基组写入 `.gjf` 的 Route Section，例如
`# M062X/6-31G Opt` 或 `# HF/6-31G** SP`；不因为 PySCF descriptor 没有某个泛函就
判定 Gaussian 方法不可用。每个 `sp` 必须依赖同一方法、同一环境的 `opt` 输出。
某个矩阵单元不可用时只阻塞该单元，不能静默替换方法或停止其他独立单元。

## 参考资料

- [method_selection.zh-CN.md](references/method_selection.zh-CN.md)：科学判据。
- [backend_contract.zh-CN.md](references/backend_contract.zh-CN.md)：Backend 与 workflow 边界。
- [job_probes.zh-CN.md](references/job_probes.zh-CN.md)：命名的本地/远端环境及远端
  Platform 细节。
- [runtime_environment.zh-CN.md](references/runtime_environment.zh-CN.md)：安装级科学运行时诊断。
