# 变更日志

这里记录面向用户的变化；当前设计见[架构文档](docs/ARCHITECTURE.zh-CN.md)，旧方案可通过 Git 历史查询。

## 未发布

- **0.19.0 不兼容更名**：产品及仓库统一为 CoRAgent / `coragent`。命令、包、服务、
  安装标识和环境变量统一新名称，不提供旧别名或回退；Python 内部导入仍为 `research_agent`。
- Host / Relay 改用 `coragent-host/2`、`coragent-link.v1`、`cah_` 和 `cad_`。

- 增加 Gaussian relaxed scan 能力文档以及 Gaussian 后端的 ASE NEB 支持。
- 从受支持的 package surface 移除已退役的 ordinary-Pi runtime；Native Pi Harness 是唯一
  运行时入口。
- 明确 Research Memory、有界 turn context、capability catalog 和 Monitor 唤醒边界。
- 增加仓库治理文档与自动化 Skill contract 检查。
- 为项目拥有的源码加入 Apache-2.0 许可证及 SPDX 元数据。

本条目还没有对应的发布 tag。发布说明必须包含 package 版本、固定的 Pi revision、迁移说明
以及运行过的测试 lane。
