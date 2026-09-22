# Model Compatibility

[English](MODEL_COMPATIBILITY.md) | [简体中文](MODEL_COMPATIBILITY.zh-CN.md)

Model access is managed by Pi. TSPi focuses on the research workflow: each
installation has one Host, and the terminal, TS Phone, and Monitor attach to
the same Pi Harness lane and model configuration.

Custom models use Pi's `models.json` and normal authentication mechanisms. TSPi
does not maintain a separate model catalog, credential store, or provider API
adapter.

## Compatibility Matrix

| Family | TSPi status | Pi provider or route |
|---|---|---|
| OpenAI GPT | Inherited, built in | `openai` or `openai-codex` |
| Google Gemini | Inherited, built in | `google` or `google-vertex` |
| DeepSeek | Inherited, built in | `deepseek`; TSPi also avoids incompatible named `tool_choice` on thinking turns |
| GLM / Zhipu | Inherited when present in the pinned Pi catalog | `zai`, `zai-coding-cn`, or a tested OpenAI-compatible custom model |
| Kimi | Inherited, built in | `kimi-coding`; compatible catalog routes such as OpenRouter may also be used |
| Other OpenAI-compatible chat models | Conditional | Define the provider/model in Pi's `models.json` with the correct `api`, `baseUrl`, auth, and `compat` fields |
| SeedDance / Seedream | Not an Agent model | These are media-generation APIs, not chat/tool-calling LLMs; TSPi does not claim Root/Compute/Review compatibility |

"Inherited" means that the exact model must exist in the pinned Pi catalog or
in a valid custom Pi model configuration, authentication must be available to
the Host account, and the endpoint must support the tool calls used by TSPi.
Provider branding alone is not a compatibility guarantee.

## Configuration And Verification

For an installation, Pi state is under `<install>/.pi/agent/`. Put custom model
definitions in `<install>/.pi/agent/models.json` and authenticate using Pi's
normal login or `auth.json`/environment mechanisms. Select a model with Pi
settings before restarting the Host:

```bash
systemctl --user restart ts-app-server-tspi.service  # user scope
systemctl restart ts-app-server-tspi.service         # system scope
```

Before production use, run one real session that exercises `read`, `write`,
`bash`, and a TSPi tool. The repository's recording-provider tests verify the
adapter contract and error taxonomy, but cannot prove a third-party endpoint's
current credentials, quota, model availability, or tool-calling behavior.
