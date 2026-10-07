# 已安装扩展合同

这里的 `extensions/` 指可安装的能力扩展。包内核心 server tool 装配位于
`apps/app-server/server-tools/`，不属于外置扩展发现流程。

TSPi 将 Agent、Research State 与具体计算软件解耦。已安装扩展是带有
`manifest.json` 的目录；App Server 从 `TSPI_EXTENSION_MANIFESTS`（按系统路径
分隔符分割）、Host 显式配置，或包内所有 `extensions/*/manifest.json` 中发现
这些 manifest。

manifest 格式为 `tspi-extension/1`，机器可验证的 JSON Schema 位于
`contracts/tspi-extension/1/extension-manifest.schema.json`：

```json
{
  "schema_version": "tspi-extension/1",
  "name": "amber-tools",
  "version": "1.2.0",
  "skills": [{"name": "amber", "path": "skills/amber"}],
  "server": {
    "entry": "server/index.mjs",
    "sha256": "sha256:<64 位十六进制字符>",
    "tools": ["amber_run"],
    "permissions": ["workspace.read"]
  }
}
```

Skill 路径必须包含普通文件 `SKILL.md`。扩展中的 provider entry 只是可选 server 集成的旧元数据；科学 Skill 不需要 provider descriptor。App Server loader 只建立扩展清单。科学 preflight 检查选定的 Job Runtime 环境；Skill 负责输入构造、命令 argv、解析和验证。科学命令通过 `job_start` 提交，它是本地与远端共用的执行边界。

现有 `apps/app-server/server-tools/extensions.json` 合同保持不变：server 工具仍要求包内
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


包内当前只有 core-tools，提供 Research State、通用 Job Runtime 和 Artifact 工具。chemical 与 email 通过包含脚本的 Skill 提供能力，不加载 chemical-tools 或原生通知入口。providers 是可选的历史元数据。可执行 Skill 的 resources_sha256 绑定 resources.json；其中路径相对扩展根，loader 校验索引及脚本/辅助模块摘要。修改后运行 scripts/update_skill_resources.py 更新摘要。
