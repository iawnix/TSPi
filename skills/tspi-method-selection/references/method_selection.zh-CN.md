# Backend 选择

Root Agent 根据科学问题、不确定性、体系大小、电子结构、目标可观测量、可用 Artifact、
成本与实时环境选择 Backend。使用 capability catalog 检查接受的任务与参数。

需要考虑：

- 方法能否表示电荷、自旋、激发态、金属中心、多参考特征、溶剂和约束；
- 任务能否产生区分 Claim 所需的 Finding；
- 候选质量与原子映射；
- 低成本探索是否具有科学信息，而不只是更便宜；
- 是否需要更高层级 recalculation 进行稳健性检查；
- 实时本地/远端软件与调度器是否就绪。

Gaussian 可用于直接 TS 优化、松弛扫描、QST 与后续表征。xTB/CREST 可高效探索构象和
粗略路径。已注册 `ase.neb` capability 使用 ASE 路径优化和 xTB 能量/力。外部 DMECP
工作流可处理交叉点搜索。根据当前研究问题决定它们的使用顺序。

在 ResearchNode/Claim 中记录方法选择及其可证伪目的。方法变化时保留之前的 intent；
若科学目标变化，使用 recalculation record 或新 Node。
