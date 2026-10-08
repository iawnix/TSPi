# IRC 验证

内禀反应坐标计算用于检验所选鞍点是否通向声明的反应物与产物势阱。它本身不能证明终端
几何是已优化极小点。

对每个方向保留来源鞍点、方向、calculation intent、路径 Artifact、端点 Artifact 与摘要。
使用显式阈值检查起始几何是否与已验证鞍点一致。检查程序正常终止、请求方向、路径完整性、
步数、最终几何、可用时的最终梯度，以及最大步数或短路径限制。

[Gaussian 显式输入 runner](../../gaussian/SKILL.zh-CN.md) 接受 `--validation irc`，
通过 `gaussian_io.py::parse_irc_log` 写出 `irc_path_summary.json`、`irc_path_points.json`
和 `gaussian_endpoint.xyz`；需要收集时通过准备 helper 的 `--collect` 显式声明。
基础检查要求路径点和端点几何存在，不证明路径完整或势阱身份。端点梯度或几何不足以
直接归属势阱时，应先优化端点。

将每个端点与一个显式选择的反应物或产物 Artifact 比较。核验元素计数、原子 mapping、
电荷、多重度或电子态、形成/断裂键、关键内坐标、片段配对、构象与立体化学。映射比较必须
通过真实分析工具或 Job 执行并登记输出；`artifact_derive` 只记录描述。不能只从文件名或路径方向推断端点 identity。

评估时组合驻点、振动模式、正向/反向路径和结构比较证据，显式将每个提取端点绑定到预期
Artifact。当前没有内置机理审计执行器；即使计算或解析成功，缺失的科学检查仍未解决。

分别记录每个方向的路径完成与端点归属。缺失、歧义或矛盾证据属于 IssueFinding。Gate
可以使端点 criterion 可见，但其 evaluation 与最终 Node/Claim 状态仍是不同变更。
