# 名称查询与 Agent 推断

## 查询

准备 `chemical.resolve@1`，传 `--name 原文`，可加 `--lookup-name 规范化名称`。
结果保留原文，所有名称采用相同查询路径。默认依次尝试 PubChem、OPSIN，安装配置
显式指定的解析器优先。某个后端得到可用候选即可结束查询；结果无法解析时继续尝试
下一个后端。每次调用至多尝试每个已启用后端一次，保留 404、限流、超时和响应异常诊断。
必要时使用有针对性的翻译或规范化查询；继续查询难以增加信息时转入候选推断。

配置来自 CORAGENT_NAME_RESOLVER_CONFIG 或
CORAGENT_INSTALL_ROOT/etc/name-resolver.toml。受管 Job 使用显式绑定：
安装器在 job.toml 中补齐本地 structure 后端的解析配置路径。保留显式设置，
远程目标需提供远端可读的路径。修改绑定后重新准备请求。缺少配置时返回
`next_step=infer_candidates`，Agent 可根据输入描述继续推断。

## 候选输入

由当前 Agent 编写 JSON，通过 `chemical.resolve-candidates@1` 的
`--input candidates=<文件>` 提交。Job 暂存文件并固定摘要，在本地检查结构，
不额外调用模型 API 或重复查询服务。

```json
{
  "name": "乙醇",
  "lookup_name": "ethanol",
  "candidates": [
    {
      "smiles": "CCO",
      "source": "llm",
      "reason": "含两个碳原子且末端为羟基的醇。",
      "assumptions": ["采用中性分子。"],
      "charge": 0,
      "multiplicity": 1
    }
  ]
}
```

`name` 和非空 `candidates` 列表必填；`lookup_name` 可选，`lookup_ref` 可引用之前
收集的查询结果。文件最多 1 MiB，包含至多 16 个候选。每个候选必填 `smiles`、
`source`（`llm` 或 `user`）。`reason`、`assumptions`、`charge`、`multiplicity` 可选。
Agent 推断时简要记录依据和相关假设。电荷由 SMILES 计算；提供电荷或多重度时检查一致性。
用户提供的 SMILES 也可直接进入 inspect/seed，无需候选文件。

## 结果与后续行动

结果保留 `schema_version=chemical-input/1` 和已有 data/candidate 字段。
`source` 记录结构来源，来源本身不改变状态或增加确认步骤。以前的记录保留原样可读。

- `resolved` / `prepare_geometry`：一个可用结构，继续生成初始几何。
- `ambiguous` / `select_or_enumerate`：存在多个候选或未指定立体化学，结合任务选用并
  说明依据，或在用户研究范围内分支探索。
- `unresolved` / `infer_candidates`：查询没有可用结构，由 Agent 推断。
- `unresolved` / `revise_candidates`：候选未通过结构检查，按具体问题修正。

`checks` 保存逐候选检查，`diagnostics` 保存查询及修正信息。可用候选包含规范/异构
SMILES、分子式、电荷、立体化学信息、来源及可选的依据、假设、多重度。
`input_provenance` 保存候选文件 SHA256 和可选的查询引用；服务依据在 `resolver_provenance`。

选用候选后，用其规范 SMILES、电荷和选定多重度准备 `chemical.seed@1`；研究立体异构
候选时加 `--enumerate-stereo`。LLM 来源不增加确认步骤，几何和后续结果保留来源与假设。
