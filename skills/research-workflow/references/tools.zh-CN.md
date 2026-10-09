# Job 与材料流程

按已安装领域 Skill 准备请求，把返回的 request_file 和 request_sha256 交给 job_start；用 node_id 明确研究归属。其它执行字段已固定在请求文件中。直接 argv 提交需声明实际输入、输出和平台。准备与诊断允许不关联 Node。

适配层在提交时固定 Node 版本和实际输入；后来修改方案不改变旧 Job 检验的内容。Job Runtime 是派发和终止事实的来源。job_status 查看、job_cancel 请求取消、job_reconcile 协调不确定性、job_collect 保存输出和来源，重复收集不会重新执行。

artifact_create 保存新文本，artifact_register 导入文件，artifact_read 有界读取。科学 Job 的输出通过收集保留生产身份；分析请求声明并暂存实际输入；验证器作为普通 Job 运行。读过文件不自动成为科学证据使用。

research_update 用 node_id 与 note 解释变化；有可引用产出时，research_result 用 node_id 与 conclusion 发布。结果文件引用已登记 artifact_ref。工作目录保存可修改草稿，正式结果关联固定材料。调用 Job 或原生文件工具前不需要研究生命周期转换。
