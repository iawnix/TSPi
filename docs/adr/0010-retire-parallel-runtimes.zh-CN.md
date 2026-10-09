# ADR 0010：清理平行运行时与旧 State 实现

- 状态：已接受
- 取代：ADR 0007，以及独立科学能力 ADR 中的 capability 调度实现
- 修订：ADR 0001、ADR 0003 的代码实现说明

## 决定

保留实际生产链：安装启动器 → Native Host/Pi Harness → 当前 Research State 与 Job Runtime。
删除仅由自身导出、孤立测试或打包白名单维持的旧实现，不再建立兼容 facade。

删除范围包括旧 AppServer/composition/client、独立会话与 context/memory store、turn router、
agent-pi-adapter、Compute/Review 协议和聚合器、通用 JS/Python Provider 执行层、
research-compute，以及平行 typed State 模型。

ResearchMap 的领域概念继续保留；实际写入、校验和视图由 agent_workspace.py、共享操作
合同、不变量和 projection.py 负责。删除旧 Python 类会改变旧导入接口，不改变规范工作区格式。

保留实际生产消费者：

- Workspace 校验、模式策略、身份和 Research State bridge。
- Native Host 活动记录和规范 ResearchMap reader。
- 连接现行 Host 的鉴权浏览器网关；无鉴权 HTTP adapter 和直连 Pi 网关已经删除。
- 原有持久计数器与 CLI ID 分配能力，迁入 research_state.operational_ids。
- research_web_bridge.py 中 TS Web 使用的 research-map-provider/1 JSONL 服务。
- 第三方扩展的 provider 发现元数据；它不提供通用执行调度。

## 验证与发行边界

旧实现的专属测试随代码删除；当前合同、工作区初始化/恢复、执行身份和 State 准入的测试
保留或迁移。清理后验证实际 Native Worker、Host/HTTP、Web JSONL 与已安装 wheel。
测试数量减少对应旧实现退出，不降低现行验收规则。

共享发行清单、npm package、Python wheel/bootstrap 映射和架构检查同步收敛。
源代码和包检查拒绝已淘汰路径重新进入，避免旧 glob 重新携带过时代码。

既有工作区、Job/证据回执及通知身份不改写，本清理不执行部署或数据迁移。
历史方案明确标为历史记录，现行架构和 Skill 只描述保留的可执行路径。
