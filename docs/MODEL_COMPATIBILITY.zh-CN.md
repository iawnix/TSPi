# 模型兼容性

TSPi 不维护第二套模型 provider。安装级 Host 直接使用
`config/pi-source.json` 固定的 Pi 版本所提供的模型目录、认证、API adapter 和
`models.json`。终端与 TS Phone 连接同一个 session Worker，因此二者使用同一个模型
和完整工具集合，不存在 Phone 专用的模型或工具降级。

## 兼容矩阵

| 模型系列 | TSPi 状态 | Pi provider 或接入方式 |
|---|---|---|
| OpenAI GPT | 继承 Pi，内置 | `openai` 或 `openai-codex` |
| Google Gemini | 继承 Pi，内置 | `google` 或 `google-vertex` |
| DeepSeek | 继承 Pi，内置 | `deepseek`；TSPi 还会在 thinking turn 避免不兼容的 named `tool_choice` |
| GLM / 智谱 | 取决于固定 Pi 版本的目录 | `zai`、`zai-coding-cn`，或经过验证的 OpenAI-compatible 自定义模型 |
| Kimi | 继承 Pi，内置 | `kimi-coding`；也可使用 OpenRouter 等目录路由 |
| 其他 OpenAI-compatible 对话模型 | 条件支持 | 在 Pi `models.json` 中正确配置 `api`、`baseUrl`、认证和 `compat` |
| SeedDance / Seedream | 不能作为 Agent 模型 | 它们是媒体生成 API，不是对话/工具调用 LLM；TSPi 不宣称其可作为 Root、Compute 或 Review 模型 |

“继承 Pi”仍有三个前提：模型存在于固定 Pi 版本的目录或合法的自定义配置中，Host
运行账户能取得认证，而且 endpoint 支持 TSPi 所需的工具调用。只有 provider 品牌名称
并不能证明兼容。

## 配置和验证

安装后的 Pi 状态位于 `<install>/.pi/agent/`。自定义模型写入
`<install>/.pi/agent/models.json`，认证沿用 Pi 的 login、`auth.json` 或环境变量机制。
可通过 Pi 设置选择默认模型，然后重启 Host：

```bash
systemctl --user restart ts-app-server-tspi.service
```

生产使用前，应执行一次真实会话并实际调用 `read`、`write`、`bash` 和至少一个 TSPi
工具。仓库中的 recording-provider 测试可以验证 adapter 合约和错误分类，但不能证明
第三方 endpoint 当前的凭证、额度、模型可用性或工具调用行为。
