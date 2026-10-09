# Research Memory 架构

实施状态：本文保留既有 Research Memory 语义，并描述 ResearchAgent 当前模块边界。此前 Research Memory 验收不代表本次重构已通过；当前进度见[实施记录](RESEARCH_AGENT_REFACTOR_STATUS.zh-CN.md)。

## 所有权

ResearchAgent 只使用 Pi 原生 Harness 循环。Workspace 是跨会话存在的研究容器；Research Memory 组织原始要求、局部问题、多次尝试、显式关系与产出，不负责科学调度或自动证明结论。

| 组件 | 负责 |
| --- | --- |
| Host / Agent Server | 工作区准入、认证输入、会话绑定、请求身份、next_run 调度 |
| Pi session | 对话、模型请求、原生工具和输入消费 |
| Research Memory | Workspace 存储合同、原始要求、Node、不可变 Result、显式研究关系 |
| Job Runtime | 派发、执行、取消、协调和收集回执 |
| Artifact Store | 不可变文件及来源 manifest |
| Monitor | 执行事件、outbox、重试和固定投递目标 |
| Email Skill | 已授权报告投递、附件固定和运输回执 |
| 检索 / Web | 可重建的预算内视图、排序理由和只读导航 |

唯一研究命名空间是 `research_agent.research`。运行适配层组合 Memory 与 Job/Artifact DTO；Memory 不导入执行器或 `research_agent.application`。共享事务和文件 IO 属于 `research_agent.foundation`。`runtime-bridge` 只传输命令，不维护另一套文件模型。

## 研究模型

Node 承载持续推进的局部问题。goal 是问题，proposal 是当前假设或思路，plan 是调查方案，progress 是进展说明。假设可为空；调参数、换构型、同目标重试通常留在原 Node。独立问题才另建 Node，不要求模型创建 Attempt 对象。

Node 状态为 open / paused / closed。关闭表示停止主动推进，不表示科学成功，也不取消 Job。内容修订号独立于后台执行观察；并发修改需要重新读取并明确合并，单纯追加笔记不覆盖其他人的判断。

Result 固定有价值的观察、判断、限制、输入版本、证据和文件，可为否定或证据不足。Result 不可变；用 supersedes 明确修正并保留旧版。Node 的 assessment 是明确选定的综合判断，不默认采用最近结果或失败。上游修正产生精确复核提示，不暗中替换下游输入或重新计算。

## 关系与来源

part_of、requires、alternative_to 由 Agent 明确声明，单次保存；反向关系与 map 索引自动生成。包含关系不能成环；反馈和竞争路径不要求整个 map 是 DAG。相互等待产生诊断，不成为工具准入关卡。

uses / cites 必须来自确证材料输入或明确结果引用。文件名相似、字节相同、浏览或检索均不能证明采用了某个科学来源。Result 引用具体的既有版本，研究反馈不造成证据循环；无法证明的来源保持未追踪。

## 模型接口

| 工具 | 最小请求 |
| --- | --- |
| research_read | `{}` 读上下文，`{ref}` 读精确对象 |
| research_search | `{query}` |
| research_create | `{goal}` |
| research_update | `{node_id, note}` |
| research_result | `{node_id, conclusion}` |

更新可按需修改思路、方案、进展、状态、综合判断及关系。结果文件引用已登记 Artifact。Session、工作区、请求身份、读取依据和版本由可信适配层提供；模型不维护事务字段、反向边或全局 progress。没有回合末 checkpoint 或强制 disposition 补写。

## 工作区与存储

`workspace_manifest.json` 使用 `research_workspace/2`。研究记录保留用户原文，并区分研究作者和运行事实来源。`research/nodes/<id>/` 保持稳定目录、当前视图与工作文件；不可变结果和历史保存旧版本。索引、反向查询与 Markdown 可重建，改标题或关系不移动目录。

`runs/jobs/` 是执行工作目录；`operations/` 保存意图、观察、收集/投递回执和精确短引用；`artifacts/<id>/payload` 及 manifest 保存固定文件及来源。可变工作文件登记后才能成为正式结果材料。报告仍是面向用户的文件，实际交付版本固定。

事务保证完整更新和中断恢复。旧图与 notebook 工作区均明确拒绝，不迁移、不改写。新建工作区并显式导入材料，没有双协议读写层。

## 上下文与 next_run

上下文预算先保留原始要求与认证触发原因，再按事件归属、明确焦点、待处理执行事实和研究关系选择 Node，并补充必要的结果及直接依赖。省略内容提供读取/检索入口，不视为完成。普通用户文本不能冒充 Monitor 元数据。

研究 Job 提交时明确绑定 node_id 和已读方案版本；准备与诊断可以没有归属。Monitor 事件跨 Node 修改和会话重启保留提交时关联。

next_run 是实际调度模式：持久化认证执行事件，会话忙或自动执行暂停时保留；可接收时幂等提交一次 Pi 输入。事件保存、Pi 消费和科学解释是不同事实。回复丢失沿用请求身份；固定批次重试时不吸收新事件。普通笔记、Node 状态和 Memory sequence 不触发或抑制投递；没有新事件就不会因 Node open 自行续跑。

## Skill 与交付

Pi 原生加载 Skill。ResearchAgent 验证安装资源摘要。使用 Pi 提供的真实 Skill 路径，相对引用以该 Skill 目录为基准。research-memory 教五种小操作，research-workflow 协调 Job 和材料，领域 Skill 提供科学方法。reaction_mapping.md 位于 chemical-input/references/。

进程完成、文件存在和 Node 关闭都不证明科学结论。Email 使用已有用户授权和独立投递回执；运输接受后 Memory 记录失败，只恢复记录，不重发。安装、运行和科学结论分别需要对应证据。
