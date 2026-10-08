# t003 可靠性改造：候选实现与验收边界

源码基线：`4e17f8c6`。代码、规划及验证记录一并提交，尚未部署。本记录对应不兼容旧契约的直接升级方案；生产 `/home/iaw/ResearchAgent` 的程序、Job、ResearchMap 和会话均未修改，也未发送邮件。

## 已实现行为

| 原问题 | 当前确定性约束与验证位置 |
| --- | --- |
| F1：locate/detail helper 缺失 | 修复查询；增加 Attempt、Artifact、解释、策略详情，分页定位与证据过滤。`test_reliability_contract.py`、Native 命令测试。 |
| F2：Gaussian `Ti ght` 折行误报 | 只修复已知输出折行，不删去所有空白；真实参数差异仍拒绝。`test_gaussian_explicit_input.py`。 |
| F3：跨 Job 输出被当作当前失败证据 | 强制直接/比较/背景角色、Attempt 归属和执行过的派生谱系；最终解释绑定当前结果回执。伪造生产者、过期回执拒绝。 |
| F4：Job 已失败但 Attempt 未结束 | status/collect/reconcile/Monitor 统一写观察；Monitor 在同一事务提交 Attempt 与 outbox。UNKNOWN 和终态冲突阻止全局终态，显式 reconcile 保留记录。 |
| F5：反复猜 Job ID | 精确 job/attempt/event selector；确定性错误缓存；三次错误后，变换不存在的 Job ID 也不再访问执行后端。查询可恢复，合法其他 Job 可继续。 |
| F6：重复计算 | request_id 重放复用 intent；同身份异参拒绝；新身份的精确内容重复要求前驱、原因、预算。准备输入复制前后校验摘要。 |
| F7：context 被旧 Artifact 挤满 | `research.context` 改为有界投影；每次 Native 模型请求注入一次最新快照，不累积到 transcript。保留目标、约束、当前事件及对应 Attempt。 |
| F8：压缩保留错误解释、Gate 缺失 | 当前事实从 State 重建；解释可被更正并标记失效。计算前登记 Gate 或创建时的豁免理由，机器条件须有执行过的验证器回执；条件修订及输入更新使旧评估失效。 |
| F9：不支持的 Node evidence subject | 文档明确 Node 使用 `artifact_refs` 关联；没有为单个案例扩展公共证据 subject。 |

收集事务将 Artifact 登记、结果回执和 Attempt 投影一起提交；不可变 payload 可先落盘，但未提交的文件不获得 State 证据身份。新增收集崩溃回归验证 redo 恢复三者；已有 Monitor 崩溃回归验证状态和通知共同恢复，不重新计算。

公共层只检查身份、版本、事务、证据角色和生命周期。Gaussian 输入边界、失败分类与频率算法全部留在 chemical 扩展。当前注册的 `chemical.gaussian_frequency/1` 仅验证解析结果中正常结束和一个负频率，不能证明振动方向、电子态、几何或 IRC 连通性。其源码摘要、实际执行、输入结果版本与输出摘要均进入回执；旧版本 Artifact 不能冒充最新输入。

## 契约切换

- 工作区、ResearchMap context、liveness、checkpoint 使用 `_2` schema；旧 `_1` 工作区在入口拒绝。
- 公共研究/Job/Artifact 字段统一为 snake_case；删除 camelCase 参数及解释/策略/检查点的顶层字段自动补齐。解释使用嵌套对象并必须声明 `kind`。
- 决策视图使用 `research-decision-context/2`，locate/decisions 使用 `/2`；collect 提供持久 `job-result/1`。
- Pi 自身 API 的 `sessionId`、`requestId` 等保留在适配边界；这不构成 TSPi 双字段协议。
- 同一新版本内部的幂等、崩溃重放和审计保留。不提供旧会话续接、旧业务 schema 读取或迁移工具。
- State 仅保留 `register_attempt`、`register_artifact`、`transition_attempt`、`link_evidence`、`create_strategy_plan`、`create_strategy_review`、`create_interpretation` 的单一操作名；删除对应 create/update/register 同义入口和旧字段回退。

## 本地验证与可复现记录

所有环境、缓存、安装包与日志均在 `/home/iaw/debug/tspi-test-env`。固定 Pi 源码为 v1.0.4、commit `7c10bd4337495ee613f2224843ecdf349b80d1df`；Native 使用实际 Harness/Worker、数据库、Host 重启及 Monitor 唤醒，模型响应由确定性 provider 提供。

最新执行记录位于 `/home/iaw/debug/tspi-test-env/t003-reliability/logs`：

| 检查 | 证据 |
| --- | --- |
| Python 全量源码与 wheel 回归 | `python-final.log`；`wheel-source.log`、`wheel-source.json`。最终 wheel 全量 476 项通过，显式移除源码包的 pytest pythonpath，并在 pytest 收集前绑定全部核心 namespace，断言导入来自隔离 wheel。 |
| 维护中的 Native 集成 | `native-final.log`：84 项通过；实际 read 工具结果被截断后，后续请求仍有目标和当前 Node；压缩保留旧 QPErr 文本时，新请求同时含正确失败事实。 |
| 类型、公开契约、架构、Skill 完整性 | `typecheck-final.log` 及 public/architecture/skills lint。 |
| 打包与独立安装 | 测试目录 `candidate/tspi-release.json`、`logs/install.json` 和 `logs/installed-native.log` 为候选包与实测记录入口。 |

