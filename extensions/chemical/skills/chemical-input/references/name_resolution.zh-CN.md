# 名称解析合同

`chemical.name.resolve@1` 是确定性分析能力。它接收原始名称和可选的 Agent 翻译后的
`lookup_name`，也可以核验显式提供的
候选 SMILES。解析器必须报告实现和版本；模型生成的候选在确定性解析器或用户明确确认
之前始终标记为 `draft`。

结果区分 `resolved`、`ambiguous`、`draft` 和 `unresolved`，并包含 canonical/isomeric
SMILES、分子式、形式电荷、可选 InChI/InChIKey、未指定的立体中心和诊断。resolver backend
缺失时返回 unsupported 的 unresolved 结果；后端可达但确定性地返回未收录时返回 invalid 的
unresolved 输入；只有 capability descriptor 缺失时才返回结构化 capability gap。三种情况都
不能借此默写一个结构。`lookup_name` 只是查询提示，必须由 resolver 确定性核验，并与
原始名称一起保留 provenance。

## 配置

自动查询使用安装目录所有的配置。新安装会把包内的 `config/name-resolver.example.toml` 复制为
`.pi/name-resolver.toml`；管理员可以替换该文件，或者用 `TSPI_NAME_RESOLVER_CONFIG` 指定绝对路径。内置的
PubChem 后端使用 PUG REST，并缓存响应证据；结果中的 `resolver_provenance` 会记录端点、
请求 URL、响应摘要、实现版本和查询时间。也可以启用 OPSIN 作为第二个确定性 HTTP 后端。
网络错误和多个候选仍分别保持未解析或歧义状态；此配置不会把 LLM 生成的候选提升为确定结构。

若 `TSPI_NAME_RESOLVER_CONFIG` 与 `${TSPI_INSTALL_ROOT}/.pi/name-resolver.toml` 都不存在，
则没有确定性 resolver backend 可用。当 capability 本身已注册时，`resolver=auto` 仍返回正常的
`ts-analysis-result/1`，其 `verdict="unsupported"`、`data.status="unresolved"`、候选为空，并在
diagnostics 中说明缺失 backend。只有实时 analysis catalog 没有该 capability descriptor 时，才
返回 `ts-capability-gap/1`。使用环境变量时，路径必须是绝对路径、可读的普通非符号链接文件。
支持的 TOML 形状为：

```toml
default_resolver = "auto"  # auto | pubchem | opsin

[backends.pubchem]
enabled = true
endpoint = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
timeout_seconds = 10  # 1..60
cache = true
# cache_dir = "/absolute/path/to/private/cache"
```

配置中只允许 `pubchem` 和 `opsin` 两个 backend。`llm` 是显式候选的输入模式，不是确定性
backend。Endpoint 必须是绝对 HTTP(S) URL；指定 cache directory 时也必须是绝对路径。Backend
被禁用、不可用、网络失败或返回多个候选时，结果仍保持 unresolved/ambiguous，并在 provenance
和 diagnostics 中说明。仅有已安装的程序目录或任意 endpoint 并不会注册 capability。

名称查询和结构身份与 3D 生成是不同步骤。候选确认后再调用 `create_mol_structure`，并使用已有分析
能力验证反应守恒和 atom mapping。
