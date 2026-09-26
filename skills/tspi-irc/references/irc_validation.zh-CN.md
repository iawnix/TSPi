# IRC 验证

内禀反应坐标计算用于检验所选鞍点是否通向声明的反应物与产物势阱。它本身不能证明终端
几何是已优化极小点。

对每个方向保留来源鞍点、方向、calculation intent、路径 Artifact、端点 Artifact 与摘要。
使用显式阈值检查起始几何是否与已验证鞍点一致。检查程序正常终止、请求方向、路径完整性、
步数、最终几何、可用时的最终梯度，以及最大步数或短路径限制。

`path.endpoint_summary` 提取有限的定向 Gaussian IRC 端点、终止与完成标记，以及可用的
起始几何。缺少起始几何或路径不完整时仍为 inconclusive。当端点梯度或几何不足以直接
归属势阱时，先优化端点。

将每个端点与一个显式选择的反应物或产物 Artifact 比较。核验元素计数、原子 mapping、
电荷、多重度或电子态、形成/断裂键、关键内坐标、片段配对、构象与立体化学。适合确定性
映射比较时使用 `artifact_compare`。不能只从文件名或路径方向推断端点 identity。

`mechanism.step.audit` 可以组合驻点、振动模式、正向/反向路径和结构比较 Artifact。预期
端点 ID 必须显式给出，每项比较必须把提取端点绑定到该目标。Audit 是结构化评估，不是
自动 Claim verdict。

分别记录每个方向的路径完成与端点归属。缺失、歧义或矛盾证据属于 IssueFinding。Gate
可以使端点 criterion 可见，但其 evaluation 与最终 Node/Claim 状态仍是不同变更。
