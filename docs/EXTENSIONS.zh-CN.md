# 已安装扩展合同

TSPi 将 Agent、Research Kernel 与具体计算软件解耦。已安装扩展是带有
`manifest.json` 的目录；App Server 从 `TSPI_EXTENSION_MANIFESTS`（按系统路径
分隔符分割）、Host 显式配置，或可选的包内 `extensions/manifest.json` 中发现
这些 manifest。

manifest 格式为 `tspi-extension/1`，机器可验证的 JSON Schema 位于
`contracts/tspi-extension/1/extension-manifest.schema.json`：

```json
{
  "schema_version": "tspi-extension/1",
  "name": "amber-tools",
  "version": "1.2.0",
  "skills": [{"name": "amber", "path": "skills/amber"}],
  "providers": [{
    "id": "amber.md",
    "version": "1",
    "kind": "compute",
    "descriptor": "providers/amber.json",
    "entry": "providers/amber.mjs",
    "sha256": "sha256:<64 位十六进制字符>"
  }],
  "server": {
    "entry": "server/index.mjs",
    "sha256": "sha256:<64 位十六进制字符>",
    "tools": ["ts_amber"],
    "permissions": ["workspace.read"]
  }
}
```

Skill 路径必须包含普通文件 `SKILL.md`。Provider 的 `kind` 必须是
`compute`、`analysis` 或 `harness` 之一，并且必须声明 descriptor 或 entry。
可执行的 provider entry 必须带 SHA-256 摘要；App Server loader 只建立清单，
不会导入或执行 provider 代码。受信任的 capability adapter 可以消费该清单，
再将其绑定到环境管理器。

对于可执行计算 provider，受信任的 adapter 通过
`register_capability_provider()` 注册 `CapabilityDescriptor`。其
`prepare(task)`（或 `prepare_task(task)`）必须返回受约束的 `PreparedTask`；可选的
`validate_inputs(workspace, intent, inputs)` 负责 provider 自己的输入检查。只有
adapter 可以把 descriptor 翻译成命令。没有已注册 adapter 的 descriptor 会报告为
不可用能力，不会退回到 shell 命令或某个后端的默认分支。

现有 `extensions/server/extensions.json` 合同保持不变：server 工具仍要求包内
manifest、allowlist 选择和逐 entry 摘要。已安装 manifest 增加 Skill、provider
元数据和显式 allowlist 的 server 工具，但不改变 Agent 核心、Harness 生命周期或
内置 server 工具。

`TSPI_EXTENSION_MANIFESTS` 未设置或为空是合法配置，此时只使用包内 Skill 和能力。
重复的 extension、provider 或 Skill 名称，路径穿越、符号链接、错误元数据及摘要
不匹配都会在 session 启动前失败。

可选的 `server` entry 只有在扩展名称进入 Host allowlist
`TSPI_INSTALLED_SERVER_EXTENSIONS` 后才会执行。其模块必须导出
`createServerExtension()`，返回的 Harness 工具必须与声明的名称、参数 schema
和生命周期 metadata 完全一致。entry 摘要会在发现阶段以及导入前再次校验；
Agent 不能选择 import 路径或绕过 allowlist。

包内 server 清单现在拆为两个带摘要的 entry，但默认 active tool 集合保持完整。
`tspi-core-tools` 负责研究/生命周期、环境、审查、dispatch、通用计算、artifact
导入/渲染和报告；`tspi-chemical-tools` 负责化学 artifact 与分析工具
（`artifact_seed`、`artifact_compare`、`analysis_run`）。默认
`tspi-chemical` 扩展中的 Gaussian 和 xTB 是 descriptor-only provider 清单项；
真正的 Python adapter 仍是执行边界，并通过环境管理器选择运行环境。
