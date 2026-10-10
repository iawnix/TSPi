---
name: method-selection
description: 选择科学方法并准备命名计算环境；用户已经指定方法时同样用于执行准备。
---

# CoRAgent 方法选择

[English version](SKILL.md)

选择方法或准备已指定方法的执行时使用本 Skill。辅助脚本生成通用 Job 请求，由 Agent 提交执行。

从用户要求的可观测量或待解决的科学问题出发，考虑体系大小、电荷、自旋、电子态、金属或多参考
风险、溶剂、约束、目标可观测量、预期误差、候选质量与成本。先根据方法 Skill 选择输入、
命令或脚本，再选择 `job.toml` 中的软件绑定与命名的本地或远端环境。`job_probe` 检查平台；
准备请求时核验所选软件和已声明依赖。需要诊断或使用原生命令时，见
[定向环境检查](references/runtime_environment.zh-CN.md)。

只有低成本探索能回答已声明问题时才使用它。明确何时需要更高层级计算、替代方法或稳健性
检查，并把选择与理由保存在研究 Node 和不可变 calculation intent 中。

对于明确要求优化/单点并比较多个方法和执行环境的请求，先展开完整的
`方法 × environment × {opt, sp}` 矩阵，再逐项探测环境并分别记录单元失败。方法 Skill
指导通过预设入口、原生命令或任务专用脚本执行；没有预设入口不代表软件缺失。
上述比较中，每个 `sp` 依赖同一方法、
同一环境的 `opt` 输出。
其它研究可选择明确的固定几何或 TS/Freq/IRC/scan 输入，由 Agent 定义计算依赖。
某个矩阵单元不可用时只阻塞该单元，不能静默替换方法或停止其他独立单元。

## 参考资料

- [method_selection.zh-CN.md](references/method_selection.zh-CN.md)：科学判据。
- [backend_contract.zh-CN.md](references/backend_contract.zh-CN.md)：科学 Job 合同与执行边界。
- [job_probes.zh-CN.md](references/job_probes.zh-CN.md)：命名的本地/远端环境及远端
  Platform 细节。
- [runtime_environment.zh-CN.md](references/runtime_environment.zh-CN.md)：安装级科学运行时诊断。

- [请求准备](references/request_preparation.zh-CN.md)：声明入口、显式输入与恢复。
- [Runner 结果、单位与电子态](references/runner_results.zh-CN.md)
