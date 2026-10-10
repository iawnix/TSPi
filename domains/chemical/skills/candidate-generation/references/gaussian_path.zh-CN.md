# 可执行的映射 DA 路径

`../scripts/prepare_path.py` 实现一条有界路径：显式中性碳 Diels–Alder 拓扑、原子映射绑定的
反应物/产物种子、Gaussian QST2+Freq，以及从收集的 TS checkpoint 出发的正反 IRC。
当前支持无同位素特定质量的闭壳层单重态。反应物立体化学必须明确；产物未指定立体化学可枚举，
最多 16 个变体。不实现 NEB、穷尽构象搜索或完整机理发现。

创建并登记 `chemical-path-spec/1` JSON Artifact，例如：

```json
{
  "schema_version": "chemical-path-spec/1",
  "mapped_smiles": "[CH2:1]=[CH:2][CH:3]=[CH2:4].[CH2:5]=[CH:6][CH3:7]>>[CH2:1]1[CH:2]=[CH:3][CH2:4][CH2:5][CH:6]1[CH3:7]",
  "transformation": {
    "kind": "diels_alder",
    "diene": [1, 2, 3, 4], "dienophile": [5, 6],
    "forming_bonds": [[1, 6], [4, 5]]
  },
  "method": "M062X", "basis": "6-31G**", "charge": 0,
  "multiplicity": 1, "threads": 12, "memory_mb": 4000
}
```

下列命令使用系统列出的真实 Skill 路径和工作区路径：

```text
"$CORAGENT_PYTHON" -m research_agent.application.executors --config "$CORAGENT_JOB_CONFIG" --environment local --executor chemical.path-candidates --version 1 --input spec=<workspace>/spec.json --input-artifact <spec-ref> --output <workspace>/candidates-request.json -- --enumerate-stereo --conformers 2
```

将返回的 request_file/request_sha256 提交并收集后，再检查候选。入口使用目标 structure 绑定，每个生成文件均保留 Job 来源。

`candidates.json` 保留每个成功或失败分支。成功分支含带摘要的 `spec.json`、`atom_order.json`、
`reactants.xyz`、`product.xyz` 和 `ts.gjf`。helper 嵌入产物构象，构建 s-cis 二烯，按原子对应
对齐并分离反应物片段。这些是未经优化的端点种子；需检查输入并保留失败分支，不能保证 QST2
收敛或有限候选集完整。登记所选分支的 spec 与几何。分支 spec 是
`chemical.diels_alder_path@1` 的验收对象，不得混用不同 spec 的证据满足同一路径。
生成的 `CoRAgentSpec` 标题将求解器输出绑定到分支 spec 摘要。TS 输入与 checkpoint 必须保留
该标题，原始 TS 和 IRC log 也必须回显它。

使用既有 method-selection helper 准备 TS 请求：

```text
"$CORAGENT_PYTHON" -m research_agent.application.executors --config <installation>/job.toml --environment local --executor chemical.gaussian-input --version 1 --input input=<branch>/ts.gjf --collect results/ts.chk --output <workspace>/ts-request.json -- --method M062X --basis '6-31G**' --threads 12 --memory-mb 4000 --validation saddle
```

将返回的 `request_file` 和 `request_sha256`  交给 `job_start`，在 Job 终止后收集结果。
runner 成功不是科学结论：可用已注册鞍点验证器检查收集的原始 `gaussian.out`。
分别审查检查结果与适用范围；解析失败不等于科学否定，也不禁止进一步探索。记录缺少的证据与下一步理由，不把未确定项说成通过。
当选择 IRC 作为下一步时，从该 Job 收集的 `ts.chk` 准备正反 IRC 输入：

```text
"$CORAGENT_PYTHON" -m research_agent.application.executors --config "$CORAGENT_JOB_CONFIG" --environment local --executor chemical.path-irc --version 1 --input spec=<branch>/spec.json --input checkpoint=<collected-ts.chk> --input-artifact <spec-ref> --input-artifact <checkpoint-ref> --output <workspace>/irc-request.json
```

先提交并收集 IRC 输入准备 Job，再使用其生成的输入和检查点。

每个方向使用 `-m research_agent.application.executors --executor chemical.gaussian-input --version 1 --input input=<workspace>/irc/forward.gjf`（另一个为 `reverse.gjf`），
传入 `--dependency <workspace>/irc/ts.chk=ts.chk`，并声明
`--collect results/irc_path_summary.json --collect results/irc_path_points.json --collect results/gaussian_endpoint.xyz`。
保持相同方法和资源，`--` 后使用 `--validation irc`。分别提交返回引用、收集结果，再验证连通性。

通过 `job_start(validator_id=..., input_artifact_ids=[...])` 执行注册验证器：

| 验证器，版本 1 | 按顺序提供的 Artifact ID |
| --- | --- |
| `chemical.reaction_mapping` | 已登记分支 spec |
| `chemical.gaussian_saddle` | 分支 spec、已收集鞍点 Gaussian log |
| `chemical.gaussian_irc_connectivity` | 分支 spec、鞍点 log、正向 IRC log、反向 IRC log |

执行前检查 schema、摘要及 producer 回执版本。映射验证覆盖全部键变化与逐原子氢计数；
鞍点验证检查 route、电荷/自旋、核数/内存读回、收敛、完整频率表及两条成键的同向位移。
IRC 验证重新检查来源鞍点、方向性完整路径、起点 RMSD ≤ 0.05 Å，以及不同的映射反应物/产物
端点连接关系。模糊的共价距离或缺失字段不能通过。端点检查覆盖明确指定的原子手性中心，
不等于通用立体化学机理证明或键级恢复。

Gaussian 解析当前要求常规笛卡尔 orientation 表、`Atom AN X Y Z` 振动模式，以及带坐标的
IRC `CURRENT STRUCTURE` 块。不支持的格式、不完整路径或缺失资源读回需要复核，不能用
Agent 自评通过替代。测试以合成 solver 输出执行真实 helper、parser 和 Job，不能证明实际
Gaussian 对每个候选都能收敛。
