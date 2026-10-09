# 存储与恢复

工作区 manifest 使用 `research_workspace/2`。原始要求、研究修改和执行观察区分来源。Python 命名空间统一为 `research_agent.research`，没有并行 state 或全局 progress 协议。

Node 身份稳定，工作目录位于 `research/nodes/<node_id>/`。不可变 Result 固定它所对应的 Node 版本和实际依据。记录保存历史；索引、反向关系、工作区/Node Markdown 与预算内检索都是可重建视图。修改组织关系不移动目录。

`operations/` 保存运行时负责的派发、收集和投递回执。`artifacts/<id>/payload` 及 manifest 保存固定文件及来源。可变工作文件应先登记，再成为正式产出。Pi 保存会话历史；Memory 跨会话存在，但不替代会话记录。

受管研究数据经公开工具写入，工作文件用原生文件工具。事务保证一致更新，请求回执用于重试恢复。未知派发结果用原身份协调，不换 Job 重发；未知邮件投递由邮件回执处理，修改 Memory 不得触发重发。

旧工作区不支持、不迁移、不改写。新建工作区并显式导入材料。引用错误应读取现有对象，不自行编造 ID 或回退路径。