安装验证还修复了一个原有测试盲点：conftest 的 bootstrap 会插入 checkout 路径，导致旧 wheel 测试实际混入源码。收紧导入来源后，发现 calculation contract loader 依赖源码目录层级；现已改为从模块旁的 contracts 目录读取，源码与 wheel 使用同一资源位置。

额外执行未纳入维护 manifest 的历史 Node 测试：当前 91 通过、9 失败；同环境基线为 89 通过、10 失败。剩余失败均属于基线已有的已删除模块引用、旧 composition/Host 方法或缺少真实 Finding 证据的 fixture。记录分别为 `node-broad-final.log`、`node-baseline.log`。这批测试没有全绿，也没有为迁就旧测试恢复兼容接口。

## 真实模型对照

增加显式 opt-in 的 `live-eval` 场景入口。它读取现有 provider 配置，在测试目录复制配置后运行，并在 finally 删除临时凭据；发送给模型的只有合成研究事实，没有生产 t003 材料。没有给评估模型执行、邮件或任意文件工具。

使用用户配置的默认 `CPA/gpt-6-luna`，每批三个场景、每场景有/无当前投影各一次，输出上限每次 1,000 tokens，单次超时 90 秒。捕获原始请求、回复、预算及用量。

- 首批 `live-eval.json`：当前投影下关键判定 2/3 正确。UNKNOWN 场景仍选择泛化的 validate，并把 Attempt ID 填入直接证据字段。
- 为 UNKNOWN/冲突的受管 Attempt 增加由代码生成的 `job_reconcile` 精确恢复入口后，第二批 `live-eval-recovery.json` 的关键动作 3/3 正确；无投影对照为 1/3。两批总用量分别为 1,527 和 1,455 tokens。
- **第二批仍有一次将 Attempt ID 当作 Artifact 的错误**。动作正确不等于整个决策合法；严格重评分保存在 `live-eval-recovery-scored.json`，整体评估未通过。评估脚本同样单独计入无效证据身份。State 的类型/存在性/生产者规则负责拒绝这类写入，不能依赖提示词保证。

这只是当前契约的上下文消融与恢复提示试验，尚未完成旧/新运行时端到端比较、多轮工具恢复率、随机重复或长程科学研究评估。因此不能宣称模型已能稳定自主把控研究方向，也不把 Native fake provider 测试称为真实模型成功率。

复现入口（提供测试根下输出路径）：

```bash
TSPI_TEST_PI_RUNTIME_ROOT=/home/iaw/debug/tspi-test-env/tui-repair-pi104 \
  /home/iaw/debug/tspi-test-env/bin/python tools/test/runner.py live-eval -- \
  --agent-dir /path/to/authorized/pi-config \
  --output /home/iaw/debug/tspi-test-env/t003-reliability/logs/live-eval-new.json
```

## 尚未覆盖的保证

1. 通用 fingerprint 检查精确执行内容；不认定 route 换行等化学语义等价。无法确定可执行程序/环境版本时标记不完整，不承诺环境相同。
2. Native 预算采用保守字节估算；关键范围放不下会明确失败并禁止新执行/最终解释/终态提交，需压缩或缩小 focus。没有 tokenizer 精确测量；尚未实现按对象的通用 CAS。现有 `expected_revision` 和回执/Gate 依赖版本检查继续生效。
3. 验证器目前从安装包内的 extension manifest 发现；没有扩展到任意外部插件目录。公共包不反向导入化学代码。
4. 本轮没有新增通用网络退避框架；身份错误与网络错误不共用缓存。真实远程调度器的断连、PID 消失及取消竞争仍需独立 smoke。
5. 崩溃前只留下暂存目录、没有提交 intent 时，会明确报 orphan staging 并要求检查，不能据目录存在推断已执行；不会自动重新派发。
6. 已有工作区只支持 research 模式；不新增计划中提及的 light 分支。生产 Gaussian 的 114/200 步差异未被本次代码修改解释，也未重新计算。

## 直接切换步骤（尚未执行）

1. 根据候选 manifest 校验归档和 wheel 摘要，以完整候选版本准备独立安装；禁止只覆盖几个 Python 文件。
2. 盘点旧工作区的本地/远程活动 Job，按授权等待或取消并核实。随后停止旧 Host/Monitor，保留原程序及配置快照。
3. 使用一致的 SQLite backup 与文件清单归档 t003。已有离线审查在测试根 `t003-review-20261008`；完整生产归档尚未执行，不把修改后的 State 伪装成历史事实。
4. 新建安装状态目录、workspace、会话库和 outbox；不扫描接入旧工作区、不续接旧会话、不重放旧事务。
5. 用全新通用文件任务验证初始化、Job→Attempt、Monitor、collect、Gate 与请求投影；确认后再决定是否开始新的科学研究。
6. 部署失败时停止新入口，恢复隔离的“旧程序＋旧状态”整套快照；新版本产生的数据单独保留，不交给旧程序读取。

当前可交付的是源码、测试和候选包；生产切换、完整历史归档以及继续科学计算仍为独立后续动作。
