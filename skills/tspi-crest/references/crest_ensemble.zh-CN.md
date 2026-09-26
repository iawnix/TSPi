# CREST 构象集合合同

已注册 capability 为 `crest.conformer_search`。它接受一个 `xyz` 输入，以及显式电荷、
未成对电子数、xTB 方法、搜索级别、优化级别、线程和溶剂设置。溶剂与溶剂模型必须同时
提供。

必需主要输出集为 `crest.out`、`crest_best.xyz`、`crest_conformers.xyz` 和
`crest.energies`。完成的搜索需要正常终止标记、全部必需文件、可解析的构象集合，以及
一致的构象数和能量表行数。后续 Node 使用集合成员前，核验原子数与坐标 identity。

## 运行就绪

远端环境的 `crest` Backend 绑定必须选择由运维管理、有版本的 CREST binary。激活脚本
必须在不修改研究 workspace 的情况下提供兼容 xTB executable。部署或环境变化后，以及
首次计算前，运行 `TSPi --check-remote`。缺失命令或激活脚本属于运行故障，不是科学结果。

不要从计算任务中安装或升级 CREST。按照[远端计算配置](../../../docs/INSTALLATION.zh-CN.md)，
再运行有边界的计算节点
smoke search。调度器退出码为零但缺少任何必需主要 Artifact 时，属于程序或集成失败，
不是空构象集合。

只在声明的 CREST 计算内部使用相对能量排序构象。自由能与势垒使用各自必需的校正进行
评估。把构象集合与选择理由保存为 Artifact 和 Finding，使其他方法可以复现或质疑选择。
