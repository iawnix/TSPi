# t007 Skill 访问与重复续跑修复验收

日期：2026-10-07（北京时间）。已安装版本：`0.17.0-sha256-046bf546f4d2c0f9`。

## 修复范围

- 收尾判断同时识别 lifecycle 和 disposition。历史投影中的 `decision_needed + user_input_required` 表示等待用户，不触发缺失处置补救；等待用户可以完成当前 Research Turn，自动 wake 不得越过等待门禁。
- Worker 在 Harness 生命周期内复用 checkpoint Hook。补救次数按 session/run 分配持久事务槽，返回续跑前预留；相同 revision/决策范围不重复补救，达到上限后不清零。重启及并发调用复用同一记录。Worker 默认最多补救一次；预留后崩溃可能消耗该次额度，优先避免重复续跑。
- Skill 读取范围来自实际加载的核心/扩展 Skill 路径及校验后的共享资源清单，支持 references/scripts。未放行整个 extensions 目录；符号链接到包内私有实现仍被拦截。
- 更新中英文 research-state、orchestration、method-selection、email 指引，明确先创建 Claim/Node 再记录策略；方法已确定时仍使用配置生成执行请求；邮件先无发送检查配置，交付失败只阻塞交付范围。清理编排入口和相关引用中的旧通知、analysis capability、launch/inspect 说明。
- 缺少策略或引用未知 Claim/Node 的错误提供可执行的恢复指引；科学方法仍由 Skill 实现，未增加科学 Provider/Capability 路由。

## 验证

全部测试文件、安装包与日志位于 `/home/iaw/debug/tspi-test-env/t007-repair`。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| Python unit + contract | 168 项通过 | pytest.log |
| Node 生命周期、补救持久化、读取保护、扩展加载、Monitor 定向测试 | 29 项通过 | node-final.log |
| 真实 Worker 启动及完整行为验证（安装包） | 2 项通过 | installed-worker.log |
| 源码完整 Worker 行为验证 | 通过 | flow.log |
| Skill frontmatter、架构、术语、打包与发布验证 | 通过 | build.json / build.log；检查命令输出 |
| 生产 Host 版本、t007 会话及 Monitor | 正常，Monitor 无错误 | host-verified.json |

完整行为测试使用本地 HTTP 模型桩驱动真实 Pi Worker：读取核心与科学 Skill、引用和共享脚本 → email check 复用配置收件人 → 创建 Claim/Node → Strategy → 提交通用 Job → 收集并登记 Artifact → 缺少处置时一次补救 → 写入等待用户 checkpoint → 停止。未调用外部模型 API、真实科学计算或 SMTP。测试服务器、Worker 和隔离目录均已关闭清理；生产 Host 按安装要求继续运行。

## t007 状态恢复

恢复前备份位于 `before-install/t007` 和 `before-install/session.sqlite`。保留历史会话、失败调用和旧 checkpoint，没有直接改写 canonical JSON 或 SQLite。

通过安装版本的正式 `checkpoint`、`apply_change` 和 Artifact 接口执行恢复：

1. 运行 email Skill 的无发送 check，确认配置启用且存在收件人，结果保存至 t007 的 reports/email-check-repair.json。
2. 恢复前缺少策略，不能直接写 continue_required；先以 deferred checkpoint 明确短暂维护状态，再补齐策略。
3. 创建 strategy_t007_repair，并新增依赖计算结果的 node_delivery，隔离邮件交付。
4. 登记配置检查 Artifact 和 Finding；没有将这些配置事实表述为科学结果。
5. 写入 checkpoint_repair_ready。当前 revision=4，disposition=continue_required，strategy=1、artifact=1、finding=1、attempt=0。

原始六组计算尚未重新提交，也未发送邮件。当前状态允许后续 Agent 回合继续原任务，方法级检查、真实计算及结果交付仍属于原研究任务；本次验收证明修复的访问、执行集成与收尾行为，不声称六组科学结果已完成。
