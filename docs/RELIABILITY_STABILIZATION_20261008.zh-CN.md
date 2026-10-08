# Research State 第一阶段稳定化实施记录

本轮落实设计审查中可独立验证的写入合同、结论评估、上下文恢复和能力文档修正。
它不是完整的研究任务验收系统，也不代表 t009 的化学工作流已经打通。

## 已完成

1. **共用操作合同**：16 个公开 ChangeSet 操作由 `research_state/contracts/operations.json`
   统一定义。Python 实际写入边界、Agent 工具 schema 和操作查询使用相同定义。
   字段、类型、枚举和嵌套 Gate 内容在写入前验证；失败保留操作索引，整批回滚。
   `assess_claim`、`revise_claim` 已进入公开工具合同；操作查询透传 `query`。
2. **结论必须经过评估**：新 Claim 只能是 `proposed`。`supported`、`contradicted`、
   `inconclusive` 必须通过带理由及证据的 `assess_claim`。
   `set_claim_status` 只允许在 `proposed`、`withdrawn` 之间转换，不能覆盖科学结论。
   已评估结论的撤回仍需记录理由。
3. **核实证据及版本**：评估时核对真实文件与摘要，解析 Artifact、Finding 和 evidence link。
   计算产物必须属于生产 Attempt 的当前收集回执；派生材料的所有输入都要检查。
   外部文献、实验数据、已有研究材料仍可登记引用，无需伪造本系统的 Job。
   登记行、派生描述或没有来源的 Finding 本身不能替代实际材料。
4. **区分当前判断和历史判断**：Claim 用 `current_assessment_id` 指向采纳的评估。
   绑定内容、来源、Finding、收集回执以及 ClaimGate 的实际评估版本。
   ClaimGate 必须全部通过才能支持 Claim；新增、修订或重评 Gate 都会使既有支持结论需要复核。
   正常证据或条件变化可以先保存，再单独重新评估。仅当前评估参与结束检查，旧评估留作历史。
   `needs_review` 阻止显式 terminal 和“所有节点关闭”推导的自动 terminal。
5. **可读取的恢复路径**：map、summary、Claim detail 和上下文显示
   `not_assessed` / `current` / `needs_review`；`research_read mode=decisions`
   可分页读取评估理由、证据绑定和历史。
   超预算上下文压缩字段或省略整条记录，保留 lifecycle、遗漏数量和可调用的读取提示，ID 不截断。
   投影或记录故障时模型仍可诊断；未知 State 不会获得执行准入。
6. **修正双语 Skill 与架构文档**：去掉不存在的分析能力调用，明确
   `artifact_derive` 只保存描述；区分真实 Gaussian runner/parser 与尚未实现的模式、IRC 端点验证。
   NEB、CREST、QBICS 区分指导、外部软件和实际内置入口。化学输入守恒检查不等于预期反应验证。
   化学扩展 manifest 的 Skill 摘要已同步。

## 兼容与限制

既有工作区不迁移到新 State schema。没有当前评估指针的旧 Claim 保留原状态，投影标记
`not_assessed`，不会被静默补成已验证，也不会因此自动阻断历史工作区。

这些检查保证材料可追溯、版本一致和结论变更有记录，不能证明材料中的科学判断正确。
本轮没有建立原始用户需求的完整覆盖约束，没有消除自拟弱 NodeGate 的问题，也没有把任意
`bash` 执行变成受管 Job。t009 的反应映射语义验证、候选生成到 TS/IRC 的可执行路径及科学评测仍待实现。

State bridge 整体离线时，模型可以解释故障，依赖 State 的工具仍可能被拒绝；本轮不放宽副作用准入。
原有历史 journal 扫描成本也未在此轮改变。

## 验证

使用 `/home/iaw/debug/tspi-test-env` 内 Python 环境、临时工作区和已验证的 patched Pi checkout。
回归覆盖无证据结论、原子回滚、外部材料、缺失/摘要不符材料、全部派生输入、收集回执变化、
Gate 新增/修订/重评、历史评估不变、自动结束恢复，以及 200 个研究节点在 2–32 KB 预算下的上下文恢复。

Python 单元、合同及选定 CLI/跨语言集成测试 **298 通过**；完整 Native Pi 测试组
**215 通过**。TypeScript 类型检查、包完整性、架构边界、Skill 合同及公共术语检查通过。

验证日志：

- `/home/iaw/debug/tspi-test-env/rectification-python.log`
- `/home/iaw/debug/tspi-test-env/rectification-node.log`
- `/home/iaw/debug/tspi-test-env/rectification-package.log`
- `/home/iaw/debug/tspi-test-env/rectification-typecheck.log`

本轮未执行真实科学计算、外发邮件或生产部署。
