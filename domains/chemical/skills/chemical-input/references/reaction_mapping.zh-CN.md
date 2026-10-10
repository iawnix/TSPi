# Explicit reaction mapping / 显式反应映射

Use chemical-input scripts/prepare.py --output mapping.json reaction --smiles
'<mapped-reactants>><mapped-products>'. Each explicit atom must have a unique
positive map label on each side. The helper checks element/charge conservation,
map coverage and element correspondence, and reports formed/broken/order-changed bonds.
For isotope or proton-transfer studies use explicit isotopes and H atoms, and
inspect that correspondence rather than treating implicit H as mapped evidence.

映射由 Agent 选择并保留，helper 核验对应关系与键变化，不证明机理或路径连通性。
用 artifact_register 保存 JSON 后，引用返回的 Artifact ID 记录有依据的研究记录。
将映射、XYZ 原子顺序、构象/立体化学和 IRC 端点身份分别核对。

对于声明的 Diels–Alder 变换，`declared_transformation.product_graph_matches` 将声明键变化
生成的产物与输入产物比较，忽略 atom-map 标签及立体化学，但保留电荷和同位素。`null` 表示
反应物键型不满足声明，无法进行该比较。图相同不会将失败的精确映射判定改为通过：对称等价
标签不证明得到不同区域异构体；同一个产物图也不证明所声明的原子轨迹或逐原子氢对应正确。
分别检查这些结果，不把映射差异直接解释为错误产物。
