# 能力驱动研究首版验证报告

日期：2026-09-16。对应[实施规划](PLAN_CAPABILITY_DRIVEN_RESEARCH.zh-CN.md) M0–M7。

## 交付范围与结论

实现了 22 项独立科学分析能力、按需能力目录、可重算的候选事实登记、Node 暂停/
恢复、finalize 默认输出推导，以及报告/Web 来源联动。保留细粒度 ResearchNode、
Claim/ProofSpec/Acceptance 的原有语义，没有固定化学流程或自动下一步路由。

本轮验证支持在明确边界内使用这些能力。它没有验证真实反应机理的普适正确性，
也没有证明行政 token 降低 25%。异步作业便利层是原规划中的条件项；本轮未获得
支持引入它的维护负担基线，因此未增加该层。

| 里程碑 | 首版交付与验证 |
| --- | --- |
| M0 | 静态协议基线、七类真实模型任务、逐次调用与错误记录、ADR 0002 |
| M1 | 候选自动展开、直接来源 digest 推导、模板 title、默认主输出、精确字段错误、Node 管理 |
| M2 | 共享 `ts_analyze`、版本化输出、Activity、重算校验、Python wheel 与原生工具接入 |
| M3 | 多组分守恒、同位素/电荷/电子态、映射歧义与截断、键变化、结构重排/布置 |
| M4 | Gaussian 输入/输出、模式耦合、路径候选、IRC 起点与目标端点绑定、步骤证据审计 |
| M5 | 显式条件/模型热化学、标准态、正反势垒、一级/二级 TST、受限初始分支 |
| M6 | 计量超边、可逆循环、平行路径、能量曲线、来源表、只读 Web 与 Node 派发状态 |
| M7 | 真实模型试用、原生进程恢复、wheel 安装、远端小体系 smoke、运维说明及本报告 |

## 自动化与安装验证

完整 wheel 环境测试使用 `scripts/test_source.py` 构建并安装当前源码 wheel，在
隔离 overlay 中运行全部测试。初次发现的操作目录预期、模块反向依赖及命名问题
已修复。最终完整回归 **698 项通过，0 失败，0 跳过**，耗时 72.99 秒；记录位于
本机证据根目录的 `source-tests-complete.json`。

原生 Pi App Server 的 10 项测试全部通过，没有跳过启动测试，覆盖固定源码入口、
会话持久化/重启恢复、公共工具、分析 Activity、通用分析与暂停/恢复。TypeScript
typecheck 和公共接口检查已通过。源码准备会补齐模型数据和 workspace build 产物，
避免只完成依赖安装却无法启动。
包清单检查覆盖 341 个文件；mechanism Skill 的结构校验通过。

科学反例包括：SN2 对称氢映射、质子/同位素/电荷不守恒、电子数与自旋不匹配、
非法反射变换、缺失/错误振动谱、错误 TS 来源和目标盆地、热修正条件或几何不兼容、
相关方法误用参考 SCF 能、G 与 E 混用、错误标准态/反应级数、分支假设不满足、
缺失共反应物、循环/平行步骤、无效证据传播、候选/来源/生成文件篡改。

验证环境：Python 3.11，NumPy 2.4.6，ASE 3.29.0，RDKit 2026.3.6，jsonschema
4.26.0，xyzrender 0.3.8。测试发现本机开发环境缺少已有 requirements 中的 xyzrender，
已补齐其依赖并通过真实 runtime probe。Pi 固定为 0.85.1，源码 commit 为
`d981de1229ef899957bbe968bc8dcda02a21f477`。

## 真实模型行为试验

使用现有 CPA provider 的 `gpt-5.5`，真实调用原生 `ts_state/ts_analyze/ts_change/
ts_manage` 和受限文件读取工具。每例独立 workspace；不提交远端科学作业。
输入中的 TS/IRC/能量是明确标注的合成 fixture，不能用于接受真实化学 Claim。

共进行了三个有记录的阶段：

更早的 `live-evaluation.json` 存在评测器包根路径和输入范围设置错误，已排除，
不用于科学完成率或协议负担统计。

1. 初始小基线：仅反应定义重复 3 次，每例最多 10 个模型回合，自动条件完成 1/3，
   错误数分别为 4、1、5。样本不足以代表全部任务。
2. 中间试验：七类各 3 次，每例 10 回合，自动条件完成 14/21。在这轮发现多输入
   候选来源顺序、手填 provenance/digest、局部引用等问题。部分试验运行期间有修复，
   不能将本轮视为冻结版本的严格对照。
3. 修复后试验：七类各 3 次，每例最多 16 回合、每次输出最多 2048 tokens、请求
   超时 90 秒。自动“指定能力覆盖且有最终答复”条件完成 19/21；逐条复核交付物后，
   21/21 满足各自这项小任务的要求。

两次自动未计入的是 IRC 只读总结：Agent 直接读取原始日志，准确报告方向、端点、
完成标志和证据限制，没有调用 `path.endpoint_summary`。这符合用户任务，因此
复核计为完成。自动能力覆盖指标保留原值；不将它伪装成独立科学判分。

