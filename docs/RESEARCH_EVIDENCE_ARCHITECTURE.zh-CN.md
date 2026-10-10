# 研究对象、执行证据与当前判断

Research Memory 保存研究过程和解释，不裁定科学真伪。Pi 继续负责 Agent 循环、工具调用及会话；这些能力不属于 Research Memory；已有工作区不会自动迁移。

## 对象与结论

Node 和 Result 的可选 `subjects` 将领域对象的不可变 Artifact/Result 引用命名为 target、calculated 等角色。引用只证明对象明确存在，不证明其内容正确；Node 与 Result 的角色由调用方明确提供。领域工具生成及对照结构身份，Memory 不读取 SMILES 或 Gaussian。

Chemical 的 inspect/seed 输出 `chemical-identity/1`，对规范异构 SMILES、电荷及 RDKit 版本生成身份摘要，原子编号不影响规范身份。`chemical.compare@1` 通过具名 target/actual 输入比较结构 JSON 或 XYZ。XYZ 必须给出实际电荷，键级推断方法明确写入结果；立体化学未确定时返回 indeterminate。比较范围不包含机理或能垒。

Result 的 observation 是记录的观察，conclusion 是作者解释，check_refs 引用具体检查材料或收集回执。验证回执中的状态由执行结果提供，不能通过发布 Result 的参数伪造一个 pass。检查失败或未确定不阻止保存研究判断。Artifact 类型的 check_ref 保留原始材料引用，不被 Memory 自动认证为验证器结论。

## 来源、解析和检查

执行器请求的 input_roles 记录每个输入角色的暂存路径和摘要，提交时与实际暂存声明核对。既有 Job 输入清单、资源摘要、环境观察、命令及不可变收集回执继续形成来源记录。验证器回执分别展示 execution_status、parsing、scientific_verdict（若验证器提供）和 provenance；来源验证不代表科学正确。

Gaussian 标题摘要是附加交叉检查。解析器支持已知标记的有界续行，包括历史 CoRAgentSpec，不对整份日志删除空白后匹配。缺失、无法读取和实际摘要不一致分别表达；原始证据保持不变。聚合 verdict 保留保守语义，scientific_verdict 另列已完成的科学条件检查，两者均注明范围。显式 Gaussian runner 的结果也分别记录执行、解析和请求检查状态。

Skill 指导 Agent 审查证据、记录缺口并选择下一步；某个自写验证器失败不构成禁止继续研究的通用门槛。原始材料缺失、引用不合法、暂存摘要不一致等工程约束仍严格检查。

## 统一受管 Python 入口

执行声明通过 module_paths 声明随 Job 暂存的导入目录，目录必须属于声明的资源闭包。准备器、提交校验和目标侧启动共同使用受摘要保护的 python_entrypoint.py。启动器只依赖标准库，独立于控制端包；设置入口与声明目录后运行脚本，加载失败返回结构化诊断。已登记的化学执行器和验证器均走此入口，新增声明可显式选择同样的方式。直接脚本调用保留兼容路径。

CF22D doctor 在错误处理范围内加载依赖，区分依赖缺失与方法初始化失败。诊断不执行 SCF，普通测试无需调用真实模型或科学求解器。

## 修订与需复核提示

发布 Result 时同时提供 as_assessment=true 和 progress，即把新结果、当前判断选择及进度作为一个原子修订。必须读过对应 Node 字段；冲突时全部不保存。普通发布不带 progress 时保持既有语义：结果可保存，而当前判断选择单独报告冲突。supersedes 显式标记纠正对象，不改写历史记录。

新 Result 保存发布时的节点上下文摘要，已有 basis_refs 保留引用来源版本。读取 Result、当前判断卡片与生成的 Markdown 时派生需复核提示：节点上下文变化、引用结果被替代、外部节点来源版本变化。单独追加笔记不会替换进度，也不会据此判定旧结果错误。

报告作为 Result 保存其 files 与 inputs/evidence_refs，使用相同的时间、来源和需复核机制；普通散落的 Markdown 文件不会被框架自动解析或重写。旧 Result 没有上下文摘要时不会伪造一个历史版本，只能根据已有引用发现替代关系。

## 验证

使用统一 tools/test/runner.py，在 local_debug 下进行确定性测试；不导入既有研究工作区的数据。回归覆盖位置异构体、原子重排、XYZ 推断、摘要折行与截断、解析失败、独立启动、真实本地比较 Job、输入角色摘要篡改、失败检查仍可发布、原子修订冲突及报告引用过期。全套验证同时检查生成协议、资源清单、原生 Pi、wheel 导入和服务清理。
