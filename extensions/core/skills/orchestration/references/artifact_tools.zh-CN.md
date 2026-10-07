# Artifact 工具

参数以注册工具 schema 为准。`artifact_create` 保存提供的内容；`artifact_register` 登记已有工作区文件，可绑定生产它的 Job 和 Node；`artifact_read` 读取已登记证据；`artifact_link` 持久关联 Claim、Finding 或 Gate。

`artifact_derive` 只保存派生描述，不执行分析或生成科学结果。结构生成、比较、解析和报告应由对应 Skill 脚本通过通用 Job Runtime 执行，再登记真实产物；不要求分析 capability 注册目录。

引用前核查内容、摘要、生产来源和单位。登记文件不代表计算收敛或 Claim 成立，应按 Skill 验证规则解释证据，再写入 Research State。