| 场景 | 自动覆盖并答复 | 交付物复核 | 每次工具错误数 | 每次工具调用数 |
| --- | --- | --- | --- | --- |
| 只有反应定义 | 3/3 | 3/3；保留六个等价映射 | 0、1、3 | 14、10、17 |
| 已有 TS 输出 | 3/3 | 3/3；提取模式并说明 IRC 缺口 | 0、0、0 | 17、10、11 |
| 仅 IRC 总结 | 1/3 | 3/3；两次合理直接读取 | 0、0、0 | 2、2、5 |
| 映射歧义 | 3/3 | 3/3；没有擅自选定映射 | 0、0、1 | 3、3、5 |
| 失败候选后准备输入 | 3/3 | 3/3；只构造输入，没有启动作业 | 0、0、0 | 8、8、7 |
| 两条竞争路径 | 3/3 | 3/3；约 11.74%/88.26%，限制为初始分支 | 1、0、0 | 15、11、14 |
| 暂停、查看、恢复 Node | 3/3 | 3/3；同 Node 恢复、科学记录不变 | 0、0、0 | 3、4、4 |

修复后共 173 次工具调用、6 次工具错误，均恢复后完成。错误包括路径抄写、
artifact binding 形状和额外 `template_ref` 字段；一处 Skill 相对路径失败来自
评测读取器，读取器现已支持包内 `skills/` 路径。保留原始错误计数，不追溯抹去。

行政参数字节总计 22,672，总工具参数字节 35,461。provider 返回累计 input
234,211、output 30,262、totalTokens 818,457；这些字段沿用 provider 的口径，
脚本没有细分缓存等计费字段，不能把它们解释为精确行政 token。回合预算改变，
基线又很小，因此本报告不声称固定比例的 token 或完成率提升。

模型试验尚未覆盖真实计算在途时的自然语言干预、多人并发、长期大网络、多个模型
或复杂开放壳层反应。提交边界、未知提交/取消、状态恢复由确定性测试覆盖。

## 真实远端小体系 smoke

选定 profile `cluster_1w`，主机 `agent.1w`，独立 workspace
`ws_a2193e49f928435282c60306`。doctor 的软件与依赖检查通过。每个任务限制为
2 CPU、1 GB 内存、10 分钟 walltime，使用 batch 队列。

| 能力 | 作业 ID | 实际结果 |
| --- | --- | --- |
| Gaussian opt/freq | 208993.cluster.hpc | 水 HF/STO-3G；完成、收集、解析；新热化学分析有效 |
| xTB 单点 | 208994.cluster.hpc | 完成、收集、解析 |
| CREST conformer search | 208995.cluster.hpc | 正常结束；修复输出捕获后恢复收集/解析 |
| ASE-NEB | 208996.cluster.hpc | 轻微形变水端点、3 images；完成、收集、解析 |
| CREST 修复后新提交 | 208997.cluster.hpc | 使用正确 `crest.out`；完成、收集、解析 |

CREST 首次问题是 stdout 名称与收集合同不一致。修复同时支持精确匹配旧脚本
digest 的历史作业；传输回执保留真实远端源路径。没有篡改旧提交记录。所有测试
作业均已结束并解析，结果报告已生成。

Gaussian 实际输出在 298.15 K 下从 1 atm 转到 1 mol/L，得到水的
`G = −196797.5610289354 kJ/mol`。该数值仅是此次 HF/STO-3G 软件衔接验收。
水形变 NEB 不代表反应；本 smoke 不是过渡态或真实机理的量化基准。

## 证据位置与复现

源码中的复现入口：`tests/mechanism_live_eval.mjs`、
`tests/mechanism_eval_fixture.py`、`tests/scientific_remote_smoke.py`、
`scripts/test_source.py`；参数用法见[运维文档](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)。

本机原始结果根目录为 `/tmp/tspi-native-validation-9Qnd4x/`。它们是临时验证产物，
不随发布包分发；下列摘要和哈希保留复核标识，临时目录清理后需重新运行试验。

| 文件 | SHA-256 |
| --- | --- |
| live-evaluation-final.json（初始小基线） | 394122b16d291ae1734357923e0e3d32442dfba69951795a64d121dd1313da31 |
| live-evaluation-after.json（中间试验） | b9d122437013864c74e1b6744dc54df447ae31a26c428b8cd07876b951e4b842 |
| live-evaluation-release.json（修复后试验） | 79f6642fc57e4dbb2962d9e4ba9b2eebd7d966189ccb2814f38a366ada619924 |
| 远端 smoke 工作区的 smoke_manifest.json | 4daa5f40d7c1a59a829cb522eab6f77480ed2c96f283fea619ff60307445ee9c |

远端工作区的 `smoke_manifest.json` 中 `report.package_dir` 记录报告绝对路径，
报告目录名为 `smoke-calc_1-parsed-calc_2-parsed-calc_3-parsed-calc_5-parsed-calc_6-parsed`。
其中 `package_manifest.json` 的 digest 为
`sha256:3bdb8371b4ed751f83cf800dd885f56c428b6c45bbcd31c0ca73e151dfaa168e`。

## 首版边界

图映射是有界候选搜索，不是机理发现。模式耦合是选定键长导数指标，单一键的
单位重叠不证明完整反应坐标。热化学目前使用可绑定的 HF/Kohn-Sham SCF 总能与
解析修正/显式 RRHO；不支持通用相关能解析、同位素 RRHO/KIE、低频非谐修正或
构象系综。初始分支比例不是循环/回流/耗竭网络的产率，微观动力学属于后续能力。

以上是可选能力及其证据边界，不为研究规定固定步骤。正式接受科学 Claim 仍应
按问题选择方法、建立适用的 ProofSpec，并由已有验证与接受机制处理。
