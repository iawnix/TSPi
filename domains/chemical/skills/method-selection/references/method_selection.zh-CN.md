# Backend 选择

Root Agent 根据科学问题、不确定性、体系大小、电子结构、目标可观测量、可用 Artifact、
成本与实时环境选择 Backend。使用 Skill instructions 检查接受的任务与参数。

需要考虑：

- 方法能否表示电荷、自旋、激发态、金属中心、多参考特征、溶剂和约束；
- 任务能否产生区分假设所需的研究记录；
- 候选质量与原子映射；
- 低成本探索是否具有科学信息，而不只是更便宜；
- 是否需要更高层级 recalculation 进行稳健性检查；
- 实时本地/远端软件与调度器是否就绪。

Gaussian 显式输入 runner 可执行已提供的 TS、扫描、QST 输入与后续计算，但不自动构造
完整机理研究。xTB/CREST 与 ASE NEB 可能适合探索，需区分科学适用性与实际执行入口。
内置 xTB runner 只支持 opt/SP；CREST、NEB 和外部交叉点工具需核实已安装命令或具体脚本，
通过通用 Job Runtime 执行。先检查共享 runner 与安装软件，再判断能力是否不可用，
根据研究问题决定使用顺序。

在 Researchresearch conclusion 中记录方法选择及其可证伪目的。方法变化时保留之前的 intent；
若科学目标变化，使用 recalculation record 或新研究 Node。
