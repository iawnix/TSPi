# 包内知识来源

## 研究运行时

按以下顺序使用来源：

1. 已注册的公共工具 schema，用于稳定调用 envelope；
2. `ts_state`，用于实时 ResearchMap、Artifact、capability 和 operation catalog；
3. `SKILL.md`，用于研究工作流；
4. 当前主题对应的一份 `references/*.md` 专用参考。

工具接受哪些字段应查询其实时合同。研究过程中需要查看实现时，包源码读取器会把查询
路由到相关公共参考资料。

## 科学来源

本地程序的主要 Artifact 和用户显式提供的事实是来源材料。记录 Finding 前必须核验。
Review、activity log、调度器历史、报告与对话用于定位底层证据，不能替代底层证据。

## 维护

维护者在作者 Git checkout 中工作，其中 schema 与运行时代码定义实际行为。修改所属合同
时同步更新文档、测试与客户端，然后构建并安装新 release。
