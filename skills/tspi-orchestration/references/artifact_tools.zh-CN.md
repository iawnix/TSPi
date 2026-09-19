# 确定性 Artifact 工具

Structure Seed、Structure Compare 与 Import 是用于准备和分析 Node 所属输入 Artifact 的
Host 工具。

## 内容

- [生成结构种子](#生成结构种子)
- [比较已注册结构](#比较已注册结构)
- [导入已有输入](#导入已有输入)
- [Activity 与来源](#activity-与来源)

## 生成结构种子

对于一个由 SMILES 描述的连通分子：

```json
{
  "operation":"generate",
  "nodeId":"node_1",
  "smiles":"C1=CCCCC1",
  "charge":0,
  "multiplicity":1,
  "optimization":"uff"
}
```

`optimization` 可取 `none` 或 `uff`。Host 固定 RDKit ETKDGv3 参数和随机种子，添加显式
氢，检查形式电荷与电子数奇偶性，并在未关闭的 Node 下写入按内容寻址的 XYZ 和来源信息。
activity 请求只保留 SMILES 摘要，不保留正文。来源记录包含 canonical SMILES、RDKit
版本、参数、metadata、输出摘要与局限。仅使用单个连通 SMILES；多片段接近几何需要显式
排列，然后导入生成的 XYZ。

初始几何应继续进行优化和表征。驻点、振动模式和连通性属性通过 Compute 与相关 Gate
建立。

## 比较已注册结构

准确比较两个已注册的 XYZ Artifact：

```json
{
  "operation":"compare",
  "nodeId":"node_1",
  "referenceArtifactId":"art_...",
  "targetArtifactId":"art_...",
  "parameters":{
    "atomMapping":[0,1,2],
    "reactionCenterAtoms":[0,1,2],
    "keyBonds":[[0,1]],
    "keyAngles":[[1,0,2]],
    "keyDihedrals":[],
    "stereochemicalChecks":[],
    "rmsdThreshold":0.5,
    "reactionCenterThreshold":0.25
  }
}
```

所有原子索引均从零开始。`parameters` 可选；详细检查由确定性 Python Kernel 校验，避免
其 schema 占用每个 Root 回合的上下文。省略阈值时默认分别为 0.5 和 0.25 angstrom。
Host 绑定两个输入 ID 与摘要，并在 `nodes/<node_id>/outputs/analysis/` 下写入幂等的私有
JSON Artifact。文档包含展开后的参数、verdict、不确定性、RMSD/内坐标/立体化学指标、
诊断与来源。

该结果属于运行记录。任何用于 Claim 或 Node 结果的值，都要通过 `ts_change` 注册为语义
Finding，并引用已核验的分析 Artifact。

## 导入已有输入

启动一个未关闭的 ResearchNode 后，使用有语义的 basename 创建一个有边界的输入。
Node 本地目录由 Host 管理：

```json
{
  "operation":"import",
  "nodeId":"node_1",
  "format":"gaussian_input",
  "inputName":"cycloaddition-ts.gjf",
  "content":"#p M062X/6-31+G(d,p) opt\n\n...\n",
  "charge":0,
  "multiplicity":1
}
```

格式包括 `gaussian_input`、`xyz_structure` 和 `xtb_control`。提供简洁且有语义的
`inputName`；Gaussian 接受 `.gjf` 或 `.com`，XYZ 要求 `.xyz`，xTB control 要求
`.inp`。Gaussian 与 XYZ 导入必须声明电荷和多重度。Host 对 UTF-8 文本进行大小限制和
校验，将名称限制为安全 basename，拒绝路径穿越与符号链接，写入私有 Node 输入，并返回
与内容绑定的逻辑 `artifactId`。

相同名称和内容的重放是幂等的；相同名称绝不会覆盖不同内容。activity journal 只保存摘要
和 metadata，不保存输入正文。QST2/QST3 导入还要求每个结构使用相同的声明电荷、多重度、
原子数与原子顺序。拒绝 multi-job `--Link1--` 输入与 Link 0 文件系统路径。Compute 前
使用 `ts_state mode=artifacts` 解析结果。

## Activity 与来源

Structure Seed、Structure Compare 与 Import 写入确定性 activity journal，其中
`node_refs` 是 operation 与 Node 之间的唯一链接。Compute 在所属 `calc_n` Attempt 下写入
一个 `sub_n` run。Render、Report 与 Notify 各自拥有专用 capability 合同。这些记录用于
诊断和报告；记录 Finding 时仍需核验其底层 Artifact。
