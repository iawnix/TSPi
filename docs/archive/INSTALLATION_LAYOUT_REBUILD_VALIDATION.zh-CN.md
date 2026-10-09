# 新安装布局验收记录

> Historical archive / 历史归档：本文记录旧设计或一次性验证，不是当前接口合同，也不代表本次重构已通过验收。当前设计见 [Research Memory plan](../RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md)。

日期：2026-10-07；应用版本：0.18.0；安装布局：`research-agent-installation/2`。

## 实现范围

- 唯一公开客户端 `ResearchAgent`，内部 Host 由 systemd 启动；删除公开 `ResearchAgentServer` 和 `bin` 链路。
- 唯一 `current` 选择 `releases/<id>`；配置在 `etc`，持久状态在 `var/state`，日志在 `var/log`，可清理缓存在 `var/cache`。
- Pi 固定依赖在 `runtimes/pi/<commit>`；Host Conda 基础环境和应用 wheel overlay 位于独立软件环境根，安装配置持久记录其位置。
- Python 启动器、安装器和卸载器复用同一标准库布局模块；Node 接收已解析路径。移除旧安装路径与 Job 配置祖先搜索。
- 安装互斥覆盖环境准备和发布；失败恢复 current、安装回执和环境绑定。安装过程不扫描旧研究工作区。
- 默认卸载保留配置、持久会话、工作区和环境，移除活动版本选择回执后允许重新安装；明确清理环境时校验归属。

## 自动化验证

所有安装和测试环境位于 `/home/iaw/debug/tspi-test-env`。

| 验证 | 结果 |
| --- | --- |
| Python integration/unit/contract 全套 | 426 通过，1 跳过 |
| 最后补充环境根限制后的 layout/suite_release 回归 | 16 通过（含 2 个新增用例） |
| Node native/fast | 88 通过 |
| 架构、Skill、公开术语检查及 diff 空白检查 | 通过 |

Node 测试包含真实固定版本 Pi Worker 与本地模型 fixture：Skill 准备、checkpoint、Host 重启恢复、Job 执行、Monitor 投递与去重、结果收集、邮件配置检查以及用户等待停止。邮件发送行为由隔离 fixture 验证，不向真实收件人发信。

## 安装包实测

隔离安装实际启动内部 Host 和 Worker、创建并读取会话；停止 Host，清空缓存后重启并读取原会话。安装根未生成 `.pi`、`.agents`、`bin` 或公开 `ResearchAgentServer`。默认卸载后，配置、会话和工作区的文件摘要保持一致，安装器识别为可重新安装。

证据目录：`/home/iaw/debug/tspi-test-env/layout-rebuild`，包括 `python-final.log`、`layout-final.log`、`node-final.log`、`installed-smoke.log`、`uninstall-smoke.json` 和 `preservation.json`。测试 Host 在 finally 中停止；没有创建测试 systemd unit。

## 生产安装边界

旧应用已停止并归档；原有 423 个工作区文件在卸载阶段摘要校验一致。生产重新安装从干净提交构建，不接入旧会话、请求回执、Monitor outbox 或自动接续。仅重新配置明确的软件绑定及凭据，不恢复整个旧 `.pi` 或 `.agents`。不提交、取消或重投历史科学计算，也不以本次安装验收证明科学计算成功。
