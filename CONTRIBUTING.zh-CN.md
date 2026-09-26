# 参与 TSPi 开发

欢迎改进 TSPi。项目是领域无关的 Research Harness，并附带计算化学 Skill 包。提交时
应保持 Harness 生命周期、ResearchMap 权威性和已注册 capability contract 清晰可见。

## 提交修改前

- 先搜索已有 issue 和文档，避免重复设计。
- 保持单一目的，说明用户行为变化以及负责该变化的 contract。
- 不要增加第二套状态存储、agent loop、Pi 运行时或公开工具别名。
- 不要提交凭据、含隐私信息的调度器输出、模型 transcript 或生成的 release 目录。

## 开发检查

测试入口由 `tools/test/manifest.toml` 统一定义：

```bash
python3 tools/test/runner.py list
python3 tools/test/runner.py fast -- -q
python3 tools/test/runner.py source -- -q
npm run typecheck
npm run lint:public
npm run lint:skills
npm run test:package
```

使用测试运行器选择的托管环境。Native Pi 测试需要匹配 `config/pi-source.json` 的 Pi
源码；远端和真实模型场景都是显式 opt-in。测试启动的服务必须在退出前停止并清理临时状态。

## Contract 变更

修改公开 capability、工具、workspace 记录或协议时：

1. 同步更新版本化 schema/catalog 和实现。
2. 同步更新中英文文档与对应 Skill reference。
3. 增加聚焦的 unit/contract 测试以及失败或恢复路径测试。
4. 运行 package check，确认 release inventory 完整。

Pull request 应说明兼容性影响、迁移或回滚方案以及运行过的测试。科学结论必须以带有
Artifact 引用的 Finding 记录；进程成功本身不是科学证据。

## Pull Request

标题应描述问题，正文说明边界明确的解决方案，并避免提交无关格式化或生成文件。发布与
所有权说明见[维护者指南](docs/MAINTAINER_GUIDE.zh-CN.md)。项目拥有的源码采用
[Apache-2.0](LICENSE) 授权；重新分发完整安装包前还必须检查第三方声明。
