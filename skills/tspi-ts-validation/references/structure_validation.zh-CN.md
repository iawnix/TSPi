# 分子结构合同

结构比较需要显式化学 identity 与几何规则。按行顺序比较坐标前先核验原子 mapping。

## Identity 与 Mapping

核验元素计数、电荷、多重度/电子态、相关同位素与一一原子 mapping。Mapping 可以来自
稳定原子顺序、显式 map metadata、图同构或经审查的确定性归属。有歧义的对称等价 mapping
仍是局限。

## 对齐

中心化后，在所选映射原子上使用 Kabsch 最小二乘刚性对齐。应用一次 proper rotation；
除非科学比较明确要求，否则不允许反射。报告对齐 RMSD 和所用原子子集/权重。

刚性对齐后，比较键长、键角、二面角、形成/断裂接触、手性和势阱 identity。

## 科学记录

将 mapping 方法、参考结构、所选原子、RMSD、关键内坐标、立体化学 verdict 和来源 Artifact
摘要记录为语义 Finding。当这些值决定任务能否完成时，使用 identity 或立体化学 Gate。

端点 identity 还要结合全局 RMSD 与渲染结构检查片段排列、构象和立体化学。

## 确定性工具参数

`artifact.compare` 暴露可选 `parameters`，字段使用 camel case：

- `atomMapping`：每个参考原子对应的一个目标 index；
- `reactionCenterAtoms`：用于局部 RMSD 的参考原子 index；
- `keyBonds`、`keyAngles`、`keyDihedrals`：由 2、3 或 4 个 index 组成的检查数组；
- `stereochemicalChecks`：显式 `tetrahedral`、`alkene` 或 `dihedral` 检查，使用
  `retain`/`invert` policy；alkene 检查还接受 `E` 或 `Z`；
- `rmsdThreshold` 与 `reactionCenterThreshold`：0 到 10 angstrom 的有限值。

Tetrahedral 检查使用 `center` 和四个 `neighbors`；alkene 检查使用两个 `atoms` 与两个
`substituents`；dihedral 检查使用四个 `atoms`，并可将 `maxDeltaDegrees` 设为 0 到 180。
Kernel 拒绝重复/越界 index、错误的类型特定字段、非 XYZ 输入、已改变摘要和已关闭的输出
Node。
