# 科学分析能力：使用与运维

[English](SCIENTIFIC_CAPABILITIES_OPERATIONS.md) | 简体中文

`ts_state mode=capabilities capabilityKind=analysis` 返回小型能力索引；
`query=<capability>@1` 返回输入角色、参数 schema、输出与适用边界。
`ts_analyze` 只调用用户问题所需要的独立能力，不规定研究顺序。

## 软件与依赖

本地确定性分析复用受管理 Python 环境中的 RDKit、NumPy、ASE、jsonschema。
`reaction.parse` 使用 RDKit；RRHO 使用 ASE IdealGasThermo。安装的 runtime probe
实际运行分子反应守恒与单原子热模型检查。版本由现有环境锁文件与 Python wheel
记录；能力目录的存在不代表某个远端可执行程序已部署。

Gaussian 输入构造和输出分析本身不启动 Gaussian。CREST、xTB、ASE-NEB、Gaussian
的执行继续使用已有 `ts_calc` 和所选 profile 的 doctor。检查配置后才进行真实
小体系作业；明确区分合成 parser fixture、本地真实分析、远端真实量化计算回执。

## Node 操作与恢复

```text
ts_manage operation=pause nodeId=node_7 rationale="用户要求暂缓该分支"
ts_manage operation=resume nodeId=node_7 rationale="用户要求继续该分支"
```

暂停阻止新的分析及提交边界。已取得提交 guard 的任务可能已在途，回执列出此前
提交 guard，需用 `ts_calc inspect` 核查；暂停不会隐式取消作业。在途作业仍可收集、
解析或按精确 intent/Attempt 取消。暂停不改 Node 的科学状态，不否定 Claim。
重复相同管理操作返回已有回执；恢复记录保留前一回执 digest，进程重启后仍生效。
回执链损坏时派发拒绝，先检查 `nodes/<node>/dispatch/` 与操作投影中的诊断。

用户指定终态节点继续研究时，通过 `ts_change start_node` 创建依赖节点并引用旧
artifact。现有 `set_focus` 可切换优先分支，不取消其他分支作业。

`ts_calc finalize` 可以省略 `artifactRef`：Kernel 从精确 intent 的预期输出推导
Gaussian log、`xtb.out`、`crest.out` 或 `neb_summary.json`。歧义时要求明确路径。
解析产物、默认展开和来源进入现有 Attempt 记录。ProofSpec 使用模板时可省略
`title`，由模板唯一展开；`dimension` 仍是显式科学分类。
直接 Observation 的 artifact binding 可省略 `sha256`，由当前 artifact ID 解析；
科学值及 `provenance.producer` 仍显式提供。引用同一事务的新对象使用 `$local_ref`。

## 结果、报告与网页

分析文件位于 `nodes/<node>/outputs/analysis/`，返回 summary、诊断、生成文件和
候选事实。`ts_change record_observation` 的 candidate 变体自动绑定值、单位、
类型和 digest。只能提升同 Node 的候选；跨 Node 引用已登记 Observation 或原始
artifact，避免改写历史来源。

报告包括科学分析索引、能量/速率表、网络参与物与来源链接；Node Web 详情包含
分析与派发状态，文件页可查看完整数据。网页继续只读。能量曲线文件使用既有
`ts-curve-data/1`，可交给 `ts_render curve`；未绘图的原始数据仍可查阅。

## 验证入口

相关单元/集成测试：`tests/test_scientific_analysis.py`、
`tests/test_node_dispatch.py`、`tests/test_reaction_mapping.py` 以及现有 compute、
report、Web、candidate、wheel 测试。参数合同检查不会加载全部科学依赖。

真实模型选择评测入口（隔离临时 workspace，不提交科学作业）：

```bash
TS_AGENT_PYTHON=/path/to/managed/python node tests/mechanism_live_eval.mjs PROVIDER MODEL 3 /tmp/tspi-evaluation.json
```

读取现有 Pi 模型配置和授权；输出不包含凭据。覆盖反应定义、已有 TS、已有 IRC、
映射歧义、失败候选、竞争路径和定向 Node 管理。检查交付物与限制，不强制精确
调用顺序。记录真实模型 usage 和行政字段字节代理；后者不能冒充精确行政 token。
自动完成率只是基础条件，需结合模型结论和来源进行科学审阅。
`TSPI_EVAL_CASES=existing_ts,existing_irc` 可限定复测场景，
`TSPI_EVAL_MAX_TURNS=16` 可调整每例预算（默认 10，最大 20）。报告必须披露预算；
能力覆盖率与科学交付分别判断，直接读取 IRC 后准确总结也可以满足只读任务。

真实远端小体系验收使用独立目录和已配置 profile：

```bash
TS_REMOTE_CONFIG=/path/to/remote.toml /path/to/managed/python -m tests.scientific_remote_smoke launch /tmp/tspi-smoke --profile PROFILE
TS_REMOTE_CONFIG=/path/to/remote.toml /path/to/managed/python -m tests.scientific_remote_smoke advance /tmp/tspi-smoke
```

launch 只提交缺失的测试，advance 查看已有作业并收集/解析。保存
`smoke_manifest.json`、Attempt 回执及生成报告；未知提交不能重放。水分子的轻微
形变 NEB 仅验证软件接口，不能作为真实反应或 TS 证据。

CREST 的标准输出现在绑定 `crest.out`。历史提交若绑定的是 `remote_job.stdout`，
只在精确匹配旧脚本 digest 时沿用该路径，收集到本地 `crest.out`；transfer manifest
保留真实远端文件名与 digest，不更改旧提交回执。

首版热化学支持匹配的 HF/Kohn-Sham SCF 总能、解析热修正及显式 RRHO。相关电子
方法、同位素 RRHO、构象系综和微观动力学超出本版；缺失或不兼容证据不能由电子
能代替。具体测试入口见本文件的“验证入口”一节；一次性验收报告不作为仓库文件保留。

原生 App Server smoke 使用 `config/pi-source.json` 固定源码版本。源码入口仍需
生成模型数据和依赖包 build 产物；`prepare_pi_source.py --install <root>` 会检查
并补齐这两项。单独运行 `npm ci --ignore-scripts` 不构成可运行的源码安装。
