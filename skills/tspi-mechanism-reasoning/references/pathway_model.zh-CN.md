# 路径 Claim

路径 Claim 描述相互连通的一组基元步骤 Claim，以及中间体或势阱 identity。不能从单个
过渡态结果或 ResearchNode 拓扑推断整条路径得到支持。

为实质性步骤和物种 identity 记录显式 Claim，并使用 Claim 关系表达其科学依赖。
ResearchNode 依赖表示研究如何产生结果，不定义化学连通性。

评审路径时，为有序步骤引用、端点/中间体 identity、共享物种一致性、电荷/自旋或态连续性
及其他已核验事实创建 FactFinding。为未解决分支、缺失步骤、冲突归属或局限创建
IssueFinding。每个 Finding 都引用来源 Artifact。

当路径需要可见标准集（例如端点 identity 与连续性）时使用 ClaimGate，并针对当前 map
revision 进行评估。Gate verdict 是对 criteria 的评估，不会自动改变 Claim status。替代
路径保留为不同 Claim。能量偏好、动力学可达性与结构连通性仍是不同问题，可能需要不同
Node 与 Gate。
