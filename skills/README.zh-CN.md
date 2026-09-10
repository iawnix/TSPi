# TSPi Skills

TSPi 作为一个 Pi package 发布，其中包含多个可以独立发现的 Skill。编排合同
和具体方法知识分开，研究会话只加载当前问题需要的内容。

| Skill | 责任 | 使用时机 |
| --- | --- | --- |
| `tspi-orchestration` | 工作区状态、Decision、证据、验证、子代理、操作和恢复 | 任何 TSPi 研究任务或状态变更 |
| `tspi-transition-state-search` | 候选结构构造和过渡态搜索策略 | 选择 QST、扫描、NEB、构象、分支或恢复策略 |
| `tspi-xtb` | xTB 和 CREST 的设置与结果解释 | 使用 xTB 预筛选、优化、频率、扫描、MD 或构象搜索 |
| `tspi-gaussian` | Gaussian 输入和输出证据 | 使用 Gaussian 单点、优化、频率或 IRC 计算 |
| `tspi-qbics` | QBICS/DMECP 电子态交叉计算 | 研究 QBICS 交叉点或非绝热电子态特征 |
| `tspi-connectivity` | 端点赋值和分子结构证据 | 检查 IRC 连通性、原子映射、立体化学或盆地身份 |
| `tspi-render` | 确定性可视化产物 | 渲染、比较、制作动画或展示反应机理 |
| `tspi-report` | 由证据绑定的报告包 | 从有效工作区构建报告 |
| `tspi-email` | 固定目标通知投递 | 发送由回执绑定的研究更新 |

每个 Skill 都提供英文 `SKILL.md` 和中文 `SKILL.zh-CN.md`。跨领域合同由
编排 Skill 负责；领域 Skill 不复制这些合同，也不获得修改规范化状态的权限。
