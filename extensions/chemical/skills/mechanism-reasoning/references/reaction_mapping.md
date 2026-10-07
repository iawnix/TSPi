# Explicit reaction mapping / 显式反应映射

Use chemical-input scripts/prepare.py --output mapping.json reaction --smiles
'<mapped-reactants>><mapped-products>'. Each explicit atom must have a unique
positive map label on each side. The helper checks element/charge conservation,
map coverage and element correspondence, and reports formed/broken/order-changed bonds.
For isotope or proton-transfer studies use explicit isotopes and H atoms, and
inspect that correspondence rather than treating implicit H as mapped evidence.

映射由 Agent 选择并保留，helper 核验对应关系与键变化，不证明机理或路径连通性。
用 artifact_register 保存 JSON 后，引用返回的 Artifact ID 记录有依据的 Finding。
将映射、XYZ 原子顺序、构象/立体化学和 IRC 端点身份分别核对。
